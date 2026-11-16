"""
Fixtures de integracion: hablan con la API real y con Keycloak real de la pila de Compose.

Ejecutar (desde la raiz del repo, con la pila arriba):
    docker compose exec app pytest
"""
import os
import random
from datetime import date, timedelta

import httpx
import pytest

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
TOKEN_URL = os.environ.get(
    "TEST_KEYCLOAK_TOKEN_URL", "http://localhost:8080/realms/medicitas/protocol/openid-connect/token"
)
PASSWORD = "Medicitas123!"
_tokens: dict[str, str] = {}


def token(username: str) -> str:
    if username not in _tokens:
        r = httpx.post(
            TOKEN_URL,
            data={"grant_type": "password", "client_id": "medicitas-api", "username": username, "password": PASSWORD},
            timeout=20,
        )
        r.raise_for_status()
        _tokens[username] = r.json()["access_token"]
    return _tokens[username]


class Cliente:
    """Cliente HTTP autenticado como un usuario de prueba (o anonimo)."""

    def __init__(self, username: str | None):
        headers = {"Authorization": f"Bearer {token(username)}"} if username else {}
        self.http = httpx.Client(base_url=BASE_URL, headers=headers, timeout=30)

    def get(self, url, **kw):
        return self.http.get(url, **kw)

    def post(self, url, **kw):
        return self.http.post(url, **kw)

    def patch(self, url, **kw):
        return self.http.patch(url, **kw)

    def put(self, url, **kw):
        return self.http.put(url, **kw)

    def delete(self, url, **kw):
        return self.http.delete(url, **kw)


@pytest.fixture(scope="session")
def cliente():
    creados: list[Cliente] = []

    def _f(username: str | None = None) -> Cliente:
        c = Cliente(username)
        creados.append(c)
        return c

    yield _f
    for c in creados:
        c.http.close()


# ------------------------------------------------------------------ ayudantes de dominio
def datos_clinica(cliente, n: int) -> dict:
    """Ids de la clinica n a partir de la semilla (profesional A, su servicio, pacientes)."""
    admin = cliente(f"admin{n}")
    profs = admin.get("/api/v1/profesionales").json()
    servs = {s["nombre"]: s for s in admin.get("/api/v1/servicios").json()}
    prof_a = next(p for p in profs if p["nombre"].startswith("Dra. Elena"))
    prof_b = next(p for p in profs if p["nombre"].startswith("Dr. Pablo"))
    pacientes = admin.get("/api/v1/pacientes", params={"limit": 200}).json()
    return {
        "prof_a": prof_a["profesional_id"],
        "prof_b": prof_b["profesional_id"],
        "serv_general": servs["Consulta general"]["servicio_id"],
        "serv_b": next(s["servicio_id"] for s in prof_b_servicios(profs, prof_b)),
        "pacientes": [p["paciente_id"] for p in pacientes],
    }


def prof_b_servicios(profs, prof_b):
    return [{"servicio_id": sid} for sid in prof_b["servicios"]]


def buscar_espacio(cli, profesional_id: int, servicio_id: int, desde_dias: int = 3, max_dias: int = 45):
    """Primer espacio libre de una fecha futura (aleatoria en el rango, para no chocar entre corridas)."""
    inicio = random.randint(desde_dias, desde_dias + 25)
    for delta in range(max_dias):
        fecha = date.today() + timedelta(days=inicio + delta)
        if fecha.isoweekday() > 5:
            continue
        r = cli.get(
            f"/api/v1/profesionales/{profesional_id}/disponibilidad",
            params={"fecha": fecha.isoformat(), "servicio_id": servicio_id},
        )
        assert r.status_code == 200, r.text
        if r.json()["espacios"]:
            return fecha, r.json()["espacios"]
    pytest.fail("No se encontro ningun espacio libre")


def reservar(cli, paciente_id, profesional_id, servicio_id, inicio):
    return cli.post(
        "/api/v1/citas",
        json={"paciente_id": paciente_id, "profesional_id": profesional_id, "servicio_id": servicio_id, "inicio": inicio},
    )


@pytest.fixture()
def limpiar_citas(cliente):
    """Cancela al terminar las citas que la prueba haya creado (deja libres los espacios)."""
    creadas: list[int] = []
    yield creadas
    recep = cliente("recep1a")
    for cita_id in creadas:
        recep.post(f"/api/v1/citas/{cita_id}/cancelar", json={"motivo": "limpieza de prueba"})
