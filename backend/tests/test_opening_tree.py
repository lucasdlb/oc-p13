import json

import pytest

from backend.app.services.opening_tree import OpeningTree, OpeningTreeError, build_opening_tree_snapshot


def _write_tsv(path, rows: list[str]) -> None:
    path.write_text("\n".join(["eco\tname\tpgn", *rows]), encoding="utf-8")


def test_build_opening_tree_snapshot_writes_versioned_artifacts(tmp_path) -> None:
    source_dir = tmp_path / "chess-openings"
    output_dir = tmp_path / "opening-tree"
    source_dir.mkdir()
    _write_tsv(
        source_dir / "a.tsv",
        [
            "B00\tKing's Pawn Game\t1. e4",
            "C20\tOpen Game\t1. e4 e5",
            "C60\tRuy Lopez\t1. e4 e5 2. Nf3 Nc6 3. Bb5",
        ],
    )
    _write_tsv(source_dir / "b.tsv", ["B20\tSicilian Defense\t1. e4 c5"])

    snapshot = build_opening_tree_snapshot(source_dir, output_dir)

    assert (output_dir / "manifest.json").exists()
    assert (output_dir / "nodes.json").exists()
    assert (output_dir / "indexes.json").exists()
    assert snapshot.manifest["schema_version"] == 1
    assert snapshot.manifest["builder_version"] == 1
    assert snapshot.manifest["source_files"]["a.tsv"]["rows_total"] == 3
    assert snapshot.manifest["source_files"]["b.tsv"]["rows_total"] == 1
    assert snapshot.manifest["rows_total"] == 4
    assert snapshot.manifest["rows_skipped"] == 0


def test_opening_tree_derives_chess_fields_parent_child_links_and_paths(tmp_path) -> None:
    source_dir = tmp_path / "chess-openings"
    output_dir = tmp_path / "opening-tree"
    source_dir.mkdir()
    _write_tsv(
        source_dir / "a.tsv",
        [
            "B00\tKing's Pawn Game\t1. e4",
            "C20\tOpen Game\t1. e4 e5",
            "C60\tRuy Lopez\t1. e4 e5 2. Nf3 Nc6 3. Bb5",
            "C65\tRuy Lopez: Berlin Defense\t1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6",
        ],
    )

    build_opening_tree_snapshot(source_dir, output_dir)
    tree = OpeningTree.from_snapshot_dir(output_dir)

    ruy = tree.identify_by_uci(["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"])
    assert ruy is not None
    assert ruy.eco == "C60"
    assert ruy.name == "Ruy Lopez"
    assert ruy.uci == ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5")
    assert ruy.san == ("e4", "e5", "Nf3", "Nc6", "Bb5")
    assert ruy.epd == "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq -"
    assert ruy.depth == 5
    assert ruy.opening_path == ("King's Pawn Game", "Open Game", "Ruy Lopez")

    window = tree.window(ruy.node_id)
    assert window.current.node_id == ruy.node_id
    assert window.parent is not None
    assert window.parent.name == "Open Game"
    assert [child.name for child in window.children] == ["Ruy Lopez: Berlin Defense"]


def test_opening_tree_skips_invalid_rows_with_report_entries(tmp_path) -> None:
    source_dir = tmp_path / "chess-openings"
    output_dir = tmp_path / "opening-tree"
    source_dir.mkdir()
    _write_tsv(
        source_dir / "a.tsv",
        [
            "B00\tKing's Pawn Game\t1. e4",
            "C00\tBroken Line\t1. e4 e5 2. DefinitelyIllegal",
            "C01\tMissing PGN\t",
        ],
    )

    snapshot = build_opening_tree_snapshot(source_dir, output_dir)

    assert len(snapshot.nodes) == 1
    assert snapshot.manifest["rows_total"] == 3
    assert snapshot.manifest["rows_skipped"] == 2
    assert [entry["name"] for entry in snapshot.manifest["skipped_rows"]] == ["Broken Line", "Missing PGN"]
    assert snapshot.manifest["skipped_rows"][0]["reason"].startswith("invalid PGN")
    assert snapshot.manifest["skipped_rows"][1]["reason"] == "missing required field"


def test_node_ids_are_stable_for_unchanged_source_rows(tmp_path) -> None:
    source_dir = tmp_path / "chess-openings"
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"
    source_dir.mkdir()
    rows = [
        "B00\tKing's Pawn Game\t1. e4",
        "C60\tRuy Lopez\t1. e4 e5 2. Nf3 Nc6 3. Bb5",
    ]
    _write_tsv(source_dir / "a.tsv", rows)

    first = build_opening_tree_snapshot(source_dir, first_output)
    second = build_opening_tree_snapshot(source_dir, second_output)

    assert {node.name: node.node_id for node in first.nodes} == {node.name: node.node_id for node in second.nodes}


def test_epd_aliases_preserve_transpositions_and_multiple_names(tmp_path) -> None:
    source_dir = tmp_path / "chess-openings"
    output_dir = tmp_path / "opening-tree"
    source_dir.mkdir()
    _write_tsv(
        source_dir / "a.tsv",
        [
            "A06\tZukertort Opening\t1. Nf3",
            "A06\tZukertort Opening: Queen's Pawn Transposition\t1. Nf3 d5 2. d4",
            "D00\tQueen's Pawn Game\t1. d4 d5",
            "D02\tQueen's Pawn Game: Zukertort Variation\t1. d4 d5 2. Nf3",
        ],
    )

    build_opening_tree_snapshot(source_dir, output_dir)
    tree = OpeningTree.from_snapshot_dir(output_dir)
    aliases = [tree.node(node_id).name for node_id in tree.aliases_by_epd[tree.identify_by_uci(["g1f3", "d7d5", "d2d4"]).epd]]

    assert aliases == ["Zukertort Opening: Queen's Pawn Transposition", "Queen's Pawn Game: Zukertort Variation"]


def test_retrieval_constraints_bound_current_children_and_deep_descendants(tmp_path) -> None:
    source_dir = tmp_path / "chess-openings"
    output_dir = tmp_path / "opening-tree"
    source_dir.mkdir()
    _write_tsv(
        source_dir / "a.tsv",
        [
            "B00\tKing's Pawn Game\t1. e4",
            "C20\tOpen Game\t1. e4 e5",
            "C60\tRuy Lopez\t1. e4 e5 2. Nf3 Nc6 3. Bb5",
            "C65\tRuy Lopez: Berlin Defense\t1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6",
            "C67\tRuy Lopez: Berlin Defense, Rio Gambit\t1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6 4. O-O Nxe4",
        ],
    )

    build_opening_tree_snapshot(source_dir, output_dir)
    tree = OpeningTree.from_snapshot_dir(output_dir)
    ruy = tree.identify_by_uci(["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"])
    assert ruy is not None

    current = tree.retrieval_constraints(ruy.node_id, include_child_prose=False)
    with_children = tree.retrieval_constraints(ruy.node_id, include_child_prose=True)

    assert current.current_node_ids == (ruy.node_id,)
    assert current.child_node_ids == ()
    assert with_children.child_node_ids == (tree.identify_by_uci(["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6"]).node_id,)
    assert with_children.excluded_descendant_node_ids == (
        tree.identify_by_uci(["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6", "e1g1", "f6e4"]).node_id,
    )


def test_context_for_position_returns_current_parent_children_and_exclusions(tmp_path) -> None:
    source_dir = tmp_path / "chess-openings"
    output_dir = tmp_path / "opening-tree"
    source_dir.mkdir()
    _write_tsv(
        source_dir / "a.tsv",
        [
            "B00\tKing's Pawn Game\t1. e4",
            "C20\tOpen Game\t1. e4 e5",
            "C60\tRuy Lopez\t1. e4 e5 2. Nf3 Nc6 3. Bb5",
            "C65\tRuy Lopez: Berlin Defense\t1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6",
            "C67\tRuy Lopez: Berlin Defense, Rio Gambit\t1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6 4. O-O Nxe4",
        ],
    )

    build_opening_tree_snapshot(source_dir, output_dir)
    tree = OpeningTree.from_snapshot_dir(output_dir)

    context = tree.context_for_position(moves=("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"))

    assert context.state == "matched"
    assert context.current is not None
    assert context.current.opening_name == "Ruy Lopez"
    assert context.parent is not None
    assert context.parent.opening_name == "Open Game"
    assert [(child.opening_name, child.entry_move) for child in context.children] == [
        ("Ruy Lopez: Berlin Defense", "Nf6")
    ]
    assert len(context.excluded_descendant_node_ids) == 1


def test_context_for_position_uses_fen_when_moves_do_not_identify_node(tmp_path) -> None:
    source_dir = tmp_path / "chess-openings"
    output_dir = tmp_path / "opening-tree"
    source_dir.mkdir()
    _write_tsv(source_dir / "a.tsv", ["B00\tKing's Pawn Game\t1. e4"])

    build_opening_tree_snapshot(source_dir, output_dir)
    tree = OpeningTree.from_snapshot_dir(output_dir)
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"

    context = tree.context_for_position(moves=(), fen=fen)

    assert context.state == "matched"
    assert context.current is not None
    assert context.current.opening_name == "King's Pawn Game"


def test_context_for_position_returns_safe_out_of_theory_context(tmp_path) -> None:
    source_dir = tmp_path / "chess-openings"
    output_dir = tmp_path / "opening-tree"
    source_dir.mkdir()
    _write_tsv(
        source_dir / "a.tsv",
        [
            "B00\tKing's Pawn Game\t1. e4",
            "C20\tOpen Game\t1. e4 e5",
        ],
    )

    build_opening_tree_snapshot(source_dir, output_dir)
    tree = OpeningTree.from_snapshot_dir(output_dir)

    context = tree.context_for_position(moves=("e2e4", "e7e5", "a2a4"))

    assert context.state == "out_of_theory"
    assert context.current is None
    assert context.children == ()


def test_opening_tree_loader_rejects_missing_artifacts(tmp_path) -> None:
    with pytest.raises(OpeningTreeError, match="missing OpeningTree artifact"):
        OpeningTree.from_snapshot_dir(tmp_path)


def test_opening_tree_snapshot_can_be_loaded_from_json_artifacts(tmp_path) -> None:
    source_dir = tmp_path / "chess-openings"
    output_dir = tmp_path / "opening-tree"
    source_dir.mkdir()
    _write_tsv(source_dir / "a.tsv", ["B00\tKing's Pawn Game\t1. e4"])

    build_opening_tree_snapshot(source_dir, output_dir)
    nodes_payload = json.loads((output_dir / "nodes.json").read_text(encoding="utf-8"))
    tree = OpeningTree.from_snapshot_dir(output_dir)

    assert nodes_payload["schema_version"] == 1
    assert tree.identify_by_epd("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -").name == "King's Pawn Game"
