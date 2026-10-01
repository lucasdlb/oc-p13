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


class StockfishSettings(BaseModel):
    binary: str = Field(default="stockfish", min_length=1)
    depth: int = Field(default=12, ge=1, le=30)
    timeout_seconds: float = Field(default=5.0, gt=0)


class MongoSettings(BaseModel):
    enabled: bool = True
    uri: str = Field(default="mongodb://localhost:27017", min_length=1)
    database: str = Field(default="chess_agent", min_length=1)
    connect_timeout_seconds: float = Field(default=1.5, gt=0)
    lichess_cache_ttl_seconds: int = Field(default=86400, ge=1)
    videos_cache_ttl_seconds: int = Field(default=604800, ge=1)


class RatingPresetSettings(BaseModel):
    min: int = Field(ge=0)
    max: int = Field(ge=0)


class RecommendationSettings(BaseModel):
    min_move_share: float = Field(default=0.001, ge=0, le=1)
    min_position_games: int = Field(default=100, ge=0)
    default_moves: int = Field(default=12, gt=0)
    rating_presets: dict[str, RatingPresetSettings] = Field(
        default_factory=lambda: {
            "debutant": RatingPresetSettings(min=1000, max=1400),
            "intermediaire": RatingPresetSettings(min=1600, max=2000),
            "avance": RatingPresetSettings(min=2200, max=2500),
        }
    )


class Settings(BaseModel):
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    lichess: LichessSettings = Field(default_factory=LichessSettings)
    stockfish: StockfishSettings = Field(default_factory=StockfishSettings)
    mongodb: MongoSettings = Field(default_factory=MongoSettings)
    recommendations: RecommendationSettings = Field(default_factory=RecommendationSettings)


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
    stripped = {**config}

    lichess = stripped.get("lichess")
    if isinstance(lichess, dict) and "token" in lichess:
        logger.warning(
            "lichess.token found in config.toml is ignored: "
            "secrets must come from LICHESS_TOKEN in the environment or .env"
        )
        stripped["lichess"] = {key: value for key, value in lichess.items() if key != "token"}

    mongodb = stripped.get("mongodb")
    if isinstance(mongodb, dict) and "uri" in mongodb:
        logger.warning(
            "mongodb.uri found in config.toml is ignored: "
            "the URI is environment-specific and must come from MONGODB_URI "
            "in the environment or .env"
        )
        stripped["mongodb"] = {key: value for key, value in mongodb.items() if key != "uri"}

    return stripped


def _with_secret_env(config: dict) -> dict:
    merged = {**config}

    lichess_token = os.environ.get("LICHESS_TOKEN") or _read_dotenv_value("LICHESS_TOKEN")
    if lichess_token:
        merged["lichess"] = {**merged.get("lichess", {}), "token": lichess_token}

    mongo_uri = os.environ.get("MONGODB_URI") or _read_dotenv_value("MONGODB_URI")
    if mongo_uri:
        merged["mongodb"] = {**merged.get("mongodb", {}), "uri": mongo_uri}

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
