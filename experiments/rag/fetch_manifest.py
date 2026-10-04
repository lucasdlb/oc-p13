"""Fetch the full Wikibooks snapshot and write a versioned, auditable manifest.

Ticket 03 of the RAG full-Wikibooks work. Consumes ``discovery.json`` (ticket 02) and, for
every discoverable content page, records: requested title, canonical title, Wikibooks page id,
revision id, source URL, fetch timestamp, raw wikitext sha256, local filename, status, and error.
Redirects are recorded as alias entries (requested -> canonical) without a separate fetch.

Refresh policies:

- ``missing`` (default): fetch only pages with no cache file yet; leave existing files untouched.
  Regenerating the manifest from an unchanged cache is byte-stable apart from ``generated_at``.
- ``changed``: refetch every page, but only overwrite a cache file (and bump its ``fetched_at``)
  when the raw wikitext hash differs. Unchanged pages keep their original timestamp.
- ``all``: refetch and overwrite every page.

A ``--reference`` run fails closed: it exits non-zero and refuses to mark the manifest complete
unless every content page fetched successfully.

HTTP 429 / Retry-After behavior: on a 429 the client honors the ``Retry-After`` header (integer
seconds; HTTP-date is treated as absent) and falls back to exponential backoff ``15 * (attempt+1)``
seconds otherwise. See :func:`_retry_delay` and :func:`_api_get`.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).with_name("corpus_config.json")
DEFAULT_DISCOVERY = REPO_ROOT / ".scratch" / "rag" / "corpus" / "wikibooks-discovery" / "discovery.json"
DEFAULT_CACHE_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus" / "wikibooks-full"

SOURCE = "wikibooks-chess-opening-theory"
BATCH_SIZE = 20
REQUEST_SLEEP = 1.0
MAX_ATTEMPTS = 4
BACKOFF_BASE = 15.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", type=Path, default=DEFAULT_DISCOVERY)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument(
        "--refresh",
        choices=["missing", "changed", "all"],
        default="missing",
    )
    parser.add_argument("--reference", action="store_true", help="fail closed unless all pages fetch")
    parser.add_argument("--max-pages", type=int, default=None, help="limit content pages fetched (testing)")
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    wikibooks = config["wikibooks"]
    api_url = wikibooks["api_url"]
    headers = {"User-Agent": wikibooks["user_agent"]}

    discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
    content_pages = discovery["content_pages"]
    redirects = discovery["redirects"]
    if args.max_pages is not None:
        content_pages = content_pages[: args.max_pages]

    args.cache_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        page_results, fetches_attempted = _fetch_content_pages(
            client, api_url, headers, content_pages, args.cache_dir, refresh=args.refresh
        )

    manifest, content_hash = build_manifest(
        api_url=api_url,
        user_agent=headers["User-Agent"],
        page_results=page_results,
        redirects=redirects,
        cache_dir=args.cache_dir,
        refresh=args.refresh,
    )

    manifest_path = args.cache_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.cache_dir / "manifest.json.sha256").write_text(
        hashlib.sha256(manifest_path.read_bytes()).hexdigest() + "\n",
        encoding="utf-8",
    )

    summary = manifest["summary"]
    print(f"content pages  : {summary['content_pages_requested']} requested, {summary['content_pages_fetched']} fetched")
    print(f"redirects      : {summary['redirects']}")
    print(f"errors/missing : {summary['pages_error']}/{summary['pages_missing']}")
    print(f"stale files    : {summary['stale_cache_files']}")
    print(f"complete       : {manifest['complete']}")
    print(f"content hash   : {content_hash}")
    print(f"manifest       : {manifest_path}")

    if args.reference and not manifest["complete"]:
        print("reference run failed: not all content pages fetched", file=sys.stderr)
        return 1
    return 0


def _slug(title: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", title).strip("_").lower()


def _page_id(title: str) -> str:
    return f"wikibooks::chess-opening-theory::{_slug(title)}"


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return BACKOFF_BASE * (attempt + 1)


def _api_get(
    client: httpx.Client,
    api_url: str,
    headers: dict,
    params: dict,
    *,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict | None:
    for attempt in range(max_attempts):
        try:
            response = client.get(api_url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < max_attempts - 1:
                time.sleep(_retry_delay(attempt, exc.response.headers.get("Retry-After")))
                continue
            print(f"skip request: {exc}")
            return None
        except (httpx.HTTPError, ValueError) as exc:
            print(f"skip request: {exc}")
            return None
    return None


def _fetch_content_pages(
    client: httpx.Client,
    api_url: str,
    headers: dict,
    content_pages: list[dict],
    cache_dir: Path,
    *,
    refresh: str,
) -> tuple[dict, int]:
    titles = [p["title"] for p in content_pages]
    page_results: dict = {}
    fetches_attempted = 0

    to_fetch: list[str] = []
    for title in titles:
        if refresh == "missing":
            filename = f"{_slug(title)}.json"
            target = cache_dir / filename
            if target.exists():
                try:
                    doc = json.loads(target.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    doc = None
                if doc is not None:
                    page_results[title] = _entry_from_cached_document(doc, filename)
                    continue
        to_fetch.append(title)

    for i in range(0, len(to_fetch), BATCH_SIZE):
        batch_titles = to_fetch[i : i + BATCH_SIZE]
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
            "prop": "revisions",
            "rvprop": "ids|content",
            "rvslots": "main",
            "titles": "|".join(batch_titles),
        }
        payload = _api_get(client, api_url, headers, params)
        if payload is None:
            for title in batch_titles:
                page_results[title] = {"status": "error", "error": "request_failed"}
            time.sleep(REQUEST_SLEEP)
            continue

        resolved = _resolve_batch(payload.get("query", {}), batch_titles)
        for requested, (canonical, page) in resolved.items():
            entry = _cache_page(requested, canonical, page, cache_dir, refresh=refresh)
            page_results[requested] = entry
            if entry["status"] == "fetched" and entry.get("written"):
                fetches_attempted += 1

        time.sleep(REQUEST_SLEEP)

    return page_results, fetches_attempted


def _entry_from_cached_document(doc: dict, filename: str) -> dict:
    return {
        "requested_title": doc.get("requested_title"),
        "canonical_title": doc.get("canonical_title"),
        "wikibooks_page_id": doc.get("wikibooks_page_id"),
        "wikibooks_revision_id": doc.get("wikibooks_revision_id"),
        "source_url": doc.get("source_url"),
        "fetched_at": doc.get("fetched_at"),
        "raw_wikitext_sha256": doc.get("raw_wikitext_sha256"),
        "local_filename": filename,
        "status": "fetched",
    }


def _resolve_batch(query: dict, requested_titles: list[str]) -> dict:
    redirects = query.get("redirects", [])
    normalized = query.get("normalized", [])
    pages = query.get("pages", [])

    redir = {r["from"]: r["to"] for r in redirects}
    norm = {n["from"]: n["to"] for n in normalized}
    by_title = {p["title"]: p for p in pages}

    resolved: dict = {}
    for title in requested_titles:
        canonical = norm.get(title, title)
        seen = set()
        while canonical in redir and canonical not in seen:
            seen.add(canonical)
            canonical = redir[canonical]
        resolved[title] = (canonical, by_title.get(canonical))
    return resolved


def _cache_page(
    requested: str,
    canonical: str,
    page: dict | None,
    cache_dir: Path,
    *,
    refresh: str,
) -> dict:
    if page is None:
        return {
            "requested_title": requested,
            "canonical_title": canonical,
            "status": "error",
            "error": "resolution_failed",
        }

    if page.get("missing"):
        return {
            "requested_title": requested,
            "canonical_title": canonical,
            "status": "missing",
            "error": "page_not_found",
        }

    revisions = page.get("revisions") or []
    revision = revisions[0] if revisions else {}
    content = (revision.get("slots", {}).get("main", {}) or {}).get("content")
    if content is None:
        return {
            "requested_title": requested,
            "canonical_title": canonical,
            "wikibooks_page_id": page.get("pageid"),
            "status": "error",
            "error": "no_wikitext",
        }

    new_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    filename = f"{_slug(canonical)}.json"
    target = cache_dir / filename

    existing = None
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            existing = None

    should_write = refresh == "all"
    if refresh == "missing":
        should_write = existing is None
    elif refresh == "changed":
        should_write = existing is None or existing.get("raw_wikitext_sha256") != new_sha

    fetched_at = None
    if should_write:
        fetched_at = datetime.now(timezone.utc).isoformat()
        document = {
            "requested_title": requested,
            "canonical_title": canonical,
            "wikibooks_page_id": page.get("pageid"),
            "wikibooks_revision_id": revision.get("revid"),
            "source_url": "https://en.wikibooks.org/wiki/" + canonical.replace(" ", "_"),
            "fetched_at": fetched_at,
            "raw_wikitext_sha256": new_sha,
            "wikitext": content,
        }
        target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif existing is not None:
        fetched_at = existing.get("fetched_at")
        new_sha = existing.get("raw_wikitext_sha256", new_sha)

    return {
        "requested_title": requested,
        "canonical_title": canonical,
        "wikibooks_page_id": page.get("pageid"),
        "wikibooks_revision_id": revision.get("revid"),
        "source_url": "https://en.wikibooks.org/wiki/" + canonical.replace(" ", "_"),
        "fetched_at": fetched_at,
        "raw_wikitext_sha256": new_sha,
        "local_filename": filename,
        "status": "fetched",
        "written": should_write,
    }


def build_manifest(
    *,
    api_url: str,
    user_agent: str,
    page_results: dict,
    redirects: list[dict],
    cache_dir: Path,
    refresh: str,
) -> tuple[dict, str]:
    content_pages_requested = len(page_results)
    fetched = [e for e in page_results.values() if e["status"] == "fetched"]
    errors = [e for e in page_results.values() if e["status"] == "error"]
    missing = [e for e in page_results.values() if e["status"] == "missing"]

    valid_files = {f"{(e['local_filename'])}" for e in fetched if e.get("local_filename")}
    stale_files = sorted(
        p.name for p in cache_dir.glob("*.json") if p.name not in valid_files and p.name != "manifest.json"
    )

    pages: list[dict] = []
    for entry in fetched:
        pages.append(
            {
                "page_id": _page_id(entry["canonical_title"]),
                "requested_title": entry["requested_title"],
                "canonical_title": entry["canonical_title"],
                "wikibooks_page_id": entry.get("wikibooks_page_id"),
                "wikibooks_revision_id": entry.get("wikibooks_revision_id"),
                "source_url": entry.get("source_url"),
                "fetched_at": entry.get("fetched_at"),
                "raw_wikitext_sha256": entry.get("raw_wikitext_sha256"),
                "local_filename": entry.get("local_filename"),
                "status": "fetched",
                "error": None,
            }
        )
    for entry in errors + missing:
        pages.append(
            {
                "page_id": _page_id(entry["canonical_title"]),
                "requested_title": entry["requested_title"],
                "canonical_title": entry["canonical_title"],
                "wikibooks_page_id": entry.get("wikibooks_page_id"),
                "wikibooks_revision_id": None,
                "source_url": entry.get("source_url"),
                "fetched_at": None,
                "raw_wikitext_sha256": None,
                "local_filename": None,
                "status": entry["status"],
                "error": entry.get("error"),
            }
        )

    canonical_titles = {e["canonical_title"] for e in fetched}
    for redirect in redirects:
        to = redirect.get("to")
        pages.append(
            {
                "page_id": _page_id(redirect["from"]),
                "requested_title": redirect["from"],
                "canonical_title": to,
                "wikibooks_page_id": redirect.get("page_id"),
                "wikibooks_revision_id": None,
                "source_url": "https://en.wikibooks.org/wiki/" + redirect["from"].replace(" ", "_"),
                "fetched_at": None,
                "raw_wikitext_sha256": None,
                "local_filename": f"{_slug(to)}.json" if to and to in canonical_titles else None,
                "status": "redirect",
                "error": None if to and to in canonical_titles else "redirect_target_not_in_corpus",
            }
        )

    pages.sort(key=lambda p: (p["requested_title"], p["status"]))

    complete = (content_pages_requested == len(fetched)) and not errors and not missing

    summary = {
        "content_pages_requested": content_pages_requested,
        "content_pages_fetched": len(fetched),
        "redirects": len(redirects),
        "pages_error": len(errors),
        "pages_missing": len(missing),
        "stale_cache_files": len(stale_files),
    }

    stable = {
        "schema_version": 1,
        "source": SOURCE,
        "api_url": api_url,
        "user_agent": user_agent,
        "refresh": refresh,
        "complete": complete,
        "summary": summary,
        "stale_cache_files": stale_files,
        "pages": pages,
    }
    content_hash = hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "api_url": api_url,
        "user_agent": user_agent,
        "refresh": refresh,
        "complete": complete,
        "content_hash": content_hash,
        "summary": summary,
        "stale_cache_files": stale_files,
        "pages": pages,
    }
    return manifest, content_hash


if __name__ == "__main__":
    raise SystemExit(main())
