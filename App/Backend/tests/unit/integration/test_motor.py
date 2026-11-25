"""
Garantias que debe dar el MOTOR aunque la aplicacion fallara: I6 (bitacora append-only),
roles de minimo privilegio y claves foraneas compuestas (refuerzo de I5).

Se conectan como el login de la aplicacion (medicitas_app) y hacen SET ROLE, igual que la API.
"""
import os

import pytest

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.integration


@pytest.fixture()
def conn():
    c = psycopg.connect(os.environ["DATABASE_URL"], autocommit=False)
    yield c
    c.rollback()
    c.close()


def _como(conn, rol):
    conn.execute(f"SET LOCAL ROLE {rol}")


@pytest.mark.parametrize("rol", ["db_admin_clinica", "db_recepcion", "db_profesional"])
@pytest.mark.parametrize("sentencia", [
    "UPDATE bitacora_auditoria SET accion = 'LECTURA'",
    "DELETE FROM bitacora_auditoria",
    "TRUNCATE bitacora_auditoria",
])
def test_bitacora_no_admite_update_delete_ni_truncate(conn, rol, sentencia):
    _como(conn, rol)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(sentencia)


def test_recepcion_y_profesional_no_leen_bitacora(conn):
    for rol in ("db_recepcion", "db_profesional"):
        conn.rollback()
        _como(conn, rol)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM bitacora_auditoria LIMIT 1")


def test_admin_y_recepcion_no_leen_notas_clinicas(conn):
    for rol in ("db_admin_clinica", "db_recepcion", "db_plataforma"):
        conn.rollback()
        _como(conn, rol)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM nota_clinica LIMIT 1")


def test_plataforma_no_accede_a_datos_clinicos(conn):
    _como(conn, "db_plataforma")
    for tabla in ("paciente", "cita", "profesional", "bitacora_auditoria"):
        conn.rollback()
        _como(conn, "db_plataforma")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"SELECT 1 FROM {tabla} LIMIT 1")


def test_ningun_rol_puede_cambiar_la_clinica_de_una_fila(conn):
    for rol, tabla in (("db_admin_clinica", "paciente"), ("db_recepcion", "paciente"), ("db_admin_clinica", "cita")):
        conn.rollback()
        _como(conn, rol)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"UPDATE {tabla} SET clinica_id = 2")


def test_fk_compuesta_impide_cita_con_paciente_de_otra_clinica(conn):
    _como(conn, "db_admin_clinica")
    pac_c2 = conn.execute("SELECT paciente_id FROM paciente WHERE clinica_id = 2 LIMIT 1").fetchone()[0]
    prof_c1, serv_c1, usr_c1 = conn.execute(
        "SELECT (SELECT profesional_id FROM profesional WHERE clinica_id = 1 LIMIT 1), "
        "       (SELECT servicio_id FROM servicio WHERE clinica_id = 1 LIMIT 1), "
        "       (SELECT usuario_id FROM usuario WHERE clinica_id = 1 LIMIT 1)"
    ).fetchone()
    # estado 2 (no vigente) para que el trigger de agenda no corte antes de que el motor evalue la FK
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado_id, creada_por) "
            "VALUES (1, %s, %s, %s, now() + interval '400 days', now() + interval '400 days', 2, %s)",
            (pac_c2, prof_c1, serv_c1, usr_c1),
        )


def test_trigger_rechaza_transicion_desde_estado_final(conn):
    _como(conn, "db_recepcion")
    cita_id = conn.execute("SELECT cita_id FROM cita WHERE estado_id = 4 LIMIT 1").fetchone()[0]
    with pytest.raises(psycopg.Error) as exc:
        conn.execute("UPDATE cita SET estado_id = 1 WHERE cita_id = %s", (cita_id,))
    assert exc.value.sqlstate == "MC001"


def test_nota_solo_en_cita_atendida_y_del_profesional_de_la_cita(conn):
    _como(conn, "db_profesional")
    # una cita cancelada (4) de la semilla: la nota se rechaza por trigger (RF15)
    cita_id, clinica_id, prof_id = conn.execute(
        "SELECT cita_id, clinica_id, profesional_id FROM cita WHERE estado_id = 4 LIMIT 1"
    ).fetchone()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO nota_clinica (clinica_id, cita_id, profesional_id, contenido) VALUES (%s, %s, %s, 'x')",
            (clinica_id, cita_id, prof_id),
        )
