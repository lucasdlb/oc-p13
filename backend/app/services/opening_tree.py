"""Structured `lichess-org/chess-openings` snapshot and deterministic loader.

The opening tree is structured metadata, not Milvus prose. It can be built from
the five TSV files offline, written as JSON artifacts, and loaded later without
MongoDB, Milvus, `RagService`, or `CoachService`.
"""

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import chess

from backend.app.services.retrieval_contracts import OpeningTreeContext, OpeningTreeNodeContext


SCHEMA_VERSION = 1
BUILDER_VERSION = 1
SOURCE_NAME = "lichess-org/chess-openings"
DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[3] / ".scratch" / "rag" / "corpus"
DEFAULT_SOURCE_DIR = DEFAULT_CORPUS_DIR / "chess-openings"
DEFAULT_OUTPUT_DIR = DEFAULT_CORPUS_DIR / "opening-tree"
_TSV_HEADER = ("eco", "name", "pgn")


class OpeningTreeError(RuntimeError):
    """Raised when an opening-tree snapshot cannot be built or loaded."""


@dataclass(frozen=True)
class OpeningNode:
    node_id: str
    eco: str
    name: str
    pgn: str
    uci: tuple[str, ...]
    san: tuple[str, ...]
    fen: str
    epd: str
    depth: int
    parent_node_id: str | None
    opening_path: tuple[str, ...]
    source_file: str
    source_row: int


@dataclass(frozen=True)
class OpeningTreeSnapshot:
    manifest: dict
    nodes: tuple[OpeningNode, ...]
    indexes: dict


@dataclass(frozen=True)
class OpeningWindow:
    current: OpeningNode
    parent: OpeningNode | None
    children: tuple[OpeningNode, ...]


@dataclass(frozen=True)
class RetrievalConstraints:
    current_node_ids: tuple[str, ...]
    parent_node_ids: tuple[str, ...]
    child_node_ids: tuple[str, ...]
    excluded_descendant_node_ids: tuple[str, ...]


class OpeningTree:
    def __init__(self, snapshot: OpeningTreeSnapshot):
        self.manifest = snapshot.manifest
        self.nodes = snapshot.nodes
        self.indexes = snapshot.indexes
        self.by_node_id = {node.node_id: node for node in self.nodes}
        self.by_uci_path: dict[str, tuple[str, ...]] = {
            key: tuple(value) for key, value in self.indexes.get("by_uci_path", {}).items()
        }
        self.by_epd: dict[str, tuple[str, ...]] = {
            key: tuple(value) for key, value in self.indexes.get("by_epd", {}).items()
        }
        self.children_by_parent: dict[str, tuple[str, ...]] = {
            key: tuple(value) for key, value in self.indexes.get("children_by_parent", {}).items()
        }
        self.aliases_by_epd: dict[str, tuple[str, ...]] = {
            key: tuple(value) for key, value in self.indexes.get("aliases_by_epd", {}).items()
        }

    @classmethod
    def from_snapshot_dir(cls, path: Path) -> "OpeningTree":
        return cls(load_opening_tree_snapshot(path))

    def node(self, node_id: str) -> OpeningNode:
        try:
            return self.by_node_id[node_id]
        except KeyError as exc:
            raise OpeningTreeError(f"unknown opening node {node_id!r}") from exc

    def identify_by_uci(self, moves: list[str] | tuple[str, ...]) -> OpeningNode | None:
        node_ids = self.by_uci_path.get(_uci_key(tuple(moves)))
        return self.node(node_ids[0]) if node_ids else None

    def identify_by_epd(self, epd: str) -> OpeningNode | None:
        node_ids = self.by_epd.get(epd)
        return self.node(node_ids[0]) if node_ids else None

    def identify_by_fen(self, fen: str) -> OpeningNode | None:
        return self.identify_by_epd(chess.Board(fen).epd())

    def window(self, node_id: str) -> OpeningWindow:
        current = self.node(node_id)
        parent = self.node(current.parent_node_id) if current.parent_node_id else None
        children = tuple(self.node(child_id) for child_id in self.children_by_parent.get(node_id, ()))
        return OpeningWindow(current=current, parent=parent, children=children)

    def retrieval_constraints(
        self,
        node_id: str,
        *,
        include_child_prose: bool = False,
    ) -> RetrievalConstraints:
        window = self.window(node_id)
        child_ids = tuple(child.node_id for child in window.children)
        return RetrievalConstraints(
            current_node_ids=(window.current.node_id,),
            parent_node_ids=(window.parent.node_id,) if window.parent else (),
            child_node_ids=child_ids if include_child_prose else (),
            excluded_descendant_node_ids=tuple(self._deep_descendants(node_id, set(child_ids))),
        )

    def context_for_position(
        self,
        *,
        moves: tuple[str, ...] | list[str] = (),
        fen: str | None = None,
    ) -> OpeningTreeContext:
        current = self.identify_by_uci(tuple(moves)) if moves else None
        if current is None and fen:
            current = self.identify_by_fen(fen)

        if current is None:
            return OpeningTreeContext(
                state="out_of_theory" if moves or fen else "unsupported",
            )

        window = self.window(current.node_id)
        direct_child_ids = {child.node_id for child in window.children}
        return OpeningTreeContext(
            state="matched",
            current=_node_context(window.current),
            parent=_node_context(window.parent) if window.parent else None,
            children=tuple(_node_context(child, entry_move=child.san[-1] if child.san else None) for child in window.children),
            excluded_descendant_node_ids=tuple(self._deep_descendants(current.node_id, direct_child_ids)),
        )

    def _deep_descendants(self, node_id: str, direct_children: set[str]) -> list[str]:
        deep: list[str] = []
        stack = list(self.children_by_parent.get(node_id, ()))
        while stack:
            current = stack.pop(0)
            if current not in direct_children:
                deep.append(current)
            stack.extend(self.children_by_parent.get(current, ()))
        return deep


def _node_context(node: OpeningNode, *, entry_move: str | None = None) -> OpeningTreeNodeContext:
    return OpeningTreeNodeContext(
        node_id=node.node_id,
        eco_code=node.eco,
        opening_name=node.name,
        pgn=node.pgn,
        uci=node.uci,
        san=node.san,
        fen=node.fen,
        epd=node.epd,
        depth=node.depth,
        entry_move=entry_move,
    )


def build_opening_tree_snapshot(source_dir: Path, output_dir: Path) -> OpeningTreeSnapshot:
    if not source_dir.exists():
        raise OpeningTreeError(f"opening TSV directory does not exist: {source_dir}")

    parsed: list[OpeningNode] = []
    skipped: list[dict] = []
    source_files: dict[str, dict] = {}
    rows_total = 0

    for path in sorted(source_dir.glob("*.tsv")):
        text = path.read_text(encoding="utf-8")
        rows_in_file = 0
        skipped_in_file = 0
        reader = csv.reader(io.StringIO(text), delimiter="\t")
        for source_row, row in enumerate(reader, start=1):
            if _is_header(row):
                continue
            rows_in_file += 1
            rows_total += 1
            if len(row) < 3:
                skipped_in_file += 1
                skipped.append(_skip(path.name, source_row, row, "missing required field"))
                continue

            eco, name, pgn = (field.strip() for field in row[:3])
            if not eco or not name or not pgn:
                skipped_in_file += 1
                skipped.append(_skip(path.name, source_row, row, "missing required field"))
                continue

            try:
                uci, san, fen, epd = _derive_position(pgn)
            except ValueError as exc:
                skipped_in_file += 1
                skipped.append(_skip(path.name, source_row, row, f"invalid PGN: {exc}"))
                continue

            parsed.append(
                OpeningNode(
                    node_id=_node_id(eco, name, pgn),
                    eco=eco,
                    name=name,
                    pgn=pgn,
                    uci=uci,
                    san=san,
                    fen=fen,
                    epd=epd,
                    depth=len(uci),
                    parent_node_id=None,
                    opening_path=(),
                    source_file=path.name,
                    source_row=source_row,
                )
            )
        source_files[path.name] = {
            "sha256": _sha256_text(text),
            "rows_total": rows_in_file,
            "rows_valid": rows_in_file - skipped_in_file,
            "rows_skipped": skipped_in_file,
        }

    if not source_files:
        raise OpeningTreeError(f"no TSV files found in {source_dir}")

    nodes = _with_relationships(parsed)
    indexes = _build_indexes(nodes)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "source": SOURCE_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_files": source_files,
        "rows_total": rows_total,
        "rows_valid": len(nodes),
        "rows_skipped": len(skipped),
        "skipped_rows": skipped,
    }
    snapshot = OpeningTreeSnapshot(manifest=manifest, nodes=tuple(nodes), indexes=indexes)
    _write_snapshot(snapshot, output_dir)
    return snapshot


def load_opening_tree_snapshot(path: Path) -> OpeningTreeSnapshot:
    manifest_path = path / "manifest.json"
    nodes_path = path / "nodes.json"
    indexes_path = path / "indexes.json"
    for artifact in (manifest_path, nodes_path, indexes_path):
        if not artifact.exists():
            raise OpeningTreeError(f"missing OpeningTree artifact: {artifact}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    nodes_payload = json.loads(nodes_path.read_text(encoding="utf-8"))
    indexes_payload = json.loads(indexes_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise OpeningTreeError(f"unsupported OpeningTree schema {manifest.get('schema_version')!r}")
    if nodes_payload.get("schema_version") != SCHEMA_VERSION:
        raise OpeningTreeError("nodes artifact schema does not match OpeningTree schema")
    if indexes_payload.get("schema_version") != SCHEMA_VERSION:
        raise OpeningTreeError("indexes artifact schema does not match OpeningTree schema")
    nodes = tuple(_node_from_json(row) for row in nodes_payload.get("nodes", []))
    return OpeningTreeSnapshot(manifest=manifest, nodes=nodes, indexes=indexes_payload.get("indexes", {}))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the structured chess-openings OpeningTree snapshot.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    try:
        snapshot = build_opening_tree_snapshot(args.source_dir, args.output_dir)
    except OpeningTreeError as exc:
        print(f"opening-tree failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "nodes": len(snapshot.nodes),
                "rows_total": snapshot.manifest["rows_total"],
                "rows_skipped": snapshot.manifest["rows_skipped"],
            },
            indent=2,
        )
    )
    return 0


def _derive_position(pgn: str) -> tuple[tuple[str, ...], tuple[str, ...], str, str]:
    board = chess.Board()
    uci: list[str] = []
    san: list[str] = []
    for token in _san_tokens(pgn):
        try:
            move = board.parse_san(token)
        except ValueError as exc:
            raise ValueError(f"{token!r}: {exc}") from exc
        san.append(token)
        uci.append(move.uci())
        board.push(move)
    if not uci:
        raise ValueError("empty movetext")
    return tuple(uci), tuple(san), board.fen(), board.epd()


def _san_tokens(pgn: str) -> list[str]:
    tokens: list[str] = []
    for raw_token in pgn.split():
        token = re.sub(r"^\d+\.(?:\.\.)?", "", raw_token.strip())
        if not token or token in {"*", "1-0", "0-1", "1/2-1/2"}:
            continue
        token = token.rstrip("!?")
        if token:
            tokens.append(token)
    return tokens


def _with_relationships(nodes: list[OpeningNode]) -> list[OpeningNode]:
    by_path: dict[tuple[str, ...], list[OpeningNode]] = {}
    for node in nodes:
        by_path.setdefault(node.uci, []).append(node)

    canonical_by_path = {path: sorted(values, key=_node_sort_key)[0] for path, values in by_path.items()}
    with_parent: dict[str, OpeningNode] = {}
    for node in sorted(nodes, key=_node_sort_key):
        parent_id = None
        for length in range(len(node.uci) - 1, 0, -1):
            parent = canonical_by_path.get(node.uci[:length])
            if parent is not None:
                parent_id = parent.node_id
                break
        with_parent[node.node_id] = _replace_node(node, parent_node_id=parent_id)

    def path_for(node: OpeningNode) -> tuple[str, ...]:
        path: list[str] = []
        current: OpeningNode | None = node
        seen: set[str] = set()
        while current is not None and current.node_id not in seen:
            seen.add(current.node_id)
            path.append(current.name)
            current = with_parent.get(current.parent_node_id) if current.parent_node_id else None
        return tuple(reversed(path))

    return [_replace_node(node, opening_path=path_for(node)) for node in with_parent.values()]


def _build_indexes(nodes: list[OpeningNode]) -> dict:
    by_uci_path: dict[str, list[str]] = {}
    by_epd: dict[str, list[str]] = {}
    by_eco: dict[str, list[str]] = {}
    by_normalized_name: dict[str, list[str]] = {}
    children_by_parent: dict[str, list[str]] = {}

    for node in sorted(nodes, key=_node_sort_key):
        by_uci_path.setdefault(_uci_key(node.uci), []).append(node.node_id)
        by_epd.setdefault(node.epd, []).append(node.node_id)
        by_eco.setdefault(node.eco, []).append(node.node_id)
        by_normalized_name.setdefault(_normalize_name(node.name), []).append(node.node_id)
        if node.parent_node_id is not None:
            children_by_parent.setdefault(node.parent_node_id, []).append(node.node_id)

    aliases_by_epd = {epd: node_ids for epd, node_ids in by_epd.items() if len(node_ids) > 1}
    return {
        "by_node_id": {node.node_id: node.node_id for node in sorted(nodes, key=_node_sort_key)},
        "by_uci_path": by_uci_path,
        "by_epd": by_epd,
        "by_eco": by_eco,
        "by_normalized_name": by_normalized_name,
        "children_by_parent": children_by_parent,
        "aliases_by_epd": aliases_by_epd,
    }


def _write_snapshot(snapshot: OpeningTreeSnapshot, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(snapshot.manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "nodes.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "nodes": [_node_to_json(node) for node in sorted(snapshot.nodes, key=_node_sort_key)],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (output_dir / "indexes.json").write_text(
        json.dumps(
            {"schema_version": SCHEMA_VERSION, "indexes": snapshot.indexes},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _node_to_json(node: OpeningNode) -> dict:
    row = asdict(node)
    row["uci"] = list(node.uci)
    row["san"] = list(node.san)
    row["opening_path"] = list(node.opening_path)
    return row


def _node_from_json(row: dict) -> OpeningNode:
    return OpeningNode(
        node_id=row["node_id"],
        eco=row["eco"],
        name=row["name"],
        pgn=row["pgn"],
        uci=tuple(row["uci"]),
        san=tuple(row["san"]),
        fen=row["fen"],
        epd=row["epd"],
        depth=row["depth"],
        parent_node_id=row.get("parent_node_id"),
        opening_path=tuple(row["opening_path"]),
        source_file=row["source_file"],
        source_row=row["source_row"],
    )


def _replace_node(
    node: OpeningNode,
    *,
    parent_node_id: str | None = None,
    opening_path: tuple[str, ...] | None = None,
) -> OpeningNode:
    return OpeningNode(
        node_id=node.node_id,
        eco=node.eco,
        name=node.name,
        pgn=node.pgn,
        uci=node.uci,
        san=node.san,
        fen=node.fen,
        epd=node.epd,
        depth=node.depth,
        parent_node_id=parent_node_id if parent_node_id is not None else node.parent_node_id,
        opening_path=opening_path if opening_path is not None else node.opening_path,
        source_file=node.source_file,
        source_row=node.source_row,
    )


def _skip(source_file: str, source_row: int, row: list[str], reason: str) -> dict:
    values = [field.strip() for field in row]
    return {
        "source_file": source_file,
        "source_row": source_row,
        "eco": values[0] if len(values) > 0 else None,
        "name": values[1] if len(values) > 1 else None,
        "pgn": values[2] if len(values) > 2 else None,
        "reason": reason,
    }


def _is_header(row: list[str]) -> bool:
    return tuple(field.strip().lower() for field in row[:3]) == _TSV_HEADER


def _node_id(eco: str, name: str, pgn: str) -> str:
    return hashlib.sha256(f"{SOURCE_NAME}\0{eco}\0{name}\0{pgn}".encode("utf-8")).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _uci_key(uci: tuple[str, ...]) -> str:
    return " ".join(uci)


def _normalize_name(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", name.casefold()).strip()


def _node_sort_key(node: OpeningNode) -> tuple[str, int, str, str, str]:
    return (node.source_file, node.source_row, node.eco, node.name, node.pgn)


if __name__ == "__main__":
    raise SystemExit(main())
