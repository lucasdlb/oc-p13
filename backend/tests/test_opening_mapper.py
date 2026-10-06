from backend.app.ingestion.opening_mapper import (
    CONF_ANCESTOR,
    CONF_EXACT,
    CONF_REFINED_SECTION,
    CONF_TRANSPOSITION,
    CONF_UNMAPPED,
    REL_DESCENDANT,
    REL_EXACT,
    REL_TRANSPOSITION,
    map_page,
    refine_section,
)
from backend.app.services.opening_tree import OpeningTree, build_opening_tree_snapshot


def _write_tsv(path, rows: list[str]) -> None:
    path.write_text("\n".join(["eco\tname\tpgn", *rows]), encoding="utf-8")


def _build_tree(tmp_path, rows: list[str]) -> OpeningTree:
    source_dir = tmp_path / "chess-openings"
    output_dir = tmp_path / "opening-tree"
    source_dir.mkdir()
    _write_tsv(source_dir / "a.tsv", rows)
    build_opening_tree_snapshot(source_dir, output_dir)
    return OpeningTree.from_snapshot_dir(output_dir)


_MAIN_LINE_ROWS = [
    "B00\tKing's Pawn Game\t1. e4",
    "C20\tOpen Game\t1. e4 e5",
    "C60\tRuy Lopez\t1. e4 e5 2. Nf3 Nc6 3. Bb5",
    "C68\tRuy Lopez: Morphy Defense\t1. e4 e5 2. Nf3 Nc6 3. Bb5 a6",
    "C65\tRuy Lopez: Berlin Defense\t1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6",
]


def test_exact_title_maps_to_tree_node(tmp_path) -> None:
    tree = _build_tree(tmp_path, _MAIN_LINE_ROWS)

    mapping = map_page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5", tree)

    assert mapping.status == "mapped"
    assert mapping.confidence == CONF_EXACT
    assert mapping.relation == REL_EXACT
    assert mapping.opening_name == "Ruy Lopez"
    assert mapping.eco_code == "C60"
    assert mapping.depth_delta == 0
    assert mapping.opening_path == ("King's Pawn Game", "Open Game", "Ruy Lopez")
    assert mapping.line_pgn == "1. e4 e5 2. Nf3 Nc6 3. Bb5"
    assert mapping.move_sequence == ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5")


def test_transposition_maps_by_epd(tmp_path) -> None:
    tree = _build_tree(
        tmp_path,
        ["D02\tQueen's Pawn Game: Zukertort Variation\t1. d4 d5 2. Nf3"],
    )

    mapping = map_page("Chess Opening Theory/1. Nf3/1...d5/2. d4", tree)

    assert mapping.status == "mapped"
    assert mapping.confidence == CONF_TRANSPOSITION
    assert mapping.relation == REL_TRANSPOSITION
    assert mapping.opening_name == "Queen's Pawn Game: Zukertort Variation"
    assert mapping.eco_code == "D02"
    assert mapping.ambiguous is False
    assert mapping.depth_delta == 0


def test_ambiguous_transposition_is_reported_not_guessed(tmp_path) -> None:
    tree = _build_tree(
        tmp_path,
        [
            "D02\tQueen's Pawn Game: Zukertort Variation\t1. d4 d5 2. Nf3 Nf6",
            "A06\tZukertort Opening: Queen's Pawn Transposition\t1. Nf3 d5 2. d4 Nf6",
        ],
    )

    mapping = map_page("Chess Opening Theory/1. Nf3/1...Nf6/2. d4/2...d5", tree)

    assert mapping.status == "mapped"
    assert mapping.confidence == CONF_TRANSPOSITION
    assert mapping.ambiguous is True
    assert mapping.node_id in {node.node_id for node in tree.nodes}


def test_deep_line_maps_to_nearest_named_ancestor(tmp_path) -> None:
    tree = _build_tree(
        tmp_path,
        ["B00\tKing's Pawn Game\t1. e4", "C20\tOpen Game\t1. e4 e5"],
    )

    mapping = map_page("Chess Opening Theory/1. e4/1...e5/2. Nf3", tree)

    assert mapping.status == "mapped"
    assert mapping.confidence == CONF_ANCESTOR
    assert mapping.relation == REL_DESCENDANT
    assert mapping.opening_name == "Open Game"
    assert mapping.eco_code == "C20"
    assert mapping.depth_delta == 1
    assert mapping.move_sequence == ("e2e4", "e7e5", "g1f3")


def test_root_page_is_unmapped_with_reason(tmp_path) -> None:
    tree = _build_tree(tmp_path, _MAIN_LINE_ROWS)

    mapping = map_page("Chess Opening Theory", tree)

    assert mapping.status == "unmapped"
    assert mapping.confidence == CONF_UNMAPPED
    assert mapping.node_id is None
    assert mapping.reason == "no_move_line"


def test_unparseable_move_line_is_unmapped_with_reason(tmp_path) -> None:
    tree = _build_tree(tmp_path, _MAIN_LINE_ROWS)

    mapping = map_page("Chess Opening Theory/1. e4/1...e5/2. Qh9", tree)

    assert mapping.status == "unmapped"
    assert mapping.confidence == CONF_UNMAPPED
    assert mapping.reason.startswith("unparseable_move_line")


def test_refine_section_maps_candidate_move_to_exact_child(tmp_path) -> None:
    tree = _build_tree(tmp_path, _MAIN_LINE_ROWS)
    page = map_page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5", tree)

    refined = refine_section(page, "3...a6", tree)

    assert refined is not None
    assert refined.confidence == CONF_REFINED_SECTION
    assert refined.relation == REL_EXACT
    assert refined.opening_name == "Ruy Lopez: Morphy Defense"
    assert refined.eco_code == "C68"
    assert refined.depth_delta == 0


def test_refine_section_maps_direct_child_alias_title(tmp_path) -> None:
    tree = _build_tree(tmp_path, _MAIN_LINE_ROWS)
    page = map_page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5", tree)

    refined = refine_section(page, "Berlin defence", tree)

    assert refined is not None
    assert refined.confidence == CONF_REFINED_SECTION
    assert refined.relation == REL_EXACT
    assert refined.opening_name == "Ruy Lopez: Berlin Defense"
    assert refined.eco_code == "C65"
    assert refined.depth_delta == 0


def test_refine_section_maps_deeper_line_to_descendant(tmp_path) -> None:
    tree = _build_tree(tmp_path, _MAIN_LINE_ROWS)
    page = map_page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5", tree)

    refined = refine_section(page, "3...a6 4. Ba4", tree)

    assert refined is not None
    assert refined.confidence == CONF_REFINED_SECTION
    assert refined.relation == REL_DESCENDANT
    assert refined.opening_name == "Ruy Lopez: Morphy Defense"
    assert refined.depth_delta == 1


def test_refine_section_rejects_prose_title(tmp_path) -> None:
    tree = _build_tree(tmp_path, _MAIN_LINE_ROWS)
    page = map_page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5", tree)

    assert refine_section(page, "Entering the endgame with 10. Bd2", tree) is None


def test_refine_section_rejects_restated_page_move(tmp_path) -> None:
    tree = _build_tree(tmp_path, _MAIN_LINE_ROWS)
    page = map_page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5", tree)

    assert refine_section(page, "3. Bb5", tree) is None


def test_refine_section_returns_none_for_unmapped_page(tmp_path) -> None:
    tree = _build_tree(tmp_path, _MAIN_LINE_ROWS)
    page = map_page("Chess Opening Theory", tree)

    assert refine_section(page, "3...a6", tree) is None


def test_chunk_and_page_field_shapes(tmp_path) -> None:
    tree = _build_tree(tmp_path, _MAIN_LINE_ROWS)
    page = map_page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5", tree)

    chunk = page.chunk_fields()
    assert chunk["opening_node_id"] == page.node_id
    assert chunk["mapping_status"] == "mapped"
    assert chunk["mapping_confidence"] == CONF_EXACT
    assert chunk["opening_path"] == ["King's Pawn Game", "Open Game", "Ruy Lopez"]
    assert chunk["move_sequence"] == ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]

    fields = page.page_fields()
    assert fields["status"] == "mapped"
    assert fields["opening_node_id"] == page.node_id
    assert fields["depth_delta"] == 0
