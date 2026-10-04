"""Validate the immutable Wikibooks snapshot builder and verifier (issue 08)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.app.ingestion.chunker import CHUNKER_VERSION
from backend.app.ingestion.snapshot import (
    SnapshotError,
    SnapshotValidationError,
    build_snapshot,
    canonical_chunks,
    canonical_manifest,
    canonical_pages,
    load_snapshot,
    verify_snapshot,
)
from backend.app.services.opening_tree import build_opening_tree_snapshot

CANONICAL_TITLE = "Chess Opening Theory/1. e4/1...e5"
CHUNK_PAGE_ID = f"wikibooks-chess-opening-theory::{CANONICAL_TITLE}"
MANIFEST_PAGE_ID = "wikibooks::chess-opening-theory::chess_opening_theory_1_e4_1_e5"
SOURCE_URL = "https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4/1...e5"
LICENSE = "CC BY-SA 4.0"


def _write_tree(tmp_path: Path, node_id: str) -> Path:
    source_dir = tmp_path / "chess-openings"
    tree_dir = tmp_path / "opening-tree"
    source_dir.mkdir()
    (source_dir / "a.tsv").write_text(
        "eco\tname\tpgn\nC20\tOpen Game\t1. e4 e5\n", encoding="utf-8"
    )
    build_opening_tree_snapshot(source_dir, tree_dir)
    return tree_dir


def _manifest(extra_pages: list[dict] | None = None) -> dict:
    pages = [
        {
            "page_id": MANIFEST_PAGE_ID,
            "requested_title": CANONICAL_TITLE,
            "canonical_title": CANONICAL_TITLE,
            "wikibooks_page_id": 1,
            "wikibooks_revision_id": 100,
            "source_url": SOURCE_URL,
            "fetched_at": "2026-10-03T00:00:00Z",
            "raw_wikitext_sha256": "abc",
            "local_filename": "chess_opening_theory_1_e4_1_e5.json",
            "status": "fetched",
            "error": None,
        }
    ]
    pages.extend(extra_pages or [])
    return {
        "schema_version": 1,
        "generated_at": "2026-10-03T00:00:00Z",
        "source": "wikibooks-chess-opening-theory",
        "complete": True,
        "content_hash": "dummy",
        "summary": {
            "content_pages_requested": len(pages),
            "content_pages_fetched": len(pages),
            "redirects": 0,
            "pages_error": 0,
            "pages_missing": 0,
            "stale_cache_files": 0,
        },
        "stale_cache_files": [],
        "pages": pages,
    }


def _page_record(status: str = "accepted", node_id: str | None = "node") -> dict:
    return {
        "page_id": MANIFEST_PAGE_ID,
        "canonical_title": CANONICAL_TITLE,
        "wikibooks_page_id": 1,
        "wikibooks_revision_id": 100,
        "source_url": SOURCE_URL,
        "license_or_terms": LICENSE,
        "status": status,
        "reason": None if status == "accepted" else "low_value_prose",
        "sections": [{"section_title": "Open Game", "intent": "intro"}],
        "mapping": {
            "status": "mapped" if node_id else "unmapped",
            "opening_node_id": node_id,
            "opening_name": "Open Game",
            "eco_code": "C20",
            "opening_path": ["Open Game"],
            "relation": "exact",
            "confidence": "exact",
            "depth_delta": 0,
            "ambiguous": False,
            "reason": None,
        },
    }


def _chunk_record(node_id: str = "node", text: str = "1. e4 e5 is the Open Game.") -> dict:
    return {
        "id": "chunk-1",
        "text": text,
        "source": "wikibooks-chess-opening-theory",
        "page_id": CHUNK_PAGE_ID,
        "canonical_title": CANONICAL_TITLE,
        "section_title": "Open Game",
        "section_index": 0,
        "part_index": 0,
        "intent": "intro",
        "side": None,
        "is_history": False,
        "is_misc": False,
        "source_url": SOURCE_URL,
        "license_or_terms": LICENSE,
        "wikibooks_revision_id": 100,
        "difficulty": None,
        "tags": [],
        "created_at": "2026-10-03T00:00:00Z",
        "opening_name": "Open Game",
        "eco_code": "C20",
        "opening_node_id": node_id,
        "opening_path": ["Open Game"],
        "line_pgn": "1. e4 e5",
        "move_sequence": ["e2e4", "e7e5"],
        "mapping_status": "mapped",
        "mapping_confidence": "exact",
        "mapping_relation": "exact",
        "mapping_depth_delta": 0,
        "mapping_ambiguous": False,
    }


def _report(pages: int = 1, chunks: int = 1) -> dict:
    return {
        "schema_version": 1,
        "generated_at": "2026-10-03T00:00:00Z",
        "cleaner_version": 2,
        "source": "wikibooks-chess-opening-theory",
        "license_or_terms": LICENSE,
        "counts": {
            "pages_total": pages,
            "pages_by_status": {"accepted": pages, "rejected": 0},
            "pages_by_reason": {},
            "accepted_pages": pages,
            "rejected_pages": 0,
            "chunks": chunks,
            "sections_by_intent": {"intro": chunks},
            "exact_duplicate_groups": 0,
            "near_duplicates": 0,
            "byte_budget_max": 16000,
            "byte_budget_max_chunk": 30,
            "byte_budget_violations": 0,
            "opening_mapping_status": "complete",
        },
        "opening_mapping": {
            "pages_mapped": pages,
            "pages_unmapped": 0,
            "chunks_mapped": chunks,
            "chunks_unmapped": 0,
            "pages_by_confidence": {"exact": pages},
            "chunks_by_confidence": {"exact": chunks},
            "pages_by_relation": {"exact": pages},
            "chunks_by_relation": {"exact": chunks},
            "chunk_depth_delta_histogram": {"0": chunks},
            "ambiguous_pages": [],
            "unmapped_pages": [],
        },
        "exact_duplicate_groups": [],
        "near_duplicates": [],
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def _test_split_hash(cases: list[dict]) -> str:
    test_cases = sorted((c for c in cases if c["split"] == "test"), key=lambda c: c["id"])
    canonical = json.dumps(test_cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _dataset(node_id: str) -> dict:
    cases = [
        {
            "id": "explain-open-game-001",
            "split": "test",
            "category": "current_opening_explanation",
            "intent": "explain_current_position",
            "support": "in_theory",
            "position": "1. e4 e5",
            "fen": None,
            "moves": ["e2e4", "e7e5"],
            "current_opening": "Open Game",
            "current_eco": "C20",
            "opening_node_id": node_id,
            "page_id": CHUNK_PAGE_ID,
            "question": "Qu'est-ce que la partie ouverte ?",
            "expected_context": {
                "current_prose": ["Open Game"],
                "child_prose_allowed": [],
                "forbidden": [],
            },
        }
    ]
    return {"schema_version": 1, "cases": cases, "test_split_sha256": _test_split_hash(cases)}


@pytest.fixture()
def corpus(tmp_path: Path):
    from backend.app.services.opening_tree import OpeningTree

    tree_dir = _write_tree(tmp_path, "node")
    tree = OpeningTree.from_snapshot_dir(tree_dir)
    node_id = tree.by_uci_path["e2e4 e7e5"][0]

    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    (clean_dir / "pages.jsonl").write_text(
        json.dumps(_page_record(node_id=node_id)) + "\n", encoding="utf-8"
    )
    (clean_dir / "chunks.jsonl").write_text(
        json.dumps(_chunk_record(node_id=node_id)) + "\n", encoding="utf-8"
    )
    (clean_dir / "quality-report.json").write_text(
        json.dumps(_report()) + "\n", encoding="utf-8"
    )

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest()) + "\n", encoding="utf-8")

    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(_dataset(node_id)) + "\n", encoding="utf-8")

    out_dir = tmp_path / "snapshot"
    return {
        "tree_dir": tree_dir,
        "clean_dir": clean_dir,
        "manifest_path": manifest_path,
        "dataset_path": dataset_path,
        "out_dir": out_dir,
        "node_id": node_id,
    }


def _build(corpus: dict, **kwargs):
    return build_snapshot(
        manifest_path=corpus["manifest_path"],
        clean_dir=corpus["clean_dir"],
        opening_tree_dir=corpus["tree_dir"],
        eval_dataset_path=corpus["dataset_path"],
        output_dir=corpus["out_dir"],
        **kwargs,
    )


def test_canonical_chunks_ignore_created_at():
    a = _chunk_record()
    b = _chunk_record()
    b["created_at"] = "2026-10-03T12:00:00Z"
    assert canonical_chunks([a]) == canonical_chunks([b])


def test_canonical_pages_sort_by_page_id():
    page_a = _page_record()
    page_b = _page_record()
    page_b["page_id"] = "wikibooks::chess-opening-theory::other"
    page_b["canonical_title"] = "Other"
    assert canonical_pages([page_b, page_a]) == canonical_pages([page_a, page_b])


def test_canonical_manifest_ignores_timestamps():
    m = _manifest()
    assert "generated_at" not in canonical_manifest(m)
    assert "fetched_at" not in canonical_manifest(m)


def test_build_snapshot_writes_components_and_manifest(corpus):
    snapshot = _build(corpus)

    assert (corpus["out_dir"] / "snapshot.json").exists()
    assert (corpus["out_dir"] / "manifest.json").exists()
    assert (corpus["out_dir"] / "pages.jsonl").exists()
    assert (corpus["out_dir"] / "chunks.jsonl").exists()
    assert (corpus["out_dir"] / "quality-report.json").exists()

    manifest = snapshot.manifest
    assert manifest["schema_version"] == 1
    assert manifest["snapshot_id"].startswith("wb-")
    assert manifest["versions"]["cleaner_version"] == 2
    assert manifest["versions"]["chunker_version"] == CHUNKER_VERSION
    assert len(manifest["snapshot_hash"]) == 64


def test_snapshot_hash_is_deterministic_across_timestamps(corpus):
    first = _build(corpus)

    # Rewrite clean inputs with different volatile timestamps only.
    clean_dir = corpus["clean_dir"]
    pages = [_page_record(node_id=corpus["node_id"])]
    chunks = [_chunk_record(node_id=corpus["node_id"])]
    chunks[0]["created_at"] = "2026-10-04T00:00:00Z"
    report = _report()
    report["generated_at"] = "2026-10-04T00:00:00Z"
    manifest = _manifest()
    manifest["generated_at"] = "2026-10-04T00:00:00Z"
    manifest["pages"][0]["fetched_at"] = "2026-10-04T00:00:00Z"

    _write_jsonl(clean_dir / "pages.jsonl", pages)
    _write_jsonl(clean_dir / "chunks.jsonl", chunks)
    (clean_dir / "quality-report.json").write_text(json.dumps(report) + "\n", encoding="utf-8")
    corpus["manifest_path"].write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    second = _build(corpus, force=True)
    assert first.snapshot_hash == second.snapshot_hash


def test_snapshot_hash_changes_when_content_changes(corpus):
    first = _build(corpus)

    chunks = [_chunk_record(node_id=corpus["node_id"], text="different prose")]
    _write_jsonl(corpus["clean_dir"] / "chunks.jsonl", chunks)
    second = _build(corpus, force=True)
    assert first.snapshot_hash != second.snapshot_hash


def test_build_snapshot_refuses_overwrite_without_force(corpus):
    _build(corpus)
    chunks = [_chunk_record(node_id=corpus["node_id"], text="changed")]
    _write_jsonl(corpus["clean_dir"] / "chunks.jsonl", chunks)
    with pytest.raises(SnapshotError):
        _build(corpus)


def test_load_snapshot_returns_snapshot_and_verifies_hashes(corpus):
    _build(corpus)
    snapshot = load_snapshot(corpus["out_dir"])
    assert snapshot.snapshot_hash == snapshot.manifest["snapshot_hash"]
    assert len(snapshot.chunks) == 1


def test_load_snapshot_detects_missing_component(corpus):
    _build(corpus)
    (corpus["out_dir"] / "chunks.jsonl").unlink()
    with pytest.raises(SnapshotError):
        load_snapshot(corpus["out_dir"])


def test_load_snapshot_detects_tampered_component(corpus):
    _build(corpus)
    chunks_path = corpus["out_dir"] / "chunks.jsonl"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    chunks["text"] = "tampered"
    chunks_path.write_text(json.dumps(chunks) + "\n", encoding="utf-8")
    with pytest.raises(SnapshotError):
        load_snapshot(corpus["out_dir"])


def test_validation_rejects_partial_manifest(corpus):
    extra = dict(_manifest()["pages"][0])
    extra["page_id"] = "wikibooks::chess-opening-theory::extra"
    extra["canonical_title"] = "Extra"
    extra["local_filename"] = "extra.json"
    corpus["manifest_path"].write_text(json.dumps(_manifest([extra])) + "\n", encoding="utf-8")
    with pytest.raises(SnapshotValidationError):
        _build(corpus)


def test_validation_requires_chunk_attribution(corpus):
    chunks = [_chunk_record(node_id=corpus["node_id"])]
    chunks[0]["license_or_terms"] = None
    _write_jsonl(corpus["clean_dir"] / "chunks.jsonl", chunks)
    with pytest.raises(SnapshotValidationError):
        _build(corpus)


def test_validation_checks_mapped_node_exists(corpus):
    chunks = [_chunk_record(node_id="bogus-node")]
    _write_jsonl(corpus["clean_dir"] / "chunks.jsonl", chunks)
    with pytest.raises(SnapshotValidationError):
        _build(corpus)


def test_validation_checks_report_counts(corpus):
    report = _report(chunks=99)
    (corpus["clean_dir"] / "quality-report.json").write_text(
        json.dumps(report) + "\n", encoding="utf-8"
    )
    with pytest.raises(SnapshotValidationError):
        _build(corpus)


def test_validation_checks_eval_anchors(corpus):
    dataset = _dataset(corpus["node_id"])
    dataset["cases"][0]["page_id"] = "wikibooks-chess-opening-theory::Missing"
    dataset["test_split_sha256"] = _test_split_hash(dataset["cases"])
    corpus["dataset_path"].write_text(json.dumps(dataset) + "\n", encoding="utf-8")
    with pytest.raises(SnapshotValidationError):
        _build(corpus)


def test_verify_snapshot_runs_full_validation(corpus):
    _build(corpus)
    snapshot = verify_snapshot(
        corpus["out_dir"],
        opening_tree_dir=corpus["tree_dir"],
        eval_dataset_path=corpus["dataset_path"],
    )
    assert snapshot.snapshot_hash


def test_verify_snapshot_detects_opening_tree_mismatch(corpus):
    _build(corpus)
    other_source = corpus["out_dir"].parent / "other-openings"
    other_tree = corpus["out_dir"].parent / "other-tree"
    other_source.mkdir()
    (other_source / "a.tsv").write_text(
        "eco\tname\tpgn\nB00\tKing's Pawn Game\t1. e4\n", encoding="utf-8"
    )
    build_opening_tree_snapshot(other_source, other_tree)
    with pytest.raises(SnapshotError):
        verify_snapshot(
            corpus["out_dir"],
            opening_tree_dir=other_tree,
            eval_dataset_path=corpus["dataset_path"],
        )
