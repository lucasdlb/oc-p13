"""Benchmark Stockfish latency across depth, MultiPV and engine threads.

Examples:
    python experiments/stockfish_latency.py --depths 8,10,12 --multipv 1,3
    python experiments/stockfish_latency.py --parallel 4 --format csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import selectors
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from itertools import product
from typing import Iterable


DEFAULT_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


@dataclass(frozen=True)
class Case:
    fen: str
    depth: int
    multipv: int
    threads: int
    hash_mb: int
    timeout_seconds: float


@dataclass(frozen=True)
class Result:
    fen: str
    depth: int
    multipv: int
    threads: int
    hash_mb: int
    timeout_seconds: float
    elapsed_ms: float
    status: str
    reason: str | None
    bestmove: str | None
    pv_lengths: tuple[int, ...]
    pvs: tuple[tuple[str, ...], ...]


def resolve_binary(binary: str) -> str:
    if os.path.sep in binary:
        return binary
    return shutil.which(binary) or binary


def run_case(case: Case, binary: str) -> Result:
    command = "\n".join(
        (
            "uci",
            f"setoption name Threads value {case.threads}",
            f"setoption name Hash value {case.hash_mb}",
            f"setoption name MultiPV value {case.multipv}",
            "isready",
            f"position fen {case.fen}",
            f"go depth {case.depth}",
        )
    ) + "\n"
    started = time.perf_counter()
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            [binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(command.encode())
        process.stdin.flush()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        output = bytearray()
        while True:
            remaining = case.timeout_seconds - (time.perf_counter() - started)
            if remaining <= 0 or not selector.select(remaining):
                return _failure(case, started, "timeout", process)
            chunk = os.read(process.stdout.fileno(), 8192)
            if not chunk:
                break
            output.extend(chunk)
            if b"\nbestmove " in output or output.startswith(b"bestmove "):
                process.stdin.write(b"quit\n")
                process.stdin.flush()
                process.wait(timeout=1)
                break
        selector.close()
        lines = output.decode(errors="replace").splitlines()

        bestmove = _bestmove(lines)
        pvs = _pvs(lines)
        if not bestmove:
            return _failure(case, started, "invalid_uci_output", process)
        return Result(
            fen=case.fen,
            depth=case.depth,
            multipv=case.multipv,
            threads=case.threads,
            hash_mb=case.hash_mb,
            timeout_seconds=case.timeout_seconds,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            status="ok",
            reason=None,
            bestmove=bestmove,
            pv_lengths=tuple(len(pv) for pv in pvs),
            pvs=tuple(pvs),
        )
    except subprocess.TimeoutExpired:
        return _failure(case, started, "timeout", process)
    except FileNotFoundError:
        return _failure(case, started, "binary_not_found", process)
    except OSError as exc:
        return _failure(case, started, f"process_error:{exc}", process)
    finally:
        _stop(process)


def _failure(
    case: Case,
    started: float,
    reason: str,
    process: subprocess.Popen[bytes] | None,
) -> Result:
    _stop(process)
    return Result(
        fen=case.fen,
        depth=case.depth,
        multipv=case.multipv,
        threads=case.threads,
        hash_mb=case.hash_mb,
        timeout_seconds=case.timeout_seconds,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        status="error",
        reason=reason,
        bestmove=None,
        pv_lengths=(),
        pvs=(),
    )


def _stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.kill()
    process.wait()


def _bestmove(lines: Iterable[str]) -> str | None:
    for line in reversed(list(lines)):
        if line.startswith("bestmove "):
            parts = line.split()
            return parts[1] if len(parts) > 1 and parts[1] != "(none)" else None
    return None


def _pvs(lines: Iterable[str]) -> list[tuple[str, ...]]:
    latest: dict[int, tuple[str, ...]] = {}
    for line in lines:
        if not line.startswith("info ") or " pv " not in line:
            continue
        fields = line.split()
        try:
            depth = int(fields[fields.index("depth") + 1])
            multipv = int(fields[fields.index("multipv") + 1]) if "multipv" in fields else 1
            pv_start = fields.index("pv") + 1
        except (ValueError, IndexError):
            continue
        if depth >= 0:
            latest[multipv] = tuple(fields[pv_start:])
    return [latest[number] for number in sorted(latest)]


def build_cases(args: argparse.Namespace) -> list[Case]:
    return [
        Case(args.fen, depth, multipv, threads, hash_mb, args.timeout)
        for depth, multipv, threads, hash_mb in product(
            args.depths,
            args.multipv,
            args.threads,
            args.hash_mb,
        )
    ]


def parse_ints(value: str) -> list[int]:
    try:
        values = [int(item) for item in value.split(",") if item]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated integers") from exc
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("values must be positive")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="stockfish")
    parser.add_argument("--fen", default=DEFAULT_FEN)
    parser.add_argument("--depths", type=parse_ints, default=[8, 10, 12, 14])
    parser.add_argument("--multipv", type=parse_ints, default=[1, 2, 3])
    parser.add_argument("--threads", type=parse_ints, default=[1, 2, 4])
    parser.add_argument("--hash-mb", type=parse_ints, default=[128])
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--parallel", type=int, default=1, help="concurrent Stockfish processes")
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    return parser.parse_args()


def print_results(results: list[Result], output_format: str) -> None:
    rows = [asdict(result) for result in results]
    if output_format == "json":
        print(json.dumps(rows, indent=2))
        return
    fields = [
        "depth",
        "multipv",
        "threads",
        "hash_mb",
        "elapsed_ms",
        "status",
        "reason",
        "bestmove",
        "pv_lengths",
    ]
    writer = csv.DictWriter(sys.stdout, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row[field] for field in fields})


def main() -> int:
    args = parse_args()
    if args.timeout <= 0 or args.parallel <= 0:
        print("--timeout and --parallel must be positive", file=sys.stderr)
        return 2

    binary = resolve_binary(args.binary)
    cases = build_cases(args)
    if args.parallel == 1:
        results = [run_case(case, binary) for case in cases]
    else:
        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            results = list(executor.map(lambda case: run_case(case, binary), cases))
    print_results(results, args.format)
    return 0 if all(result.status == "ok" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
