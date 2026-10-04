"""Deterministic Wikibooks page -> OpeningTree mapping (ticket 05).

Maps an accepted Wikibooks page (identified by its canonical title, which encodes
the move line) to a node of the structured ``chess-openings`` tree, and optionally
refines a chunk's mapping when a section title legally extends the page's line.

The mapping is rules-only and offline: it consumes the :class:`OpeningTree` snapshot
built by ``backend/app/services/opening_tree.py`` and never touches Milvus, MongoDB,
or a model. It records confidence and position relation explicitly so eval v2 can
diagnose current-node prose, direct-child prose, and deep-descendant pollution.

Resolution tiers, in order:

1. ``exact``        — the page's move path is itself a tree node.
2. ``transposition`` — the final position (EPD) matches a tree node reached by a
   different move order. Multiple matches are reported as ``ambiguous`` but still
   resolved deterministically to the first node.
3. ``ancestor``     — no named node at the exact path, so the deepest named ancestor
   along the UCI prefix is recorded with ``relation=descendant`` and a ``depth_delta``
   (the page line is ``depth_delta`` plies deeper than its node).
4. ``unmapped``     — no move line (e.g. the root "Chess Opening Theory" page) or an
   unparseable line. Such pages remain accepted with explicit absent metadata and a
   recorded reason.

``refine_section`` adds a fifth confidence ``refined_section`` for chunks whose section
title starts with SAN moves that legally continue the page line (used for candidate-move
sections such as "4...d5"). It is deliberately conservative: any leading non-move token
aborts the refinement.
"""

import re
from dataclasses import dataclass

import chess

from backend.app.services.opening_tree import OpeningTree

ROOT_TITLE = "Chess Opening Theory"
PREFIX = ROOT_TITLE + "/"

CONF_EXACT = "exact"
CONF_TRANSPOSITION = "transposition"
CONF_ANCESTOR = "ancestor"
CONF_REFINED_SECTION = "refined_section"
CONF_UNMAPPED = "unmapped"

REL_EXACT = "exact"
REL_TRANSPOSITION = "transposition"
REL_DESCENDANT = "descendant"

REASON_NO_MOVE_LINE = "no_move_line"
REASON_UNPARSEABLE_MOVE_LINE = "unparseable_move_line"

_MAX_REFINEMENT_PLIES = 4

_MOVE_NUMBER_RE = re.compile(r"^\d+\s*\.{1,3}\s*")


@dataclass(frozen=True)
class PageMapping:
    node_id: str | None
    opening_name: str | None
    eco_code: str | None
    opening_path: tuple[str, ...]
    line_pgn: str | None
    move_sequence: tuple[str, ...]
    relation: str | None
    confidence: str
    depth_delta: int | None
    ambiguous: bool
    reason: str | None

    @property
    def status(self) -> str:
        return "mapped" if self.node_id is not None else "unmapped"

    def chunk_fields(self) -> dict:
        return {
            "opening_name": self.opening_name,
            "eco_code": self.eco_code,
            "opening_node_id": self.node_id,
            "opening_path": list(self.opening_path),
            "line_pgn": self.line_pgn,
            "move_sequence": list(self.move_sequence),
            "mapping_status": self.status,
            "mapping_confidence": self.confidence,
            "mapping_relation": self.relation,
            "mapping_depth_delta": self.depth_delta,
            "mapping_ambiguous": self.ambiguous,
        }

    def page_fields(self) -> dict:
        return {
            "status": self.status,
            "opening_node_id": self.node_id,
            "opening_name": self.opening_name,
            "eco_code": self.eco_code,
            "opening_path": list(self.opening_path),
            "relation": self.relation,
            "confidence": self.confidence,
            "depth_delta": self.depth_delta,
            "ambiguous": self.ambiguous,
            "reason": self.reason,
        }


def map_page(canonical_title: str, tree: OpeningTree) -> PageMapping:
    try:
        uci = _parse_title_moves(canonical_title)
    except ValueError as exc:
        return _unmapped(REASON_UNPARSEABLE_MOVE_LINE, str(exc))

    if not uci:
        return _unmapped(REASON_NO_MOVE_LINE, None)

    exact_ids = tree.by_uci_path.get(" ".join(uci))
    if exact_ids:
        return _from_node(tree.node(exact_ids[0]), uci, CONF_EXACT, REL_EXACT, 0)

    transposition_ids = tree.by_epd.get(_epd_of(uci))
    if transposition_ids:
        node = tree.node(transposition_ids[0])
        return _from_node(
            node,
            uci,
            CONF_TRANSPOSITION,
            REL_TRANSPOSITION,
            0,
            ambiguous=len(transposition_ids) > 1,
        )

    for length in range(len(uci) - 1, 0, -1):
        ancestor_ids = tree.by_uci_path.get(" ".join(uci[:length]))
        if ancestor_ids:
            node = tree.node(ancestor_ids[0])
            return _from_node(node, uci, CONF_ANCESTOR, REL_DESCENDANT, len(uci) - node.depth)

    return _unmapped(REASON_NO_MOVE_LINE, None)


def refine_section(
    page_mapping: PageMapping,
    section_title: str | None,
    tree: OpeningTree,
) -> PageMapping | None:
    if page_mapping.node_id is None or not section_title or not page_mapping.move_sequence:
        return None

    child_mapping = _match_direct_child_by_title(page_mapping, section_title, tree)
    if child_mapping is not None:
        return child_mapping

    extension = _parse_continuation(section_title, page_mapping.move_sequence)
    if not extension:
        return None

    extended = page_mapping.move_sequence + extension
    exact_ids = tree.by_uci_path.get(" ".join(extended))
    if exact_ids:
        return _from_node(tree.node(exact_ids[0]), extended, CONF_REFINED_SECTION, REL_EXACT, 0)

    for length in range(len(extended) - 1, len(page_mapping.move_sequence), -1):
        ancestor_ids = tree.by_uci_path.get(" ".join(extended[:length]))
        if ancestor_ids:
            node = tree.node(ancestor_ids[0])
            return _from_node(
                node,
                extended,
                CONF_REFINED_SECTION,
                REL_DESCENDANT,
                len(extended) - node.depth,
            )

    return None


def _match_direct_child_by_title(
    page_mapping: PageMapping,
    section_title: str,
    tree: OpeningTree,
) -> PageMapping | None:
    title_key = _text_key(section_title)
    for child_id in tree.children_by_parent.get(page_mapping.node_id or "", ()):
        child = tree.node(child_id)
        for alias in _opening_aliases(child.name):
            alias_key = _text_key(alias)
            if alias_key and (alias_key in title_key or title_key in alias_key):
                return _from_node(child, child.uci, CONF_REFINED_SECTION, REL_EXACT, 0)
    return None


def _parse_title_moves(title: str) -> tuple[str, ...]:
    if not title.startswith(PREFIX):
        return ()
    segments = [segment.strip() for segment in title[len(PREFIX):].split("/") if segment.strip()]
    if not segments:
        return ()

    board = chess.Board()
    uci: list[str] = []
    for segment in segments:
        token = _clean_move_token(segment)
        if not token:
            raise ValueError(f"empty move token in title {title!r}")
        try:
            move = board.parse_san(token)
        except ValueError as exc:
            raise ValueError(f"{token!r}: {exc}") from exc
        uci.append(move.uci())
        board.push(move)
    return tuple(uci)


def _parse_continuation(section_title: str, base_uci: tuple[str, ...]) -> tuple[str, ...] | None:
    board = chess.Board()
    for move_uci in base_uci:
        board.push(chess.Move.from_uci(move_uci))

    extension: list[str] = []
    for raw_token in section_title.split():
        token = _clean_move_token(raw_token)
        if not token:
            continue
        try:
            move = board.parse_san(token)
        except ValueError:
            break
        board.push(move)
        extension.append(move.uci())
        if len(extension) >= _MAX_REFINEMENT_PLIES:
            break
    return tuple(extension) if extension else None


def _clean_move_token(token: str) -> str:
    token = _MOVE_NUMBER_RE.sub("", token.strip())
    return token.rstrip("!?").rstrip("+#").strip(".,;:·—–()[]{}")


def _opening_aliases(name: str) -> tuple[str, ...]:
    aliases = [name]
    for separator in (":", ","):
        if separator in name:
            aliases.append(name.rsplit(separator, 1)[1].strip())
    return tuple(alias for alias in aliases if alias)


def _text_key(value: str) -> str:
    return " ".join(value.casefold().replace("defense", "defence").split())


def _epd_of(uci: tuple[str, ...]) -> str:
    board = chess.Board()
    for move_uci in uci:
        board.push(chess.Move.from_uci(move_uci))
    return board.epd()


def _line_pgn(uci: tuple[str, ...]) -> str:
    board = chess.Board()
    return board.variation_san([chess.Move.from_uci(move_uci) for move_uci in uci])


def _from_node(
    node,
    uci: tuple[str, ...],
    confidence: str,
    relation: str,
    depth_delta: int,
    *,
    ambiguous: bool = False,
) -> PageMapping:
    return PageMapping(
        node_id=node.node_id,
        opening_name=node.name,
        eco_code=node.eco,
        opening_path=node.opening_path,
        line_pgn=_line_pgn(uci),
        move_sequence=tuple(uci),
        relation=relation,
        confidence=confidence,
        depth_delta=depth_delta,
        ambiguous=ambiguous,
        reason=None,
    )


def _unmapped(reason: str, detail: str | None) -> PageMapping:
    return PageMapping(
        node_id=None,
        opening_name=None,
        eco_code=None,
        opening_path=(),
        line_pgn=None,
        move_sequence=(),
        relation=None,
        confidence=CONF_UNMAPPED,
        depth_delta=None,
        ambiguous=False,
        reason=reason if detail is None else f"{reason}: {detail}",
    )
