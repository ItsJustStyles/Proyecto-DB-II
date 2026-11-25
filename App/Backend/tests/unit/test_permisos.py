import pytest

from app.permisos import ADMIN_CLINICA, ADMIN_PLATAFORMA, PERMISOS, PROFESIONAL, RECEPCION, rol_permitido

# Matriz del enunciado (seccion 3): (permiso, rol, permitido)
CASOS = [
    ("clinica.crear", ADMIN_PLATAFORMA, True),
    ("clinica.crear", ADMIN_CLINICA, False),
    ("clinica.crear", RECEPCION, False),
    ("usuario.gestionar", ADMIN_CLINICA, True),
    ("usuario.gestionar", RECEPCION, False),
    ("usuario.gestionar", PROFESIONAL, False),
    ("usuario.gestionar", ADMIN_PLATAFORMA, False),
    ("horario.gestionar", PROFESIONAL, True),   # solo los propios: lo verifica la capa de acceso
    ("horario.gestionar", RECEPCION, False),
    ("disponibilidad.consultar", RECEPCION, True),
    ("disponibilidad.consultar", ADMIN_PLATAFORMA, False),
    ("cita.operar", RECEPCION, True),
    ("cita.operar", ADMIN_CLINICA, True),
    ("cita.operar", PROFESIONAL, False),
    ("cita.desenlace", PROFESIONAL, True),
    ("paciente.escribir", PROFESIONAL, False),  # profesional: solo lectura
    ("paciente.leer", PROFESIONAL, True),
    ("nota.escribir", PROFESIONAL, True),
    ("nota.escribir", ADMIN_CLINICA, False),
    ("nota.escribir", RECEPCION, False),
    ("nota.leer", ADMIN_CLINICA, False),
    ("bitacora.consultar", ADMIN_CLINICA, True),
    ("bitacora.consultar", RECEPCION, False),
    ("bitacora.consultar", PROFESIONAL, False),
]


@pytest.mark.parametrize("permiso,rol,esperado", CASOS)
def test_matriz(permiso, rol, esperado):
    assert rol_permitido(permiso, rol) is esperado


def test_el_administrador_de_plataforma_no_accede_a_datos_clinicos():
    clinicos = [
        "paciente.leer", "paciente.escribir", "paciente.historial", "nota.leer", "nota.escribir",
        "cita.operar", "cita.desenlace", "bitacora.consultar", "agenda.dia",
    ]
    for permiso in clinicos:
        assert not rol_permitido(permiso, ADMIN_PLATAFORMA), permiso


def test_permiso_desconocido_se_deniega():
    assert rol_permitido("no.existe", ADMIN_CLINICA) is False


def test_todo_permiso_tiene_al_menos_un_rol():
    assert all(roles for roles in PERMISOS.values())
