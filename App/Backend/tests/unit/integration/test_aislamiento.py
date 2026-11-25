"""I5 / criterio 4: ninguna clinica alcanza datos de otra, ni siquiera manipulando parametros."""
import pytest

from .conftest import datos_clinica, reservar, buscar_espacio

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def clinica2(cliente):
    d = datos_clinica(cliente, 2)
    admin2 = cliente("admin2")
    d["cita_ids"] = [c["cita_id"] for c in admin2.get(f"/api/v1/pacientes/{d['pacientes'][0]}/citas").json()]
    assert d["cita_ids"], "la semilla deberia dar citas a la clinica 2"
    return d


def test_listado_con_clinica_id_manipulado_devuelve_solo_la_propia(cliente, clinica2):
    admin1 = cliente("admin1")
    base = {p["paciente_id"] for p in admin1.get("/api/v1/pacientes", params={"limit": 200}).json()}
    for param in ("clinica_id", "clinicaId", "tenant"):
        manipulado = {
            p["paciente_id"] for p in admin1.get("/api/v1/pacientes", params={"limit": 200, param: 2}).json()
        }
        assert manipulado == base
    assert base.isdisjoint(clinica2["pacientes"])


def test_acceso_directo_por_id_ajeno_es_404(cliente, clinica2):
    admin1, recep1 = cliente("admin1"), cliente("recep1a")
    ajeno = clinica2["pacientes"][0]
    assert admin1.get(f"/api/v1/pacientes/{ajeno}").status_code == 404
    assert admin1.get(f"/api/v1/pacientes/{ajeno}/citas").status_code == 404
    assert recep1.patch(f"/api/v1/pacientes/{ajeno}", json={"nombre": "Hackeado"}).status_code == 404
    cita_ajena = clinica2["cita_ids"][0]
    assert recep1.get(f"/api/v1/citas/{cita_ajena}").status_code == 404
    assert recep1.post(f"/api/v1/citas/{cita_ajena}/cancelar", json={"motivo": "intento de fuga"}).status_code == 404
    assert recep1.post(f"/api/v1/citas/{cita_ajena}/desenlace", json={"resultado": "ATENDIDA"}).status_code == 404


def test_clinica_id_en_el_cuerpo_no_tiene_efecto(cliente, clinica2):
    admin1, admin2 = cliente("admin1"), cliente("admin2")
    r = admin1.post(
        "/api/v1/pacientes",
        json={
            "clinica_id": 2,
            "identificacion": "FUGA-0001",
            "nombre": "Prueba",
            "apellidos": "Aislamiento",
            "fecha_nacimiento": "1990-01-01",
        },
    )
    assert r.status_code in (201, 409), r.text  # 409 si es una re-ejecucion
    ids2 = {p["identificacion"] for p in admin2.get("/api/v1/pacientes", params={"q": "FUGA", "limit": 200}).json()}
    assert "FUGA-0001" not in ids2
    ids1 = {p["identificacion"] for p in admin1.get("/api/v1/pacientes", params={"q": "FUGA", "limit": 200}).json()}
    assert "FUGA-0001" in ids1


def test_no_se_puede_reservar_con_paciente_o_servicio_de_otra_clinica(cliente, clinica2):
    d1 = datos_clinica(cliente, 1)
    recep1 = cliente("recep1a")
    fecha, espacios = buscar_espacio(recep1, d1["prof_a"], d1["serv_general"])
    inicio = espacios[0]["inicio"]
    # paciente de la clinica 2: la FK compuesta (clinica_id, paciente_id) lo impide en el motor
    r = reservar(recep1, clinica2["pacientes"][0], d1["prof_a"], d1["serv_general"], inicio)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["codigo"] == "REFERENCIA_INVALIDA"
    # profesional de la clinica 2
    r = reservar(recep1, d1["pacientes"][0], clinica2["prof_a"], d1["serv_general"], inicio)
    assert r.status_code in (404, 422), r.text
    # servicio de la clinica 2
    r = reservar(recep1, d1["pacientes"][0], d1["prof_a"], clinica2["serv_general"], inicio)
    assert r.status_code == 422, r.text


def test_disponibilidad_de_profesional_ajeno_es_404(cliente, clinica2):
    r = cliente("recep1a").get(
        f"/api/v1/profesionales/{clinica2['prof_a']}/disponibilidad",
        params={"fecha": "2030-01-08", "servicio_id": clinica2["serv_general"]},
    )
    assert r.status_code in (404, 422)


def test_bitacora_solo_muestra_la_propia_clinica(cliente, clinica2):
    admin1 = cliente("admin1")
    filas = admin1.get("/api/v1/bitacora", params={"limit": 500}).json()
    assert all(f["paciente_id"] not in clinica2["pacientes"] for f in filas)
    # filtrar por un paciente de otra clinica no devuelve nada
    assert admin1.get("/api/v1/bitacora", params={"paciente_id": clinica2["pacientes"][0]}).json() == []


def test_notas_de_otra_clinica_no_son_accesibles(cliente, clinica2):
    prof1 = cliente("prof1a")
    r = prof1.get(f"/api/v1/citas/{clinica2['cita_ids'][0]}/nota")
    assert r.status_code == 404
