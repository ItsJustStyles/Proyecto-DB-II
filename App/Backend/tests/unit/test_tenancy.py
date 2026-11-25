import pytest

from app.tenancy import TenantGuardError, asegurar_filtro_clinica, parametros_con_clinica


def test_consulta_sin_filtro_es_rechazada():
    with pytest.raises(TenantGuardError):
        asegurar_filtro_clinica("SELECT * FROM paciente WHERE paciente_id = %(id)s")


def test_consulta_con_filtro_pasa():
    asegurar_filtro_clinica("SELECT * FROM paciente WHERE clinica_id = %(clinica_id)s AND paciente_id = %(id)s")


def test_clinica_del_llamador_se_sobrescribe_con_la_de_la_identidad():
    # I5: aunque el codigo (o un parametro manipulado) pase otra clinica, gana la de la identidad
    params = parametros_con_clinica({"clinica_id": 999, "x": 1}, clinica_id=7)
    assert params["clinica_id"] == 7
    assert params["x"] == 1


def test_identidad_sin_clinica_no_consulta_tablas_de_negocio():
    with pytest.raises(TenantGuardError):
        parametros_con_clinica({}, clinica_id=None)
