import re
import selectors
import shutil
import subprocess
import time
from functools import lru_cache
from typing import Any

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

    def evaluate(self, fen: str) -> dict[str, Any]:
        command = "\n".join(
            [
                "uci",
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
        stop_sent = False
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
                if (
                    not stop_sent
                    and line.startswith("info ")
                    and re.search(rf"\bdepth {self.settings.depth}\b", line)
                ):
                    process.stdin.write("stop\nquit\n")
                    process.stdin.flush()
                    stop_sent = True
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

        result = _parse_uci_output("".join(output), self.settings.depth)
        return result or {"status": "unavailable", "reason": "invalid_uci_output"}


def _parse_uci_output(output: str, depth: int) -> dict[str, Any] | None:
    best_move: str | None = None
    score: dict[str, int | str] | None = None

    for line in output.splitlines():
        if line.startswith("info "):
            score_match = re.search(r"\bscore (cp|mate) (-?\d+)", line)
            if score_match:
                score = {"type": score_match.group(1), "value": int(score_match.group(2))}
        elif line.startswith("bestmove "):
            candidate = line.split()[1:]
            if candidate and candidate[0] != "(none)":
                best_move = candidate[0]

    if best_move is None or score is None:
        return None

    return {
        "status": "ok",
        "best_move": best_move,
        "score": score,
        "depth": depth,
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
