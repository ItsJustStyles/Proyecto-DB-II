"""
Criterio 2: reservar, reprogramar, cancelar y registrar desenlace; transiciones invalidas rechazadas.
Cubre RF9 a RF13, I4 e I7."""
from datetime import datetime, timedelta

import pytest

from .conftest import buscar_espacio, datos_clinica, reservar

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def c1(cliente):
    return datos_clinica(cliente, 1)


def test_reservar_concedida_y_duracion_la_fija_el_servicio(cliente, c1, limpiar_citas):
    recep = cliente("recep1a")
    _, espacios = buscar_espacio(recep, c1["prof_a"], c1["serv_general"])
    r = reservar(recep, c1["pacientes"][0], c1["prof_a"], c1["serv_general"], espacios[0]["inicio"])
    assert r.status_code == 201, r.text
    cita = r.json()
    limpiar_citas.append(cita["cita_id"])
    # I4: 'Consulta general' dura 30 min; el cliente no manda 'fin' y aunque lo mandara se ignora
    dur = datetime.fromisoformat(cita["fin"]) - datetime.fromisoformat(cita["inicio"])
    assert dur == timedelta(minutes=30)
    assert cita["estado_id"] == 1


def test_reserva_invalida_es_422(cliente, c1):
    recep = cliente("recep1a")
    pasado = (datetime.now().astimezone() - timedelta(days=1)).isoformat()
    assert reservar(recep, c1["pacientes"][0], c1["prof_a"], c1["serv_general"], pasado).status_code == 422
    # sin zona horaria
    r = recep.post("/api/v1/citas", json={"paciente_id": 1, "profesional_id": 1, "servicio_id": 1, "inicio": "2031-01-01T08:00:00"})
    assert r.status_code == 422
    # fuera del horario de atencion (domingo 03:00): lo rechaza el trigger de agenda (I3)
    fecha, _ = buscar_espacio(recep, c1["prof_a"], c1["serv_general"])
    madrugada = datetime.combine(fecha, datetime.min.time()).replace(hour=3).astimezone().isoformat()
    r = reservar(recep, c1["pacientes"][0], c1["prof_a"], c1["serv_general"], madrugada)
    assert r.status_code == 422, r.text


def test_espacio_ya_tomado_es_409(cliente, c1, limpiar_citas):
    recep = cliente("recep1a")
    _, espacios = buscar_espacio(recep, c1["prof_a"], c1["serv_general"])
    inicio = espacios[0]["inicio"]
    r1 = reservar(recep, c1["pacientes"][0], c1["prof_a"], c1["serv_general"], inicio)
    assert r1.status_code == 201
    limpiar_citas.append(r1.json()["cita_id"])
    r2 = reservar(recep, c1["pacientes"][1], c1["prof_a"], c1["serv_general"], inicio)
    assert r2.status_code == 409
    assert r2.json()["detail"]["codigo"] == "ESPACIO_TOMADO"


def test_paciente_no_puede_tener_dos_citas_solapadas_I2(cliente, c1, limpiar_citas):
    """El mismo paciente en dos profesionales distintos al mismo instante: la segunda se rechaza."""
    recep = cliente("recep1a")
    fecha, esp_b = buscar_espacio(recep, c1["prof_b"], c1["serv_b"])
    esp_a = recep.get(
        f"/api/v1/profesionales/{c1['prof_a']}/disponibilidad",
        params={"fecha": fecha.isoformat(), "servicio_id": c1["serv_general"]},
    ).json()["espacios"]
    horas_a = {datetime.fromisoformat(s["inicio"]) for s in esp_a}
    comunes = [s["inicio"] for s in esp_b if datetime.fromisoformat(s["inicio"]) in horas_a]
    assert comunes, "ambos profesionales deberian coincidir libres en algun instante"
    inicio = comunes[0]
    r1 = reservar(recep, c1["pacientes"][2], c1["prof_a"], c1["serv_general"], inicio)
    assert r1.status_code == 201, r1.text
    limpiar_citas.append(r1.json()["cita_id"])
    r2 = reservar(recep, c1["pacientes"][2], c1["prof_b"], c1["serv_b"], inicio)
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["codigo"] == "PACIENTE_OCUPADO"


def test_reprogramar_cancelar_y_estados_finales(cliente, c1, limpiar_citas):
    recep = cliente("recep1a")
    fecha, espacios = buscar_espacio(recep, c1["prof_a"], c1["serv_general"])
    r = reservar(recep, c1["pacientes"][3], c1["prof_a"], c1["serv_general"], espacios[0]["inicio"])
    assert r.status_code == 201
    original = r.json()
    limpiar_citas.append(original["cita_id"])

    # RF10: reprogramar a otro espacio libre
    nuevo_inicio = espacios[-1]["inicio"]
    rp = recep.post(f"/api/v1/citas/{original['cita_id']}/reprogramar", json={"inicio": nuevo_inicio})
    assert rp.status_code == 201, rp.text
    nueva = rp.json()
    limpiar_citas.append(nueva["cita_id"])
    assert nueva["cita_origen_id"] == original["cita_id"] and nueva["estado_id"] == 1
    assert recep.get(f"/api/v1/citas/{original['cita_id']}").json()["estado_id"] == 5  # REPROGRAMADA

    # I7: el espacio original queda libre y visible de inmediato
    libres = recep.get(
        f"/api/v1/profesionales/{c1['prof_a']}/disponibilidad",
        params={"fecha": fecha.isoformat(), "servicio_id": c1["serv_general"]},
    ).json()["espacios"]
    assert original["inicio"] in [s["inicio"] for s in libres] or any(
        datetime.fromisoformat(s["inicio"]) == datetime.fromisoformat(original["inicio"]) for s in libres
    )

    # una cita reprogramada (estado final) ya no admite cambios
    assert recep.post(f"/api/v1/citas/{original['cita_id']}/cancelar", json={"motivo": "x"}).status_code == 409
    assert recep.post(f"/api/v1/citas/{original['cita_id']}/reprogramar", json={"inicio": nuevo_inicio}).status_code == 409

    # RF11: cancelar deja registro de motivo y usuario; cancelar dos veces es 409
    c = recep.post(f"/api/v1/citas/{nueva['cita_id']}/cancelar", json={"motivo": "Paciente viaja"})
    assert c.status_code == 200, c.text
    assert c.json()["estado_id"] == 4 and c.json()["motivo_cancelacion"] == "Paciente viaja"
    assert c.json()["cancelada_por"] is not None
    assert recep.post(f"/api/v1/citas/{nueva['cita_id']}/cancelar", json={"motivo": "otra vez"}).status_code == 409
    assert recep.post(f"/api/v1/citas/{nueva['cita_id']}/cancelar", json={}).status_code == 422  # motivo obligatorio


def test_reprogramar_a_espacio_ocupado_deja_la_original_intacta(cliente, c1, limpiar_citas):
    recep = cliente("recep1a")
    _, espacios = buscar_espacio(recep, c1["prof_a"], c1["serv_general"])
    a = reservar(recep, c1["pacientes"][4], c1["prof_a"], c1["serv_general"], espacios[0]["inicio"])
    b = reservar(recep, c1["pacientes"][5], c1["prof_a"], c1["serv_general"], espacios[-1]["inicio"])
    assert a.status_code == b.status_code == 201
    limpiar_citas.extend([a.json()["cita_id"], b.json()["cita_id"]])
    rp = recep.post(f"/api/v1/citas/{a.json()['cita_id']}/reprogramar", json={"inicio": espacios[-1]["inicio"]})
    assert rp.status_code == 409
    # RF10: atomicidad; la cita A sigue vigente, no quedo ni duplicada ni liberada
    assert recep.get(f"/api/v1/citas/{a.json()['cita_id']}").json()["estado_id"] == 1


def test_desenlace_solo_tras_la_hora_de_inicio(cliente, c1, limpiar_citas):
    recep = cliente("recep1a")
    _, espacios = buscar_espacio(recep, c1["prof_a"], c1["serv_general"])
    r = reservar(recep, c1["pacientes"][6], c1["prof_a"], c1["serv_general"], espacios[0]["inicio"])
    cita_id = r.json()["cita_id"]
    limpiar_citas.append(cita_id)
    d = recep.post(f"/api/v1/citas/{cita_id}/desenlace", json={"resultado": "ATENDIDA"})
    assert d.status_code == 409, d.text  # cita futura: el trigger lo rechaza (RF12)
    assert recep.post(f"/api/v1/citas/{cita_id}/desenlace", json={"resultado": "OTRA"}).status_code == 422


def test_desenlace_de_cita_pasada_y_estado_final(cliente, c1):
    """Usa citas pasadas de la semilla: una reservada pasada se puede marcar y luego es final."""
    admin = cliente("admin1")
    # citas de la semilla ya resueltas (estado final) no admiten un nuevo desenlace (RF13)
    historial = admin.get(f"/api/v1/pacientes/{c1['pacientes'][0]}/citas").json()
    finales = [c for c in historial if c["estado_id"] in (2, 3, 4)]
    assert finales, "la semilla deberia tener citas en estado final"
    r = admin.post(f"/api/v1/citas/{finales[0]['cita_id']}/desenlace", json={"resultado": "AUSENTE"})
    assert r.status_code == 409


def test_profesional_registra_desenlace_solo_de_sus_citas(cliente, c1):
    prof_b = cliente("prof1b")  # profesional B no es la Dra. Elena
    admin = cliente("admin1")
    citas_de_a = [
        c for pid in c1["pacientes"] for c in admin.get(f"/api/v1/pacientes/{pid}/citas").json()
        if c["profesional_id"] == c1["prof_a"]
    ]
    assert citas_de_a
    r = prof_b.post(f"/api/v1/citas/{citas_de_a[0]['cita_id']}/desenlace", json={"resultado": "ATENDIDA"})
    assert r.status_code == 403
