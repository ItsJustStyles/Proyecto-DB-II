import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    cache_ttl_seconds: int
    max_retries: int
    # Keycloak:
    oidc_issuer: str
    oidc_jwks_url: str
    oidc_client_id: str


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL"),
        redis_url=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        cache_ttl_seconds=int(os.environ.get("CACHE_TTL_SECONDS", "300")),
        max_retries=int(os.environ.get("MAX_RETRIES", "3")),
        # Keycloak
        oidc_issuer=os.environ.get("OIDC_ISSUER", "http://localhost:8080/realms/medicitas"),
        oidc_jwks_url=os.environ.get(
            "OIDC_JWKS_URL", "http://keycloak:8080/realms/medicitas/protocol/openid-connect/certs"
        ),
        oidc_client_id=os.environ.get("OIDC_CLIENT_ID", "medicitas-api"),
    )


settings = load_settings()