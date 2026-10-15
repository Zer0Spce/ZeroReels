from __future__ import annotations

from pathlib import Path
import re
import shutil
import urllib.parse

from PySide6.QtWidgets import QLabel

from . import ui, v071_pipeline, v071_web_media as web_media
from .models import Project, Scene


_ORIGINAL_INIT = web_media.WikimediaImageService.__init__
_ORIGINAL_GENERATE = web_media.WikimediaImageService.generate

_HYPOTHETICAL_PREFIX = re.compile(
    r"^(?:what\s+if|what\s+would\s+happen\s+if|what\s+happens\s+if)\s+",
    re.IGNORECASE,
)
_HYPOTHETICAL_TAIL = re.compile(
    r"\b(?:suddenly\s+)?(?:disappeared|disappears|vanished|vanishes|stopped\s+working|stops\s+working|"
    r"ceased\s+to\s+exist|ceases\s+to\s+exist|never\s+existed|did\s+not\s+exist|didn't\s+exist|was\s+gone|were\s+gone)\b.*$",
    re.IGNORECASE,
)

# Search-only guard. These words are still allowed in narration when they actually belong to the
# user's topic; they are excluded from scene-detail search expansion when they leaked in from an
# unrelated research result.
_SENSITIVE_SEARCH_TERMS = {
    "porn", "porno", "pornography", "pornographic", "sexual", "sex", "nude", "nudity", "adult",
}


def topic_core(topic: str) -> str:
    """Reduce editorial/hypothetical titles to the thing the video is actually about."""
    value = " ".join((topic or "").split()).strip(" \t\r\n?.!,:;-—")
    if not value:
        return ""
    value = _HYPOTHETICAL_PREFIX.sub("", value).strip()
    value = _HYPOTHETICAL_TAIL.sub("", value).strip(" \t\r\n?.!,:;-—")
    value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.IGNORECASE).strip()
    value = web_media._topic_subject(value).strip(" \t\r\n?.!,:;-—")
    return value or web_media._topic_subject(topic)


def _tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]{1,}", value or "")
        if token.lower() not in web_media.STOPWORDS
    }


def _title_relevant(title: str, core: str, snippet: str = "") -> bool:
    title_clean = " ".join((title or "").split()).strip()
    core_clean = " ".join((core or "").split()).strip()
    if not title_clean or not core_clean:
        return False
    title_fold = title_clean.casefold()
    core_fold = core_clean.casefold()
    if title_fold == core_fold:
        return True
    core_tokens = _tokens(core_clean)
    if not core_tokens:
        return False
    title_tokens = _tokens(title_clean)
    # For a single broad concept such as "Internet", do not accept "Internet pornography" as
    # the primary page just because it contains the same generic word. Exact title wins.
    if len(core_tokens) == 1:
        token = next(iter(core_tokens))
        if token in title_tokens and len(title_tokens) == 1:
            return True
        # Acronyms can be expanded by Wikipedia; the result snippet often contains the acronym.
        if len(token) <= 5 and re.search(rf"\b{re.escape(token)}\b", (snippet or "").lower()):
            return True
        return False
    overlap = len(core_tokens & title_tokens)
    return overlap / max(1, len(core_tokens)) >= 0.5


def safe_fetch_wikipedia_context(topic: str, max_chars: int = 4600) -> tuple[str, str]:
    """Ground scripts only with Wikipedia pages that match the user's actual subject."""
    core = topic_core(topic) or " ".join((topic or "").split()).strip()
    if not core:
        return "", ""
    search_url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": core,
        "srlimit": 5,
        "utf8": 1,
        "format": "json",
        "origin": "*",
    })
    try:
        search = web_media._json(search_url)
        rows = search.get("query", {}).get("search", [])
        if not rows:
            return "", ""

        # Prefer an exact Wikipedia title. Otherwise keep only genuinely related search hits.
        exact = [row for row in rows if str(row.get("title", "")).casefold() == core.casefold()]
        candidates = exact[:1] if exact else [
            row for row in rows
            if _title_relevant(
                str(row.get("title", "")),
                core,
                web_media._clean_html(str(row.get("snippet", ""))),
            )
        ][:2]
        if not candidates:
            return "", ""

        pageids = [str(row.get("pageid")) for row in candidates if row.get("pageid")]
        if not pageids:
            return "", ""
        extract_url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query",
            "prop": "extracts|info",
            "pageids": "|".join(pageids),
            "exintro": 1,
            "explaintext": 1,
            "inprop": "url",
            "format": "json",
            "origin": "*",
        })
        data = web_media._json(extract_url)
        pages = data.get("query", {}).get("pages", {})
        chunks: list[str] = []
        source = ""
        for pageid in pageids:
            page = pages.get(pageid, {})
            title = " ".join(str(page.get("title", "")).split()).strip()
            extract = " ".join(str(page.get("extract", "")).split()).strip()
            if not title or not extract or not _title_relevant(title, core, extract):
                continue
            if not source:
                source = str(page.get("fullurl", ""))
            chunks.append(f"{title}: {extract}")
        if not chunks:
            return "", ""
        return "\n\n".join(chunks)[:max_chars], source
    except Exception:
        return "", ""


def safe_primary_subject(project: Project) -> str:
    """Never let an unrelated research page replace the user's actual subject."""
    core = topic_core(project.topic)
    context = str(getattr(project, "research_context", "") or "").strip()
    if context:
        first = context.splitlines()[0].strip()
        if ":" in first:
            title = first.split(":", 1)[0].strip()
            if _title_relevant(title, core):
                return title
    source = str(getattr(project, "research_source", "") or "").strip()
    if source:
        try:
            slug = urllib.parse.unquote(urllib.parse.urlparse(source).path.rsplit("/", 1)[-1]).replace("_", " ").strip()
            if _title_relevant(slug, core):
                return slug
        except Exception:
            pass
    return core or web_media._topic_subject(project.topic)


def _safe_scene_keywords(project: Project, scene: Scene, limit: int = 3) -> list[str]:
    topic_words = _tokens(project.topic)
    result: list[str] = []
    for word in web_media._keywords(scene.narration, 8):
        key = word.lower().strip("'’")
        if key in _SENSITIVE_SEARCH_TERMS and key not in topic_words:
            continue
        # Avoid unrelated proper names introduced by bad research. Proper names that are in the
        # user's topic remain allowed; common scene words remain useful for visual specificity.
        if word[:1].isupper() and key not in topic_words:
            continue
        result.append(word)
        if len(result) >= limit:
            break
    return result


def safe_build_image_queries(project: Project, scene: Scene) -> list[str]:
    subject = safe_primary_subject(project)
    core = topic_core(project.topic)
    details = _safe_scene_keywords(project, scene, 3)
    candidates: list[str] = []
    if subject and details:
        candidates.append(f"{subject} {details[0]}")
    if subject:
        candidates.append(subject)
    if core and core.casefold() != subject.casefold():
        candidates.append(core)
    # Broad visual fallbacks for common hypothetical tech stories. They stay real-media based
    # and are intentionally generic rather than drifting into unrelated named pages.
    core_tokens = _tokens(core)
    if "internet" in core_tokens or "network" in core_tokens:
        candidates.extend(["Internet infrastructure", "computer network", "data center", "fiber optic cable"])
    elif "electricity" in core_tokens or "power" in core_tokens:
        candidates.extend(["electrical grid", "power station", "transmission lines"])
    elif "gravity" in core_tokens:
        candidates.extend(["Earth from space", "astronaut microgravity"])

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = " ".join(candidate.split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            unique.append(cleaned)
    return unique or ([core] if core else [])


def resilient_init(self, project: Project) -> None:
    _ORIGINAL_INIT(self, project)
    self.subject = safe_primary_subject(project)


def _reuse_previous_real_image(project: Project, scene: Scene, out_dir: Path) -> Path | None:
    candidates = [
        item for item in project.scenes
        if item.index < scene.index
        and item.source_type == "Wikimedia Commons"
        and item.image_path
        and Path(item.image_path).exists()
    ]
    if not candidates:
        return None
    # Avoid simply repeating the immediately previous frame when there is another real source.
    source = candidates[-3] if len(candidates) >= 3 else candidates[0]
    source_path = Path(source.image_path)
    suffix = source_path.suffix.lower() if source_path.suffix else ".jpg"
    target = out_dir / f"scene_{scene.index:03d}_web_fallback{suffix}"
    shutil.copy2(source_path, target)
    scene.source_type = "Wikimedia Commons"
    scene.source_url = source.source_url
    scene.source_credit = source.source_credit
    scene.source_license = source.source_license
    scene.source_query = f"Topic-safe fallback reuse from scene {source.index}: {source.source_query}"
    scene.quality_score = 82
    scene.quality_notes = [
        "real-media fallback • unique Commons search exhausted",
        f"reused source from scene {source.index} with different edit/motion",
    ]
    return target


def resilient_generate(self, scene: Scene, out_dir: Path, fmt: str) -> Path:
    """A single weak Commons search must never throw away an otherwise complete video."""
    try:
        return _ORIGINAL_GENERATE(self, scene, out_dir, fmt)
    except Exception as first_exc:
        # Retry once with the safe topic subject and permit reuse of a Commons result that was
        # already used earlier. Niche subjects sometimes expose fewer unique files than scenes.
        previous_used = set(getattr(self, "used", set()))
        previous_subject = getattr(self, "subject", "")
        self.subject = safe_primary_subject(self.project)
        self.used = set()
        try:
            target = _ORIGINAL_GENERATE(self, scene, out_dir, fmt)
            self.used = previous_used | set(getattr(self, "used", set()))
            if scene.source_query:
                scene.source_query = "Topic-safe retry: " + scene.source_query
            return target
        except Exception:
            self.used = previous_used
            self.subject = previous_subject or safe_primary_subject(self.project)
            reused = _reuse_previous_real_image(self.project, scene, out_dir)
            if reused is not None:
                return reused
            raise RuntimeError(
                "Real Web Images could not retrieve even one topic-relevant Commons image. "
                "Check the internet connection or switch Image Source to Hybrid. "
                f"Original search error: {str(first_exc)[:260]}"
            ) from first_exc


def install() -> None:
    # Patch the module globals used by WikimediaImageService.generate at runtime.
    web_media.fetch_wikipedia_context = safe_fetch_wikipedia_context
    web_media.primary_subject = safe_primary_subject
    web_media.build_image_queries = safe_build_image_queries
    web_media.build_image_query = lambda project, scene: (safe_build_image_queries(project, scene) or [""])[0]
    web_media.WikimediaImageService.__init__ = resilient_init
    web_media.WikimediaImageService.generate = resilient_generate

    # v071_pipeline imported the research function directly, so replace that binding too.
    v071_pipeline.fetch_wikipedia_context = safe_fetch_wikipedia_context

    original_sidebar = ui.MainWindow._sidebar

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.8.1 WEB")
                label.setMaximumWidth(126)
                break
        return frame

    ui.MainWindow._sidebar = sidebar
