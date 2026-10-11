from backend.app.core.settings import (
    EmbeddingsSettings,
    LichessSettings,
    LLMSettings,
    MilvusSettings,
    MongoSettings,
    Settings,
    StockfishSettings,
    TypeSafeSettings,
    YouTubeSettings,
)


def mongo_settings(**overrides) -> MongoSettings:  # type: ignore[no-untyped-def]
    values = {
        "enabled": True,
        "uri": "mongodb://localhost:27017",
        "database": "test",
        "connect_timeout_seconds": 0.05,
        "lichess_cache_ttl_seconds": 86400,
        "videos_cache_ttl_seconds": 604800,
    }
    values.update(overrides)
    return MongoSettings(**values)


def milvus_settings(**overrides) -> MilvusSettings:  # type: ignore[no-untyped-def]
    values = {
        "uri": "http://localhost:19530",
        "collection": "c",
        "metric_type": "COSINE",
        "index_type": "HNSW",
        "index_m": 16,
        "index_ef_construction": 200,
        "search_ef": 64,
        "dimension": 4,
        "max_text_length": 8000,
        "timeout_seconds": 10.0,
    }
    values.update(overrides)
    return MilvusSettings(**values)


def stockfish_settings(**overrides) -> StockfishSettings:  # type: ignore[no-untyped-def]
    values = {
        "binary": "stockfish",
        "depth": 12,
        "depth_by_level": {"debutant": 12, "intermediaire": 16, "avance": 20},
        "threads": 4,
        "hash_mb": 128,
        "timeout_seconds": 8.0,
    }
    values.update(overrides)
    return StockfishSettings(**values)


def youtube_settings(**overrides) -> YouTubeSettings:  # type: ignore[no-untyped-def]
    values = {
        "enabled": True,
        "base_url": "https://www.googleapis.com/youtube/v3",
        "timeout_seconds": 2.0,
        "max_results": 3,
        "relevance_language": "fr",
    }
    values.update(overrides)
    return YouTubeSettings(**values)


def lichess_settings(**overrides) -> LichessSettings:  # type: ignore[no-untyped-def]
    values = {
        "enabled": True,
        "base_url": "https://explorer.lichess.org",
        "timeout_seconds": 2.0,
    }
    values.update(overrides)
    return LichessSettings(**values)


def embeddings_settings(**overrides) -> EmbeddingsSettings:  # type: ignore[no-untyped-def]
    values = {
        "base_url": "http://localhost:11434",
        "model": "qwen3-embedding:0.6b",
        "dimension": 1024,
        "batch_size": 32,
        "keep_alive": "5m",
        "query_instruction": "Given a web search query, retrieve relevant passages that answer the query",
        "timeout_seconds": 120.0,
    }
    values.update(overrides)
    return EmbeddingsSettings(**values)


def llm_settings(**overrides) -> LLMSettings:  # type: ignore[no-untyped-def]
    values = {
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "qwen2.5:7b-instruct",
        "temperature": 0.2,
        "max_tokens": 512,
        "num_ctx": 4096,
        "think": False,
        "keep_alive": "5m",
        "timeout_seconds": 60.0,
        "coach_timeout_seconds": 12.0,
        "retries": 1,
        "retry_backoff_seconds": 2.0,
    }
    values.update(overrides)
    return LLMSettings(**values)


def typesafe_settings(**overrides) -> TypeSafeSettings:  # type: ignore[no-untyped-def]
    values = {
        "enabled": False,
        "base_url": None,
        "model": "jev-latest",
        "timeout_seconds": 5.0,
        "high_confidence": 0.75,
        "medium_confidence": 0.5,
    }
    values.update(overrides)
    return TypeSafeSettings(**values)


def app_settings(**overrides) -> Settings:  # type: ignore[no-untyped-def]
    from backend.tests.test_settings import _settings_config

    return Settings.model_validate(_settings_config(**overrides))
