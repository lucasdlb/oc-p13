from functools import lru_cache
import logging
import os
from pathlib import Path
from typing import Literal
import tomllib

from pydantic import BaseModel, Field


logger = logging.getLogger("backend.settings")


class LoggingSettings(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["json", "text"] = "json"
    request_id_header: str = Field(default="X-Request-ID", min_length=1)


class LichessSettings(BaseModel):
    enabled: bool = False
    base_url: str = Field(default="https://explorer.lichess.org", min_length=1)
    timeout_seconds: float = Field(default=2.0, gt=0)
    token: str | None = None


class Settings(BaseModel):
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    lichess: LichessSettings = Field(default_factory=LichessSettings)


def _config_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config.toml"


def _env_path() -> Path:
    return Path(__file__).resolve().parents[3] / ".env"


@lru_cache
def get_settings() -> Settings:
    path = _config_path()
    if not path.exists():
        return Settings.model_validate(_with_secret_env({}))

    with path.open("rb") as config_file:
        config = _without_config_secrets(tomllib.load(config_file))
        return Settings.model_validate(_with_secret_env(config))


def _without_config_secrets(config: dict) -> dict:
    lichess = config.get("lichess")
    if not isinstance(lichess, dict) or "token" not in lichess:
        return config

    logger.warning(
        "lichess.token found in config.toml is ignored: "
        "secrets must come from LICHESS_TOKEN in the environment or .env"
    )
    merged = {**config}
    merged["lichess"] = {key: value for key, value in lichess.items() if key != "token"}
    return merged


def _with_secret_env(config: dict) -> dict:
    lichess_token = os.environ.get("LICHESS_TOKEN") or _read_dotenv_value("LICHESS_TOKEN")
    if not lichess_token:
        return config

    merged = {**config}
    merged["lichess"] = {**merged.get("lichess", {}), "token": lichess_token}
    return merged


def _read_dotenv_value(name: str) -> str | None:
    path = _env_path()
    if not path.exists():
        return None

    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_dotenv_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if key == name:
            return value or None

    return None


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export "):].lstrip()
    if "=" not in stripped:
        return None

    key, _, raw_value = stripped.partition("=")
    return key.strip(), _parse_dotenv_value(raw_value)


def _parse_dotenv_value(raw: str) -> str:
    value = raw.strip()
    if value[:1] in {'"', "'"}:
        return _unquote(value)

    comment_index = value.find(" #")
    if comment_index != -1:
        value = value[:comment_index].rstrip()
    return value


def _unquote(value: str) -> str:
    quote = value[0]
    end = value.find(quote, 1)
    if end == -1:
        return value
    return value[1:end]
