"""Fetch the curated RAG corpus into `.scratch/rag/corpus/` (gitignored).

Sources (see `corpus_config.json`):
- `lichess-org/chess-openings` TSVs `a`-`e` (CC0-1.0): structured opening metadata for the
  matching / `eco_code` path; deliberately NOT vectorized into Milvus (ADR 0006).
- Curated Wikibooks Chess Opening Theory pages (CC BY-SA) via the MediaWiki API: the prose
  corpus that is actually ingested into Milvus.

Run: `uv run python -m experiments.rag.fetch_corpus`
"""

import argparse
import json
import re
import time
from pathlib import Path

import httpx


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).with_name("corpus_config.json")
DEFAULT_CORPUS_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--openings-only", action="store_true")
    parser.add_argument("--wikibooks-only", action="store_true")
    parser.add_argument("--force", action="store_true", help="re-download files that already exist")
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    args.corpus_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        if not args.wikibooks_only:
            _fetch_openings(client, config["openings_tsv"], args.corpus_dir, force=args.force)
        if not args.openings_only:
            _fetch_wikibooks(client, config["wikibooks"], args.corpus_dir, force=args.force)

    return 0


def _fetch_openings(client: httpx.Client, config: dict, corpus_dir: Path, *, force: bool) -> None:
    dest = corpus_dir / "chess-openings"
    dest.mkdir(parents=True, exist_ok=True)

    for name in config["files"]:
        target = dest / name
        if target.exists() and not force:
            print(f"openings   {name}: cached")
            continue
        url = f"{config['base_url'].rstrip('/')}/{name}"
        response = client.get(url)
        response.raise_for_status()
        target.write_text(response.text, encoding="utf-8")
        print(f"openings   {name}: {len(response.text.splitlines()) - 1} rows")


def _fetch_wikibooks(client: httpx.Client, config: dict, corpus_dir: Path, *, force: bool) -> None:
    dest = corpus_dir / "wikibooks"
    dest.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": config["user_agent"]}

    for page in config["pages"]:
        target = dest / f"{_slug(page['title'])}.json"
        if target.exists() and not force:
            print(f"wikibooks  {page['title']}: cached")
            continue

        payload = _fetch_page(client, config["api_url"], headers, page["title"])
        if payload is None:
            continue

        document = {
            "title": payload["parse"]["title"],
            "url": "https://en.wikibooks.org/wiki/" + payload["parse"]["title"].replace(" ", "_"),
            "eco": page["eco"],
            "opening_name": page["opening_name"],
            "wikitext": payload["parse"]["wikitext"]["*"],
        }
        target.write_text(
            json.dumps(document, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"wikibooks  {page['title']}: {len(document['wikitext'])} chars")
        time.sleep(1.0)


def _fetch_page(
    client: httpx.Client,
    api_url: str,
    headers: dict,
    title: str,
    attempts: int = 4,
) -> dict | None:
    params = {"action": "parse", "format": "json", "prop": "wikitext", "redirects": "1", "page": title}

    for attempt in range(attempts):
        try:
            response = client.get(api_url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
            payload["parse"]["wikitext"]["*"]
            return payload
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < attempts - 1:
                time.sleep(15.0 * (attempt + 1))
                continue
            print(f"wikibooks  SKIP {title}: {exc}")
            return None
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            print(f"wikibooks  SKIP {title}: {exc}")
            return None
    return None


def _slug(title: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", title).strip("_").lower()


if __name__ == "__main__":
    raise SystemExit(main())
