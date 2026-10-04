import hashlib
import json

from experiments.rag import fetch_manifest


def test_retry_delay_honors_retry_after_integer() -> None:
    assert fetch_manifest._retry_delay(0, "7") == 7.0


def test_retry_delay_honors_retry_after_fractional() -> None:
    assert fetch_manifest._retry_delay(2, "1.5") == 1.5


def test_retry_delay_ignores_non_numeric_retry_after() -> None:
    assert fetch_manifest._retry_delay(0, "Fri, 31 Dec 1999 23:59:59 GMT") == 15.0


def test_retry_delay_falls_back_when_absent() -> None:
    assert fetch_manifest._retry_delay(0, None) == 15.0
    assert fetch_manifest._retry_delay(2, None) == 45.0


def test_manifest_content_hash_is_stable_regardless_of_generated_at(tmp_path) -> None:
    page_results = {
        "Chess Opening Theory/1. e4": {
            "requested_title": "Chess Opening Theory/1. e4",
            "canonical_title": "Chess Opening Theory/1. e4",
            "wikibooks_page_id": 123,
            "wikibooks_revision_id": 456,
            "source_url": "https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4",
            "fetched_at": "2026-10-03T00:00:00+00:00",
            "raw_wikitext_sha256": hashlib.sha256(b"hello").hexdigest(),
            "local_filename": "chess_opening_theory_1_e4.json",
            "status": "fetched",
        }
    }
    (tmp_path / "chess_opening_theory_1_e4.json").write_text("{}")

    first, hash_a = fetch_manifest.build_manifest(
        api_url="https://en.wikibooks.org/w/api.php",
        user_agent="test",
        page_results=page_results,
        redirects=[],
        cache_dir=tmp_path,
        refresh="missing",
    )
    second, hash_b = fetch_manifest.build_manifest(
        api_url="https://en.wikibooks.org/w/api.php",
        user_agent="test",
        page_results=page_results,
        redirects=[],
        cache_dir=tmp_path,
        refresh="missing",
    )

    assert hash_a == hash_b
    assert first["content_hash"] == hash_a


def test_manifest_reports_stale_cache_files(tmp_path) -> None:
    page_results = {
        "Chess Opening Theory/1. e4": {
            "requested_title": "Chess Opening Theory/1. e4",
            "canonical_title": "Chess Opening Theory/1. e4",
            "wikibooks_page_id": 123,
            "wikibooks_revision_id": 456,
            "source_url": "https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4",
            "fetched_at": "2026-10-03T00:00:00+00:00",
            "raw_wikitext_sha256": hashlib.sha256(b"hello").hexdigest(),
            "local_filename": "chess_opening_theory_1_e4.json",
            "status": "fetched",
        }
    }
    (tmp_path / "chess_opening_theory_1_e4.json").write_text("{}")
    (tmp_path / "stale_page.json").write_text("{}")

    manifest, _ = fetch_manifest.build_manifest(
        api_url="https://en.wikibooks.org/w/api.php",
        user_agent="test",
        page_results=page_results,
        redirects=[],
        cache_dir=tmp_path,
        refresh="missing",
    )

    assert manifest["stale_cache_files"] == ["stale_page.json"]


def test_resolve_batch_follows_redirect() -> None:
    query = {
        "redirects": [{"from": "A", "to": "B"}],
        "pages": [{"pageid": 1, "ns": 0, "title": "B", "revisions": [{"revid": 9}]}],
    }
    resolved = fetch_manifest._resolve_batch(query, ["A"])
    assert resolved["A"][0] == "B"
    assert resolved["A"][1]["pageid"] == 1


def test_resolve_batch_reports_missing_page() -> None:
    query = {"pages": [{"title": "A", "missing": True}]}
    resolved = fetch_manifest._resolve_batch(query, ["A"])
    assert resolved["A"][0] == "A"
    assert resolved["A"][1]["missing"] is True
