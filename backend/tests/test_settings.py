import logging

from backend.app.core.settings import (
    _parse_dotenv_line,
    _without_config_secrets,
    _with_secret_env,
)


def test_strips_lichess_token_from_config(caplog) -> None:  # type: ignore[no-untyped-def]
    config = {
        "lichess": {
            "enabled": True,
            "base_url": "https://explorer.lichess.org",
            "timeout_seconds": 2.0,
            "token": "toml-secret",
        }
    }

    with caplog.at_level(logging.WARNING, logger="backend.settings"):
        result = _without_config_secrets(config)

    assert result["lichess"] == {
        "enabled": True,
        "base_url": "https://explorer.lichess.org",
        "timeout_seconds": 2.0,
    }
    assert result["lichess"] is not config["lichess"]
    assert any(
        record.name == "backend.settings" and "is ignored" in record.getMessage()
        for record in caplog.records
    )


def test_strips_mongodb_uri_from_config(caplog) -> None:  # type: ignore[no-untyped-def]
    config = {
        "mongodb": {
            "enabled": True,
            "database": "chess_agent",
            "uri": "mongodb://from-config:27017",
        }
    }

    with caplog.at_level(logging.WARNING, logger="backend.settings"):
        result = _without_config_secrets(config)

    assert result["mongodb"] == {"enabled": True, "database": "chess_agent"}
    assert any(
        record.name == "backend.settings"
        and "mongodb.uri" in record.getMessage()
        and "is ignored" in record.getMessage()
        for record in caplog.records
    )


def test_with_secret_env_prefers_mongodb_uri_from_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("LICHESS_TOKEN", raising=False)
    monkeypatch.setattr(
        "backend.app.core.settings._read_dotenv_value",
        lambda name: "mongodb://env-host:27017" if name == "MONGODB_URI" else None,
    )

    result = _with_secret_env({"mongodb": {"database": "chess_agent"}})

    assert result["mongodb"]["uri"] == "mongodb://env-host:27017"
    assert result["mongodb"]["database"] == "chess_agent"


def test_with_secret_env_keeps_default_without_mongodb_uri(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("LICHESS_TOKEN", raising=False)
    monkeypatch.setattr("backend.app.core.settings._read_dotenv_value", lambda _name: None)

    result = _with_secret_env({"mongodb": {"database": "chess_agent"}})

    assert "uri" not in result["mongodb"]


def test_keeps_config_without_lichess_token_unchanged() -> None:
    config = {"logging": {"level": "INFO"}, "lichess": {"enabled": True}}

    assert _without_config_secrets(config) == config


def test_keeps_config_without_lichess_section_unchanged() -> None:
    config = {"logging": {"level": "INFO"}}

    assert _without_config_secrets(config) == config


def test_parses_plain_assignment() -> None:
    assert _parse_dotenv_line("LICHESS_TOKEN=abc") == ("LICHESS_TOKEN", "abc")


def test_strips_inline_comment() -> None:
    assert _parse_dotenv_line("LICHESS_TOKEN=abc # generated token") == ("LICHESS_TOKEN", "abc")


def test_parses_export_prefixed_assignment() -> None:
    assert _parse_dotenv_line("export LICHESS_TOKEN=abc") == ("LICHESS_TOKEN", "abc")


def test_parses_double_quoted_value() -> None:
    assert _parse_dotenv_line('LICHESS_TOKEN="abc"') == ("LICHESS_TOKEN", "abc")


def test_parses_single_quoted_value() -> None:
    assert _parse_dotenv_line("LICHESS_TOKEN='abc'") == ("LICHESS_TOKEN", "abc")


def test_quoted_value_ignores_trailing_comment() -> None:
    assert _parse_dotenv_line('LICHESS_TOKEN="abc" # note') == ("LICHESS_TOKEN", "abc")


def test_keeps_hash_inside_quoted_value() -> None:
    assert _parse_dotenv_line('LICHESS_TOKEN="ab#c"') == ("LICHESS_TOKEN", "ab#c")


def test_keeps_unspaced_hash_in_value() -> None:
    assert _parse_dotenv_line("LICHESS_TOKEN=abc#note") == ("LICHESS_TOKEN", "abc#note")


def test_ignores_comments_blank_lines_and_bare_text() -> None:
    assert _parse_dotenv_line("# comment") is None
    assert _parse_dotenv_line("") is None
    assert _parse_dotenv_line("   ") is None
    assert _parse_dotenv_line("just_text") is None


def test_empty_value_returns_empty_string() -> None:
    assert _parse_dotenv_line("LICHESS_TOKEN=") == ("LICHESS_TOKEN", "")
