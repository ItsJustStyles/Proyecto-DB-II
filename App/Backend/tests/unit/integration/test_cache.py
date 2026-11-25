"""
Criterio 5 / I8 / I7: la cache no miente. Consultar, reservar uno de los espacios devueltos y
volver a consultar debe mostrarlo tomado, sin esperar a que expire ninguna entrada."""
from datetime import datetime

import pytest

from .conftest import buscar_espacio, datos_clinica, reservar

pytestmark = pytest.mark.integration


def _inicios(cli, prof, fecha, serv):
    r = cli.get(f"/api/v1/profesionales/{prof}/disponibilidad", params={"fecha": fecha.isoformat(), "servicio_id": serv})
    assert r.status_code == 200
    return {datetime.fromisoformat(s["inicio"]) for s in r.json()["espacios"]}


def test_reserva_invalida_la_cache_de_inmediato(cliente, limpiar_citas):
    d = datos_clinica(cliente, 1)
    recep = cliente("recep1a")
    fecha, espacios = buscar_espacio(recep, d["prof_a"], d["serv_general"])
    objetivo = datetime.fromisoformat(espacios[0]["inicio"])

    antes_1 = _inicios(recep, d["prof_a"], fecha, d["serv_general"])   # llena la cache
    antes_2 = _inicios(recep, d["prof_a"], fecha, d["serv_general"])   # se sirve desde la cache
    assert antes_1 == antes_2 and objetivo in antes_2

    r = reservar(recep, d["pacientes"][7], d["prof_a"], d["serv_general"], espacios[0]["inicio"])
    assert r.status_code == 201
    limpiar_citas.append(r.json()["cita_id"])

    despues = _inicios(recep, d["prof_a"], fecha, d["serv_general"])
    assert objetivo not in despues                                       # I8: nada de copia vieja
    # el espacio contiguo que se solapa con la cita tambien desaparece; el resto sigue
    assert len(despues) < len(antes_2)


def test_cancelar_libera_el_espacio_de_inmediato(cliente):
    d = datos_clinica(cliente, 1)
    recep = cliente("recep1a")
    fecha, espacios = buscar_espacio(recep, d["prof_a"], d["serv_general"])
    objetivo = datetime.fromisoformat(espacios[0]["inicio"])
    r = reservar(recep, d["pacientes"][8], d["prof_a"], d["serv_general"], espacios[0]["inicio"])
    assert r.status_code == 201
    assert objetivo not in _inicios(recep, d["prof_a"], fecha, d["serv_general"])   # cache con el espacio tomado
    c = recep.post(f"/api/v1/citas/{r.json()['cita_id']}/cancelar", json={"motivo": "I7"})
    assert c.status_code == 200
    assert objetivo in _inicios(recep, d["prof_a"], fecha, d["serv_general"])        # I7: liberado y visible ya


def test_bloqueo_retira_disponibilidad_aunque_haya_cache(cliente):
    d = datos_clinica(cliente, 1)
    admin = cliente("admin1")
    fecha, espacios = buscar_espacio(admin, d["prof_a"], d["serv_general"])
    assert _inicios(admin, d["prof_a"], fecha, d["serv_general"])  # cache llena
    ini, fin = espacios[0]["inicio"], espacios[-1]["fin"]
    b = admin.post(f"/api/v1/profesionales/{d['prof_a']}/bloqueos", json={"inicio": ini, "fin": fin, "motivo": "prueba cache"})
    assert b.status_code == 201, b.text
    try:
        assert _inicios(admin, d["prof_a"], fecha, d["serv_general"]) == set()
    finally:
        admin.delete(f"/api/v1/bloqueos/{b.json()['bloqueo_id']}")
    assert _inicios(admin, d["prof_a"], fecha, d["serv_general"])


def test_disponibilidad_por_servicio_en_rango(cliente):
    d = datos_clinica(cliente, 1)
    from datetime import date, timedelta

    hoy = date.today()
    r = cliente("recep1a").get("/api/v1/disponibilidad", params={"servicio_id": d["serv_general"], "desde": hoy.isoformat(), "hasta": (hoy + timedelta(days=7)).isoformat()})
    assert r.status_code == 200
    profs = r.json()["profesionales"]
    assert profs and all(p["profesional_id"] == d["prof_a"] for p in profs)
    assert cliente("recep1a").get("/api/v1/disponibilidad", params={"servicio_id": d["serv_general"], "desde": "2030-02-01", "hasta": "2030-01-01"}).status_code == 422
