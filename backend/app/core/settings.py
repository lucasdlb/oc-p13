from functools import lru_cache
import logging
import os
from pathlib import Path
from typing import Any, Literal
import tomllib

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


logger = logging.getLogger("backend.settings")

_DEFAULT_LLM_PROVIDERS = {
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "qwen2.5:7b-instruct",
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "nvidia/nemotron-3-super-120b-a12b",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-large-latest",
    },
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoggingSettings(StrictModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["json", "text"] = "json"
    request_id_header: str = Field(default="X-Request-ID", min_length=1)


class OrchestrationSettings(StrictModel):
    langgraph_enabled: bool = True


class LichessSettings(StrictModel):
    enabled: bool = False
    base_url: str = Field(default="https://explorer.lichess.org", min_length=1)
    timeout_seconds: float = Field(default=2.0, gt=0)
    token: SecretStr | None = None


class StockfishSettings(StrictModel):
    binary: str = Field(default="stockfish", min_length=1)
    depth: int = Field(default=12, ge=1, le=30)
    timeout_seconds: float = Field(default=5.0, gt=0)


class MongoSettings(StrictModel):
    enabled: bool = True
    uri: str = Field(default="mongodb://localhost:27017", min_length=1)
    database: str = Field(default="chess_agent", min_length=1)
    connect_timeout_seconds: float = Field(default=1.5, gt=0)
    lichess_cache_ttl_seconds: int = Field(default=86400, ge=1)
    videos_cache_ttl_seconds: int = Field(default=604800, ge=1)


class EmbeddingsSettings(StrictModel):
    base_url: str = Field(default="http://localhost:11434", min_length=1)
    model: str = Field(default="qwen3-embedding:0.6b", min_length=1)
    dimension: int = Field(default=1024, ge=1, le=4096)
    batch_size: int = Field(default=32, gt=0)
    keep_alive: str = Field(default="5m", min_length=1)
    query_instruction: str = Field(
        default="Given a web search query, retrieve relevant passages that answer the query",
        min_length=1,
    )
    timeout_seconds: float = Field(default=120.0, gt=0)


class MilvusSettings(StrictModel):
    uri: str = Field(default="http://localhost:19530", min_length=1)
    collection: str = Field(default="chess_knowledge", min_length=1)
    metric_type: Literal["COSINE", "L2", "IP"] = "COSINE"
    index_type: str = Field(default="HNSW", min_length=1)
    index_m: int = Field(default=16, ge=1)
    index_ef_construction: int = Field(default=200, ge=1)
    search_ef: int = Field(default=64, ge=1)
    dimension: int = Field(default=1024, ge=1, le=4096)
    max_text_length: int = Field(default=8000, ge=1)
    timeout_seconds: float = Field(default=10.0, gt=0)


class RagSettings(StrictModel):
    k: int = Field(default=5, gt=0)
    granularity: Literal["page", "section"] = "section"
    min_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    soft_eco_filter: bool = True


class LLMSettings(StrictModel):
    provider: Literal["ollama", "nvidia", "mistral"] = "ollama"
    base_url: str = Field(default="http://localhost:11434", min_length=1)
    model: str = Field(default="qwen2.5:7b-instruct", min_length=1)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, gt=0)
    num_ctx: int = Field(default=4096, gt=0)
    think: bool = False
    thinking: bool | None = None
    enable_thinking: bool | None = None
    reasoning_effort: Literal["none", "low", "medium", "high", "max"] | int | None = None
    keep_alive: str = Field(default="5m", min_length=1)
    seed: int | None = None
    timeout_seconds: float = Field(default=60.0, gt=0)
    coach_timeout_seconds: float = Field(default=12.0, gt=0)
    retries: int = Field(default=1, ge=0, le=3)
    retry_backoff_seconds: float = Field(default=2.0, gt=0)
    api_key: SecretStr | None = None

    @model_validator(mode="before")
    @classmethod
    def apply_provider_defaults(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        provider = values.get("provider", "ollama")
        defaults = _DEFAULT_LLM_PROVIDERS.get(provider)
        if defaults is None:
            return values
        return {
            **defaults,
            **values,
        }

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
    enabled: bool = False
    base_url: str = Field(default="https://api.typesafe.ai", min_length=1)
    model: str = Field(default="jev-latest", min_length=1)
    timeout_seconds: float = Field(default=1.0, gt=0)
    high_confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    medium_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_confidence_order(self) -> "TypeSafeSettings":
        if self.high_confidence < self.medium_confidence:
            raise ValueError("typesafe.high_confidence must be greater than or equal to medium_confidence")
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


class Settings(StrictModel):
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    orchestration: OrchestrationSettings = Field(default_factory=OrchestrationSettings)
    lichess: LichessSettings = Field(default_factory=LichessSettings)
    stockfish: StockfishSettings = Field(default_factory=StockfishSettings)
    mongodb: MongoSettings = Field(default_factory=MongoSettings)
    embeddings: EmbeddingsSettings = Field(default_factory=EmbeddingsSettings)
    milvus: MilvusSettings = Field(default_factory=MilvusSettings)
    rag: RagSettings = Field(default_factory=RagSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    typesafe: TypeSafeSettings = Field(default_factory=TypeSafeSettings)
    recommendations: RecommendationSettings = Field(default_factory=RecommendationSettings)

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
        return Settings.model_validate(_with_secret_env({}))

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
    _strip_config_key(
        stripped,
        "typesafe",
        "base_url",
        "typesafe.base_url found in config.toml is ignored: "
        "it is environment-specific and must come from TYPESAFE_BASE_URL "
        "in the environment or .env",
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

    typesafe_base_url = os.environ.get("TYPESAFE_BASE_URL") or _read_dotenv_value("TYPESAFE_BASE_URL")
    if typesafe_base_url:
        merged["typesafe"] = {**merged.get("typesafe", {}), "base_url": typesafe_base_url}

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
