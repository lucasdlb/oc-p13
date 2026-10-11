from functools import lru_cache
import logging
import os
from pathlib import Path
from typing import Literal
import tomllib

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


logger = logging.getLogger("backend.settings")

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsConfigError(RuntimeError):
    """Raised when the versioned runtime configuration cannot be loaded."""


class LoggingSettings(StrictModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    format: Literal["json", "text"]
    request_id_header: str = Field(min_length=1)


class OrchestrationSettings(StrictModel):
    langgraph_enabled: bool


class LichessSettings(StrictModel):
    enabled: bool
    base_url: str = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)
    token: SecretStr | None = None


class YouTubeSettings(StrictModel):
    enabled: bool
    base_url: str = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)
    max_results: int = Field(ge=1, le=50)
    relevance_language: str = Field(min_length=2, max_length=5)
    api_key: SecretStr | None = None


class StockfishSettings(StrictModel):
    binary: str = Field(min_length=1)
    depth: int = Field(ge=1, le=30)
    depth_by_level: dict[str, int]
    threads: int = Field(ge=1, le=1024)
    hash_mb: int = Field(ge=1, le=33554432)
    timeout_seconds: float = Field(gt=0)

    def depth_for_level(self, level: str) -> int:
        return self.depth_by_level.get(level, self.depth)


class MongoSettings(StrictModel):
    enabled: bool
    uri: str | None = Field(default=None, min_length=1)
    database: str = Field(min_length=1)
    connect_timeout_seconds: float = Field(gt=0)
    lichess_cache_ttl_seconds: int = Field(ge=1)
    videos_cache_ttl_seconds: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_uri_when_enabled(self) -> "MongoSettings":
        if self.enabled and not self.uri:
            raise ValueError("MONGODB_URI is required when mongodb.enabled = true")
        return self


class EmbeddingsSettings(StrictModel):
    base_url: str | None = Field(default=None, min_length=1)
    model: str = Field(min_length=1)
    dimension: int = Field(ge=1, le=4096)
    batch_size: int = Field(gt=0)
    keep_alive: str = Field(min_length=1)
    query_instruction: str = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_base_url(self) -> "EmbeddingsSettings":
        if not self.base_url:
            raise ValueError("OLLAMA_BASE_URL is required for embeddings")
        return self


class MilvusSettings(StrictModel):
    uri: str | None = Field(default=None, min_length=1)
    collection: str = Field(min_length=1)
    metric_type: Literal["COSINE", "L2", "IP"]
    index_type: str = Field(min_length=1)
    index_m: int = Field(ge=1)
    index_ef_construction: int = Field(ge=1)
    search_ef: int = Field(ge=1)
    dimension: int = Field(ge=1, le=4096)
    max_text_length: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_uri(self) -> "MilvusSettings":
        if not self.uri:
            raise ValueError("MILVUS_URI is required")
        return self


class RagSettings(StrictModel):
    k: int = Field(gt=0)
    granularity: Literal["page", "section"]
    min_score: float = Field(ge=-1.0, le=1.0)
    soft_eco_filter: bool


class LLMSettings(StrictModel):
    provider: Literal["ollama", "nvidia", "mistral"]
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(gt=0)
    num_ctx: int = Field(gt=0)
    think: bool
    thinking: bool | None = None
    enable_thinking: bool | None = None
    reasoning_effort: Literal["none", "low", "medium", "high", "max"] | int | None = None
    keep_alive: str = Field(min_length=1)
    seed: int | None = None
    timeout_seconds: float = Field(gt=0)
    coach_timeout_seconds: float = Field(gt=0)
    retries: int = Field(ge=0, le=3)
    retry_backoff_seconds: float = Field(gt=0)
    api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_provider_credentials(self) -> "LLMSettings":
        if self.provider == "ollama" and self.api_key:
            raise ValueError("llm.api_key is not valid for the ollama provider")
        if self.provider != "ollama" and not self.api_key:
            raise ValueError(f"an API key is required for the {self.provider} provider")
        return self

    @model_validator(mode="after")
    def validate_reasoning_controls(self) -> "LLMSettings":
        controls = [self.thinking, self.enable_thinking, self.reasoning_effort]
        if sum(control is not None for control in controls) > 1:
            raise ValueError("llm.thinking, llm.enable_thinking, and llm.reasoning_effort are mutually exclusive")
        if isinstance(self.reasoning_effort, int) and not 1 <= self.reasoning_effort <= 100:
            raise ValueError("llm.reasoning_effort must be between 1 and 100")
        return self


class TypeSafeSettings(StrictModel):
    enabled: bool
    base_url: str | None = Field(default=None, min_length=1)
    model: str = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)
    high_confidence: float = Field(ge=0.0, le=1.0)
    medium_confidence: float = Field(ge=0.0, le=1.0)
    api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_confidence_order(self) -> "TypeSafeSettings":
        if self.high_confidence < self.medium_confidence:
            raise ValueError("typesafe.high_confidence must be greater than or equal to medium_confidence")
        if self.enabled and not self.api_key:
            raise ValueError("TYPESAFE_API_KEY is required when typesafe.enabled = true")
        if self.enabled and not self.base_url:
            raise ValueError("typesafe.base_url is required when typesafe.enabled = true")
        return self


class RatingPresetSettings(StrictModel):
    min: int = Field(ge=0)
    max: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> "RatingPresetSettings":
        if self.min > self.max:
            raise ValueError("recommendations.rating_presets.min must be less than or equal to max")
        return self


class RecommendationSettings(StrictModel):
    min_move_share: float = Field(ge=0, le=1)
    min_position_games: int = Field(ge=0)
    default_moves: int = Field(gt=0)
    rating_presets: dict[str, RatingPresetSettings]


class Settings(StrictModel):
    logging: LoggingSettings
    orchestration: OrchestrationSettings
    lichess: LichessSettings
    youtube: YouTubeSettings
    stockfish: StockfishSettings
    mongodb: MongoSettings
    embeddings: EmbeddingsSettings
    milvus: MilvusSettings
    rag: RagSettings
    llm: LLMSettings
    typesafe: TypeSafeSettings
    recommendations: RecommendationSettings

    @model_validator(mode="after")
    def validate_embedding_dimension(self) -> "Settings":
        if self.embeddings.dimension != self.milvus.dimension:
            raise ValueError("embeddings.dimension must match milvus.dimension")
        return self


def _config_path() -> Path:
    override = os.environ.get("CONFIG_PATH")
    return Path(override) if override else Path(__file__).resolve().parents[3] / "config.toml"


def _env_path() -> Path:
    return Path(__file__).resolve().parents[3] / ".env"


@lru_cache
def get_settings() -> Settings:
    path = _config_path()
    if not path.exists():
        raise SettingsConfigError(f"runtime config file not found: {path}")

    with path.open("rb") as config_file:
        config = _without_config_secrets(tomllib.load(config_file))
        return Settings.model_validate(_with_secret_env(config))


def _without_config_secrets(config: dict) -> dict:
    stripped = {**config}

    _strip_config_key(
        stripped,
        "lichess",
        "token",
        "lichess.token found in config.toml is ignored: "
        "secrets must come from LICHESS_TOKEN in the environment or .env",
    )
    _strip_config_key(
        stripped,
        "youtube",
        "api_key",
        "youtube.api_key found in config.toml is ignored: "
        "secrets must come from YOUTUBE_API_KEY in the environment or .env",
    )
    _strip_config_key(
        stripped,
        "mongodb",
        "uri",
        "mongodb.uri found in config.toml is ignored: "
        "the URI is environment-specific and must come from MONGODB_URI "
        "in the environment or .env",
    )
    _strip_config_key(
        stripped,
        "milvus",
        "uri",
        "milvus.uri found in config.toml is ignored: "
        "the URI is environment-specific and must come from MILVUS_URI "
        "in the environment or .env",
    )
    _strip_config_key(
        stripped,
        "embeddings",
        "base_url",
        "embeddings.base_url found in config.toml is ignored: "
        "it is environment-specific and must come from OLLAMA_BASE_URL "
        "in the environment or .env",
    )
    _strip_config_key(
        stripped,
        "llm",
        "api_key",
        "llm.api_key found in config.toml is ignored: "
        "secrets must come from the selected provider's environment variable",
    )
    llm = stripped.get("llm")
    if isinstance(llm, dict):
        providers = llm.get("providers")
        if isinstance(providers, dict):
            cleaned_providers = {}
            for provider, values in providers.items():
                if isinstance(values, dict):
                    cleaned_providers[provider] = {
                        key: value for key, value in values.items() if key != "api_key"
                    }
            stripped["llm"] = {**llm, "providers": cleaned_providers}
    _strip_config_key(
        stripped,
        "typesafe",
        "api_key",
        "typesafe.api_key found in config.toml is ignored: "
        "secrets must come from TYPESAFE_API_KEY in the environment or .env",
    )

    return stripped


def _strip_config_key(config: dict, section: str, key: str, message: str) -> None:
    values = config.get(section)
    if not isinstance(values, dict) or key not in values:
        return

    logger.warning(message)
    config[section] = {name: value for name, value in values.items() if name != key}


def _with_secret_env(config: dict) -> dict:
    merged = {**config}

    lichess_token = os.environ.get("LICHESS_TOKEN") or _read_dotenv_value("LICHESS_TOKEN")
    if lichess_token:
        merged["lichess"] = {**merged.get("lichess", {}), "token": lichess_token}

    youtube_api_key = os.environ.get("YOUTUBE_API_KEY") or _read_dotenv_value("YOUTUBE_API_KEY")
    if youtube_api_key:
        merged["youtube"] = {**merged.get("youtube", {}), "api_key": youtube_api_key}

    mongo_uri = os.environ.get("MONGODB_URI") or _read_dotenv_value("MONGODB_URI")
    if mongo_uri:
        merged["mongodb"] = {**merged.get("mongodb", {}), "uri": mongo_uri}

    milvus_uri = os.environ.get("MILVUS_URI") or _read_dotenv_value("MILVUS_URI")
    if milvus_uri:
        merged["milvus"] = {**merged.get("milvus", {}), "uri": milvus_uri}

    ollama_base_url = os.environ.get("OLLAMA_BASE_URL") or _read_dotenv_value("OLLAMA_BASE_URL")
    if ollama_base_url:
        merged["embeddings"] = {**merged.get("embeddings", {}), "base_url": ollama_base_url}

    llm_updates: dict[str, str] = {}
    llm_config = merged.get("llm")
    if isinstance(llm_config, dict):
        provider = llm_config.get("provider", "ollama")
        provider_config = llm_config.get("providers", {}).get(provider, {})
        if isinstance(provider_config, dict):
            merged["llm"] = {**llm_config, **provider_config}
        if provider == "ollama" and ollama_base_url:
            merged["llm"] = {**merged.get("llm", {}), "base_url": ollama_base_url}
        if isinstance(merged.get("llm"), dict):
            # Provider profiles are a config-loader concern, not LLMSettings fields.
            merged["llm"] = {key: value for key, value in merged["llm"].items() if key != "providers"}
        secret_name = {
            "nvidia": "NVIDIA_API_KEY",
            "mistral": "MISTRAL_API_KEY",
        }.get(provider)
        if secret_name:
            api_key = os.environ.get(secret_name) or _read_dotenv_value(secret_name)
            if api_key:
                llm_updates["api_key"] = api_key

    if llm_updates:
        merged["llm"] = {**merged.get("llm", {}), **llm_updates}

    typesafe_api_key = os.environ.get("TYPESAFE_API_KEY") or _read_dotenv_value("TYPESAFE_API_KEY")
    if typesafe_api_key:
        merged["typesafe"] = {**merged.get("typesafe", {}), "api_key": typesafe_api_key}

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
