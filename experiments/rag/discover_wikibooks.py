"""Discover the complete ``Chess Opening Theory/`` Wikibooks page set.

Ticket 02 of the RAG full-Wikibooks work. This only enumerates the discoverable page set
(titles, page IDs, redirect map); it does NOT fetch wikitext, clean, chunk, or touch Milvus.
The next ticket (03, versioned manifest) consumes the produced artifact.

Run: ``uv run python -m experiments.rag.discover_wikibooks``
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).with_name("corpus_config.json")
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus" / "wikibooks-discovery"

PREFIX = "Chess Opening Theory"
ROOT_TITLE = PREFIX
SUBPAGE_PREFIX = PREFIX + "/"
REDIRECT_BATCH_SIZE = 50
REQUEST_SLEEP = 1.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-pages", type=int, default=None, help="stop early after N content pages (for testing)")
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    wikibooks = config["wikibooks"]
    api_url = wikibooks["api_url"]
    headers = {"User-Agent": wikibooks["user_agent"]}

    args.output_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        content_pages, content_partial, content_cursor = _list_all(
            client, api_url, headers, apfilterredir="nonredirects", max_pages=args.max_pages
        )
        redirect_pages, redirect_partial, redirect_cursor = _list_all(
            client, api_url, headers, apfilterredir="redirects"
        )
        redirect_map = _resolve_redirects(client, api_url, headers, redirect_pages)

    complete = not (content_partial or redirect_partial)

    discovery = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_url": api_url,
        "user_agent": headers["User-Agent"],
        "prefix": PREFIX,
        "complete": complete,
        "partial_reason": None if complete else _partial_reason(content_partial, redirect_partial),
        "continue_cursor": {
            "content_pages": content_cursor,
            "redirects": redirect_cursor,
        },
        "summary": {
            "content_pages": len(content_pages),
            "redirects": len(redirect_map),
        },
        "content_pages": content_pages,
        "redirects": redirect_map,
    }

    target = args.output_dir / "discovery.json"
    target.write_text(json.dumps(discovery, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"content pages : {len(content_pages)}")
    print(f"redirects     : {len(redirect_map)}")
    print(f"complete      : {complete}")
    print(f"wrote         : {target}")
    return 0


def _in_scope(title: str) -> bool:
    return title == ROOT_TITLE or title.startswith(SUBPAGE_PREFIX)


def _list_all(
    client: httpx.Client,
    api_url: str,
    headers: dict,
    *,
    apfilterredir: str,
    max_pages: int | None = None,
) -> tuple[list[dict], bool, str | None]:
    pages: list[dict] = []
    params = {
        "action": "query",
        "format": "json",
        "list": "allpages",
        "apprefix": PREFIX,
        "apnamespace": "0",
        "aplimit": "500",
        "apfilterredir": apfilterredir,
    }
    partial = False
    cursor: str | None = None

    while True:
        payload = _api_get(client, api_url, headers, params)
        if payload is None:
            partial = True
            break
        batch = payload.get("query", {}).get("allpages", [])
        pages.extend(
            {
                "title": p["title"],
                "page_id": p["pageid"],
                "source_url": "https://en.wikibooks.org/wiki/" + p["title"].replace(" ", "_"),
            }
            for p in batch
            if _in_scope(p["title"])
        )
        if max_pages is not None and len(pages) >= max_pages:
            partial = True
            break
        continuation = payload.get("continue", {})
        apcontinue = continuation.get("apcontinue")
        if not apcontinue:
            break
        cursor = apcontinue
        params["apcontinue"] = apcontinue
        time.sleep(REQUEST_SLEEP)

    return pages, partial, cursor


def _resolve_redirects(
    client: httpx.Client,
    api_url: str,
    headers: dict,
    redirect_pages: list[dict],
) -> list[dict]:
    resolved: list[dict] = []
    for i in range(0, len(redirect_pages), REDIRECT_BATCH_SIZE):
        batch = redirect_pages[i : i + REDIRECT_BATCH_SIZE]
        titles = "|".join(p["title"] for p in batch)
        params = {
            "action": "query",
            "format": "json",
            "titles": titles,
            "redirects": "1",
        }
        payload = _api_get(client, api_url, headers, params)
        if payload is None:
            for p in batch:
                resolved.append({"from": p["title"], "to": None, "page_id": p["page_id"]})
            continue

        redirect_targets = payload.get("query", {}).get("redirects", [])
        targets_by_from = {r["from"]: r["to"] for r in redirect_targets}
        for p in batch:
            resolved.append(
                {
                    "from": p["title"],
                    "to": targets_by_from.get(p["title"]),
                    "page_id": p["page_id"],
                }
            )
        time.sleep(REQUEST_SLEEP)

    return resolved


def _api_get(
    client: httpx.Client,
    api_url: str,
    headers: dict,
    params: dict,
    attempts: int = 4,
) -> dict | None:
    for attempt in range(attempts):
        try:
            response = client.get(api_url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < attempts - 1:
                time.sleep(15.0 * (attempt + 1))
                continue
            print(f"skip request: {exc}")
            return None
        except (httpx.HTTPError, ValueError) as exc:
            print(f"skip request: {exc}")
            return None
    return None


def _partial_reason(content_partial: bool, redirect_partial: bool) -> str:
    reasons = []
    if content_partial:
        reasons.append("content page enumeration did not exhaust pagination")
    if redirect_partial:
        reasons.append("redirect enumeration did not exhaust pagination")
    return "; ".join(reasons)


if __name__ == "__main__":
    raise SystemExit(main())
