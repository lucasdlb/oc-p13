import re
import selectors
import shutil
import subprocess
import time
from functools import lru_cache
from typing import Any

import chess

from backend.app.core.settings import StockfishSettings


@lru_cache
def engine_version(binary: str) -> str:
    """Engine version via a one-shot UCI handshake, cached per binary.

    Returns "unknown" when the binary cannot be probed: a missing engine
    means no evaluation to cache anyway.
    """
    try:
        process = subprocess.Popen(
            [_resolve_binary(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return "unknown"

    assert process.stdin is not None
    assert process.stdout is not None
    try:
        process.stdin.write("uci\nquit\n")
        process.stdin.flush()
        output, _ = process.communicate(timeout=3)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        process.kill()
        return "unknown"

    for line in (output or "").splitlines():
        if line.startswith("id name "):
            return line[len("id name "):].strip()
    return "unknown"


class StockfishService:
    def __init__(self, settings: StockfishSettings) -> None:
        self.settings = settings

    def evaluate(self, fen: str, *, multipv: int = 1) -> dict[str, Any]:
        board = chess.Board(fen)
        command = "\n".join(
            [
                "uci",
                f"setoption name MultiPV value {multipv}",
                "isready",
                f"position fen {fen}",
                f"go depth {self.settings.depth}",
            ]
        ) + "\n"

        try:
            process = subprocess.Popen(
                [_resolve_binary(self.settings.binary)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except FileNotFoundError:
            return {"status": "unavailable", "reason": "binary_not_found"}
        except OSError:
            return {"status": "unavailable", "reason": "process_error"}

        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(command)
        process.stdin.flush()

        output: list[str] = []
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + self.settings.timeout_seconds
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    return {"status": "unavailable", "reason": "timeout"}
                if not selector.select(remaining):
                    process.kill()
                    return {"status": "unavailable", "reason": "timeout"}

                line = process.stdout.readline()
                if not line:
                    break
                output.append(line)
                if line.startswith("bestmove "):
                    try:
                        process.stdin.write("quit\n")
                        process.stdin.flush()
                        process.communicate(timeout=1)
                    except BrokenPipeError:
                        process.wait(timeout=1)
                    break
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return {"status": "unavailable", "reason": "timeout"}
        finally:
            selector.close()
            if process.poll() is None:
                process.kill()
                process.communicate()

        result = _parse_uci_output("".join(output), self.settings.depth, board.turn, multipv)
        return result or {"status": "unavailable", "reason": "invalid_uci_output"}


def _parse_uci_output(output: str, depth: int, side_to_move: bool = chess.WHITE, multipv: int = 1) -> dict[str, Any] | None:
    best_move: str | None = None
    variations: dict[int, dict[str, Any]] = {}

    for line in output.splitlines():
        if line.startswith("info "):
            depth_match = re.search(r"\bdepth (\d+)\b", line)
            if not depth_match or int(depth_match.group(1)) != depth:
                continue
            multipv_match = re.search(r"\bmultipv (\d+)\b", line)
            variation_number = int(multipv_match.group(1)) if multipv_match else 1
            score_match = re.search(r"\bscore (cp|mate) (-?\d+)", line)
            if score_match:
                value = int(score_match.group(2))
                if side_to_move == chess.BLACK:
                    value = -value
                pv_match = re.search(r"\bpv\s+(.+)$", line)
                pv = tuple(pv_match.group(1).split()) if pv_match else ()
                variations[variation_number] = {
                    "best_move": pv[0] if pv else None,
                    "score": {"type": score_match.group(1), "value": value},
                    "pv": pv,
                }
        elif line.startswith("bestmove "):
            candidate = line.split()[1:]
            if candidate and candidate[0] != "(none)":
                best_move = candidate[0]

    if best_move is None and not variations:
        return None

    primary = variations.get(1, {})
    if best_move is None:
        best_move = primary.get("best_move")
    if not best_move:
        return None
    if not primary:
        primary = {"best_move": best_move, "score": None, "pv": (best_move,)}

    return {
        "status": "ok",
        "best_move": best_move,
        "score": primary.get("score"),
        "depth": depth,
        "pv": tuple(primary.get("pv") or (best_move,)),
        "multipv": multipv,
        "variations": (
            [variations[number] for number in sorted(variations)]
            if multipv > 1
            else []
        ),
    }


def _resolve_binary(binary: str) -> str:
    if "/" in binary:
        return binary

    resolved = shutil.which(binary)
    if resolved:
        return resolved

    for candidate in (f"/usr/games/{binary}", f"/usr/local/games/{binary}"):
        if shutil.which(candidate):
            return candidate

    return binary
