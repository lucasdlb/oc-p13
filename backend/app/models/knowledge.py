"""Common knowledge schema shared by ingestion adapters and the retrieval store."""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def chunk_id(
    *,
    source: str,
    page_id: str | None,
    section_index: int | None,
    part_index: int,
    text: str,
) -> str:
    """Stable vector identity: source + chunk location + text only."""

    identity = {
        "source": source,
        "page_id": page_id,
        "section_index": section_index,
        "part_index": part_index,
        "text": text,
    }
    return hashlib.sha256(
        repr(sorted(identity.items())).encode("utf-8")
    ).hexdigest()


def page_identifier(source: str, page_title: str) -> str:
    """Readable, deterministic page identity used to reassemble section chunks."""
    return f"{source}::{page_title}"


@dataclass(frozen=True)
class KnowledgeChunk:
    id: str
    text: str
    source: str
    page_id: str
    canonical_title: str
    section_index: int | None
    part_index: int = 0
    section_title: str | None = None
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
    created_at: str = field(default_factory=utc_now_iso)


def build_chunk(
    *,
    text: str,
    source: str,
    page_id: str,
    canonical_title: str,
    section_index: int | None,
    part_index: int = 0,
    section_title: str | None = None,
    source_url: str | None = None,
    license_or_terms: str | None = None,
    opening_name: str | None = None,
    eco_code: str | None = None,
    opening_node_id: str | None = None,
    line_pgn: str | None = None,
    intent: str = "misc",
    side: str | None = None,
    is_history: bool = False,
    is_misc: bool = True,
    created_at: str | None = None,
) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=chunk_id(
            source=source,
            page_id=page_id,
            section_index=section_index,
            part_index=part_index,
            text=text,
        ),
        text=text,
        source=source,
        page_id=page_id,
        canonical_title=canonical_title,
        section_index=section_index,
        part_index=part_index,
        section_title=section_title,
        source_url=source_url,
        license_or_terms=license_or_terms,
        opening_name=opening_name,
        eco_code=eco_code,
        opening_node_id=opening_node_id,
        line_pgn=line_pgn,
        intent=intent,
        side=side,
        is_history=is_history,
        is_misc=is_misc,
        created_at=created_at or utc_now_iso(),
    )


@dataclass(frozen=True)
class EmbeddedChunk:
    chunk: KnowledgeChunk
    vector: list[float]


@dataclass(frozen=True)
class ScoredChunk:
    chunk: KnowledgeChunk
    score: float
