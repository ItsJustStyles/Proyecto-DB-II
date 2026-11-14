"""RF9 a RF13, RF20 y RF21: ciclo de vida de la cita.

Reserva (RF9): un INSERT en una transaccion. La carrera por el ultimo espacio la decide la
exclusion constraint ex_cita_profesional_sin_solape (I1): la transaccion que llega segunda
espera al commit de la primera y recibe 23P01, que la API responde como 409 ESPACIO_TOMADO.

Reprogramacion (RF10): en UNA transaccion, bloquea la cita vigente (SELECT ... FOR UPDATE),
la pasa a REPROGRAMADA e inserta la nueva. Si la insercion falla, todo se revierte y la cita
original sigue vigente; nunca queda duplicada ni con los dos espacios ocupados.
"""
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Query
from psycopg import errors as pgerr

from .. import db
from ..schemas import CancelarIn, CitaIn, DesenlaceIn, ReprogramarIn

router = APIRouter(prefix="/api/v1", tags=["citas"])

_CITA_COLS = (
    "cita_id, paciente_id, profesional_id, servicio_id, "
    "inicio, fin, estado_id, cita_origen_id, "
    "creada_por, cancelada_por, motivo_cancelacion, "
    "desenlace_registrado_por, creada_en, actualizada_en"
)
_CITA_COLS_ALIAS = ", ".join(f"c.{col.strip()}" for col in _CITA_COLS.split(","))

_ESTADO_RESERVADA = 1
_ESTADO_CANCELADA = 4
_ESTADO_REPROGRAMADA = 5
_ESTADO_POR_NOMBRE = {
    "ATENDIDA": 2,
    "AUSENTE": 3,
}


def _error(status_code: int, codigo: str, mensaje: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"codigo": codigo, "mensaje": mensaje},
    )


def _manejar_error_pg(exc: pgerr.DatabaseError) -> HTTPException:
    if isinstance(exc, pgerr.ExclusionViolation):
        return _error(409, "ESPACIO_TOMADO", "El profesional o el paciente ya tiene una cita vigente en ese horario")
    if exc.sqlstate == "MC002":
        msg = exc.diag.message_primary if exc.diag and exc.diag.message_primary else "La cita no cumple las reglas de agenda"
        return _error(422, "CITA_INVALIDA", msg)
    if exc.sqlstate == "MC001":
        msg = exc.diag.message_primary if exc.diag and exc.diag.message_primary else "Transicion de estado no permitida"
        return _error(409, "TRANSICION_INVALIDA", msg)
    if isinstance(exc, pgerr.ForeignKeyViolation):
        return _error(422, "REFERENCIA_INVALIDA", "Paciente, profesional, servicio o usuario inexistente en la clinica")
    raise exc


async def _zona_clinica(cur, clinica_id: int) -> ZoneInfo:
    await cur.execute(
        "SELECT zona_horaria FROM clinica WHERE clinica_id = %(cid)s",
        {"cid": clinica_id},
    )
    row = await cur.fetchone()
    if row is None:
        raise _error(404, "NO_ENCONTRADO", "La clinica no existe")
    return ZoneInfo(row["zona_horaria"])


def _limites_dia(fecha: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    ini = datetime.combine(fecha, time.min, tzinfo=tz)
    fin = datetime.fromtimestamp(ini.timestamp() + 86400, tz=tz)
    return ini, fin


# ---------------------------------------------------------------- RF9 reservar
@router.post(
    "/citas",
    status_code=201,
    summary="RF9: reservar una cita (201 concedida, 409 espacio tomado, 422 invalida)",
)
async def reservar(
    body: CitaIn,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    usuario_id: int = Header(..., alias="X-Usuario-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    if body.inicio <= datetime.now(timezone.utc):
        raise _error(422, "CITA_INVALIDA", "La cita debe iniciar en el futuro")

    try:
        async with db.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    # `fin` lo calcula el trigger trg_cita_fin_por_servicio a partir del servicio (I4)
                    await cur.execute(
                        f"""
                        INSERT INTO cita (
                            clinica_id, paciente_id, profesional_id, servicio_id,
                            inicio, fin, creada_por
                        )
                        VALUES (
                            %(clinica_id)s, %(pac)s, %(pid)s, %(sid)s,
                            %(i)s, %(i)s, %(u)s
                        )
                        RETURNING {_CITA_COLS}
                        """,
                        {
                            "clinica_id": clinica_id,
                            "pac": body.paciente_id,
                            "pid": body.profesional_id,
                            "sid": body.servicio_id,
                            "i": body.inicio,
                            "u": usuario_id,
                        },
                    )
                    return await cur.fetchone()
    except pgerr.DatabaseError as exc:
        raise _manejar_error_pg(exc)


# ---------------------------------------------------------------- RF10 reprogramar
@router.post(
    "/citas/{cita_id}/reprogramar",
    status_code=201,
    summary="RF10: reprogramar una cita vigente a otro espacio",
)
async def reprogramar(
    cita_id: int,
    body: ReprogramarIn,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    usuario_id: int = Header(..., alias="X-Usuario-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    if body.inicio <= datetime.now(timezone.utc):
        raise _error(422, "CITA_INVALIDA", "La nueva cita debe iniciar en el futuro")

    try:
        async with db.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT cita_id, paciente_id, profesional_id, servicio_id, inicio, estado_id
                          FROM cita
                         WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s
                           FOR UPDATE
                        """,
                        {"clinica_id": clinica_id, "c": cita_id},
                    )
                    vieja = await cur.fetchone()
                    if vieja is None:
                        raise _error(404, "NO_ENCONTRADO", "La cita no existe en esta clinica")
                    if vieja["estado_id"] != _ESTADO_RESERVADA:
                        raise _error(409, "TRANSICION_INVALIDA", "Solo una cita vigente puede reprogramarse")

                    nuevo_prof = body.profesional_id or vieja["profesional_id"]

                    # 1) La cita original pasa a REPROGRAMADA (libera el rango en la misma transaccion)
                    await cur.execute(
                        """
                        UPDATE cita
                           SET estado_id = %(e)s
                         WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s
                        """,
                        {"e": _ESTADO_REPROGRAMADA, "clinica_id": clinica_id, "c": cita_id},
                    )

                    # 2) Se inserta la nueva; si hay choque o regla invalida, la transaccion revierte todo
                    await cur.execute(
                        f"""
                        INSERT INTO cita (
                            clinica_id, paciente_id, profesional_id, servicio_id,
                            inicio, fin, cita_origen_id, creada_por
                        )
                        VALUES (
                            %(clinica_id)s, %(pac)s, %(pid)s, %(sid)s,
                            %(i)s, %(i)s, %(orig)s, %(u)s
                        )
                        RETURNING {_CITA_COLS}
                        """,
                        {
                            "clinica_id": clinica_id,
                            "pac": vieja["paciente_id"],
                            "pid": nuevo_prof,
                            "sid": vieja["servicio_id"],
                            "i": body.inicio,
                            "orig": cita_id,
                            "u": usuario_id,
                        },
                    )
                    return await cur.fetchone()
    except pgerr.DatabaseError as exc:
        raise _manejar_error_pg(exc)


# ---------------------------------------------------------------- RF11 cancelar
@router.post(
    "/citas/{cita_id}/cancelar",
    summary="RF11: cancelar una cita vigente (registra motivo y usuario)",
)
async def cancelar(
    cita_id: int,
    body: CancelarIn,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    usuario_id: int = Header(..., alias="X-Usuario-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    try:
        async with db.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT profesional_id, inicio, estado_id
                          FROM cita
                         WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s
                           FOR UPDATE
                        """,
                        {"clinica_id": clinica_id, "c": cita_id},
                    )
                    actual = await cur.fetchone()
                    if actual is None:
                        raise _error(404, "NO_ENCONTRADO", "La cita no existe en esta clinica")
                    if actual["estado_id"] != _ESTADO_RESERVADA:
                        raise _error(409, "TRANSICION_INVALIDA", "Una cita en estado final no admite cambios de estado")

                    await cur.execute(
                        f"""
                        UPDATE cita
                           SET estado_id = %(e)s,
                               cancelada_por = %(u)s,
                               motivo_cancelacion = %(m)s
                         WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s
                         RETURNING {_CITA_COLS}
                        """,
                        {
                            "e": _ESTADO_CANCELADA,
                            "u": usuario_id,
                            "m": body.motivo,
                            "clinica_id": clinica_id,
                            "c": cita_id,
                        },
                    )
                    return await cur.fetchone()
    except pgerr.DatabaseError as exc:
        raise _manejar_error_pg(exc)


# ---------------------------------------------------------------- RF12 desenlace
@router.post(
    "/citas/{cita_id}/desenlace",
    summary="RF12: registrar atendida o ausente (solo pasada la hora de inicio)",
)
async def desenlace(
    cita_id: int,
    body: DesenlaceIn,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    usuario_id: int = Header(..., alias="X-Usuario-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    try:
        async with db.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT profesional_id, inicio, estado_id
                          FROM cita
                         WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s
                           FOR UPDATE
                        """,
                        {"clinica_id": clinica_id, "c": cita_id},
                    )
                    actual = await cur.fetchone()
                    if actual is None:
                        raise _error(404, "NO_ENCONTRADO", "La cita no existe en esta clinica")
                    if actual["estado_id"] != _ESTADO_RESERVADA:
                        raise _error(409, "TRANSICION_INVALIDA", "Una cita en estado final no admite cambios de estado")

                    await cur.execute(
                        f"""
                        UPDATE cita
                           SET estado_id = %(e)s,
                               desenlace_registrado_por = %(u)s
                         WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s
                         RETURNING {_CITA_COLS}
                        """,
                        {
                            "e": _ESTADO_POR_NOMBRE[body.resultado],
                            "u": usuario_id,
                            "clinica_id": clinica_id,
                            "c": cita_id,
                        },
                    )
                    return await cur.fetchone()
    except pgerr.DatabaseError as exc:
        raise _manejar_error_pg(exc)


@router.get("/citas/{cita_id}", summary="Detalle de una cita de la clinica")
async def obtener_cita(
    cita_id: int,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT {_CITA_COLS_ALIAS}, e.codigo AS estado
                  FROM cita c
                  JOIN estado_cita e ON e.estado_id = c.estado_id
                 WHERE c.clinica_id = %(clinica_id)s AND c.cita_id = %(c)s
                """,
                {"clinica_id": clinica_id, "c": cita_id},
            )
            row = await cur.fetchone()
            if row is None:
                raise _error(404, "NO_ENCONTRADO", "La cita no existe en esta clinica")
            return row


# ---------------------------------------------------------------- RF20 agenda del dia
@router.get("/agenda", summary="RF20: agenda del dia (de un profesional o de toda la clinica)")
async def agenda_del_dia(
    fecha: date,
    profesional_id: int | None = Query(default=None),
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            tz = await _zona_clinica(cur, clinica_id)
            ini, fin = _limites_dia(fecha, tz)
            await cur.execute(
                """
                SELECT c.cita_id, c.profesional_id, c.paciente_id, c.servicio_id,
                       c.inicio, c.fin, c.estado_id, e.codigo AS estado,
                       pa.nombre || ' ' || pa.apellidos AS paciente
                  FROM cita c
                  JOIN paciente pa ON pa.clinica_id = c.clinica_id AND pa.paciente_id = c.paciente_id
                  JOIN estado_cita e ON e.estado_id = c.estado_id
                 WHERE c.clinica_id = %(clinica_id)s
                   AND c.inicio >= %(i)s AND c.inicio < %(f)s
                   AND (%(pid)s::bigint IS NULL OR c.profesional_id = %(pid)s::bigint)
                 ORDER BY c.inicio, c.profesional_id
                """,
                {"clinica_id": clinica_id, "i": ini, "f": fin, "pid": profesional_id},
            )
            return await cur.fetchall()


# ---------------------------------------------------------------- RF21 conteo por estado
@router.get("/citas/conteo/por-estado", summary="RF21: conteo de citas por estado en un rango de fechas")
async def conteo_por_estado(
    desde: date,
    hasta: date,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    if hasta < desde:
        raise _error(422, "RANGO_INVALIDO", "'hasta' debe ser mayor o igual que 'desde'")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            tz = await _zona_clinica(cur, clinica_id)
            ini, _ = _limites_dia(desde, tz)
            _, fin = _limites_dia(hasta, tz)
            await cur.execute(
                """
                SELECT e.codigo AS estado, count(c.cita_id) AS total
                  FROM estado_cita e
                  LEFT JOIN cita c
                    ON c.estado_id = e.estado_id
                   AND c.clinica_id = %(clinica_id)s
                   AND c.inicio >= %(i)s AND c.inicio < %(f)s
                 GROUP BY e.estado_id, e.codigo
                 ORDER BY e.estado_id
                """,
                {"clinica_id": clinica_id, "i": ini, "f": fin},
            )
            return await cur.fetchall()