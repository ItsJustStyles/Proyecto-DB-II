import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str

def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL")
    )

settings = load_settings()