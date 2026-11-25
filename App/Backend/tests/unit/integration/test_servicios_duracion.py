"""I4: la duracion de la cita la determina el servicio y ninguna operacion la altera por su cuenta."""
from datetime import datetime, timedelta

import pytest

from .conftest import buscar_espacio, datos_clinica, reservar

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def c1(cliente):
    return datos_clinica(cliente, 1)


def test_duracion_cita_la_fija_el_servicio(cliente, c1, limpiar_citas):
    recep = cliente("recep1a")
    _, espacios = buscar_espacio(recep, c1["prof_a"], c1["serv_general"])
    r = reservar(recep, c1["pacientes"][0], c1["prof_a"], c1["serv_general"], espacios[0]["inicio"])
    assert r.status_code == 201, r.text
    cita = r.json()
    limpiar_citas.append(cita["cita_id"])

    duracion = datetime.fromisoformat(cita["fin"]) - datetime.fromisoformat(cita["inicio"])
    assert duracion == timedelta(minutes=30)


def test_cambiar_duracion_servicio_no_altera_citas_ya_agendadas(cliente, c1, limpiar_citas):
    admin = cliente("admin1")
    recep = cliente("recep1a")
    _, espacios = buscar_espacio(recep, c1["prof_a"], c1["serv_general"])

    r = reservar(recep, c1["pacientes"][1], c1["prof_a"], c1["serv_general"], espacios[0]["inicio"])
    assert r.status_code == 201, r.text
    cita_original = r.json()
    limpiar_citas.append(cita_original["cita_id"])

    patch_ok = admin.patch(f"/api/v1/servicios/{c1['serv_general']}", json={"duracion_min": 45})
    assert patch_ok.status_code == 200, patch_ok.text

    try:
        # La cita previamente agendada conserva intacto su fin y su duracion de 30 min
        cita_despues = recep.get(f"/api/v1/citas/{cita_original['cita_id']}").json()
        assert cita_despues["fin"] == cita_original["fin"]
        dur_antes = datetime.fromisoformat(cita_despues["fin"]) - datetime.fromisoformat(cita_despues["inicio"])
        assert dur_antes == timedelta(minutes=30)

        # Una nueva cita reservada despues del cambio si adopta los 45 min
        _, nuevos_espacios = buscar_espacio(recep, c1["prof_a"], c1["serv_general"])
        r_nueva = reservar(recep, c1["pacientes"][2], c1["prof_a"], c1["serv_general"], nuevos_espacios[0]["inicio"])
        assert r_nueva.status_code == 201, r_nueva.text
        cita_nueva = r_nueva.json()
        limpiar_citas.append(cita_nueva["cita_id"])
        dur_nueva = datetime.fromisoformat(cita_nueva["fin"]) - datetime.fromisoformat(cita_nueva["inicio"])
        assert dur_nueva == timedelta(minutes=45)
    finally:
        admin.patch(f"/api/v1/servicios/{c1['serv_general']}", json={"duracion_min": 30})