"""Milvus store lifecycle.

One collection (`chess_knowledge`) with a single embedding model, dimension and
metric. Sources are separated by metadata, never by collection. The same client
serves Milvus Lite (a local file `uri`) for dev/tests and Milvus Standalone
(`http(s)://` uri) in the demo stack.

Every collection carries a JSON **manifest** in its description (schema version,
dimension, metric, index, embedding signature). Reusing an existing collection
requires an exact manifest match: a same-dimension model swap or a schema change
must force a reindex instead of silently mixing incompatible vectors. VARCHAR
limits are enforced in **UTF-8 bytes** (Milvus counts bytes, not characters).
"""

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass
from collections.abc import Iterator, Sequence

from pymilvus import DataType, MilvusClient

from backend.app.core.settings import MilvusSettings
from backend.app.models.knowledge import EmbeddedChunk, KnowledgeChunk, ScoredChunk


logger = logging.getLogger("backend.milvus")

SCHEMA_VERSION = 4

_MANIFEST_PROPERTY = "p13_manifest"

_ECO_CODE_PATTERN = re.compile(r"^[A-Za-z][0-9]{2}(-[A-Za-z]?[0-9]{2})?$")
_SAFE_FILTER_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/ -]{0,511}$")

_STRING_FIELDS = (
    "text",
    "source",
    "source_url",
    "license_or_terms",
    "page_id",
    "canonical_title",
    "opening_name",
    "eco_code",
    "opening_node_id",
    "line_pgn",
    "section_title",
    "intent",
    "side",
    "created_at",
)

_INT_FIELDS = ("section_index", "part_index")
_BOOL_FIELDS = ("is_history", "is_misc")

_OUTPUT_FIELDS = _STRING_FIELDS + _INT_FIELDS + _BOOL_FIELDS

_FIELD_LIMITS = {
    "source": 128,
    "created_at": 40,
    "source_url": 512,
    "license_or_terms": 128,
    "page_id": 512,
    "canonical_title": 512,
    "opening_name": 256,
    "eco_code": 16,
    "opening_node_id": 64,
    "line_pgn": 512,
    "section_title": 256,
    "intent": 64,
    "side": 16,
}

_QUERY_BATCH_SIZE = 1_000
_UPSERT_BATCH_SIZE = 500


class MilvusStoreError(RuntimeError):
    """Raised when Milvus cannot serve a read or write."""


@dataclass(frozen=True)
class MilvusMetadataFilter:
    opening_node_ids: tuple[str, ...] = ()
    intent_in: tuple[str, ...] = ()
    intent_not_in: tuple[str, ...] = ()
    source: tuple[str, ...] = ()
    page_id: tuple[str, ...] = ()
    is_history: bool | None = None
    is_misc: bool | None = None

    def to_expression(self) -> str | None:
        clauses: list[str] = []
        _append_string_clause(clauses, "opening_node_id", self.opening_node_ids)
        _append_string_clause(clauses, "intent", self.intent_in)
        _append_string_clause(clauses, "source", self.source)
        _append_string_clause(clauses, "page_id", self.page_id)
        _append_string_clause(clauses, "intent", self.intent_not_in, negate=True)
        if self.is_history is not None:
            clauses.append(f"is_history == {str(self.is_history).lower()}")
        if self.is_misc is not None:
            clauses.append(f"is_misc == {str(self.is_misc).lower()}")
        return " and ".join(clauses) if clauses else None


class MilvusStore:
    def __init__(
        self,
        settings: MilvusSettings,
        *,
        embedding_signature: str | None = None,
        collection_provenance: dict | None = None,
        create_if_missing: bool = True,
        allow_legacy_source: bool = False,
    ) -> None:
        self._settings = settings
        self._embedding_signature = embedding_signature
        self._collection_provenance = collection_provenance
        self._create_if_missing = create_if_missing
        self._allow_legacy_source = allow_legacy_source
        self._client: MilvusClient | None = None
        self._ensure_lock = threading.Lock()
        self._ensured = False
        self._recorded_manifest: dict | None = None

    def available(self) -> bool:
        try:
            self._client_or_create().list_collections()
        except Exception:  # noqa: BLE001 - any client/RPC failure means unavailable
            return False
        return True

    def ensure_collection(self) -> None:
        if self._ensured:
            return

        with self._ensure_lock:
            if self._ensured:
                return

            try:
                client = self._client_or_create()
                if not client.has_collection(self._settings.collection):
                    if not self._create_if_missing:
                        raise MilvusStoreError(
                            f"collection {self._settings.collection!r} does not exist"
                        )
                    self._create_collection(client)
                    self._recorded_manifest = self._manifest()
                else:
                    self._assert_compatible(client)
                client.load_collection(self._settings.collection)
            except MilvusStoreError:
                raise
            except Exception as exc:  # noqa: BLE001 - surfaced as a domain error
                raise MilvusStoreError(f"Milvus collection setup failed: {exc}") from exc

            self._ensured = True

    def upsert(self, records: Sequence[EmbeddedChunk]) -> int:
        if not records:
            return 0

        self.ensure_collection()
        try:
            rows = [self._row(record) for record in records]
            for batch in _batched(rows, _UPSERT_BATCH_SIZE):
                self._client_or_create().upsert(
                    collection_name=self._settings.collection,
                    data=list(batch),
                )
        except Exception as exc:  # noqa: BLE001 - surfaced as a domain error
            raise MilvusStoreError(f"Milvus upsert failed: {exc}") from exc
        return len(records)

    def search(
        self,
        vector: Sequence[float],
        k: int,
        *,
        eco_code: str | None = None,
        metadata_filter: MilvusMetadataFilter | None = None,
        min_score: float | None = None,
    ) -> list[ScoredChunk]:
        self.ensure_collection()
        try:
            response = self._client_or_create().search(
                collection_name=self._settings.collection,
                data=[list(vector)],
                limit=k,
                filter=self._search_filter(eco_code, metadata_filter),
                output_fields=["id", *_OUTPUT_FIELDS],
                search_params={
                    "metric_type": self._settings.metric_type,
                    "params": {"ef": max(self._settings.search_ef, k)},
                },
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a domain error
            raise MilvusStoreError(f"Milvus search failed: {exc}") from exc

        hits = response[0] if response else []
        results: list[ScoredChunk] = []
        for hit in hits:
            score = float(hit["distance"])
            if min_score is not None and score < min_score:
                continue
            results.append(ScoredChunk(chunk=self._chunk_from_hit(hit), score=score))
        return results

    def drop(self) -> None:
        self._ensured = False
        self._recorded_manifest = None
        try:
            client = self._client_or_create()
            if client.has_collection(self._settings.collection):
                client.drop_collection(self._settings.collection)
        except Exception as exc:  # noqa: BLE001 - surfaced as a domain error
            raise MilvusStoreError(f"Milvus drop failed: {exc}") from exc

    def count(self) -> int:
        self.ensure_collection()
        try:
            rows = self._client_or_create().query(
                collection_name=self._settings.collection,
                filter="",
                output_fields=["count(*)"],
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a domain error
            raise MilvusStoreError(f"Milvus count failed: {exc}") from exc

        if rows and isinstance(rows[0], dict):
            return int(rows[0].get("count(*)", 0))
        return 0

    def existing_ids(self, ids: Sequence[str]) -> set[str]:
        """Return the requested IDs that exist, using bounded batch queries."""

        self.ensure_collection()
        existing: set[str] = set()
        try:
            for batch in _batched(ids, _QUERY_BATCH_SIZE):
                rows = self._client_or_create().query(
                    collection_name=self._settings.collection,
                    filter=f"id in {json.dumps(list(batch))}",
                    output_fields=["id"],
                )
                existing.update(str(row["id"]) for row in rows if isinstance(row, dict) and "id" in row)
        except Exception as exc:  # noqa: BLE001 - surfaced as a domain error
            raise MilvusStoreError(f"Milvus ID lookup failed: {exc}") from exc
        return existing

    def list_ids(self) -> set[str]:
        """List every collection ID without relying on a fixed query result limit."""

        self.ensure_collection()
        iterator = None
        try:
            iterator = self._client_or_create().query_iterator(
                collection_name=self._settings.collection,
                batch_size=_QUERY_BATCH_SIZE,
                filter="",
                output_fields=["id"],
            )
            ids: set[str] = set()
            while rows := iterator.next():
                ids.update(str(row["id"]) for row in rows if isinstance(row, dict) and "id" in row)
            return ids
        except Exception as exc:  # noqa: BLE001 - surfaced as a domain error
            raise MilvusStoreError(f"Milvus ID listing failed: {exc}") from exc
        finally:
            if iterator is not None:
                iterator.close()

    def get_vectors(self, ids: Sequence[str]) -> dict[str, list[float]]:
        """Fetch vectors for the requested IDs using bounded batch queries."""

        self.ensure_collection()
        vectors: dict[str, list[float]] = {}
        try:
            for batch in _batched(ids, _QUERY_BATCH_SIZE):
                rows = self._client_or_create().query(
                    collection_name=self._settings.collection,
                    filter=f"id in {json.dumps(list(batch))}",
                    output_fields=["id", "vector"],
                )
                for row in rows:
                    if isinstance(row, dict) and "id" in row and isinstance(row.get("vector"), list):
                        vectors[str(row["id"])] = [float(value) for value in row["vector"]]
        except Exception as exc:  # noqa: BLE001 - surfaced as a domain error
            raise MilvusStoreError(f"Milvus vector fetch failed: {exc}") from exc
        return vectors

    def fetch_page(self, page_id: str) -> list[KnowledgeChunk]:
        """Fetch all chunks for a page in deterministic reconstruction order."""

        self.ensure_collection()
        escaped_page_id = page_id.replace("\\", "\\\\").replace('"', '\\"')
        try:
            rows = self._client_or_create().query(
                collection_name=self._settings.collection,
                filter=f'page_id == "{escaped_page_id}"',
                output_fields=["id", *_OUTPUT_FIELDS],
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a domain error
            raise MilvusStoreError(f"Milvus page fetch failed: {exc}") from exc

        chunks = [
            self._chunk_from_hit({"id": row["id"], "entity": row})
            for row in rows
            if isinstance(row, dict) and "id" in row
        ]
        return sorted(
            chunks,
            key=lambda chunk: (
                chunk.section_index if chunk.section_index is not None else -1,
                chunk.part_index,
            ),
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._ensured = False
            self._recorded_manifest = None

    def manifest(self) -> dict:
        return self._manifest()

    def storage_compatibility(self) -> dict:
        """Return only properties that determine whether vectors can be reused."""

        self.ensure_collection()
        manifest = self._recorded_manifest or self._manifest()
        return {
            "schema_version": manifest["schema_version"],
            "embedding": manifest["embedding"],
            "dimension": manifest["dimension"],
            "metric_type": manifest["metric_type"],
            "index_type": manifest["index_type"],
            "index_m": manifest["index_m"],
            "index_ef_construction": manifest["index_ef_construction"],
            "max_text_length": manifest["max_text_length"],
            "vector_format": "float32",
        }

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(_storage_manifest(self._manifest()), sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _manifest(self) -> dict:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "dimension": self._settings.dimension,
            "metric_type": self._settings.metric_type,
            "index_type": self._settings.index_type,
            "index_m": self._settings.index_m,
            "index_ef_construction": self._settings.index_ef_construction,
            "max_text_length": self._settings.max_text_length,
            "embedding": self._embedding_signature,
        }
        if self._collection_provenance is not None:
            manifest["corpus"] = self._collection_provenance
        return manifest

    def _create_collection(self, client: MilvusClient) -> None:
        manifest = json.dumps(self._manifest(), sort_keys=True)
        index_params = self._build_index(client)
        try:
            client.create_collection(
                self._settings.collection,
                schema=self._build_schema(client),
                index_params=index_params,
                description=manifest,
                properties={_MANIFEST_PROPERTY: manifest},
                consistency_level="Strong",
            )
        except Exception as first_exc:  # noqa: BLE001 - some deployments reject properties/index params
            logger.info(
                "Milvus create_collection with properties/index_params failed; falling back: %s",
                first_exc,
            )
            client.create_collection(
                self._settings.collection,
                schema=self._build_schema(client),
                description=manifest,
                consistency_level="Strong",
            )
            try:
                client.create_index(self._settings.collection, index_params)
            except Exception:
                client.drop_collection(self._settings.collection)
                raise

    def _assert_compatible(self, client: MilvusClient) -> None:
        info = client.describe_collection(self._settings.collection)

        recorded = _read_manifest(info)
        expected = self._manifest()
        if recorded is None:
            raise MilvusStoreError(
                f"collection {self._settings.collection!r} has no compatibility manifest; "
                "drop and reindex it"
            )
        comparable_recorded = _storage_manifest(recorded or {})
        comparable_expected = _storage_manifest(expected)
        legacy_source = (
            self._allow_legacy_source
            and isinstance(comparable_recorded.get("schema_version"), int)
            and 2 <= comparable_recorded["schema_version"] < SCHEMA_VERSION
            and comparable_expected.get("schema_version") == SCHEMA_VERSION
        )
        if legacy_source:
            comparable_recorded["schema_version"] = SCHEMA_VERSION
        if recorded is not None and comparable_recorded != comparable_expected:
            raise MilvusStoreError(
                f"collection {self._settings.collection!r} is incompatible "
                f"(recorded {recorded} != expected {expected}); drop and reindex it"
            )
        expected_corpus = expected.get("corpus")
        if expected_corpus is not None and recorded.get("corpus") != expected_corpus:
            raise MilvusStoreError(
                f"collection {self._settings.collection!r} has different corpus provenance; "
                "use a new immutable collection"
            )
        self._recorded_manifest = recorded

        fields = {field.get("name"): field for field in info.get("fields", [])}
        required_fields = (
            ("id", "vector")
            if legacy_source
            else ("id", "vector", *_STRING_FIELDS, *_INT_FIELDS, *_BOOL_FIELDS)
        )
        for name in required_fields:
            if name not in fields:
                raise MilvusStoreError(
                    f"collection {self._settings.collection!r} is missing field {name!r}; "
                    "drop and reindex it"
                )

        vector_params = fields["vector"].get("params", {})
        if vector_params.get("dim") != self._settings.dimension:
            raise MilvusStoreError(
                f"collection {self._settings.collection!r} has dimension "
                f"{vector_params.get('dim')}, expected {self._settings.dimension}; drop and reindex it"
            )

        metric = self._stored_metric(client)
        if metric is not None and metric.upper() != self._settings.metric_type.upper():
            raise MilvusStoreError(
                f"collection {self._settings.collection!r} uses metric {metric!r}, "
                f"expected {self._settings.metric_type!r}; drop and reindex it"
            )

    def _stored_metric(self, client: MilvusClient) -> str:
        try:
            for index_name in client.list_indexes(self._settings.collection):
                described = client.describe_index(self._settings.collection, index_name)
                if described.get("field_name") == "vector" and described.get("metric_type"):
                    return str(described["metric_type"])
        except Exception as exc:  # noqa: BLE001 - compatibility must be fail-closed
            raise MilvusStoreError(
                f"could not verify the vector index for collection "
                f"{self._settings.collection!r}; drop and reindex it"
            ) from exc
        raise MilvusStoreError(
            f"collection {self._settings.collection!r} has no verifiable vector index; "
            "drop and reindex it"
        )

    def _client_or_create(self) -> MilvusClient:
        if self._client is None:
            self._client = MilvusClient(
                uri=self._settings.uri,
                timeout=self._settings.timeout_seconds,
            )
        return self._client

    def _build_schema(self, client: MilvusClient):  # type: ignore[no-untyped-def]
        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self._settings.dimension)
        schema.add_field("text", DataType.VARCHAR, max_length=self._settings.max_text_length)
        schema.add_field("source", DataType.VARCHAR, max_length=_FIELD_LIMITS["source"])
        schema.add_field("created_at", DataType.VARCHAR, max_length=_FIELD_LIMITS["created_at"])
        schema.add_field("source_url", DataType.VARCHAR, max_length=_FIELD_LIMITS["source_url"], nullable=True)
        schema.add_field(
            "license_or_terms",
            DataType.VARCHAR,
            max_length=_FIELD_LIMITS["license_or_terms"],
            nullable=True,
        )
        schema.add_field("page_id", DataType.VARCHAR, max_length=_FIELD_LIMITS["page_id"])
        schema.add_field(
            "canonical_title",
            DataType.VARCHAR,
            max_length=_FIELD_LIMITS["canonical_title"],
        )
        schema.add_field(
            "opening_name",
            DataType.VARCHAR,
            max_length=_FIELD_LIMITS["opening_name"],
            nullable=True,
        )
        schema.add_field("eco_code", DataType.VARCHAR, max_length=_FIELD_LIMITS["eco_code"], nullable=True)
        schema.add_field(
            "opening_node_id",
            DataType.VARCHAR,
            max_length=_FIELD_LIMITS["opening_node_id"],
            nullable=True,
        )
        schema.add_field("line_pgn", DataType.VARCHAR, max_length=_FIELD_LIMITS["line_pgn"], nullable=True)
        schema.add_field(
            "section_title", DataType.VARCHAR, max_length=_FIELD_LIMITS["section_title"], nullable=True
        )
        schema.add_field("intent", DataType.VARCHAR, max_length=_FIELD_LIMITS["intent"])
        schema.add_field("side", DataType.VARCHAR, max_length=_FIELD_LIMITS["side"], nullable=True)
        schema.add_field("is_history", DataType.BOOL)
        schema.add_field("is_misc", DataType.BOOL)
        schema.add_field("section_index", DataType.INT64, nullable=True)
        schema.add_field("part_index", DataType.INT64)
        return schema

    def _build_index(self, client: MilvusClient):  # type: ignore[no-untyped-def]
        index_params = client.prepare_index_params()
        params: dict[str, int] = {}
        if self._settings.index_type == "HNSW":
            params = {
                "M": self._settings.index_m,
                "efConstruction": self._settings.index_ef_construction,
            }
        index_params.add_index(
            field_name="vector",
            index_type=self._settings.index_type,
            metric_type=self._settings.metric_type,
            params=params,
        )
        for field in ("source", "eco_code", "opening_name", "opening_node_id", "page_id", "intent"):
            index_params.add_index(field_name=field, index_type="INVERTED")
        return index_params

    def _eco_filter(self, eco_code: str | None) -> str | None:
        if not eco_code:
            return None
        normalized = eco_code.upper()
        if not _ECO_CODE_PATTERN.fullmatch(normalized):
            logger.warning("Ignoring invalid eco_code filter: %r", eco_code)
            return None
        return f'eco_code == "{normalized}"'

    def _search_filter(
        self,
        eco_code: str | None,
        metadata_filter: MilvusMetadataFilter | None,
    ) -> str | None:
        clauses = [clause for clause in (self._eco_filter(eco_code), metadata_filter.to_expression() if metadata_filter else None) if clause]
        return " and ".join(clauses) if clauses else None

    def _row(self, record: EmbeddedChunk) -> dict:
        chunk = record.chunk
        row = {
            "id": _bounded("id", chunk.id, 64),
            "vector": list(record.vector),
            "text": _bounded("text", chunk.text, self._settings.max_text_length),
            "source": _bounded("source", chunk.source, _FIELD_LIMITS["source"]),
            "created_at": _bounded("created_at", chunk.created_at, _FIELD_LIMITS["created_at"]),
            "source_url": _bounded("source_url", chunk.source_url, _FIELD_LIMITS["source_url"]),
            "license_or_terms": _bounded(
                "license_or_terms", chunk.license_or_terms, _FIELD_LIMITS["license_or_terms"]
            ),
            "page_id": _bounded("page_id", chunk.page_id, _FIELD_LIMITS["page_id"]),
            "canonical_title": _bounded(
                "canonical_title", chunk.canonical_title, _FIELD_LIMITS["canonical_title"]
            ),
            "opening_name": _bounded("opening_name", chunk.opening_name, _FIELD_LIMITS["opening_name"]),
            "eco_code": _bounded("eco_code", chunk.eco_code, _FIELD_LIMITS["eco_code"]),
            "opening_node_id": _bounded(
                "opening_node_id", chunk.opening_node_id, _FIELD_LIMITS["opening_node_id"]
            ),
            "line_pgn": _bounded("line_pgn", chunk.line_pgn, _FIELD_LIMITS["line_pgn"]),
            "section_title": _bounded("section_title", chunk.section_title, _FIELD_LIMITS["section_title"]),
            "intent": _bounded("intent", chunk.intent, _FIELD_LIMITS["intent"]),
            "side": _bounded("side", chunk.side, _FIELD_LIMITS["side"]),
            "is_history": chunk.is_history,
            "is_misc": chunk.is_misc,
            "section_index": chunk.section_index,
            "part_index": chunk.part_index,
        }
        return row

    def _chunk_from_hit(self, hit: dict) -> KnowledgeChunk:
        entity = hit.get("entity", {})
        return KnowledgeChunk(
            id=str(hit["id"]),
            text=entity.get("text") or "",
            source=entity.get("source") or "",
            page_id=entity.get("page_id") or "",
            canonical_title=entity.get("canonical_title") or "",
            section_index=entity.get("section_index"),
            part_index=entity.get("part_index") or 0,
            section_title=entity.get("section_title"),
            source_url=entity.get("source_url"),
            license_or_terms=entity.get("license_or_terms"),
            opening_name=entity.get("opening_name"),
            eco_code=entity.get("eco_code"),
            opening_node_id=entity.get("opening_node_id"),
            line_pgn=entity.get("line_pgn"),
            intent=entity.get("intent") or "misc",
            side=entity.get("side"),
            is_history=bool(entity.get("is_history")),
            is_misc=bool(entity.get("is_misc", True)),
            created_at=entity.get("created_at") or "",
        )


def _read_manifest(info: dict) -> dict | None:
    properties = info.get("properties")
    if isinstance(properties, dict):
        recorded = _parse_manifest(properties.get(_MANIFEST_PROPERTY))
        if recorded is not None:
            return recorded
    return _parse_manifest(info.get("description"))


def _storage_manifest(manifest: dict) -> dict:
    """Normalize legacy manifests to storage-only compatibility fields."""

    return {
        key: manifest.get(key)
        for key in (
            "schema_version",
            "dimension",
            "metric_type",
            "index_type",
            "index_m",
            "index_ef_construction",
            "max_text_length",
            "embedding",
        )
    }


def _parse_manifest(value: object) -> dict | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _append_string_clause(
    clauses: list[str],
    field: str,
    values: Sequence[str],
    *,
    negate: bool = False,
) -> None:
    safe_values = tuple(_safe_filter_value(field, value) for value in values)
    if not safe_values:
        return
    operator = "not in" if negate else "in"
    if len(safe_values) == 1 and not negate:
        clauses.append(f'{field} == {json.dumps(safe_values[0])}')
        return
    clauses.append(f"{field} {operator} {json.dumps(list(safe_values))}")


def _safe_filter_value(field: str, value: str) -> str:
    if field not in {"opening_node_id", "intent", "source", "page_id"}:
        raise MilvusStoreError(f"unsupported metadata filter field: {field}")
    if not isinstance(value, str) or not _SAFE_FILTER_VALUE_PATTERN.fullmatch(value):
        raise MilvusStoreError(f"invalid {field} metadata filter value")
    if len(value.encode("utf-8")) > _FIELD_LIMITS[field]:
        raise MilvusStoreError(f"invalid {field} metadata filter value")
    return value


def _utf8_length(value: str) -> int:
    return len(value.encode("utf-8"))


def _bounded(field: str, value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    if _utf8_length(value) > limit:
        raise MilvusStoreError(
            f"field {field!r} is {_utf8_length(value)} UTF-8 bytes, over the {limit}-byte VARCHAR limit"
        )
    return value


def _batched[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
