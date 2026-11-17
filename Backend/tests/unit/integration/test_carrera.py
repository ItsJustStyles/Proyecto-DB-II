"""
Criterio 6 / pregunta rectora: dos recepcionistas reservan el ultimo espacio al mismo tiempo.

Que hace el sistema: ambas peticiones ejecutan un INSERT en su propia transaccion (READ COMMITTED).
La exclusion constraint ex_cita_profesional_sin_solape (I1) serializa a las dos sobre el mismo
rango: la segunda espera a que la primera confirme y recibe 23P01, que la API traduce a 409
ESPACIO_TOMADO. Resultado: exactamente una cita vigente, sin duplicados.

Reproducibilidad: un Barrier libera a todos los hilos a la vez y la prueba se repite varias
rondas con espacios distintos; el resultado debe ser identico en todas.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from .conftest import BASE_URL, buscar_espacio, datos_clinica, token

pytestmark = pytest.mark.integration

RONDAS = 10


def _post_concurrente(usuario: str, cuerpo: dict, barrera: threading.Barrier) -> tuple[int, dict]:
    with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token(usuario)}"}, timeout=30) as http:
        barrera.wait()
        r = http.post("/api/v1/citas", json=cuerpo)
        return r.status_code, r.json()


def _citas_vigentes_en(cliente, profesional_id: int, fecha, inicio: str) -> list[dict]:
    from datetime import datetime

    agenda = cliente("admin1").get("/api/v1/agenda", params={"fecha": fecha.isoformat(), "profesional_id": profesional_id}).json()
    objetivo = datetime.fromisoformat(inicio)
    return [c for c in agenda if c["estado_id"] == 1 and datetime.fromisoformat(c["inicio"]) == objetivo]


def test_dos_recepcionistas_un_solo_espacio(cliente):
    d = datos_clinica(cliente, 1)
    recep = cliente("recep1a")
    a_cancelar: list[int] = []
    for ronda in range(RONDAS):
        fecha, espacios = buscar_espacio(recep, d["prof_a"], d["serv_general"])
        inicio = espacios[0]["inicio"]
        barrera = threading.Barrier(2)
        pacientes = d["pacientes"][ronda % 6], d["pacientes"][(ronda % 6) + 6]  # distintos: aisla I1 de I2
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_post_concurrente, "recep1a", {"paciente_id": pacientes[0], "profesional_id": d["prof_a"], "servicio_id": d["serv_general"], "inicio": inicio}, barrera)
            f2 = pool.submit(_post_concurrente, "recep1b", {"paciente_id": pacientes[1], "profesional_id": d["prof_a"], "servicio_id": d["serv_general"], "inicio": inicio}, barrera)
            (s1, b1), (s2, b2) = f1.result(), f2.result()

        assert sorted([s1, s2]) == [201, 409], f"ronda {ronda}: {s1}, {s2}"
        perdedora = b1 if s1 == 409 else b2
        assert perdedora["detail"]["codigo"] == "ESPACIO_TOMADO"
        ganadora = b1 if s1 == 201 else b2
        a_cancelar.append(ganadora["cita_id"])
        # sin duplicados: exactamente una cita vigente en ese instante para ese profesional (I1)
        assert len(_citas_vigentes_en(cliente, d["prof_a"], fecha, inicio)) == 1
    for cita_id in a_cancelar:
        recep.post(f"/api/v1/citas/{cita_id}/cancelar", json={"motivo": "limpieza de prueba"})


def test_muchos_clientes_un_solo_espacio(cliente):
    """Mas contencion: 8 clientes simultaneos por el mismo espacio -> exactamente un 201."""
    d = datos_clinica(cliente, 1)
    recep = cliente("recep1a")
    fecha, espacios = buscar_espacio(recep, d["prof_a"], d["serv_general"])
    inicio = espacios[0]["inicio"]
    n = 8
    barrera = threading.Barrier(n)
    usuarios = ["recep1a", "recep1b"] * (n // 2)
    with ThreadPoolExecutor(max_workers=n) as pool:
        futuros = [
            pool.submit(_post_concurrente, usuarios[i], {"paciente_id": d["pacientes"][i], "profesional_id": d["prof_a"], "servicio_id": d["serv_general"], "inicio": inicio}, barrera)
            for i in range(n)
        ]
        resultados = [f.result() for f in futuros]
    codigos = [s for s, _ in resultados]
    assert codigos.count(201) == 1, codigos
    assert codigos.count(409) == n - 1, codigos
    assert len(_citas_vigentes_en(cliente, d["prof_a"], fecha, inicio)) == 1
    ganadora = next(b for s, b in resultados if s == 201)
    recep.post(f"/api/v1/citas/{ganadora['cita_id']}/cancelar", json={"motivo": "limpieza de prueba"})


def test_reprogramaciones_concurrentes_de_la_misma_cita(cliente, limpiar_citas):
    """Dos reprogramaciones simultaneas de la misma cita: una gana; la otra recibe 409 y no hay duplicados."""
    d = datos_clinica(cliente, 1)
    recep = cliente("recep1a")
    fecha, espacios = buscar_espacio(recep, d["prof_a"], d["serv_general"])
    assert len(espacios) >= 3
    r = recep.post("/api/v1/citas", json={"paciente_id": d["pacientes"][0], "profesional_id": d["prof_a"], "servicio_id": d["serv_general"], "inicio": espacios[0]["inicio"]})
    assert r.status_code == 201
    cita_id = r.json()["cita_id"]
    limpiar_citas.append(cita_id)
    barrera = threading.Barrier(2)

    def reprogramar(usuario: str, inicio: str):
        with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token(usuario)}"}, timeout=30) as http:
            barrera.wait()
            resp = http.post(f"/api/v1/citas/{cita_id}/reprogramar", json={"inicio": inicio})
            return resp.status_code, resp.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(reprogramar, "recep1a", espacios[-1]["inicio"])
        f2 = pool.submit(reprogramar, "recep1b", espacios[-2]["inicio"])
        (s1, b1), (s2, b2) = f1.result(), f2.result()
    assert sorted([s1, s2]) == [201, 409], (s1, s2)
    ganadora = b1 if s1 == 201 else b2
    limpiar_citas.append(ganadora["cita_id"])
    # la FOR UPDATE serializo las dos: la perdedora vio la cita ya REPROGRAMADA
    vigentes = [c for c in cliente("admin1").get("/api/v1/agenda", params={"fecha": fecha.isoformat(), "profesional_id": d["prof_a"]}).json()
                if c["paciente_id"] == d["pacientes"][0] and c["estado_id"] == 1]
    assert len(vigentes) == 1
