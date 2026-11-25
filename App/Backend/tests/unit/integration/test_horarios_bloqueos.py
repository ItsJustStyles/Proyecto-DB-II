"""I3: toda cita vigente cae dentro del horario de atencion del profesional y fuera de sus bloqueos."""
from datetime import date, datetime, timedelta

import pytest

from .conftest import buscar_espacio, datos_clinica, reservar

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def c1(cliente):
    return datos_clinica(cliente, 1)


def test_reserva_fuera_de_horario_atencion_es_rechazada(cliente, c1):
    recep = cliente("recep1a")
    fecha, _ = buscar_espacio(recep, c1["prof_a"], c1["serv_general"])
    madrugada = datetime.combine(fecha, datetime.min.time()).replace(hour=3).astimezone().isoformat()
    r = reservar(recep, c1["pacientes"][0], c1["prof_a"], c1["serv_general"], madrugada)
    assert r.status_code == 422, r.text


def test_reserva_dentro_de_bloqueo_es_rechazada(cliente, c1):
    admin = cliente("admin1")
    recep = cliente("recep1a")
    _, espacios = buscar_espacio(recep, c1["prof_a"], c1["serv_general"])
    objetivo = espacios[0]

    b = admin.post(
        f"/api/v1/profesionales/{c1['prof_a']}/bloqueos",
        json={"inicio": objetivo["inicio"], "fin": objetivo["fin"], "motivo": "Prueba I3 bloqueo"},
    )
    assert b.status_code == 201, b.text
    bloqueo_id = b.json()["bloqueo_id"]

    try:
        r = reservar(recep, c1["pacientes"][0], c1["prof_a"], c1["serv_general"], objetivo["inicio"])
        assert r.status_code == 422, r.text
    finally:
        admin.delete(f"/api/v1/bloqueos/{bloqueo_id}")


def test_bloqueo_lista_citas_en_conflicto_sin_cancelarlas(cliente, c1, limpiar_citas):
    admin = cliente("admin1")
    recep = cliente("recep1a")
    _, espacios = buscar_espacio(recep, c1["prof_a"], c1["serv_general"])
    objetivo = espacios[0]

    cita = reservar(recep, c1["pacientes"][1], c1["prof_a"], c1["serv_general"], objetivo["inicio"])
    assert cita.status_code == 201, cita.text
    cita_id = cita.json()["cita_id"]
    limpiar_citas.append(cita_id)

    b = admin.post(
        f"/api/v1/profesionales/{c1['prof_a']}/bloqueos",
        json={"inicio": objetivo["inicio"], "fin": objetivo["fin"], "motivo": "Permiso medico"},
    )
    assert b.status_code == 201, b.text
    bloqueo = b.json()
    try:
        assert any(c["cita_id"] == cita_id for c in bloqueo["conflictos"])
        assert recep.get(f"/api/v1/citas/{cita_id}").json()["estado_id"] == 1
    finally:
        admin.delete(f"/api/v1/bloqueos/{bloqueo['bloqueo_id']}")


def test_eliminar_horario_impide_reservar_en_esa_franja(cliente, c1):
    admin = cliente("admin1")
    recep = cliente("recep1a")

    h = admin.post(
        f"/api/v1/profesionales/{c1['prof_a']}/horarios",
        json={"dia_semana": 6, "hora_inicio": "08:00:00", "hora_fin": "10:00:00"},
    )
    assert h.status_code == 201, h.text
    horario_id = h.json()["horario_id"]

    sabado = date.today() + timedelta(days=14)
    while sabado.isoweekday() != 6:
        sabado += timedelta(days=1)

    espacios = recep.get(
        f"/api/v1/profesionales/{c1['prof_a']}/disponibilidad",
        params={"fecha": sabado.isoformat(), "servicio_id": c1["serv_general"]},
    ).json()["espacios"]
    assert espacios
    slot_sabado = espacios[0]["inicio"]

    assert admin.delete(f"/api/v1/horarios/{horario_id}").status_code == 204
    r = reservar(recep, c1["pacientes"][0], c1["prof_a"], c1["serv_general"], slot_sabado)
    assert r.status_code == 422, r.text