"""Shared chunker for every ingestion adapter.

`granularity` is a config axis (ADR 0006):

- `page`: one opening/page becomes one chunk, giving full-page context.
- `section`: one chunk per section, so retrieval can match a specific idea.

Chunks carry no overlap and every chunk is guaranteed to fit in a UTF-8 byte
budget, because the Milvus `VARCHAR` limit is expressed in bytes, not
characters. The budget is derived from the model context window and stays well
below it: it only constrains oversized sections, and Qwen3's 32K context means
clipping is the exception.

Oversized sections are split into ordered continuation chunks (`part_index`)
so no content is dropped. An oversized **page** is rejected instead, because a
page chunk is meant to be the whole page; use `granularity=section` for pages
that exceed the budget. Every chunk carries a stable `page_id` so section hits
can be reassembled into their source page (`reconstruct_page`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from backend.app.models.knowledge import (
    KnowledgeChunk,
    build_chunk,
    page_identifier,
)


Granularity = Literal["page", "section"]

CHUNKER_VERSION = 1


class ChunkerError(ValueError):
    """Raised when a source cannot be chunked under the byte budget."""


@dataclass(frozen=True)
class ChunkSection:
    title: str | None
    text: str
    intent: str | None = None
    side: str | None = None
    is_history: bool | None = None
    is_misc: bool | None = None


@dataclass(frozen=True)
class ChunkSource:
    source: str
    page_title: str
    page_text: str
    source_url: str | None = None
    license_or_terms: str | None = None
    opening_name: str | None = None
    eco_code: str | None = None
    opening_node_id: str | None = None
    line_pgn: str | None = None
    intent: str = "misc"
    side: str | None = None
    is_history: bool = False
    is_misc: bool = True
    sections: tuple[ChunkSection, ...] = ()


def utf8_length(text: str) -> int:
    return len(text.encode("utf-8"))


def chunk_source(
    source: ChunkSource,
    *,
    granularity: Granularity,
    max_bytes: int = 16000,
) -> list[KnowledgeChunk]:
    page_id = page_identifier(source.source, source.page_title)

    if granularity == "page" or not source.sections:
        text = _compose(source.page_title, source.page_text)
        if utf8_length(text) > max_bytes:
            raise ChunkerError(
                f"page {source.page_title!r} exceeds the {max_bytes}-byte budget; "
                "use granularity=section or split the page"
            )
        return [
            _to_chunk(
                source,
                source.page_title,
                text,
                page_id=page_id,
                section_index=None,
                part_index=0,
            )
        ]

    chunks: list[KnowledgeChunk] = []
    section_index = 0
    for section in source.sections:
        if not section.text.strip():
            continue
        title = section.title or source.page_title
        header = _compose(source.page_title, section.title)
        body_budget = max_bytes - utf8_length(header) - 2
        if body_budget < 1:
            raise ChunkerError(
                f"section header for {title!r} exceeds the {max_bytes}-byte budget"
            )
        for part_index, part in enumerate(_split_to_budget(section.text, body_budget)):
            text = _compose(source.page_title, section.title, part)
            chunks.append(
                _to_chunk(
                    source,
                    title,
                    text,
                    page_id=page_id,
                    section_index=section_index,
                    part_index=part_index,
                    intent=section.intent,
                    side=section.side,
                    is_history=section.is_history,
                    is_misc=section.is_misc,
                )
            )
        section_index += 1
    return chunks


def reconstruct_page(chunks: Sequence[KnowledgeChunk]) -> str:
    """Reassemble the chunks of one page in deterministic reading order.

    Retrieval headers are removed before joining. The result reconstructs the
    cleaned page/section text, not the original wikitext markup.
    """

    ordered = sorted(
        chunks,
        key=lambda chunk: (
            chunk.section_index if chunk.section_index is not None else -1,
            chunk.part_index,
        ),
    )
    return "\n\n".join(_chunk_body(chunk) for chunk in ordered if chunk.text.strip())


def _chunk_body(chunk: KnowledgeChunk) -> str:
    """Remove the retrieval headers repeated in each stored chunk."""

    text = chunk.text.strip()
    if chunk.page_id and "::" in chunk.page_id:
        page_title = chunk.page_id.split("::", 1)[1]
        if text.startswith(page_title):
            text = text[len(page_title) :].lstrip()
    if chunk.section_index is not None and chunk.section_title:
        if text.startswith(chunk.section_title):
            text = text[len(chunk.section_title) :].lstrip()
    return text


def _to_chunk(
    source: ChunkSource,
    title: str,
    text: str,
    *,
    page_id: str,
    section_index: int | None,
    part_index: int,
    intent: str | None = None,
    side: str | None = None,
    is_history: bool | None = None,
    is_misc: bool | None = None,
) -> KnowledgeChunk:
    return build_chunk(
        text=text,
        source=source.source,
        page_id=page_id,
        canonical_title=source.page_title,
        source_url=source.source_url,
        license_or_terms=source.license_or_terms,
        opening_name=source.opening_name,
        eco_code=source.eco_code,
        opening_node_id=source.opening_node_id,
        line_pgn=source.line_pgn,
        section_title=title,
        section_index=section_index,
        part_index=part_index,
        intent=source.intent if intent is None else intent,
        side=source.side if side is None else side,
        is_history=source.is_history if is_history is None else is_history,
        is_misc=source.is_misc if is_misc is None else is_misc,
    )


def _compose(*parts: str | None) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def _split_to_budget(text: str, max_bytes: int) -> list[str]:
    if max_bytes <= 0:
        raise ChunkerError("max_bytes must be positive")
    if utf8_length(text) <= max_bytes:
        return [text]

    parts: list[str] = []
    for block in text.split("\n\n"):
        if utf8_length(block) <= max_bytes:
            parts.append(block)
        else:
            parts.extend(_split_block(block, max_bytes))
    return [part for part in parts if part.strip()]


def _split_block(block: str, max_bytes: int) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    current_length = 0

    for word in block.split():
        word_length = utf8_length(word)
        if word_length > max_bytes:
            if current:
                parts.append(" ".join(current))
                current, current_length = [], 0
            parts.extend(_hard_slice(word, max_bytes))
            continue

        separator = 1 if current else 0
        if current_length + word_length + separator > max_bytes:
            parts.append(" ".join(current))
            current, current_length = [word], word_length
        else:
            current.append(word)
            current_length += word_length + separator

    if current:
        parts.append(" ".join(current))
    return parts


def _hard_slice(text: str, max_bytes: int) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    current_length = 0

    for character in text:
        character_length = utf8_length(character)
        if current_length + character_length > max_bytes:
            parts.append("".join(current))
            current, current_length = [character], character_length
        else:
            current.append(character)
            current_length += character_length

    if current:
        parts.append("".join(current))
    return parts
