import pytest

from backend.app.ingestion.pipeline import IngestionError, snapshot_hash, sync_collection
from backend.app.services.embeddings import EmbeddingProviderError
from backend.app.models.knowledge import EmbeddedChunk, KnowledgeChunk


COMPATIBILITY = {
    "schema_version": 3,
    "embedding": "model@sha256:abc",
    "dimension": 2,
    "metric_type": "COSINE",
    "index_type": "HNSW",
    "index_m": 16,
    "index_ef_construction": 200,
    "max_text_length": 8000,
    "vector_format": "float32",
}


class FakeStore:
    def __init__(
        self,
        records: list[EmbeddedChunk] | None = None,
        *,
        compatibility: dict | None = None,
    ) -> None:
        self.records = {record.chunk.id: record for record in records or []}
        self.compatibility = compatibility or COMPATIBILITY
        self.upsert_batches: list[list[str]] = []

    def storage_compatibility(self) -> dict:
        return self.compatibility

    def existing_ids(self, ids: list[str]) -> set[str]:
        return set(ids) & self.records.keys()

    def list_ids(self) -> set[str]:
        return set(self.records)

    def get_vectors(self, ids: list[str]) -> dict[str, list[float]]:
        return {identifier: self.records[identifier].vector for identifier in ids if identifier in self.records}

    def upsert(self, records: list[EmbeddedChunk]) -> int:
        self.upsert_batches.append([record.chunk.id for record in records])
        self.records.update({record.chunk.id: record for record in records})
        return len(records)


class RecordingProvider:
    dimension = 2

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(texts)
        return [[float(len(text)), 0.0] for text in texts]


class FailingProvider(RecordingProvider):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingProviderError("provider failed")


def _chunk(identifier: str, text: str | None = None, **metadata: object) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=identifier,
        text=text or identifier,
        source="test",
        page_id=str(metadata.pop("page_id", "test::page")),
        canonical_title=str(metadata.pop("canonical_title", "Page")),
        section_index=metadata.pop("section_index", 0),  # type: ignore[arg-type]
        created_at="2026-10-02T00:00:00+00:00",
        **metadata,  # type: ignore[arg-type]
    )


def test_empty_target_embeds_and_inserts_every_chunk_in_bounded_batches() -> None:
    target = FakeStore()
    provider = RecordingProvider()

    report = sync_collection(
        [_chunk("a"), _chunk("b"), _chunk("c")],
        target,
        provider,
        batch_size=2,
    )

    assert provider.batches == [["a", "b"], ["c"]]
    assert target.upsert_batches == [["a", "b"], ["c"]]
    assert report.requested == 3
    assert report.already_present == 0
    assert report.reused == 0
    assert report.embedded == 3
    assert report.inserted == 3
    assert report.final_count == 3
    assert set(report.timings_seconds) == {"inspect", "reuse", "embed", "upsert", "verify", "total"}


def test_complete_target_embeds_nothing() -> None:
    chunks = [_chunk("a"), _chunk("b")]
    target = FakeStore(
        [EmbeddedChunk(chunk=chunk, vector=[1.0, 0.0]) for chunk in chunks]
    )
    provider = RecordingProvider()

    report = sync_collection(chunks, target, provider)

    assert provider.batches == []
    assert target.upsert_batches == [["a", "b"]]
    assert (report.already_present, report.embedded, report.inserted, report.final_count) == (2, 0, 0, 2)


def test_complete_target_refreshes_metadata_without_embedding() -> None:
    stored = _chunk("a", opening_name="Old name")
    desired = _chunk("a", opening_name="Current name")
    target = FakeStore([EmbeddedChunk(chunk=stored, vector=[0.25, 0.75])])
    provider = RecordingProvider()

    report = sync_collection([desired], target, provider)

    assert provider.batches == []
    assert report.already_present == 1
    assert report.embedded == 0
    assert target.records["a"].vector == [0.25, 0.75]
    assert target.records["a"].chunk.opening_name == "Current name"


def test_partial_target_embeds_only_missing_chunks() -> None:
    chunks = [_chunk("a"), _chunk("b"), _chunk("c")]
    target = FakeStore([EmbeddedChunk(chunk=chunks[0], vector=[1.0, 0.0])])
    provider = RecordingProvider()

    report = sync_collection(chunks, target, provider)

    assert provider.batches == [["b", "c"]]
    assert report.already_present == 1
    assert report.embedded == 2


def test_compatible_predecessor_reuses_intersection_with_current_metadata() -> None:
    old_a = _chunk("a", opening_name="Old name")
    desired_a = _chunk("a", opening_name="Current name")
    desired_b = _chunk("b")
    predecessor = FakeStore([EmbeddedChunk(chunk=old_a, vector=[0.25, 0.75])])
    target = FakeStore()
    provider = RecordingProvider()

    report = sync_collection([desired_a, desired_b], target, provider, predecessor)

    assert report.reused == 1
    assert report.embedded == 1
    assert target.records["a"].vector == [0.25, 0.75]
    assert target.records["a"].chunk.opening_name == "Current name"
    assert provider.batches == [["b"]]
    assert predecessor.records["a"].chunk.opening_name == "Old name"


def test_incompatible_predecessor_fails_before_writing() -> None:
    predecessor = FakeStore(
        [EmbeddedChunk(chunk=_chunk("a"), vector=[1.0, 0.0])],
        compatibility={**COMPATIBILITY, "embedding": "other@sha256:def"},
    )
    target = FakeStore()
    provider = RecordingProvider()

    with pytest.raises(IngestionError, match="embedding"):
        sync_collection([_chunk("a")], target, provider, predecessor)

    assert target.records == {}
    assert target.upsert_batches == []
    assert provider.batches == []


def test_physical_index_mismatch_fails_before_reuse() -> None:
    predecessor = FakeStore(
        [EmbeddedChunk(chunk=_chunk("a"), vector=[1.0, 0.0])],
        compatibility={**COMPATIBILITY, "index_m": 32},
    )
    target = FakeStore()
    provider = RecordingProvider()

    with pytest.raises(IngestionError, match="index_m"):
        sync_collection([_chunk("a")], target, provider, predecessor)

    assert target.records == {}
    assert provider.batches == []


@pytest.mark.parametrize(
    "target_ids",
    [["unexpected"], ["a", "unexpected"]],
    ids=["same-cardinality-different-id", "extra-id"],
)
def test_unexpected_target_ids_fail(target_ids: list[str]) -> None:
    target = FakeStore(
        [EmbeddedChunk(chunk=_chunk(identifier), vector=[1.0, 0.0]) for identifier in target_ids]
    )

    with pytest.raises(IngestionError, match="unexpected IDs"):
        sync_collection([_chunk("a")], target, RecordingProvider())


def test_provider_failure_keeps_predecessor_unchanged_and_target_resumable() -> None:
    predecessor_record = EmbeddedChunk(chunk=_chunk("a"), vector=[0.25, 0.75])
    predecessor = FakeStore([predecessor_record])
    target = FakeStore()
    desired = [_chunk("a"), _chunk("b")]

    with pytest.raises(EmbeddingProviderError):
        sync_collection(desired, target, FailingProvider(), predecessor)

    assert predecessor.records == {"a": predecessor_record}
    assert set(target.records) == {"a"}

    report = sync_collection(desired, target, RecordingProvider(), predecessor)
    assert report.already_present == 1
    assert report.reused == 0
    assert report.embedded == 1
    assert report.final_count == 2


def test_duplicate_id_with_conflicting_metadata_is_rejected() -> None:
    with pytest.raises(IngestionError, match="duplicate desired ID"):
        sync_collection(
            [_chunk("same", opening_name="first"), _chunk("same", opening_name="second")],
            FakeStore(),
            RecordingProvider(),
        )


def test_snapshot_hash_includes_metadata_but_excludes_created_at() -> None:
    original = _chunk("a", opening_name="Ruy Lopez")
    later = KnowledgeChunk(**{**original.__dict__, "created_at": "2027-01-01T00:00:00+00:00"})
    changed = KnowledgeChunk(**{**original.__dict__, "opening_name": "Spanish Opening"})

    assert snapshot_hash([original]) == snapshot_hash([later])
    assert snapshot_hash([original]) != snapshot_hash([changed])
