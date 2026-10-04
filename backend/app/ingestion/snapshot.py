"""Immutable validated Wikibooks snapshot (ticket 08).

Combines the versioned manifest (ticket 03), the cleaned pages/chunks and quality
report (ticket 04), and the opening-tree mapping outputs (ticket 05) into a single
immutable, content-addressed snapshot directory. The OpeningTree itself and the
frozen Eval V2 dataset are referenced by hash rather than copied.

Design:

- The snapshot directory holds verbatim copies of ``manifest.json``, ``pages.jsonl``,
  ``chunks.jsonl``, ``quality-report.json`` plus a ``snapshot.json`` manifest that
  records per-component hashes, versions, input references, and the composite
  ``snapshot_hash``.
- Every hash is computed over a *canonical* form that strips volatile timestamps
  (``created_at``, ``generated_at``, ``fetched_at``) and orders records
  deterministically (pages by ``page_id``, chunks by ``id``). Rebuilding from the
  same inputs therefore produces the same hash even when timestamps differ.
- ``build_snapshot`` validates first and writes nothing on failure; it refuses to
  overwrite an existing snapshot unless its content hash is unchanged or ``--force``
  is passed.
- ``load_snapshot`` re-verifies the stored component hashes and the composite hash,
  raising :class:`SnapshotError` on a missing (partial) or tampered component.
- ``verify_snapshot`` re-runs the full consistency validation against the referenced
  OpeningTree and Eval V2 dataset, so reference runs fail closed on any inconsistency.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.app.ingestion.chunker import CHUNKER_VERSION, utf8_length
from backend.app.services.opening_tree import OpeningTree

SCHEMA_VERSION = 1
SOURCE_NAME = "wikibooks-chess-opening-theory"
DEFAULT_MAX_BYTES = 16000

VOLATILE_FIELDS = frozenset({"created_at", "generated_at", "fetched_at"})

_COMPONENT_FILES = ("manifest.json", "pages.jsonl", "chunks.jsonl", "quality-report.json")


class SnapshotError(RuntimeError):
    """Raised when a snapshot cannot be built, loaded, or verified."""


class SnapshotValidationError(SnapshotError):
    """Raised when a snapshot is partial or inconsistent."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("snapshot validation failed: " + "; ".join(self.errors))


@dataclass(frozen=True)
class Snapshot:
    manifest: dict
    wikibooks_manifest: dict
    pages: tuple[dict, ...]
    chunks: tuple[dict, ...]
    report: dict

    @property
    def snapshot_hash(self) -> str:
        return self.manifest["snapshot_hash"]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_volatile(obj):
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in obj.items() if k not in VOLATILE_FIELDS}
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_pages(pages) -> str:
    rows = [_strip_volatile(p) for p in pages]
    rows.sort(key=lambda p: (p.get("page_id", ""), p.get("canonical_title", "")))
    return _dumps(rows)


def canonical_chunks(chunks) -> str:
    rows = [_strip_volatile(c) for c in chunks]
    rows.sort(key=lambda c: c.get("id", ""))
    return _dumps(rows)


def canonical_report(report) -> str:
    return _dumps(_strip_volatile(report))


def canonical_manifest(manifest) -> str:
    stable = _strip_volatile(manifest)
    if isinstance(stable.get("pages"), list):
        stable["pages"] = sorted(
            stable["pages"],
            key=lambda p: (p.get("page_id", ""), p.get("requested_title", "")),
        )
    if isinstance(stable.get("stale_cache_files"), list):
        stable["stale_cache_files"] = sorted(stable["stale_cache_files"])
    return _dumps(stable)


def _test_split_hash(cases: list[dict]) -> str:
    test_cases = sorted((c for c in cases if c["split"] == "test"), key=lambda c: c["id"])
    return _sha256(_dumps(test_cases))


def validate(wikibooks_manifest, pages, chunks, report, tree, dataset) -> list[str]:
    """Return a list of consistency errors; an empty list means the snapshot is valid."""
    errors: list[str] = []

    if not wikibooks_manifest.get("complete"):
        errors.append("manifest is not complete")
    summary = wikibooks_manifest.get("summary", {})
    if summary.get("pages_error") or summary.get("pages_missing"):
        errors.append("manifest reports fetch errors or missing pages")

    fetched_page_ids = {
        p.get("page_id")
        for p in wikibooks_manifest.get("pages", [])
        if p.get("status") == "fetched"
    }
    page_ids = {p.get("page_id") for p in pages}
    if fetched_page_ids != page_ids:
        missing = fetched_page_ids - page_ids
        extra = page_ids - fetched_page_ids
        errors.append(
            f"page_id mismatch: {len(missing)} manifest pages missing from pages.jsonl, "
            f"{len(extra)} extra records"
        )

    accepted_titles: set[str] = set()
    accepted_count = 0
    rejected_count = 0
    for p in pages:
        status = p.get("status")
        if status == "accepted":
            accepted_count += 1
            accepted_titles.add(p.get("canonical_title"))
            for field in ("page_id", "canonical_title", "source_url", "license_or_terms", "wikibooks_revision_id"):
                if not p.get(field):
                    errors.append(f"accepted page {p.get('page_id')!r} missing {field}")
        elif status == "rejected":
            rejected_count += 1
            if not p.get("reason"):
                errors.append(f"rejected page {p.get('page_id')!r} missing reason")
        else:
            errors.append(f"page {p.get('page_id')!r} has unexpected status {status!r}")

    budget = report.get("counts", {}).get("byte_budget_max", DEFAULT_MAX_BYTES)
    seen_ids: set[str] = set()
    chunk_page_ids: set[str] = set()
    for c in chunks:
        cid = c.get("id")
        if cid in seen_ids:
            errors.append(f"duplicate chunk id {cid!r}")
        seen_ids.add(cid)
        chunk_page_ids.add(c.get("page_id"))
        for field in ("id", "source", "page_id", "canonical_title", "source_url", "license_or_terms", "wikibooks_revision_id"):
            if not c.get(field):
                errors.append(f"chunk {cid!r} missing {field}")
        if c.get("canonical_title") not in accepted_titles:
            errors.append(f"chunk {cid!r} references non-accepted page {c.get('canonical_title')!r}")
        if utf8_length(c.get("text", "")) > budget:
            errors.append(f"chunk {cid!r} exceeds the {budget}-byte budget")

    for c in chunks:
        if c.get("mapping_status") == "mapped" and c.get("opening_node_id"):
            node_id = c["opening_node_id"]
            if node_id not in tree.by_node_id:
                errors.append(f"chunk {c.get('id')!r} references unknown opening node {node_id!r}")

    counts = report.get("counts", {})
    if counts.get("pages_total") != len(pages):
        errors.append(f"report pages_total {counts.get('pages_total')!r} != {len(pages)}")
    if counts.get("accepted_pages") != accepted_count:
        errors.append(f"report accepted_pages {counts.get('accepted_pages')!r} != {accepted_count}")
    if counts.get("rejected_pages") != rejected_count:
        errors.append(f"report rejected_pages {counts.get('rejected_pages')!r} != {rejected_count}")
    if counts.get("chunks") != len(chunks):
        errors.append(f"report chunks {counts.get('chunks')!r} != {len(chunks)}")
    if counts.get("byte_budget_violations", 0) != 0:
        errors.append("report records byte budget violations")

    if dataset.get("test_split_sha256") != _test_split_hash(dataset.get("cases", [])):
        errors.append("eval dataset test split hash mismatch")
    for case in dataset.get("cases", []):
        if case.get("support") != "in_theory":
            continue
        page_id = case.get("page_id")
        if page_id and page_id not in chunk_page_ids:
            errors.append(f"eval case {case.get('id')!r} page_id {page_id!r} not found in chunks")
        node_id = case.get("opening_node_id")
        if node_id and node_id not in tree.by_node_id:
            errors.append(f"eval case {case.get('id')!r} opening_node_id {node_id!r} unknown")

    return errors


def _identity(versions, inputs, component_shas) -> str:
    return _dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "cleaner_version": versions["cleaner_version"],
            "chunker_version": versions["chunker_version"],
            "opening_tree_schema_version": versions["opening_tree_schema_version"],
            "opening_tree_builder_version": versions["opening_tree_builder_version"],
            "manifest_sha256": component_shas["manifest.json"],
            "opening_tree_manifest_sha256": inputs["opening_tree"]["manifest_sha256"],
            "eval_test_split_sha256": inputs["eval_dataset"]["test_split_sha256"],
            "pages_sha256": component_shas["pages.jsonl"],
            "chunks_sha256": component_shas["chunks.jsonl"],
            "quality_report_sha256": component_shas["quality-report.json"],
        }
    )


def build_snapshot(
    *,
    manifest_path: Path,
    clean_dir: Path,
    opening_tree_dir: Path,
    eval_dataset_path: Path,
    output_dir: Path,
    force: bool = False,
) -> Snapshot:
    wikibooks_manifest = _load_json(manifest_path)
    pages = _read_jsonl(clean_dir / "pages.jsonl")
    chunks = _read_jsonl(clean_dir / "chunks.jsonl")
    report = _load_json(clean_dir / "quality-report.json")
    tree = OpeningTree.from_snapshot_dir(opening_tree_dir)
    dataset = _load_json(eval_dataset_path)

    errors = validate(wikibooks_manifest, pages, chunks, report, tree, dataset)
    if errors:
        raise SnapshotValidationError(errors)

    component_shas = {
        "manifest.json": _sha256(canonical_manifest(wikibooks_manifest)),
        "pages.jsonl": _sha256(canonical_pages(pages)),
        "chunks.jsonl": _sha256(canonical_chunks(chunks)),
        "quality-report.json": _sha256(canonical_report(report)),
    }

    versions = {
        "cleaner_version": report.get("cleaner_version"),
        "chunker_version": CHUNKER_VERSION,
        "opening_tree_schema_version": tree.manifest.get("schema_version"),
        "opening_tree_builder_version": tree.manifest.get("builder_version"),
    }
    inputs = {
        "manifest": {
            "content_hash": wikibooks_manifest.get("content_hash"),
            "pages_fetched": len(fetched_page_ids(wikibooks_manifest)),
        },
        "opening_tree": {
            "manifest_sha256": _sha256(canonical_manifest(tree.manifest)),
            "nodes": len(tree.nodes),
        },
        "eval_dataset": {
            "test_split_sha256": _test_split_hash(dataset.get("cases", [])),
            "cases": len(dataset.get("cases", [])),
        },
    }
    snapshot_hash = _sha256(_identity(versions, inputs, component_shas))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": f"wb-{snapshot_hash[:16]}",
        "snapshot_hash": snapshot_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_NAME,
        "versions": versions,
        "inputs": inputs,
        "components": {
            "manifest.json": {"sha256": component_shas["manifest.json"], "records": len(wikibooks_manifest.get("pages", []))},
            "pages.jsonl": {"sha256": component_shas["pages.jsonl"], "records": len(pages)},
            "chunks.jsonl": {"sha256": component_shas["chunks.jsonl"], "records": len(chunks)},
            "quality-report.json": {"sha256": component_shas["quality-report.json"]},
        },
        "counts": {
            "pages_total": len(pages),
            "pages_accepted": sum(1 for p in pages if p.get("status") == "accepted"),
            "pages_rejected": sum(1 for p in pages if p.get("status") == "rejected"),
            "chunks": len(chunks),
        },
        "validation": {"status": "ok", "checks": ["consistency", "attribution", "mapping", "eval_anchors"], "errors": []},
    }

    existing = output_dir / "snapshot.json"
    if existing.exists():
        prev = _load_json(existing)
        if prev.get("snapshot_hash") == snapshot_hash:
            return load_snapshot(output_dir)
        if not force:
            raise SnapshotError(
                f"snapshot already exists at {output_dir} with different content; use --force to overwrite"
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "snapshot.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(wikibooks_manifest, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output_dir / "pages.jsonl").write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in pages) + "\n", encoding="utf-8"
    )
    (output_dir / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n", encoding="utf-8"
    )
    (output_dir / "quality-report.json").write_text(
        json.dumps(report, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return load_snapshot(output_dir)


def fetched_page_ids(wikibooks_manifest: dict) -> list[str]:
    return [
        p["page_id"]
        for p in wikibooks_manifest.get("pages", [])
        if p.get("status") == "fetched"
    ]


def load_snapshot(snapshot_dir: Path) -> Snapshot:
    manifest_path = snapshot_dir / "snapshot.json"
    if not manifest_path.exists():
        raise SnapshotError(f"snapshot manifest not found: {manifest_path}")
    manifest = _load_json(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotError(f"unsupported snapshot schema {manifest.get('schema_version')!r}")

    for name in _COMPONENT_FILES:
        if not (snapshot_dir / name).exists():
            raise SnapshotError(f"snapshot is partial: missing component {name}")

    wikibooks_manifest = _load_json(snapshot_dir / "manifest.json")
    pages = _read_jsonl(snapshot_dir / "pages.jsonl")
    chunks = _read_jsonl(snapshot_dir / "chunks.jsonl")
    report = _load_json(snapshot_dir / "quality-report.json")

    computed = {
        "manifest.json": _sha256(canonical_manifest(wikibooks_manifest)),
        "pages.jsonl": _sha256(canonical_pages(pages)),
        "chunks.jsonl": _sha256(canonical_chunks(chunks)),
        "quality-report.json": _sha256(canonical_report(report)),
    }
    for name, expected in manifest.get("components", {}).items():
        if expected.get("sha256") != computed.get(name):
            raise SnapshotError(f"snapshot is inconsistent: component {name} hash mismatch")

    snapshot_hash = _sha256(
        _identity(manifest["versions"], manifest["inputs"], computed)
    )
    if snapshot_hash != manifest.get("snapshot_hash"):
        raise SnapshotError("snapshot is inconsistent: composite hash mismatch")

    return Snapshot(
        manifest=manifest,
        wikibooks_manifest=wikibooks_manifest,
        pages=tuple(pages),
        chunks=tuple(chunks),
        report=report,
    )


def verify_snapshot(
    snapshot_dir: Path,
    *,
    opening_tree_dir: Path,
    eval_dataset_path: Path,
) -> Snapshot:
    snapshot = load_snapshot(snapshot_dir)

    tree = OpeningTree.from_snapshot_dir(opening_tree_dir)
    expected_tree = snapshot.manifest["inputs"]["opening_tree"]["manifest_sha256"]
    actual_tree = _sha256(canonical_manifest(tree.manifest))
    if actual_tree != expected_tree:
        raise SnapshotError("opening tree manifest hash does not match the snapshot reference")

    dataset = _load_json(eval_dataset_path)
    expected_split = snapshot.manifest["inputs"]["eval_dataset"]["test_split_sha256"]
    actual_split = _test_split_hash(dataset.get("cases", []))
    if actual_split != expected_split:
        raise SnapshotError("eval dataset test split hash does not match the snapshot reference")

    errors = validate(
        snapshot.wikibooks_manifest,
        list(snapshot.pages),
        list(snapshot.chunks),
        snapshot.report,
        tree,
        dataset,
    )
    if errors:
        raise SnapshotValidationError(errors)

    return snapshot
