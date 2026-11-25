"""
I8 / Criterio 5: la disponibilidad servida desde Redis nunca contradice a PostgreSQL.
Complementa test_cache.py con reprogramacion entre fechas, cambios de horario y medicion antes/despues.
"""
import statistics
import time
from datetime import date, datetime, timedelta

import pytest

from .conftest import buscar_espacio, datos_clinica, reservar

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def c1(cliente):
    return datos_clinica(cliente, 1)


def _consultar_disponibilidad(cli, prof_id: int, fecha: date, serv_id: int) -> tuple[float, set[datetime]]:
    t0 = time.perf_counter()
    r = cli.get(
        f"/api/v1/profesionales/{prof_id}/disponibilidad",
        params={"fecha": fecha.isoformat(), "servicio_id": serv_id},
    )
    latencia_ms = (time.perf_counter() - t0) * 1000.0
    assert r.status_code == 200, r.text
    inicios = {datetime.fromisoformat(s["inicio"]) for s in r.json()["espacios"]}
    return latencia_ms, inicios


def test_reprogramar_entre_dias_actualiza_cache_origen_y_destino(cliente, c1, limpiar_citas):
    recep = cliente("recep1a")
    fecha_1, esp_1 = buscar_espacio(recep, c1["prof_a"], c1["serv_general"], desde_dias=3, max_dias=20)
    fecha_2, esp_2 = buscar_espacio(recep, c1["prof_a"], c1["serv_general"], desde_dias=25, max_dias=45)

    slot_origen = esp_1[0]["inicio"]
    slot_destino = esp_2[0]["inicio"]
    dt_origen = datetime.fromisoformat(slot_origen)
    dt_destino = datetime.fromisoformat(slot_destino)

    # 1) Reservar en fecha_1 y calentar ambas caches en Redis
    r = reservar(recep, c1["pacientes"][0], c1["prof_a"], c1["serv_general"], slot_origen)
    assert r.status_code == 201, r.text
    cita_id = r.json()["cita_id"]
    limpiar_citas.append(cita_id)

    _, libres_1_antes = _consultar_disponibilidad(recep, c1["prof_a"], fecha_1, c1["serv_general"])
    _, libres_2_antes = _consultar_disponibilidad(recep, c1["prof_a"], fecha_2, c1["serv_general"])
    assert dt_origen not in libres_1_antes
    assert dt_destino in libres_2_antes

    # 2) Reprogramar de fecha_1 hacia fecha_2 -> debe invalidar ambas fechas tras el commit
    rp = recep.post(f"/api/v1/citas/{cita_id}/reprogramar", json={"inicio": slot_destino})
    assert rp.status_code == 201, rp.text
    limpiar_citas.append(rp.json()["cita_id"])

    # 3) Sin esperar TTL, Redis refleja ambos cambios al instante
    _, libres_1_despues = _consultar_disponibilidad(recep, c1["prof_a"], fecha_1, c1["serv_general"])
    _, libres_2_despues = _consultar_disponibilidad(recep, c1["prof_a"], fecha_2, c1["serv_general"])
    assert dt_origen in libres_1_despues
    assert dt_destino not in libres_2_despues


def test_cambio_horario_semanal_invalida_cache_del_profesional(cliente, c1):
    admin = cliente("admin1")

    # Buscar un sabado futuro (dia_semana = 6, sin horario en la semilla)
    sabado = date.today() + timedelta(days=14)
    while sabado.isoweekday() != 6:
        sabado += timedelta(days=1)

    # 1) Primera consulta guarda lista vacia en cache
    _, antes = _consultar_disponibilidad(admin, c1["prof_a"], sabado, c1["serv_general"])
    assert antes == set()

    # 2) Agregar bloque horario el sabado -> invalida ver:prof en Redis
    h = admin.post(
        f"/api/v1/profesionales/{c1['prof_a']}/horarios",
        json={"dia_semana": 6, "hora_inicio": "08:00:00", "hora_fin": "10:00:00"},
    )
    assert h.status_code == 201, h.text
    horario_id = h.json()["horario_id"]

    try:
        # 3) La siguiente consulta ya devuelve los espacios nuevos sin esperar TTL
        _, despues = _consultar_disponibilidad(admin, c1["prof_a"], sabado, c1["serv_general"])
        assert len(despues) > 0
    finally:
        admin.delete(f"/api/v1/horarios/{horario_id}")


def test_medicion_latencia_antes_y_despues_de_cache(cliente, c1):
    """Mide tiempo de respuesta en Cache MISS (PostgreSQL) vs Cache HIT (Redis) para el informe."""
    recep = cliente("recep1a")

    # Elegir un dia habil lejano aun no consultado para forzar Cache MISS real
    fecha_virgen = date.today() + timedelta(days=60)
    while fecha_virgen.isoweekday() > 5:
        fecha_virgen += timedelta(days=1)

    # Antes (MISS: consulta a PostgreSQL + calculo de slots + escritura en Redis)
    ms_miss, espacios_miss = _consultar_disponibilidad(recep, c1["prof_a"], fecha_virgen, c1["serv_general"])
    assert espacios_miss

    # Despues (30 HITs consecutivos servidos directo desde Redis)
    tiempos_hit: list[float] = []
    for _ in range(30):
        ms_hit, espacios_hit = _consultar_disponibilidad(recep, c1["prof_a"], fecha_virgen, c1["serv_general"])
        assert espacios_hit == espacios_miss
        tiempos_hit.append(ms_hit)

    promedio_hit = statistics.mean(tiempos_hit)
    mediana_hit = statistics.median(tiempos_hit)
    print(
        f"\n[Benchmark RF7] MISS (PostgreSQL): {ms_miss:.2f} ms | "
        f"HIT (Redis) promedio: {promedio_hit:.2f} ms | mediana: {mediana_hit:.2f} ms"
    )
    assert promedio_hit > 0