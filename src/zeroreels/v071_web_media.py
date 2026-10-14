from __future__ import annotations

from html import unescape
from pathlib import Path
import json
import re
import urllib.parse
import urllib.request

from .models import Project, Scene


USER_AGENT = "ZeroReels/0.7.1 (local desktop app; https://github.com/Zer0Spce/ZeroReels)"
STOPWORDS = {
    "about", "after", "again", "against", "also", "among", "because", "before", "being", "between",
    "could", "does", "during", "each", "from", "have", "into", "just", "more", "most", "other", "over",
    "scene", "story", "than", "that", "their", "there", "these", "they", "this", "through", "under", "very",
    "what", "when", "where", "which", "while", "with", "would", "your", "were", "been", "will", "only",
    "then", "them", "some", "such", "like", "because", "around", "still", "even", "much", "many",
}


def _json(url: str, timeout: int = 20) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = unescape(text)
    return " ".join(text.split()).strip()


def fetch_wikipedia_context(topic: str, max_chars: int = 4600) -> tuple[str, str]:
    """Return lightweight factual grounding from public Wikipedia APIs, no key required."""
    query = " ".join((topic or "").split()).strip()
    if not query:
        return "", ""
    search_url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": query, "srlimit": 3,
        "utf8": 1, "format": "json", "origin": "*",
    })
    try:
        search = _json(search_url)
        rows = search.get("query", {}).get("search", [])
        if not rows:
            return "", ""
        pageids = [str(row.get("pageid")) for row in rows if row.get("pageid")]
        if not pageids:
            return "", ""
        extract_url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "prop": "extracts|info", "pageids": "|".join(pageids),
            "exintro": 1, "explaintext": 1, "inprop": "url", "format": "json", "origin": "*",
        })
        data = _json(extract_url)
        pages = data.get("query", {}).get("pages", {})
        chunks: list[str] = []
        source = ""
        for pageid in pageids:
            page = pages.get(pageid, {})
            title = " ".join(str(page.get("title", "")).split()).strip()
            extract = " ".join(str(page.get("extract", "")).split()).strip()
            if not source:
                source = str(page.get("fullurl", ""))
            if title and extract:
                chunks.append(f"{title}: {extract}")
        combined = "\n\n".join(chunks)
        return combined[:max_chars], source
    except Exception:
        return "", ""


def grounded_topic(topic: str, context: str) -> str:
    if not context:
        return topic
    return (
        f"{topic}\n\nVERIFIED RESEARCH CONTEXT (Wikipedia, for factual grounding only):\n{context}\n\n"
        "Use the context to avoid invented details. If the context does not support a claim, keep the narration cautious instead of making it up."
    )


def _keywords(text: str, limit: int = 5) -> list[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]{2,}", text or "")
    seen: set[str] = set()
    result: list[str] = []
    for word in words:
        key = word.lower()
        if key in STOPWORDS or key in seen or len(key) < 4:
            continue
        seen.add(key)
        result.append(word)
        if len(result) >= limit:
            break
    return result


def build_image_query(project: Project, scene: Scene) -> str:
    topic = " ".join(project.topic.split()).strip()
    details = _keywords(scene.narration, 5)
    # Shot role words are deliberately omitted; Commons searches perform better on subjects/events than cinematography terms.
    return " ".join([topic, *details]).strip()


class WikimediaImageService:
    """Fetch relevant, license-traceable real imagery from Wikimedia Commons."""

    def __init__(self, project: Project):
        self.project = project
        self.used: set[str] = set()

    def _search(self, query: str) -> list[dict]:
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": 18,
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "iiurlwidth": 1600,
            "format": "json",
            "origin": "*",
        })
        data = _json(url, timeout=30)
        pages = list(data.get("query", {}).get("pages", {}).values())
        pages.sort(key=lambda item: int(item.get("index", 9999)))
        return pages

    @staticmethod
    def _meta(page: dict) -> tuple[str, str, str, str, int, int]:
        info_rows = page.get("imageinfo", [])
        if not info_rows:
            return "", "", "", "", 0, 0
        info = info_rows[0]
        meta = info.get("extmetadata", {}) or {}
        thumb = str(info.get("thumburl") or info.get("url") or "")
        page_url = str(info.get("descriptionurl") or "")
        artist = _clean_html(str((meta.get("Artist") or {}).get("value", "")))
        credit = _clean_html(str((meta.get("Credit") or {}).get("value", "")))
        license_name = _clean_html(str((meta.get("LicenseShortName") or {}).get("value", "")))
        width = int(info.get("thumbwidth") or info.get("width") or 0)
        height = int(info.get("thumbheight") or info.get("height") or 0)
        return thumb, page_url, artist or credit, license_name, width, height

    def generate(self, scene: Scene, out_dir: Path, fmt: str) -> Path:
        query = build_image_query(self.project, scene)
        pages = self._search(query)
        chosen = None
        for page in pages:
            thumb, page_url, credit, license_name, width, height = self._meta(page)
            if not thumb or thumb in self.used:
                continue
            mime = str((page.get("imageinfo") or [{}])[0].get("mime", ""))
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            if width and height and min(width, height) < 420:
                continue
            chosen = (page, thumb, page_url, credit, license_name)
            break
        if chosen is None:
            raise RuntimeError(f"No suitable Wikimedia Commons image found for: {query}")

        page, thumb, page_url, credit, license_name = chosen
        request = urllib.request.Request(thumb, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
        with urllib.request.urlopen(request, timeout=60) as response:
            content_type = response.headers.get_content_type()
            data = response.read(18 * 1024 * 1024 + 1)
        if len(data) > 18 * 1024 * 1024:
            raise RuntimeError("Wikimedia image exceeded the 18 MB scene limit")
        if len(data) < 4096:
            raise RuntimeError("Wikimedia returned an invalid/empty image")
        suffix = {"image/png": ".png", "image/webp": ".webp"}.get(content_type, ".jpg")
        target = out_dir / f"scene_{scene.index:03d}_web{suffix}"
        target.write_bytes(data)

        self.used.add(thumb)
        scene.source_type = "Wikimedia Commons"
        scene.source_url = page_url or thumb
        scene.source_credit = credit or _clean_html(str(page.get("title", "")))
        scene.source_license = license_name or "See source page"
        scene.source_query = query
        scene.quality_score = 100
        scene.quality_notes = ["real web image", f"license: {scene.source_license}"]
        return target


def hybrid_prefers_web(scene: Scene, index: int) -> bool:
    # Keep high-concept action/reveal moments available to FLUX while grounding the story
    # with authentic establishing, detail and aftermath imagery every few beats.
    if scene.shot_role in {"Establishing", "Detail", "Aftermath", "Landing"}:
        return True
    return index % 4 == 1
