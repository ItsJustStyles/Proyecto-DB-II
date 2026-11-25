docker compose --profile test up -d --build keycloak redis db_test app_test
docker compose exec app_test python -m pytest -v  