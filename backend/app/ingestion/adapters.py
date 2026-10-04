"""Ingestion adapters: one adapter per source, one common `ChunkSource` output.

`chess-openings` is structured opening metadata (ECO/name/line), not pedagogical
prose: it feeds the structured opening lookup and the `eco_code` join, and is
**not** ingested into Milvus (ADR 0006, revised). `ChessOpeningsAdapter` still
parses it deterministically for that structured path.

- `ChessOpeningsAdapter`: the `lichess-org/chess-openings` TSVs (`eco`/`name`/
  `pgn`); licence CC0-1.0.
- `WikibooksAdapter`: Wikibooks Chess Opening Theory prose, split into sections.
  Licence CC BY-SA (attribution + share-alike); status "a verifier" (ADR 0006).

Fetching is deliberately separate (`experiments/rag/fetch_corpus.py` and the
ingestion CLI); adapters turn already-fetched text into chunk sources.
"""

import csv
import html
import io
import re
from dataclasses import dataclass

import mwparserfromhell

from backend.app.ingestion.chunker import ChunkSection, ChunkSource


CHESS_OPENINGS_SOURCE = "lichess-org/chess-openings"
CHESS_OPENINGS_URL = "https://github.com/lichess-org/chess-openings"
CHESS_OPENINGS_LICENSE = "CC0-1.0"

WIKIBOOKS_SOURCE = "wikibooks-chess-opening-theory"
WIKIBOOKS_LICENSE = "CC BY-SA 4.0"
WIKIBOOKS_CLEANER_VERSION = 2

_TSV_HEADER = ("eco", "name", "pgn")


class WikibooksAdapterError(ValueError):
    """Raised when a Wikibooks page cannot produce clean pedagogical prose."""


def _is_header(row: list[str]) -> bool:
    """Detect the TSV header, including when several files are concatenated."""

    return tuple(field.strip().lower() for field in row[:3]) == _TSV_HEADER


class ChessOpeningsAdapter:
    source = CHESS_OPENINGS_SOURCE

    def parse(self, tsv_text: str, *, limit: int | None = None) -> list[ChunkSource]:
        sources: list[ChunkSource] = []
        reader = csv.reader(io.StringIO(tsv_text), delimiter="\t")
        for row in reader:
            if _is_header(row):
                continue
            if len(row) < 3:
                continue

            eco, name, pgn = (field.strip() for field in row[:3])
            if not eco or not name or not pgn:
                continue

            sources.append(
                ChunkSource(
                    source=self.source,
                    page_title=f"ECO {eco} — {name}",
                    page_text=f"ECO {eco} — {name}: {pgn}",
                    source_url=CHESS_OPENINGS_URL,
                    license_or_terms=CHESS_OPENINGS_LICENSE,
                    opening_name=name,
                    eco_code=eco,
                    line_pgn=pgn,
                )
            )
            if limit is not None and len(sources) >= limit:
                break
        return sources


@dataclass(frozen=True)
class WikibooksPage:
    title: str
    wikitext: str

    def url(self) -> str:
        return "https://en.wikibooks.org/wiki/" + self.title.replace(" ", "_")


class WikibooksAdapter:
    source = WIKIBOOKS_SOURCE

    def parse(
        self,
        page: WikibooksPage,
        *,
        eco_code: str | None = None,
        opening_name: str | None = None,
        url: str | None = None,
    ) -> ChunkSource:
        parsed = _parse_sections(page.wikitext)
        sections = tuple(
            ChunkSection(title=title, text=body)
            for title, body in parsed
            if body.strip()
        )
        page_text = "\n\n".join(
            "\n\n".join(part for part in (title, body) if part)
            for title, body in parsed
            if body.strip()
        )
        if not sections or not page_text.strip():
            raise WikibooksAdapterError(f"page {page.title!r} contains no pedagogical prose")
        if _RESIDUAL_MARKUP_RE.search(page_text):
            raise WikibooksAdapterError(f"page {page.title!r} contains residual MediaWiki markup")
        return ChunkSource(
            source=self.source,
            page_title=page.title,
            page_text=page_text,
            source_url=url or page.url(),
            license_or_terms=WIKIBOOKS_LICENSE,
            opening_name=opening_name,
            eco_code=eco_code,
            sections=sections,
        )


_HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$")
_LIST_RE = re.compile(r"^[*#:;]+\s*(.*)$")
_INTERWIKI_RE = re.compile(r"^[a-z][a-z-]{1,11}:", re.IGNORECASE)
_EXCLUDED_SECTION_TITLES = {
    "external links",
    "further reading",
    "references",
    "see also",
    "theory table",
}
_REMOVED_TAGS = {"gallery", "math", "ref", "references", "table"}
_RESIDUAL_MARKUP_RE = re.compile(r"\{\{|\}\}|\[\[|\]\]|\{\||\|\}|</?[A-Za-z][^>]*>")


def _parse_sections(
    wikitext: str,
    *,
    extra_excluded: frozenset[str] = frozenset(),
) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, str]] = []
    title: str | None = None
    lines: list[str] = []
    excluded_level: int | None = None

    for line in wikitext.splitlines():
        match = _HEADING_RE.match(line.strip())
        if match is not None:
            if excluded_level is None:
                sections.append((title, _clean("\n".join(lines))))

            level = len(match.group(1))
            if excluded_level is not None and level <= excluded_level:
                excluded_level = None

            title = _clean(match.group(2))
            key = _section_key(title)
            if excluded_level is None and (key in _EXCLUDED_SECTION_TITLES or key in extra_excluded):
                excluded_level = level
            lines = []
        elif excluded_level is None:
            lines.append(line)
    if excluded_level is None:
        sections.append((title, _clean("\n".join(lines))))
    return sections


def _clean(text: str) -> str:
    text = re.sub(r"__[A-Za-z]+__", "", text)
    text = re.sub(r"(?m)^\s*[*#]+\s*", "- ", text)
    code = mwparserfromhell.parse(text)

    for template in list(code.filter_templates(recursive=True)):
        try:
            code.remove(template, recursive=True)
        except ValueError:
            pass

    for tag in list(code.filter_tags(recursive=True)):
        if str(tag.tag).strip().casefold() in _REMOVED_TAGS:
            try:
                code.remove(tag, recursive=True)
            except ValueError:
                pass

    for link in list(code.filter_wikilinks(recursive=True)):
        title = str(link.title).strip()
        if _is_navigation_link(title):
            replacement = ""
        elif link.text is not None:
            replacement = str(link.text).strip()
        else:
            replacement = title.split("#", 1)[0].strip("/").rsplit("/", 1)[-1]
        try:
            code.replace(link, replacement, recursive=True)
        except ValueError:
            pass

    for link in list(code.filter_external_links(recursive=True)):
        replacement = str(link.title).strip() if link.title is not None else ""
        try:
            code.replace(link, replacement, recursive=True)
        except ValueError:
            pass

    cleaned = html.unescape(code.strip_code(normalize=True, collapse=False))
    normalized: list[str] = []
    previous_blank = True
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        list_match = _LIST_RE.match(line)
        if list_match is not None:
            line = f"- {list_match.group(1).strip()}"
        if (
            line.startswith("- ")
            and normalized
            and normalized[-1]
            and not normalized[-1].startswith("- ")
        ):
            normalized.append("")
        if line:
            normalized.append(line)
            previous_blank = False
        elif not previous_blank:
            normalized.append("")
            previous_blank = True
    while normalized and not normalized[-1]:
        normalized.pop()
    return "\n".join(normalized)


def _section_key(title: str | None) -> str:
    return " ".join((title or "").casefold().split())


def _is_navigation_link(title: str) -> bool:
    namespace = title.lstrip(":").split(":", 1)[0].casefold()
    return namespace in {"category", "file", "image"} or _INTERWIKI_RE.match(title) is not None
