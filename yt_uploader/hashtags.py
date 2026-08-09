"""Hashtag handling for titles/descriptions.

The exact required tokens are appended case-sensitively (they are specified
verbatim: #shorts #SHORT #short and #movieclips #movie <topic> #latest
#trending). Existing content is preserved; only missing tags are appended,
mirroring the proven ensure_tags approach from the let me paint please project.
"""

import re

from .config import DESCRIPTION_TAGS, TITLE_TAGS


def _tag_present(text: str, tag: str) -> bool:
    """Exact-token presence check (case-sensitive, whole token only)."""
    return re.search(re.escape(tag) + r"(?![#\w])", text or "") is not None


def ensure_tags(text: str, tags: list) -> str:
    """Append any missing tags to the text as a trailing block."""
    text = (text or "").strip()
    missing = [t for t in tags if not _tag_present(text, t)]
    if not missing:
        return text
    block = "\n".join(missing)
    return f"{text}\n\n{block}" if text else block


def topic_tag_from_base(base_name: str) -> str:
    """Derive the per-video hashtag from the file base name, e.g.
    spiderman.mp4 -> #spiderman."""
    clean = re.sub(r"[^a-z0-9]+", "", (base_name or "").lower())
    return f"#{clean}" if clean else ""


def build_title(base_title: str) -> str:
    """First line of the sidecar = title; append the required hashtags and
    cap at YouTube's 100-character limit."""
    title = (base_title or "").strip()
    missing = [t for t in TITLE_TAGS if not _tag_present(title, t)]
    if missing:
        title = f"{title} {' '.join(missing)}" if title else " ".join(missing)
    return title[:100]


def build_description(base_description: str, base_name: str) -> str:
    """Remaining sidecar lines = description; append the required hashtags
    (including the topic tag derived from the file name), preserving the
    original content."""
    required = [topic_tag_from_base(base_name)] + DESCRIPTION_TAGS
    required = [t for t in required if t]
    return ensure_tags(base_description, required)
