"""Incremental, resumable ingestion behind one offline interface."""

import hashlib
import json
import time
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

from backend.app.models.knowledge import EmbeddedChunk, KnowledgeChunk


class IngestionError(RuntimeError):
    """Raised when a snapshot cannot be synchronized safely."""


@dataclass(frozen=True)
class IngestReport:
    requested: int
    already_present: int
    reused: int
    embedded: int
    inserted: int
    final_count: int
    timings_seconds: dict[str, float]


class IngestionStore(Protocol):
    def storage_compatibility(self) -> dict: ...

    def existing_ids(self, ids: Sequence[str]) -> set[str]: ...

    def list_ids(self) -> set[str]: ...

    def get_vectors(self, ids: Sequence[str]) -> dict[str, list[float]]: ...

    def upsert(self, records: Sequence[EmbeddedChunk]) -> int: ...


class DocumentEmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


def sync_collection(
    chunks: Iterable[KnowledgeChunk],
    target_store: IngestionStore,
    embedding_provider: DocumentEmbeddingProvider,
    reuse_from_store: IngestionStore | None = None,
    *,
    batch_size: int = 64,
) -> IngestReport:
    """Make a target contain exactly the desired snapshot without destructive writes.

    Existing target records are retained, compatible predecessor vectors are copied
    with current metadata, and only the remaining chunks are embedded. Every query
    and write is bounded by ``batch_size`` and the final ID set is checked exactly.
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    started = time.perf_counter()
    desired = _unique_chunks(chunks)
    desired_by_id = {chunk.id: chunk for chunk in desired}
    expected_ids = set(desired_by_id)
    timings = {name: 0.0 for name in ("inspect", "reuse", "embed", "upsert", "verify")}

    stage = time.perf_counter()
    if reuse_from_store is not None:
        _assert_compatible(target_store, reuse_from_store)
    present_ids = target_store.existing_ids([chunk.id for chunk in desired])
    actual_ids = target_store.list_ids()
    unexpected = actual_ids - expected_ids
    if unexpected:
        raise IngestionError(
            f"target contains {len(unexpected)} unexpected IDs: {sorted(unexpected)[:5]}"
        )
    if present_ids != actual_ids:
        raise IngestionError("target ID lookup was inconsistent with its complete ID listing")
    timings["inspect"] = time.perf_counter() - stage

    missing_ids = [chunk.id for chunk in desired if chunk.id not in present_ids]
    reused = 0
    if reuse_from_store is not None and missing_ids:
        stage = time.perf_counter()
        reusable_ids = reuse_from_store.existing_ids(missing_ids)
        reusable_ordered = [identifier for identifier in missing_ids if identifier in reusable_ids]
        timings["reuse"] = time.perf_counter() - stage

        for identifiers in _batched(reusable_ordered, batch_size):
            reuse_started = time.perf_counter()
            vectors = reuse_from_store.get_vectors(identifiers)
            timings["reuse"] += time.perf_counter() - reuse_started
            if set(vectors) != set(identifiers):
                raise IngestionError("predecessor did not return every reusable vector")
            records = [
                EmbeddedChunk(chunk=desired_by_id[identifier], vector=vectors[identifier])
                for identifier in identifiers
            ]
            write_started = time.perf_counter()
            target_store.upsert(records)
            timings["upsert"] += time.perf_counter() - write_started
            reused += len(records)
        missing_ids = [identifier for identifier in missing_ids if identifier not in reusable_ids]

    # IDs alone do not identify mutable metadata. Re-upsert present records with
    # their existing vectors so a resumed explicit target matches the snapshot.
    present_ordered = [chunk.id for chunk in desired if chunk.id in present_ids]
    for identifiers in _batched(present_ordered, batch_size):
        reuse_started = time.perf_counter()
        vectors = target_store.get_vectors(identifiers)
        timings["reuse"] += time.perf_counter() - reuse_started
        if set(vectors) != set(identifiers):
            raise IngestionError("target did not return every existing vector")
        records = [
            EmbeddedChunk(chunk=desired_by_id[identifier], vector=vectors[identifier])
            for identifier in identifiers
        ]
        write_started = time.perf_counter()
        target_store.upsert(records)
        timings["upsert"] += time.perf_counter() - write_started

    embedded = 0
    for identifiers in _batched(missing_ids, batch_size):
        texts = [desired_by_id[identifier].text for identifier in identifiers]
        embed_started = time.perf_counter()
        vectors = embedding_provider.embed_documents(texts)
        timings["embed"] += time.perf_counter() - embed_started
        if len(vectors) != len(identifiers):
            raise IngestionError("embedding provider response does not match request size")
        records = [
            EmbeddedChunk(chunk=desired_by_id[identifier], vector=vector)
            for identifier, vector in zip(identifiers, vectors, strict=True)
        ]
        write_started = time.perf_counter()
        target_store.upsert(records)
        timings["upsert"] += time.perf_counter() - write_started
        embedded += len(records)

    stage = time.perf_counter()
    final_ids = target_store.list_ids()
    if final_ids != expected_ids:
        missing = expected_ids - final_ids
        extra = final_ids - expected_ids
        raise IngestionError(
            f"final snapshot ID mismatch: {len(missing)} missing, {len(extra)} unexpected"
        )
    timings["verify"] = time.perf_counter() - stage
    timings["total"] = time.perf_counter() - started

    return IngestReport(
        requested=len(desired),
        already_present=len(present_ids),
        reused=reused,
        embedded=embedded,
        inserted=reused + embedded,
        final_count=len(final_ids),
        timings_seconds=timings,
    )


def snapshot_hash(chunks: Iterable[KnowledgeChunk]) -> str:
    """Hash IDs and significant current metadata, excluding volatile creation time."""

    canonical = sorted((_canonical_chunk(chunk) for chunk in _unique_chunks(chunks)), key=lambda row: row["id"])
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _unique_chunks(chunks: Iterable[KnowledgeChunk]) -> list[KnowledgeChunk]:
    unique: dict[str, KnowledgeChunk] = {}
    canonical: dict[str, dict] = {}
    for chunk in chunks:
        current = _canonical_chunk(chunk)
        if chunk.id in canonical and canonical[chunk.id] != current:
            raise IngestionError(f"duplicate desired ID {chunk.id!r} has conflicting content or metadata")
        canonical[chunk.id] = current
        unique.setdefault(chunk.id, chunk)
    return list(unique.values())


def _canonical_chunk(chunk: KnowledgeChunk) -> dict:
    value = asdict(chunk)
    value.pop("created_at", None)
    return value


def _assert_compatible(target: IngestionStore, predecessor: IngestionStore) -> None:
    required = (
        "schema_version",
        "embedding",
        "dimension",
        "metric_type",
        "index_type",
        "index_m",
        "index_ef_construction",
        "max_text_length",
        "vector_format",
    )
    target_compatibility = target.storage_compatibility()
    predecessor_compatibility = predecessor.storage_compatibility()
    mismatches = [
        key
        for key in required
        if key != "schema_version"
        and target_compatibility.get(key) != predecessor_compatibility.get(key)
    ]
    target_schema = target_compatibility.get("schema_version")
    predecessor_schema = predecessor_compatibility.get("schema_version")
    schemas_compatible = target_schema == predecessor_schema or (
        isinstance(predecessor_schema, int)
        and isinstance(target_schema, int)
        and 2 <= predecessor_schema < target_schema
    )
    if not schemas_compatible:
        mismatches.append("schema_version")
    if mismatches:
        raise IngestionError(
            "predecessor storage is incompatible for vector reuse: " + ", ".join(mismatches)
        )


def _batched(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
