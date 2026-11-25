"""I6 / RF18 / RF19: bitacora append-only registra accesos sensibles y no admite modificacion ni borrado."""
import pytest

from .conftest import datos_clinica

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def c1(cliente):
    return datos_clinica(cliente, 1)


def _bitacora_ids(admin, paciente_id: int) -> set[int]:
    r = admin.get("/api/v1/bitacora", params={"paciente_id": paciente_id, "limit": 200})
    assert r.status_code == 200, r.text
    return {fila["bitacora_id"] for fila in r.json()}


def test_lectura_y_actualizacion_de_paciente_registran_auditoria(cliente, c1):
    admin = cliente("admin1")
    recep = cliente("recep1a")
    prof_a = cliente("prof1a")
    paciente_id = c1["pacientes"][0]

    ids_antes = _bitacora_ids(admin, paciente_id)

    # 1) Lectura de ficha/contacto por profesional -> debe auditar LECTURA en PACIENTE_CONTACTO (RF18)
    lec = prof_a.get(f"/api/v1/pacientes/{paciente_id}")
    assert lec.status_code == 200, lec.text

    filas_tras_lectura = admin.get("/api/v1/bitacora", params={"paciente_id": paciente_id, "limit": 200}).json()
    nuevas_lectura = [f for f in filas_tras_lectura if f["bitacora_id"] not in ids_antes]
    assert any(
        f["accion"] == "LECTURA" and f["entidad"] == "PACIENTE_CONTACTO" and f["entidad_id"] == paciente_id
        for f in nuevas_lectura
    )

    # 2) Actualizacion de datos de contacto por recepcion -> debe auditar ACTUALIZACION en PACIENTE_CONTACTO
    ids_antes_upd = {f["bitacora_id"] for f in filas_tras_lectura}
    tel_original = lec.json().get("telefono") or "+506-8888-0001"
    upd = recep.patch(f"/api/v1/pacientes/{paciente_id}", json={"telefono": "+506-8999-1111"})
    assert upd.status_code == 200, upd.text
    try:
        filas_tras_upd = admin.get("/api/v1/bitacora", params={"paciente_id": paciente_id, "limit": 200}).json()
        nuevas_upd = [f for f in filas_tras_upd if f["bitacora_id"] not in ids_antes_upd]
        assert any(
            f["accion"] == "ACTUALIZACION" and f["entidad"] == "PACIENTE_CONTACTO" and f["entidad_id"] == paciente_id
            for f in nuevas_upd
        )
    finally:
        recep.patch(f"/api/v1/pacientes/{paciente_id}", json={"telefono": tel_original})


def test_lectura_de_nota_clinica_registra_auditoria(cliente, c1):
    admin = cliente("admin1")
    prof_a = cliente("prof1a")

    # Buscar una cita atendida (estado_id = 2) de la Dra. Elena en la semilla
    cita_atendida = None
    for pid in c1["pacientes"]:
        citas = admin.get(f"/api/v1/pacientes/{pid}/citas").json()
        atendidas = [c for c in citas if c["profesional_id"] == c1["prof_a"] and c["estado_id"] == 2]
        if atendidas:
            cita_atendida = atendidas[0]
            break

    assert cita_atendida is not None, "La semilla debe tener al menos una cita atendida para prof1a"
    paciente_id = cita_atendida["paciente_id"]
    cita_id = cita_atendida["cita_id"]

    ids_antes = _bitacora_ids(admin, paciente_id)

    # El profesional dueñ@ de la cita lee la nota clinica -> audita LECTURA sobre NOTA_CLINICA
    nota_resp = prof_a.get(f"/api/v1/citas/{cita_id}/nota")
    assert nota_resp.status_code == 200, nota_resp.text

    filas = admin.get("/api/v1/bitacora", params={"paciente_id": paciente_id, "limit": 200}).json()
    nuevas = [f for f in filas if f["bitacora_id"] not in ids_antes]
    assert any(f["accion"] == "LECTURA" and f["entidad"] == "NOTA_CLINICA" for f in nuevas)


def test_filtros_bitacora_y_rutas_inmutables_en_api(cliente, c1):
    admin = cliente("admin1")
    paciente_id = c1["pacientes"][0]

    # RF19: filtro por usuario_id y paciente_id devuelve solo coincidencias exactas
    todas = admin.get("/api/v1/bitacora", params={"paciente_id": paciente_id, "limit": 50}).json()
    assert todas
    usuario_objetivo = todas[0]["usuario_id"]

    filtradas = admin.get(
        "/api/v1/bitacora",
        params={"usuario_id": usuario_objetivo, "paciente_id": paciente_id, "limit": 50},
    ).json()
    assert filtradas
    assert all(f["usuario_id"] == usuario_objetivo and f["paciente_id"] == paciente_id for f in filtradas)

    # I6: la API no expone rutas de modificacion ni borrado sobre la bitacora
    bitacora_id = todas[0]["bitacora_id"]
    assert admin.delete(f"/api/v1/bitacora/{bitacora_id}").status_code in (404, 405)
    assert admin.patch(f"/api/v1/bitacora/{bitacora_id}", json={"accion": "LECTURA"}).status_code in (404, 405)
    assert admin.put(f"/api/v1/bitacora/{bitacora_id}", json={"accion": "LECTURA"}).status_code in (404, 405)