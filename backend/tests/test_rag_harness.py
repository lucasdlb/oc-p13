import argparse

import pytest
from pydantic import ValidationError

from backend.app.core.settings import Settings
from backend.tests.test_settings import _settings_config
from experiments.rag import run


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict = {
        "granularity": None,
        "k": None,
        "no_ingest": False,
        "resume": False,
        "reuse_from_collection": None,
        "ingest_mode": "full",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_load_settings_merges_env_aware_base_config_and_cli(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    base = Settings.model_validate(_settings_config(embeddings={"base_url": "http://from-env:11434"}))
    monkeypatch.setattr(run, "get_settings", lambda: base)

    config = {"rag": {"k": 3, "granularity": "page"}}
    settings = run._load_settings(config, _args(k=7))

    assert settings.embeddings.base_url == "http://from-env:11434"
    assert settings.rag.k == 7
    assert settings.rag.granularity == "page"


def test_load_settings_revalidates_invalid_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(run, "get_settings", lambda: Settings.model_validate(_settings_config()))

    with pytest.raises(ValidationError):
        run._load_settings({}, _args(k=-1))


def test_load_settings_rejects_invalid_granularity(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(run, "get_settings", lambda: Settings.model_validate(_settings_config()))

    with pytest.raises(ValidationError):
        run._load_settings({}, _args(granularity="paragraph"))


@pytest.mark.parametrize(
    "config",
    [
        {"embeddings": {"base_url": "http://config:11434"}},
        {"llm": {"base_url": "http://config:11434"}},
        {"milvus": {"uri": "http://config:19530"}},
    ],
)
def test_load_settings_rejects_environment_specific_config_values(config: dict) -> None:
    with pytest.raises(ValueError):
        run._load_settings(config, _args())


@pytest.mark.parametrize("value", [-1, True, "1"])
def test_validate_limit_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValueError):
        run._validate_limit("wikibooks_limit", value)


def test_validate_limit_accepts_zero_and_none() -> None:
    run._validate_limit("wikibooks_limit", 0)
    run._validate_limit("wikibooks_limit", None)


def test_zero_wikibooks_limit_loads_no_sources(tmp_path) -> None:  # type: ignore[no-untyped-def]
    wikibooks = tmp_path / "wikibooks"
    wikibooks.mkdir()
    (wikibooks / "page.json").write_text(
        '{"title":"Chess Opening Theory/Test","wikitext":"Useful prose."}',
        encoding="utf-8",
    )

    assert run._load_sources(tmp_path, wikibooks_limit=0) == []


def test_collection_name_is_deterministic_and_fingerprinted() -> None:
    settings = Settings.model_validate(_settings_config())
    first = run._collection_name("section", settings, "corpus-a", "model@rev")
    again = run._collection_name("section", settings, "corpus-a", "model@rev")
    other_corpus = run._collection_name("section", settings, "corpus-b", "model@rev")
    other_model = run._collection_name("section", settings, "corpus-a", "model@rev2")

    assert first == again
    assert first.startswith("chess_knowledge_section_")
    assert first != other_corpus
    assert first != other_model


def test_collection_name_changes_with_wikibooks_cleaner(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings.model_validate(_settings_config())
    first = run._collection_name("section", settings, "corpus-a", "model@rev")

    monkeypatch.setattr(run, "WIKIBOOKS_CLEANER_VERSION", 999)

    assert run._collection_name("section", settings, "corpus-a", "model@rev") != first


def test_collection_name_changes_with_physical_index() -> None:
    settings = Settings.model_validate(_settings_config())
    first = run._collection_name("section", settings, "corpus-a", "model@rev")
    changed = settings.model_copy(
        update={"milvus": settings.milvus.model_copy(update={"index_m": 32})}
    )

    assert run._collection_name("section", changed, "corpus-a", "model@rev") != first


def test_is_remote_only_flags_non_loopback_hosts() -> None:
    assert run._is_remote("http://localhost:19530") is False
    assert run._is_remote("http://127.0.0.1:19530") is False
    assert run._is_remote("/tmp/milvus.db") is False
    assert run._is_remote("http://milvus.example.com:19530") is True


def test_resume_selects_incremental_ingestion() -> None:
    assert run._ingest_mode(_args(resume=True)) == "incremental"


def test_no_ingest_remains_strict_read_only() -> None:
    assert run._ingest_mode(_args(no_ingest=True)) == "no-ingest"
    with pytest.raises(ValueError):
        run._ingest_mode(_args(no_ingest=True, reuse_from_collection="old"))


def test_predecessor_reuse_must_be_explicitly_incremental() -> None:
    with pytest.raises(ValueError):
        run._ingest_mode(_args(reuse_from_collection="old"))
    assert (
        run._ingest_mode(
            _args(ingest_mode="incremental", reuse_from_collection="explicit-old")
        )
        == "incremental"
    )
