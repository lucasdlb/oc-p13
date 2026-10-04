import pytest

from backend.app.core.settings import MilvusSettings
from backend.app.models.knowledge import EmbeddedChunk, KnowledgeChunk
from backend.app.services.milvus import MilvusMetadataFilter, MilvusStore, MilvusStoreError


@pytest.fixture
def store(tmp_path) -> MilvusStore:  # type: ignore[no-untyped-def]
    settings = MilvusSettings(
        uri=str(tmp_path / "milvus.db"),
        collection="test_knowledge",
        dimension=4,
        max_text_length=2000,
    )
    milvus = MilvusStore(settings)
    yield milvus
    milvus.close()


def _embedded(
    identifier: str,
    text: str,
    vector: list[float],
    **metadata: object,
) -> EmbeddedChunk:
    chunk = KnowledgeChunk(
        id=identifier,
        text=text,
        source=str(metadata.pop("source", "test-source")),
        page_id=str(metadata.pop("page_id", "test-source::page")),
        canonical_title=str(metadata.pop("canonical_title", "Page")),
        section_index=metadata.pop("section_index", 0),  # type: ignore[arg-type]
        created_at="2026-01-01T00:00:00+00:00",
        **metadata,  # type: ignore[arg-type]
    )
    return EmbeddedChunk(chunk=chunk, vector=vector)


def test_upsert_then_search_round_trip(store: MilvusStore) -> None:
    store.upsert(
        [
            _embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0], eco_code="C60"),
            _embedded("b", "sicilian", [0.0, 1.0, 0.0, 0.0], eco_code="B90"),
        ]
    )

    results = store.search([1.0, 0.0, 0.0, 0.0], k=5)

    assert [result.chunk.id for result in results] == ["a", "b"]
    assert results[0].score == pytest.approx(1.0, abs=1e-5)
    assert results[0].chunk.text == "ruy lopez"
    assert results[0].chunk.eco_code == "C60"


def test_search_filters_by_eco_code(store: MilvusStore) -> None:
    store.upsert(
        [
            _embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0], eco_code="C60"),
            _embedded("b", "sicilian", [1.0, 0.0, 0.0, 0.0], eco_code="B90"),
        ]
    )

    results = store.search([1.0, 0.0, 0.0, 0.0], k=5, eco_code="C60")

    assert [result.chunk.id for result in results] == ["a"]


def test_search_normalizes_lowercase_eco_code_filter(store: MilvusStore) -> None:
    store.upsert(
        [
            _embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0], eco_code="C60"),
            _embedded("b", "sicilian", [1.0, 0.0, 0.0, 0.0], eco_code="B90"),
        ]
    )

    results = store.search([1.0, 0.0, 0.0, 0.0], k=5, eco_code="c60")

    assert [result.chunk.id for result in results] == ["a"]


def test_search_ignores_invalid_eco_code_filter(store: MilvusStore) -> None:
    store.upsert([_embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0], eco_code="C60")])

    results = store.search([1.0, 0.0, 0.0, 0.0], k=5, eco_code='C60" or "1"=="1')

    assert len(results) == 1


def test_search_ignores_eco_code_with_trailing_newline(store: MilvusStore) -> None:
    store.upsert(
        [
            _embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0], eco_code="C60"),
            _embedded("b", "sicilian", [0.0, 1.0, 0.0, 0.0], eco_code="B90"),
        ]
    )

    results = store.search([1.0, 0.0, 0.0, 0.0], k=5, eco_code="C60\n")

    assert {result.chunk.id for result in results} == {"a", "b"}


def test_search_filters_by_opening_node_ids(store: MilvusStore) -> None:
    store.upsert(
        [
            _embedded("a", "ruy", [1.0, 0.0, 0.0, 0.0], opening_node_id="ruy-node"),
            _embedded("b", "berlin", [1.0, 0.0, 0.0, 0.0], opening_node_id="berlin-node"),
            _embedded("c", "morphy", [1.0, 0.0, 0.0, 0.0], opening_node_id="morphy-node"),
        ]
    )

    results = store.search(
        [1.0, 0.0, 0.0, 0.0],
        k=5,
        metadata_filter=MilvusMetadataFilter(opening_node_ids=("berlin-node", "morphy-node")),
    )

    assert [result.chunk.id for result in results] == ["b", "c"]


def test_search_filters_by_intent_inclusion_and_exclusion(store: MilvusStore) -> None:
    store.upsert(
        [
            _embedded("plan", "plan", [1.0, 0.0, 0.0, 0.0], intent="plan", is_history=False, is_misc=False),
            _embedded("history", "history", [1.0, 0.0, 0.0, 0.0], intent="history", is_history=True, is_misc=False),
            _embedded("misc", "misc", [1.0, 0.0, 0.0, 0.0], intent="misc", is_history=False, is_misc=True),
        ]
    )

    history = store.search(
        [1.0, 0.0, 0.0, 0.0],
        k=5,
        metadata_filter=MilvusMetadataFilter(intent_in=("history",), is_history=True),
    )
    non_misc = store.search(
        [1.0, 0.0, 0.0, 0.0],
        k=5,
        metadata_filter=MilvusMetadataFilter(intent_not_in=("misc",), is_misc=False),
    )

    assert [result.chunk.id for result in history] == ["history"]
    assert [result.chunk.id for result in non_misc] == ["plan", "history"]


def test_metadata_filter_rejects_suspicious_values() -> None:
    with pytest.raises(MilvusStoreError, match="opening_node_id"):
        MilvusMetadataFilter(opening_node_ids=('ruy-node" or true',)).to_expression()

    with pytest.raises(MilvusStoreError, match="intent"):
        MilvusMetadataFilter(intent_in=("history\n",)).to_expression()


def test_search_combines_eco_and_metadata_filters_safely() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.filter: str | None = None

        def search(self, **kwargs):  # type: ignore[no-untyped-def]
            self.filter = kwargs["filter"]
            return [[]]

    client = FakeClient()
    store = MilvusStore(MilvusSettings(collection="c", dimension=4))
    store._client = client  # type: ignore[assignment]
    store._ensured = True

    store.search(
        [1.0, 0.0, 0.0, 0.0],
        k=5,
        eco_code="C60",
        metadata_filter=MilvusMetadataFilter(source=("wikibooks",), page_id=("wikibooks::Ruy_Lopez",)),
    )

    assert client.filter == 'eco_code == "C60" and source == "wikibooks" and page_id == "wikibooks::Ruy_Lopez"'


def test_upsert_is_idempotent_by_id(store: MilvusStore) -> None:
    store.upsert([_embedded("same", "first text", [1.0, 0.0, 0.0, 0.0])])
    store.upsert([_embedded("same", "updated text", [1.0, 0.0, 0.0, 0.0])])

    results = store.search([1.0, 0.0, 0.0, 0.0], k=5)

    assert store.count() == 1
    assert [result.chunk.text for result in results] == ["updated text"]


def test_batch_id_and_vector_interfaces(store: MilvusStore) -> None:
    store.upsert(
        [
            _embedded("a", "first", [1.0, 0.0, 0.0, 0.0]),
            _embedded("b", "second", [0.0, 1.0, 0.0, 0.0]),
        ]
    )

    assert store.existing_ids(["missing", "b", "a"]) == {"a", "b"}
    assert store.list_ids() == {"a", "b"}
    assert store.get_vectors(["missing", "b"]) == {"b": [0.0, 1.0, 0.0, 0.0]}


def test_storage_compatibility_includes_physical_index(store: MilvusStore) -> None:
    store.upsert([_embedded("a", "first", [1.0, 0.0, 0.0, 0.0])])

    compatibility = store.storage_compatibility()

    assert compatibility["index_type"] == "HNSW"
    assert compatibility["index_m"] == 16
    assert compatibility["index_ef_construction"] == 200
    assert compatibility["max_text_length"] == 2000


def test_search_applies_min_score(store: MilvusStore) -> None:
    store.upsert(
        [
            _embedded("close", "close", [1.0, 0.0, 0.0, 0.0]),
            _embedded("far", "far", [0.0, 1.0, 0.0, 0.0]),
        ]
    )

    results = store.search([1.0, 0.0, 0.0, 0.0], k=5, min_score=0.5)

    assert [result.chunk.id for result in results] == ["close"]


def test_search_on_empty_collection_returns_empty(store: MilvusStore) -> None:
    assert store.search([1.0, 0.0, 0.0, 0.0], k=5) == []


def test_available_true_for_lite_store(store: MilvusStore) -> None:
    assert store.available() is True


def test_drop_removes_collection(store: MilvusStore) -> None:
    store.upsert([_embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0])])

    store.drop()

    assert store.search([1.0, 0.0, 0.0, 0.0], k=5) == []


def test_drop_clears_recorded_manifest(store: MilvusStore) -> None:
    store.upsert([_embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0])])
    store.storage_compatibility()

    store.drop()

    assert store._recorded_manifest is None


def test_search_uses_at_least_k_for_hnsw_ef() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.search_params: dict | None = None

        def search(self, **kwargs):  # type: ignore[no-untyped-def]
            self.search_params = kwargs["search_params"]
            return [[]]

    client = FakeClient()
    store = MilvusStore(MilvusSettings(collection="c", dimension=4, search_ef=2))
    store._client = client  # type: ignore[assignment]
    store._ensured = True

    store.search([1.0, 0.0, 0.0, 0.0], k=5)

    assert client.search_params == {"metric_type": "COSINE", "params": {"ef": 5}}


def test_upsert_batches_rows(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeClient:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def upsert(self, *, collection_name: str, data: list[dict]) -> None:
            self.batch_sizes.append(len(data))

    monkeypatch.setattr("backend.app.services.milvus._UPSERT_BATCH_SIZE", 2)
    client = FakeClient()
    store = MilvusStore(MilvusSettings(collection="c", dimension=4))
    store._client = client  # type: ignore[assignment]
    store._ensured = True

    count = store.upsert(
        [
            _embedded("a", "a", [1.0, 0.0, 0.0, 0.0]),
            _embedded("b", "b", [1.0, 0.0, 0.0, 0.0]),
            _embedded("c", "c", [1.0, 0.0, 0.0, 0.0]),
        ]
    )

    assert count == 3
    assert client.batch_sizes == [2, 1]


def test_page_identity_and_ordering_round_trip(store: MilvusStore) -> None:
    store.upsert(
        [
            _embedded(
                "a",
                "first",
                [1.0, 0.0, 0.0, 0.0],
                page_id="src::page",
                section_index=0,
                part_index=0,
            ),
            _embedded(
                "b",
                "second",
                [1.0, 0.0, 0.0, 0.0],
                page_id="src::page",
                section_index=0,
                part_index=1,
            ),
        ]
    )

    results = store.search([1.0, 0.0, 0.0, 0.0], k=5)

    by_id = {result.chunk.id: result.chunk for result in results}
    assert by_id["a"].page_id == "src::page"
    assert by_id["b"].section_index == 0
    assert by_id["b"].part_index == 1
    assert [chunk.id for chunk in store.fetch_page("src::page")] == ["a", "b"]


def test_reusing_a_compatible_collection_succeeds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = MilvusSettings(uri=str(tmp_path / "m.db"), collection="c", dimension=4)

    first = MilvusStore(settings, embedding_signature="model@rev")
    first.upsert([_embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0])])
    first.close()

    second = MilvusStore(settings, embedding_signature="model@rev")
    try:
        assert [result.chunk.id for result in second.search([1.0, 0.0, 0.0, 0.0], k=5)] == ["a"]
    finally:
        second.close()


def test_collection_without_manifest_is_rejected(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = MilvusSettings(uri=str(tmp_path / "m.db"), collection="c", dimension=4)
    first = MilvusStore(settings, embedding_signature="model@rev")
    first.upsert([_embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0])])
    first.close()

    monkeypatch.setattr("backend.app.services.milvus._read_manifest", lambda _info: None)
    second = MilvusStore(settings, embedding_signature="model@rev")
    try:
        with pytest.raises(MilvusStoreError):
            second.search([1.0, 0.0, 0.0, 0.0], k=5)
    finally:
        second.close()


def test_read_only_store_does_not_create_a_missing_collection(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = MilvusSettings(uri=str(tmp_path / "m.db"), collection="missing", dimension=4)
    read_only = MilvusStore(settings, create_if_missing=False)
    try:
        with pytest.raises(MilvusStoreError, match="does not exist"):
            read_only.list_ids()
    finally:
        read_only.close()

    writable = MilvusStore(settings)
    try:
        assert writable.list_ids() == set()
    finally:
        writable.close()


def test_incompatible_embedding_signature_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = MilvusSettings(uri=str(tmp_path / "m.db"), collection="c", dimension=4)

    first = MilvusStore(settings, embedding_signature="model@rev1")
    first.upsert([_embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0])])
    first.close()

    second = MilvusStore(settings, embedding_signature="model@rev2")
    try:
        with pytest.raises(MilvusStoreError):
            second.search([1.0, 0.0, 0.0, 0.0], k=5)
    finally:
        second.close()


def test_legacy_schema_two_is_read_only_and_allowed_as_explicit_source(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    settings = MilvusSettings(uri=str(tmp_path / "m.db"), collection="c", dimension=4)
    first = MilvusStore(settings, embedding_signature="model@rev")
    first.upsert([_embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0])])
    legacy_manifest = {**first.manifest(), "schema_version": 2}
    first.close()
    monkeypatch.setattr("backend.app.services.milvus._read_manifest", lambda _info: legacy_manifest)

    target = MilvusStore(settings, embedding_signature="model@rev")
    try:
        with pytest.raises(MilvusStoreError):
            target.list_ids()
    finally:
        target.close()

    source = MilvusStore(
        settings,
        embedding_signature="model@rev",
        create_if_missing=False,
        allow_legacy_source=True,
    )
    try:
        assert source.list_ids() == {"a"}
        assert source.storage_compatibility()["schema_version"] == 2
    finally:
        source.close()


def test_incompatible_dimension_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    first = MilvusStore(MilvusSettings(uri=str(tmp_path / "m.db"), collection="c", dimension=4))
    first.upsert([_embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0])])
    first.close()

    second = MilvusStore(MilvusSettings(uri=str(tmp_path / "m.db"), collection="c", dimension=8))
    try:
        with pytest.raises(MilvusStoreError):
            second.search([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], k=5)
    finally:
        second.close()


def test_search_ef_does_not_invalidate_stored_vectors(tmp_path) -> None:  # type: ignore[no-untyped-def]
    base = MilvusSettings(
        uri=str(tmp_path / "m.db"), collection="c", dimension=4, search_ef=32
    )
    first = MilvusStore(base, embedding_signature="model@rev")
    first.upsert([_embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0])])
    fingerprint = first.fingerprint()
    first.close()

    second = MilvusStore(
        base.model_copy(update={"search_ef": 256}), embedding_signature="model@rev"
    )
    try:
        assert second.list_ids() == {"a"}
        assert second.fingerprint() == fingerprint
    finally:
        second.close()


def test_collection_provenance_is_recorded_but_not_part_of_storage_fingerprint(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = MilvusSettings(uri=str(tmp_path / "m.db"), collection="c", dimension=4)
    provenance = {"snapshot_id": "wb-one", "snapshot_hash": "hash-one"}
    first = MilvusStore(settings, embedding_signature="model@rev", collection_provenance=provenance)
    first.upsert([_embedded("a", "ruy lopez", [1.0, 0.0, 0.0, 0.0])])
    fingerprint = first.fingerprint()
    assert first.manifest()["corpus"] == provenance
    first.close()

    same = MilvusStore(settings, embedding_signature="model@rev", collection_provenance=provenance)
    try:
        assert same.list_ids() == {"a"}
        assert same.fingerprint() == fingerprint
    finally:
        same.close()

    different = MilvusStore(
        settings,
        embedding_signature="model@rev",
        collection_provenance={"snapshot_id": "wb-two", "snapshot_hash": "hash-two"},
    )
    try:
        with pytest.raises(MilvusStoreError, match="provenance"):
            different.list_ids()
    finally:
        different.close()


def test_text_over_the_utf8_byte_limit_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = MilvusSettings(
        uri=str(tmp_path / "m.db"), collection="c", dimension=4, max_text_length=10
    )
    store = MilvusStore(settings)
    try:
        with pytest.raises(MilvusStoreError):
            store.upsert([_embedded("a", "é" * 6, [1.0, 0.0, 0.0, 0.0])])
    finally:
        store.close()
