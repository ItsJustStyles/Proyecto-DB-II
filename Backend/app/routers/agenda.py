"""RF5 a RF8: horarios, bloqueos y disponibilidad (con cache en Redis)."""
import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Query, Response
from psycopg import errors as pgerr

from .. import cache, db
from ..schemas import BloqueoIn, HorarioIn

router = APIRouter(prefix="/api/v1", tags=["agenda"])

_SLOT_STEP_MIN = int(os.environ.get("SLOT_STEP_MIN", "15"))

_CONFLICTOS_SQL = """
    SELECT cita_id, paciente_id, inicio, fin
      FROM cita
     WHERE clinica_id = %(clinica_id)s
       AND profesional_id = %(pid)s
       AND estado_id = 1
       AND tstzrange(inicio, fin) && tstzrange(%(i)s, %(f)s)
     ORDER BY inicio
"""


def _error(status_code: int, codigo: str, mensaje: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"codigo": codigo, "mensaje": mensaje},
    )


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


def _calcular_slots(
    fecha: date,
    tz: ZoneInfo,
    bloques: list[tuple[time, time]],
    duracion_min: int,
    ocupados: list[tuple[datetime, datetime]],
    bloqueos: list[tuple[datetime, datetime]],
    ahora_utc: datetime,
    paso_min: int,
) -> list[dict]:
    duracion = timedelta(minutes=duracion_min)
    paso = timedelta(minutes=paso_min)
    disponibles: list[dict] = []

    for hora_ini, hora_fin in bloques:
        cursor = datetime.combine(fecha, hora_ini, tzinfo=tz)
        limite = datetime.combine(fecha, hora_fin, tzinfo=tz)

        while cursor + duracion <= limite:
            fin_slot = cursor + duracion
            if cursor > ahora_utc:
                choca_cita = any(cursor < o_fin and fin_slot > o_ini for o_ini, o_fin in ocupados)
                choca_bloqueo = any(cursor < b_fin and fin_slot > b_ini for b_ini, b_fin in bloqueos)
                if not choca_cita and not choca_bloqueo:
                    disponibles.append(
                        {
                            "inicio": cursor.isoformat(),
                            "fin": fin_slot.isoformat(),
                        }
                    )
            cursor += paso

    return disponibles


# ---------------------------------------------------------------- RF5 horarios
@router.post(
    "/profesionales/{profesional_id}/horarios",
    status_code=201,
    summary="RF5: agrega un bloque semanal de atencion",
)
async def crear_horario(
    profesional_id: int,
    body: HorarioIn,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    try:
        async with db.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin)
                    VALUES (%(clinica_id)s, %(pid)s, %(d)s, %(hi)s, %(hf)s)
                    RETURNING horario_id, profesional_id, dia_semana, hora_inicio, hora_fin
                    """,
                    {
                        "clinica_id": clinica_id,
                        "pid": profesional_id,
                        "d": body.dia_semana,
                        "hi": body.hora_inicio,
                        "hf": body.hora_fin,
                    },
                )
                row = await cur.fetchone()
    except pgerr.ExclusionViolation:
        raise _error(409, "HORARIO_SOLAPADO", "El bloque se solapa con otro horario del profesional en ese dia")
    except pgerr.ForeignKeyViolation:
        raise _error(404, "NO_ENCONTRADO", "El profesional no existe en esta clinica")

    await cache.invalidar_profesional(clinica_id, profesional_id)
    return row


@router.get(
    "/profesionales/{profesional_id}/horarios",
    summary="Horario semanal del profesional",
)
async def listar_horarios(
    profesional_id: int,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT horario_id, dia_semana, hora_inicio, hora_fin
                  FROM horario_atencion
                 WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s
                 ORDER BY dia_semana, hora_inicio
                """,
                {"clinica_id": clinica_id, "pid": profesional_id},
            )
            return await cur.fetchall()


@router.delete(
    "/horarios/{horario_id}",
    status_code=204,
    summary="RF5: elimina un bloque semanal",
)
async def eliminar_horario(
    horario_id: int,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM horario_atencion
                 WHERE clinica_id = %(clinica_id)s AND horario_id = %(h)s
                RETURNING profesional_id
                """,
                {"clinica_id": clinica_id, "h": horario_id},
            )
            row = await cur.fetchone()
            if row is None:
                raise _error(404, "NO_ENCONTRADO", "El horario no existe en esta clinica")

    await cache.invalidar_profesional(clinica_id, row["profesional_id"])
    return Response(status_code=204)


# ---------------------------------------------------------------- RF6 bloqueos
@router.post(
    "/profesionales/{profesional_id}/bloqueos",
    status_code=201,
    summary="RF6: registra un bloqueo y lista las citas en conflicto",
)
async def crear_bloqueo(
    profesional_id: int,
    body: BloqueoIn,
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
                        INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo, creado_por)
                        VALUES (%(clinica_id)s, %(pid)s, %(i)s, %(f)s, %(m)s, %(u)s)
                        RETURNING bloqueo_id, profesional_id, inicio, fin, motivo
                        """,
                        {
                            "clinica_id": clinica_id,
                            "pid": profesional_id,
                            "i": body.inicio,
                            "f": body.fin,
                            "m": body.motivo,
                            "u": usuario_id,
                        },
                    )
                    row = await cur.fetchone()

                    # El bloqueo no cancela citas; devuelve las ya reservadas en conflicto para reprogramar
                    await cur.execute(
                        _CONFLICTOS_SQL,
                        {
                            "clinica_id": clinica_id,
                            "pid": profesional_id,
                            "i": body.inicio,
                            "f": body.fin,
                        },
                    )
                    conflictos = await cur.fetchall()
    except pgerr.ForeignKeyViolation:
        raise _error(404, "REFERENCIA_INVALIDA", "Profesional o usuario inexistente en esta clinica")

    await cache.invalidar_profesional(clinica_id, profesional_id)
    return {**row, "conflictos": conflictos}


@router.get(
    "/profesionales/{profesional_id}/bloqueos",
    summary="Bloqueos del profesional",
)
async def listar_bloqueos(
    profesional_id: int,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT bloqueo_id, inicio, fin, motivo
                  FROM bloqueo_agenda
                 WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s
                 ORDER BY inicio
                """,
                {"clinica_id": clinica_id, "pid": profesional_id},
            )
            return await cur.fetchall()


@router.get(
    "/bloqueos/{bloqueo_id}/conflictos",
    summary="RF6: citas vigentes que caen dentro del bloqueo",
)
async def conflictos_bloqueo(
    bloqueo_id: int,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT profesional_id, inicio, fin
                  FROM bloqueo_agenda
                 WHERE clinica_id = %(clinica_id)s AND bloqueo_id = %(b)s
                """,
                {"clinica_id": clinica_id, "b": bloqueo_id},
            )
            b = await cur.fetchone()
            if b is None:
                raise _error(404, "NO_ENCONTRADO", "El bloqueo no existe en esta clinica")

            await cur.execute(
                _CONFLICTOS_SQL,
                {
                    "clinica_id": clinica_id,
                    "pid": b["profesional_id"],
                    "i": b["inicio"],
                    "f": b["fin"],
                },
            )
            return await cur.fetchall()


@router.delete(
    "/bloqueos/{bloqueo_id}",
    status_code=204,
    summary="Elimina un bloqueo",
)
async def eliminar_bloqueo(
    bloqueo_id: int,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM bloqueo_agenda
                 WHERE clinica_id = %(clinica_id)s AND bloqueo_id = %(b)s
                RETURNING profesional_id
                """,
                {"clinica_id": clinica_id, "b": bloqueo_id},
            )
            row = await cur.fetchone()
            if row is None:
                raise _error(404, "NO_ENCONTRADO", "El bloqueo no existe en esta clinica")

    await cache.invalidar_profesional(clinica_id, row["profesional_id"])
    return Response(status_code=204)


# ---------------------------------------------------------------- RF7 / RF8 disponibilidad
async def _espacios_profesional(
    clinica_id: int,
    profesional_id: int,
    fecha: date,
    servicio_id: int,
    ahora_utc: datetime,
) -> list[dict]:
    # 1) Leer versiones y buscar en Redis ANTES de consultar PostgreSQL (I8)
    cacheado, clave = await cache.leer(clinica_id, profesional_id, fecha.isoformat(), servicio_id)

    if cacheado is None:
        async with db.pool.connection() as conn:
            async with conn.cursor() as cur:
                tz = await _zona_clinica(cur, clinica_id)

                await cur.execute(
                    "SELECT activo FROM profesional WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s",
                    {"clinica_id": clinica_id, "pid": profesional_id},
                )
                prof = await cur.fetchone()
                if prof is None:
                    raise _error(404, "NO_ENCONTRADO", "El profesional no existe en esta clinica")

                await cur.execute(
                    """
                    SELECT s.duracion_min, s.activo
                      FROM servicio s
                      JOIN profesional_servicio ps
                        ON ps.clinica_id = s.clinica_id AND ps.servicio_id = s.servicio_id
                     WHERE s.clinica_id = %(clinica_id)s
                       AND s.servicio_id = %(sid)s
                       AND ps.profesional_id = %(pid)s
                    """,
                    {"clinica_id": clinica_id, "sid": servicio_id, "pid": profesional_id},
                )
                serv = await cur.fetchone()
                if serv is None:
                    raise _error(422, "SERVICIO_NO_HABILITADO", "El profesional no atiende ese servicio en esta clinica")

                if not prof["activo"] or not serv["activo"]:
                    cacheado = []
                else:
                    ini_dia, fin_dia = _limites_dia(fecha, tz)

                    await cur.execute(
                        """
                        SELECT hora_inicio, hora_fin
                          FROM horario_atencion
                         WHERE clinica_id = %(clinica_id)s
                           AND profesional_id = %(pid)s
                           AND dia_semana = %(dow)s
                         ORDER BY hora_inicio
                        """,
                        {"clinica_id": clinica_id, "pid": profesional_id, "dow": fecha.isoweekday()},
                    )
                    bloques = await cur.fetchall()

                    await cur.execute(
                        """
                        SELECT inicio, fin
                          FROM cita
                         WHERE clinica_id = %(clinica_id)s
                           AND profesional_id = %(pid)s
                           AND estado_id = 1
                           AND inicio < %(fd)s AND fin > %(id)s
                        """,
                        {"clinica_id": clinica_id, "pid": profesional_id, "id": ini_dia, "fd": fin_dia},
                    )
                    ocupados = await cur.fetchall()

                    await cur.execute(
                        """
                        SELECT inicio, fin
                          FROM bloqueo_agenda
                         WHERE clinica_id = %(clinica_id)s
                           AND profesional_id = %(pid)s
                           AND tstzrange(inicio, fin) && tstzrange(%(id)s, %(fd)s)
                        """,
                        {"clinica_id": clinica_id, "pid": profesional_id, "id": ini_dia, "fd": fin_dia},
                    )
                    bloqueos = await cur.fetchall()

                    # Se guarda el dia completo en cache; el filtro de espacios pasados se aplica al servir
                    cacheado = _calcular_slots(
                        fecha=fecha,
                        tz=tz,
                        bloques=[(b["hora_inicio"], b["hora_fin"]) for b in bloques],
                        duracion_min=serv["duracion_min"],
                        ocupados=[(o["inicio"], o["fin"]) for o in ocupados],
                        bloqueos=[(b["inicio"], b["fin"]) for b in bloqueos],
                        ahora_utc=datetime(1970, 1, 1, tzinfo=timezone.utc),
                        paso_min=_SLOT_STEP_MIN,
                    )

        await cache.guardar(clave, cacheado)

    return [s for s in cacheado if datetime.fromisoformat(s["inicio"]) > ahora_utc]


@router.get(
    "/profesionales/{profesional_id}/disponibilidad",
    summary="RF7: espacios libres de un profesional en una fecha",
)
async def disponibilidad_profesional(
    profesional_id: int,
    fecha: date,
    servicio_id: int,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    espacios = await _espacios_profesional(
        clinica_id=clinica_id,
        profesional_id=profesional_id,
        fecha=fecha,
        servicio_id=servicio_id,
        ahora_utc=datetime.now(timezone.utc),
    )
    return {
        "profesional_id": profesional_id,
        "fecha": fecha,
        "servicio_id": servicio_id,
        "espacios": espacios,
    }


@router.get(
    "/disponibilidad",
    summary="RF8: profesionales con espacio para un servicio en un rango de fechas",
)
async def disponibilidad_por_servicio(
    servicio_id: int,
    desde: date,
    hasta: date,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    if hasta < desde:
        raise _error(422, "RANGO_INVALIDO", "'hasta' debe ser mayor o igual que 'desde'")
    if (hasta - desde).days > 30:
        raise _error(422, "RANGO_EXCESIVO", "El rango maximo es de 31 dias")

    ahora_utc = datetime.now(timezone.utc)

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT p.profesional_id, p.nombre
                  FROM profesional p
                  JOIN profesional_servicio ps
                    ON ps.clinica_id = p.clinica_id AND ps.profesional_id = p.profesional_id
                 WHERE p.clinica_id = %(clinica_id)s
                   AND p.activo
                   AND ps.servicio_id = %(sid)s
                 ORDER BY p.profesional_id
                """,
                {"clinica_id": clinica_id, "sid": servicio_id},
            )
            candidatos = await cur.fetchall()

    resultado = []
    for prof in candidatos:
        dias = []
        d = desde
        while d <= hasta:
            espacios = await _espacios_profesional(
                clinica_id=clinica_id,
                profesional_id=prof["profesional_id"],
                fecha=d,
                servicio_id=servicio_id,
                ahora_utc=ahora_utc,
            )
            if espacios:
                dias.append({"fecha": d, "espacios": espacios})
            d += timedelta(days=1)

        if dias:
            resultado.append(
                {
                    "profesional_id": prof["profesional_id"],
                    "nombre": prof["nombre"],
                    "dias": dias,
                }
            )

    return {
        "servicio_id": servicio_id,
        "desde": desde,
        "hasta": hasta,
        "profesionales": resultado,
    }