"""Build the validated immutable Wikibooks snapshot (ticket 08).

Consumes the versioned manifest (ticket 03), the clean outputs (ticket 04), the
OpeningTree snapshot (ticket 00), and the frozen Eval V2 dataset (ticket 06), then
validates everything and writes an immutable snapshot directory. Fails closed on
any inconsistency.

Run: ``uv run python -m experiments.rag.build_snapshot``
"""

import argparse
import sys
from pathlib import Path

from backend.app.ingestion.snapshot import (
    SnapshotError,
    SnapshotValidationError,
    build_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / ".scratch" / "rag" / "corpus" / "wikibooks-full" / "manifest.json"
DEFAULT_CLEAN_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus" / "wikibooks-clean"
DEFAULT_OPENING_TREE_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus" / "opening-tree"
DEFAULT_EVAL_DATASET = REPO_ROOT / "experiments" / "rag" / "eval_v2" / "dataset.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus" / "wikibooks-snapshot"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--clean-dir", type=Path, default=DEFAULT_CLEAN_DIR)
    parser.add_argument("--opening-tree-dir", type=Path, default=DEFAULT_OPENING_TREE_DIR)
    parser.add_argument("--eval-dataset", type=Path, default=DEFAULT_EVAL_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--force", action="store_true", help="overwrite an existing snapshot")
    args = parser.parse_args()

    try:
        snapshot = build_snapshot(
            manifest_path=args.manifest,
            clean_dir=args.clean_dir,
            opening_tree_dir=args.opening_tree_dir,
            eval_dataset_path=args.eval_dataset,
            output_dir=args.output_dir,
            force=args.force,
        )
    except SnapshotValidationError as exc:
        print("snapshot validation failed:", file=sys.stderr)
        for error in exc.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    except SnapshotError as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 2

    counts = snapshot.manifest["counts"]
    print(f"snapshot : {snapshot.manifest['snapshot_id']}")
    print(f"hash     : {snapshot.snapshot_hash}")
    print(f"pages    : {counts['pages_total']} total -> {counts['pages_accepted']} accepted, "
          f"{counts['pages_rejected']} rejected")
    print(f"chunks   : {counts['chunks']}")
    print(f"output   : {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
