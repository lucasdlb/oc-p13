import logging

from backend.app.core.settings import _parse_dotenv_line, _without_config_secrets


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
