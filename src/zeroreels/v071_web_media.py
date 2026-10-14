from __future__ import annotations

from html import unescape
from pathlib import Path
import json
import re
import urllib.parse
import urllib.request

from .models import Project, Scene


USER_AGENT = "ZeroReels/0.7.2 (local desktop app; https://github.com/Zer0Spce/ZeroReels)"
STOPWORDS = {
    "about", "after", "again", "against", "also", "among", "because", "before", "being", "between",
    "could", "does", "during", "each", "from", "have", "into", "just", "more", "most", "other", "over",
    "scene", "story", "than", "that", "their", "there", "these", "they", "this", "through", "under", "very",
    "what", "when", "where", "which", "while", "with", "would", "your", "were", "been", "will", "only",
    "then", "them", "some", "such", "like", "because", "around", "still", "even", "much", "many",
}

TOPIC_PREFIXES = (
    r"the\s+rise\s+and\s+fall\s+of",
    r"rise\s+and\s+fall\s+of",
    r"the\s+story\s+of",
    r"story\s+of",
    r"the\s+history\s+of",
    r"history\s+of",
    r"the\s+mystery\s+of",
    r"mystery\s+of",
    r"the\s+truth\s+about",
    r"truth\s+about",
    r"what\s+happened\s+to",
    r"who\s+was",
    r"who\s+is",
)


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
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]{2,}", text or "")
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


def _topic_subject(topic: str) -> str:
    value = " ".join((topic or "").split()).strip(" .,:;-—")
    if not value:
        return ""
    prefix = "^(?:" + "|".join(TOPIC_PREFIXES) + r")\s+"
    value = re.sub(prefix, "", value, flags=re.IGNORECASE).strip()
    # Remove common editorial descriptors that make Commons full-text search needlessly strict.
    value = re.sub(
        r"^(?:(?:NBA|NFL|MLB|NHL|UFC|WWE)\s+)?(?:superstar|star|legend|player|athlete)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"^(?:NBA|NFL|MLB|NHL|UFC|WWE)\s+(?:superstar|star|legend|player|athlete)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    return value or " ".join((topic or "").split()).strip()


def primary_subject(project: Project) -> str:
    """Prefer the verified Wikipedia page title, then a cleaned version of the user's topic."""
    context = str(getattr(project, "research_context", "") or "").strip()
    if context:
        first = context.splitlines()[0].strip()
        if ":" in first:
            title = first.split(":", 1)[0].strip()
            if 2 <= len(title) <= 100 and len(title.split()) <= 12:
                return title
    source = str(getattr(project, "research_source", "") or "").strip()
    if source:
        try:
            slug = urllib.parse.unquote(urllib.parse.urlparse(source).path.rsplit("/", 1)[-1]).replace("_", " ").strip()
            if 2 <= len(slug) <= 100:
                return slug
        except Exception:
            pass
    return _topic_subject(project.topic)


def build_image_queries(project: Project, scene: Scene) -> list[str]:
    """Build a broadening query ladder instead of one sentence-sized all-or-nothing search."""
    subject = primary_subject(project)
    topic = " ".join(project.topic.split()).strip()
    details = _keywords(scene.narration, 6)
    candidates: list[str] = []

    # Start specific enough to follow the scene, but never append an entire narration sentence.
    if subject and details:
        candidates.append(" ".join([subject, *details[:2]]))
        candidates.append(" ".join([subject, details[0]]))
    if subject:
        candidates.append(subject)
    cleaned_topic = _topic_subject(topic)
    if cleaned_topic:
        candidates.append(cleaned_topic)
    if topic and len(topic.split()) <= 8:
        candidates.append(topic)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = " ".join(candidate.split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            unique.append(cleaned)
    return unique or ([topic] if topic else [])


def build_image_query(project: Project, scene: Scene) -> str:
    queries = build_image_queries(project, scene)
    return queries[0] if queries else ""


class WikimediaImageService:
    """Fetch relevant, license-traceable real imagery from Wikimedia Commons."""

    def __init__(self, project: Project):
        self.project = project
        self.used: set[str] = set()
        self.subject = primary_subject(project)

    @staticmethod
    def _image_props() -> dict[str, object]:
        return {
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "iiurlwidth": 1600,
            "format": "json",
            "origin": "*",
        }

    def _search(self, query: str) -> list[dict]:
        params: dict[str, object] = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": 24,
            **self._image_props(),
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        data = _json(url, timeout=30)
        pages = list(data.get("query", {}).get("pages", {}).values())
        pages.sort(key=lambda item: int(item.get("index", 9999)))
        return pages

    def _category(self, subject: str) -> list[dict]:
        if not subject:
            return []
        params: dict[str, object] = {
            "action": "query",
            "generator": "categorymembers",
            "gcmtitle": f"Category:{subject}",
            "gcmtype": "file",
            "gcmlimit": 50,
            **self._image_props(),
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        data = _json(url, timeout=30)
        return list(data.get("query", {}).get("pages", {}).values())

    def _lookup_file(self, filename: str) -> list[dict]:
        name = filename.strip()
        if not name:
            return []
        if not name.lower().startswith("file:"):
            name = "File:" + name
        params: dict[str, object] = {
            "action": "query",
            "titles": name,
            **self._image_props(),
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        data = _json(url, timeout=30)
        return [page for page in data.get("query", {}).get("pages", {}).values() if "missing" not in page]

    def _wikipedia_lead(self, subject: str) -> list[dict]:
        """Resolve Wikipedia's lead image back through Commons so licensing stays traceable."""
        if not subject:
            return []
        params = {
            "action": "query",
            "prop": "pageimages",
            "piprop": "name",
            "titles": subject,
            "redirects": 1,
            "format": "json",
            "origin": "*",
        }
        url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
        data = _json(url, timeout=25)
        for page in data.get("query", {}).get("pages", {}).values():
            filename = str(page.get("pageimage", "")).strip()
            if filename:
                return self._lookup_file(filename)
        return []

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

    def _choose(self, pages: list[dict]):
        for page in pages:
            thumb, page_url, credit, license_name, width, height = self._meta(page)
            if not thumb or thumb in self.used:
                continue
            mime = str((page.get("imageinfo") or [{}])[0].get("mime", ""))
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            if width and height and min(width, height) < 420:
                continue
            return page, thumb, page_url, credit, license_name
        return None

    def generate(self, scene: Scene, out_dir: Path, fmt: str) -> Path:
        attempts: list[str] = []
        chosen = None
        query_used = ""

        for query in build_image_queries(self.project, scene):
            attempts.append(query)
            try:
                chosen = self._choose(self._search(query))
            except Exception:
                chosen = None
            if chosen is not None:
                query_used = query
                break

        # Named people/places often have a rich Commons category even when full-text scene
        # wording is too specific. This is what fixes topics such as Derrick Rose.
        if chosen is None and self.subject:
            category_label = f"Category:{self.subject}"
            attempts.append(category_label)
            try:
                chosen = self._choose(self._category(self.subject))
            except Exception:
                chosen = None
            if chosen is not None:
                query_used = category_label

        # Last real-media fallback: ask Wikipedia for the subject's lead image, but only keep
        # it if the exact file resolves through Commons (so attribution/license stay available).
        if chosen is None and self.subject:
            lead_label = f"Wikipedia lead:{self.subject}"
            attempts.append(lead_label)
            try:
                chosen = self._choose(self._wikipedia_lead(self.subject))
            except Exception:
                chosen = None
            if chosen is not None:
                query_used = lead_label

        if chosen is None:
            tried = " | ".join(attempts[-6:]) or self.subject or self.project.topic
            raise RuntimeError(f"No suitable Wikimedia Commons image found after broadened search: {tried}")

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
        scene.source_query = query_used
        scene.quality_score = 100
        scene.quality_notes = [
            f"real web image • {scene.source_license}",
            f"credit: {scene.source_credit or 'see source page'}",
        ]
        return target


def hybrid_prefers_web(scene: Scene, index: int) -> bool:
    # Keep high-concept action/reveal moments available to FLUX while grounding the story
    # with authentic establishing, detail and aftermath imagery every few beats.
    if scene.shot_role in {"Establishing", "Detail", "Aftermath", "Landing"}:
        return True
    return index % 4 == 1
