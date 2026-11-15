import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    cache_ttl_seconds: int = 300

def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL"),
        redis_url=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        cache_ttl_seconds=int(os.environ.get("CACHE_TTL_SECONDS", "300")),
    )

settings = load_settings()