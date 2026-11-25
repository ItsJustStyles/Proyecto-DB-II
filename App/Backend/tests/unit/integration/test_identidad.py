"""RF17 / criterio 3: 401 sin token valido, 403 con rol insuficiente, 200 con rol adecuado."""
import pytest

pytestmark = pytest.mark.integration


def test_ruta_protegida_sin_token_es_401(cliente):
    assert cliente(None).get("/api/v1/pacientes").status_code == 401


def test_token_basura_es_401(cliente):
    c = cliente(None)
    r = c.get("/api/v1/pacientes", headers={"Authorization": "Bearer esto.no.es.un.jwt"})
    assert r.status_code == 401


def test_token_con_firma_ajena_es_401(cliente):
    # JWT con forma valida pero firmado con otra llave: la validacion contra el JWKS lo rechaza
    import jwt as pyjwt

    falso = pyjwt.encode({"sub": "x", "iss": "http://localhost:8080/realms/medicitas", "exp": 9999999999}, "secreto", algorithm="HS256")
    r = cliente(None).get("/api/v1/pacientes", headers={"Authorization": f"Bearer {falso}"})
    assert r.status_code == 401


def test_rol_incorrecto_es_403(cliente):
    assert cliente("recep1a").post("/api/v1/clinicas", json={}).status_code == 403          # solo plataforma
    assert cliente("admin1").post("/api/v1/clinicas", json={}).status_code == 403
    assert cliente("prof1a").post("/api/v1/citas", json={}).status_code == 403              # profesional no reserva
    assert cliente("recep1a").get("/api/v1/bitacora").status_code == 403                    # solo admin de clinica
    assert cliente("prof1a").get("/api/v1/usuarios").status_code == 403
    assert cliente("plataforma").get("/api/v1/pacientes").status_code == 403                # plataforma sin datos clinicos


def test_rol_correcto_funciona(cliente):
    assert cliente("admin1").get("/api/v1/usuarios").status_code == 200
    assert cliente("recep1a").get("/api/v1/pacientes").status_code == 200
    assert cliente("plataforma").get("/api/v1/clinicas").status_code == 200


def test_cuerpo_mal_formado_no_tumba_el_servicio(cliente):
    c = cliente("recep1a")
    r = c.post("/api/v1/citas", content="{no es json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert c.get("/api/v1/citas/999999999").status_code == 404
    assert cliente(None).get("/health").status_code == 200
