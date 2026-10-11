import json

from backend.app.ingestion.cli import (
    _collection_name,
    _collection_provenance,
    _load_chunks,
    _target_collection_name,
    chunks_from_snapshot,
)
from backend.app.ingestion.snapshot import Snapshot
from backend.app.services.opening_tree import OpeningTree, build_opening_tree_snapshot
from backend.tests.settings_factories import milvus_settings


def _snapshot() -> Snapshot:
    manifest = {
        "snapshot_id": "wb-test",
        "snapshot_hash": "abc123",
        "source": "wikibooks-chess-opening-theory",
        "versions": {"cleaner_version": 2, "chunker_version": 1},
        "inputs": {"eval_dataset": {"test_split_sha256": "split"}},
        "components": {"chunks.jsonl": {"sha256": "chunks", "records": 1}},
        "counts": {"chunks": 1},
    }
    return Snapshot(
        manifest=manifest,
        wikibooks_manifest={},
        pages=(),
        chunks=(
            {
                "id": "chunk-1",
                "text": "Ruy Lopez prose",
                "source": "wikibooks-chess-opening-theory",
                "page_id": "wikibooks::ruy-lopez",
                "canonical_title": "Ruy Lopez",
                "section_index": 2,
                "part_index": 0,
                "section_title": "Plans",
                "source_url": "https://example.test/ruy",
                "license_or_terms": "CC BY-SA 4.0",
                "opening_name": "Ruy Lopez",
                "eco_code": "C60",
                "opening_node_id": "node-1",
                "line_pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
                "intent": "plan",
                "side": "white",
                "is_history": False,
                "is_misc": False,
                "created_at": "2026-10-03T00:00:00+00:00",
                "wikibooks_revision_id": 123,
                "opening_path": ["Open Game", "Ruy Lopez"],
                "mapping_status": "mapped",
            },
        ),
        report={},
    )


def test_chunks_from_snapshot_maps_retrieval_fields_and_ignores_diagnostics() -> None:
    chunks = chunks_from_snapshot(_snapshot())

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.id == "chunk-1"
    assert chunk.page_id == "wikibooks::ruy-lopez"
    assert chunk.opening_node_id == "node-1"
    assert chunk.intent == "plan"
    assert chunk.is_misc is False


def test_collection_provenance_records_snapshot_identity_separately() -> None:
    provenance = _collection_provenance(_snapshot())

    assert provenance == {
        "source": "wikibooks-chess-opening-theory",
        "snapshot_id": "wb-test",
        "snapshot_hash": "abc123",
        "versions": {"cleaner_version": 2, "chunker_version": 1},
        "inputs": {"eval_dataset": {"test_split_sha256": "split"}},
        "components": {"chunks.jsonl": {"sha256": "chunks", "records": 1}},
        "counts": {"chunks": 1},
    }


def test_no_ingest_uses_configured_collection_without_adding_fingerprint() -> None:
    settings = milvus_settings(collection="chess_knowledge_live_abc123")

    collection = _target_collection_name(
        settings,
        corpus_snapshot_hash="corpus-hash",
        embedding_signature="model@digest",
        granularity="section",
        explicit_collection=None,
        no_ingest=True,
    )

    assert collection == "chess_knowledge_live_abc123"
    assert _collection_name(settings, "corpus-hash", "model@digest", "section") != collection


def test_load_chunks_maps_raw_wikibooks_to_opening_tree(tmp_path) -> None:
    corpus_dir = tmp_path / "corpus"
    wikibooks_dir = corpus_dir / "wikibooks"
    openings_dir = corpus_dir / "chess-openings"
    tree_dir = corpus_dir / "opening-tree"
    wikibooks_dir.mkdir(parents=True)
    openings_dir.mkdir()
    (openings_dir / "c.tsv").write_text(
        "\n".join(
            [
                "eco\tname\tpgn",
                "B00\tKing's Pawn Game\t1. e4",
                "C20\tOpen Game\t1. e4 e5",
                "C60\tRuy Lopez\t1. e4 e5 2. Nf3 Nc6 3. Bb5",
                "C65\tRuy Lopez: Berlin Defense\t1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6",
            ]
        ),
        encoding="utf-8",
    )
    build_opening_tree_snapshot(openings_dir, tree_dir)
    prose = " ".join(["White develops with pressure on the e5 pawn and prepares castling."] * 8)
    child = " ".join(["The Berlin Defense begins after Black plays Nf6 and attacks e4."] * 8)
    (wikibooks_dir / "ruy.json").write_text(
        json.dumps(
            {
                "title": "Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5",
                "url": "https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4/1...e5/2._Nf3/2...Nc6/3._Bb5",
                "wikitext": f"== 3. Bb5 · Ruy Lopez ==\n{prose}\n\n== 3...Nf6 ==\n{child}",
            }
        ),
        encoding="utf-8",
    )

    chunks = _load_chunks(
        corpus_dir,
        opening_tree_dir=tree_dir,
        granularity="section",
        max_bytes=8000,
        limit=None,
    )
    tree = OpeningTree.from_snapshot_dir(tree_dir)
    ruy_id = next(node.node_id for node in tree.nodes if node.name == "Ruy Lopez")
    berlin_id = next(node.node_id for node in tree.nodes if node.name == "Ruy Lopez: Berlin Defense")

    assert {chunk.opening_node_id for chunk in chunks if chunk.section_title == "3. Bb5 · Ruy Lopez"} == {
        ruy_id
    }
    assert {chunk.opening_node_id for chunk in chunks if chunk.section_title == "3...Nf6"} == {
        berlin_id
    }
    assert {chunk.intent for chunk in chunks} <= {"intro", "candidate_move"}
