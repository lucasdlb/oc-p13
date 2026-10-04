"""Deterministic v2 classification for cleaned Wikibooks pages (ticket 04).

Rules-only, reproducible, offline. The v1 `WikibooksAdapter` cleaner (adapters.py)
still strips templates/navigation and rejects on residual markup; this module adds:

- page-level gates that *record* a rejection reason instead of raising;
- per-section intent classification (schema-v2 `intent` vocabulary);
- derived `is_history`/`is_misc` convenience flags;
- duplicate and near-duplicate detection over accepted section prose.

Classification is deliberately conservative: uncertain sections default to `intent=misc`,
which is cheap to downrank at retrieval time. Chunk identity is independent of these
labels (validated schema), so reclassifying later never creates duplicate vectors.
"""

import hashlib
import re
from dataclasses import dataclass, field

from backend.app.ingestion.adapters import (
    _RESIDUAL_MARKUP_RE,
    _parse_sections,
)

ROOT_TITLE = "Chess Opening Theory"
PREFIX = ROOT_TITLE + "/"

INTENT_VOCABULARY = (
    "intro",
    "plan",
    "candidate_move",
    "variation",
    "trap",
    "mistake",
    "history",
    "misc",
    "general_principle",
)

MIN_PROSE_CHARS = 200

# Extra utility/data sections excluded on top of the v1 set (references, see also,
# theory table, external links). These are data or meta, not teaching prose.
EXTRA_EXCLUDED_SECTION_TITLES = frozenset(
    {
        "statistics",
        "bibliography",
        "footnotes",
        "notes",
        "further reading",
        "estimated next move likelihood",
    }
)

_MOVE_PATH_RE = re.compile(r"^\d+\.")
_MOVE_TITLE_RE = re.compile(r"^(\d+)\s*(\.{3}|\.)\s*[A-Za-z0-9]")

_CANDIDATE_MOVE_TITLES = {
    "responses",
    "black's responses",
    "white's responses",
    "other moves",
    "next moves",
    "next move",
}
_TRAP_TITLES = {"traps", "trap", "common traps"}
_MISTAKE_TITLES = {"bad moves", "mistakes", "common mistakes", "mistake"}

_PLAN_TITLES = {
    "ideas",
    "plans",
    "plan",
    "strategy",
    "strategic ideas",
    "typical ideas",
}
_PLAN_PREFIXES = (
    "accept ",
    "decline ",
    "trade ",
    "defend ",
    "develop ",
    "control ",
    "open ",
    "attack ",
)
_VARIATION_KEYWORDS = (
    "defence",
    "defense",
    "variation",
    "gambit",
    "attack",
    "sideline",
    "main line",
)

_SAMPLE_GAME_TITLES = {"sample game", "sample games"}


@dataclass(frozen=True)
class SectionClassification:
    title: str | None
    text: str
    section_index: int
    intent: str
    side: str | None
    tags: tuple[str, ...]
    difficulty: str | None
    is_history: bool
    is_misc: bool


@dataclass
class PageResult:
    title: str
    status: str
    reason: str | None
    page_text: str
    sections: list[SectionClassification] = field(default_factory=list)


def classify_page(title: str, wikitext: str) -> PageResult:
    """Gate, clean, and classify a single page into a :class:`PageResult`."""

    if "#invoke" in wikitext or (_is_non_move_path(title) and title != ROOT_TITLE):
        return PageResult(title=title, status="rejected", reason="utility_navigation_page", page_text="")

    sections = [
        (title, body)
        for title, body in _parse_sections(wikitext, extra_excluded=EXTRA_EXCLUDED_SECTION_TITLES)
        if body.strip()
    ]
    page_text = "\n\n".join(
        "\n\n".join(part for part in (t, b) if part) for t, b in sections
    ).strip()

    if not page_text:
        return PageResult(title=title, status="rejected", reason="no_pedagogical_prose", page_text="")
    if len(page_text) < MIN_PROSE_CHARS:
        return PageResult(title=title, status="rejected", reason="low_value_prose", page_text=page_text)
    if _RESIDUAL_MARKUP_RE.search(page_text):
        return PageResult(title=title, status="rejected", reason="residual_markup", page_text=page_text)

    classified = [
        _classify_section(title, body, index)
        for index, (title, body) in enumerate(sections)
    ]
    return PageResult(
        title=title,
        status="accepted",
        reason=None,
        page_text=page_text,
        sections=classified,
    )


def _is_non_move_path(title: str) -> bool:
    path = title[len(PREFIX):] if title.startswith(PREFIX) else title
    return not bool(_MOVE_PATH_RE.match(path))


def _classify_section(title: str | None, text: str, section_index: int) -> SectionClassification:
    intent = _classify_intent(title, section_index)
    side = _classify_side(title)
    tags: tuple[str, ...] = ()
    if _section_key(title) in _SAMPLE_GAME_TITLES:
        tags = ("game-score",)
    return SectionClassification(
        title=title,
        text=text,
        section_index=section_index,
        intent=intent,
        side=side,
        tags=tags,
        difficulty=None,
        is_history=intent == "history",
        is_misc=intent == "misc",
    )


def _classify_intent(title: str | None, section_index: int) -> str:
    key = _section_key(title)

    if section_index == 0:
        return "intro"
    if key == "history":
        return "history"
    if key in _CANDIDATE_MOVE_TITLES:
        return "candidate_move"
    if key in _TRAP_TITLES:
        return "trap"
    if key in _MISTAKE_TITLES:
        return "mistake"
    if key in _SAMPLE_GAME_TITLES:
        return "misc"
    if title and _MOVE_TITLE_RE.match(title.strip()):
        return "candidate_move"
    if key in _PLAN_TITLES or key.startswith(_PLAN_PREFIXES):
        return "plan"
    if any(keyword in key for keyword in _VARIATION_KEYWORDS):
        return "variation"
    return "misc"


def _classify_side(title: str | None) -> str | None:
    if not title:
        return None
    match = _MOVE_TITLE_RE.match(title.strip())
    if match is None:
        return None
    return "black" if match.group(2) == "..." else "white"


def _section_key(title: str | None) -> str:
    return " ".join((title or "").casefold().split())


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _shingles(normalized: str, n: int = 5) -> set[str]:
    tokens = normalized.split()
    if len(tokens) < n:
        return frozenset((normalized,))
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def find_duplicates(
    sections: list[tuple[str, str, str | None]],
    *,
    jaccard_threshold: float = 0.85,
    max_shingle_freq: int = 500,
    min_tokens: int = 8,
) -> tuple[list[list[dict]], list[dict]]:
    """Detect exact and near-duplicate sections.

    ``sections`` is a list of ``(page_id, text, section_title)``. Returns
    ``(exact_groups, near_duplicates)`` where exact groups are lists of member refs
    and near-duplicates are pairs with a Jaccard score. Sections shorter than
    ``min_tokens`` tokens (e.g. a bare opening name used as a lead) are ignored:
    they are not meaningful duplicated prose.
    """

    exact: dict[str, list[dict]] = {}
    refs: list[dict] = []
    shingle_sets: list[frozenset[str]] = []

    for page_id, text, title in sections:
        normalized = _normalize(text)
        if not normalized or len(normalized.split()) < min_tokens:
            continue
        ref = {"page_id": page_id, "section_title": title}
        refs.append(ref)
        exact.setdefault(hashlib.sha256(normalized.encode("utf-8")).hexdigest(), []).append(ref)
        shingle_sets.append(_shingles(normalized))

    exact_groups = [group for group in exact.values() if len(group) > 1]

    index: dict[str, set[int]] = {}
    for i, shingles in enumerate(shingle_sets):
        for sh in shingles:
            index.setdefault(sh, set()).add(i)

    stop_shingles = {sh for sh, ids in index.items() if len(ids) > max_shingle_freq}
    near: dict[tuple[int, int], float] = {}

    for i, shingles in enumerate(shingle_sets):
        candidates: set[int] = set()
        for sh in shingles:
            if sh in stop_shingles:
                continue
            candidates |= index[sh]
        candidates.discard(i)
        for j in candidates:
            if j <= i:
                continue
            inter = len(shingles & shingle_sets[j])
            union = len(shingles | shingle_sets[j])
            score = inter / union if union else 0.0
            if score >= jaccard_threshold:
                near[(i, j)] = round(score, 3)

    near_duplicates = [
        {
            "a": refs[i],
            "b": refs[j],
            "jaccard": score,
        }
        for (i, j), score in sorted(near.items(), key=lambda kv: -kv[1])
    ]
    return exact_groups, near_duplicates
