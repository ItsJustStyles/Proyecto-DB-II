"""RF14 y RF16: pacientes e historial. Los datos de contacto se auditan (RF18)."""
from fastapi import APIRouter, Header, HTTPException, Query
from psycopg import errors as pgerr

from .. import db
from ..schemas import PacienteIn, PacientePatch

router = APIRouter(prefix="/api/v1", tags=["pacientes"])

_COLS_COMPLETAS = (
    "paciente_id, identificacion, nombre, apellidos, "
    "fecha_nacimiento, telefono, correo, activo, creado_en"
)
_CITA_COLS = (
    "c.cita_id, c.paciente_id, c.profesional_id, c.servicio_id, "
    "c.inicio, c.fin, c.estado_id, c.cita_origen_id, "
    "c.creada_por, c.cancelada_por, c.motivo_cancelacion, "
    "c.desenlace_registrado_por, c.creada_en, c.actualizada_en"
)
_CAMPOS_CONTACTO = {"telefono", "correo"}


def _error(status_code: int, codigo: str, mensaje: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"codigo": codigo, "mensaje": mensaje},
    )


async def _auditar(
    cur,
    clinica_id: int,
    usuario_id: int,
    paciente_id: int,
    accion: str,
    entidad: str,
    entidad_id: int,
) -> None:
    await cur.execute(
        """
        INSERT INTO bitacora_auditoria (clinica_id, usuario_id, paciente_id, accion, entidad, entidad_id)
        VALUES (%(clinica_id)s, %(usuario_id)s, %(paciente_id)s, %(accion)s, %(entidad)s, %(entidad_id)s)
        """,
        {
            "clinica_id": clinica_id,
            "usuario_id": usuario_id,
            "paciente_id": paciente_id,
            "accion": accion,
            "entidad": entidad,
            "entidad_id": entidad_id,
        },
    )


@router.post("/pacientes", status_code=201, summary="RF14: registrar paciente")
async def crear_paciente(
    body: PacienteIn,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    usuario_id: int = Header(..., alias="X-Usuario-Id", description="Temporal para bitacora mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    try:
        async with db.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        f"""
                        INSERT INTO paciente (
                            clinica_id, identificacion, nombre, apellidos,
                            fecha_nacimiento, telefono, correo
                        )
                        VALUES (
                            %(clinica_id)s, %(identificacion)s, %(nombre)s, %(apellidos)s,
                            %(fecha_nacimiento)s, %(telefono)s, %(correo)s
                        )
                        RETURNING {_COLS_COMPLETAS}
                        """,
                        {"clinica_id": clinica_id, **body.model_dump()},
                    )
                    row = await cur.fetchone()
                    await _auditar(
                        cur,
                        clinica_id=clinica_id,
                        usuario_id=usuario_id,
                        paciente_id=row["paciente_id"],
                        accion="CREACION",
                        entidad="PACIENTE_CONTACTO",
                        entidad_id=row["paciente_id"],
                    )
                    return row
    except pgerr.UniqueViolation:
        raise _error(409, "PACIENTE_DUPLICADO", "Ya existe un paciente con esa identificacion en la clinica")
    except pgerr.ForeignKeyViolation:
        raise _error(400, "REFERENCIA_INVALIDA", "La clinica o el usuario indicado no existen")
    except pgerr.CheckViolation:
        raise _error(422, "DATOS_INVALIDOS", "La fecha de nacimiento no puede ser futura")


@router.get("/pacientes", summary="RF14: busqueda de pacientes (sin datos de contacto)")
async def buscar_pacientes(
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    patron = f"%{q}%" if q else None
    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT paciente_id, identificacion, nombre, apellidos, fecha_nacimiento, activo
                  FROM paciente
                 WHERE clinica_id = %(clinica_id)s
                   AND (%(q)s::text IS NULL
                        OR apellidos ILIKE %(q)s
                        OR nombre ILIKE %(q)s
                        OR identificacion ILIKE %(q)s)
                 ORDER BY apellidos, nombre
                 LIMIT %(lim)s OFFSET %(off)s
                """,
                {"clinica_id": clinica_id, "q": patron, "lim": limit, "off": offset},
            )
            return await cur.fetchall()


@router.get("/pacientes/{paciente_id}", summary="RF14: detalle con datos de contacto (queda en la bitacora)")
async def obtener_paciente(
    paciente_id: int,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    usuario_id: int = Header(..., alias="X-Usuario-Id", description="Temporal para bitacora mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    try:
        async with db.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        f"""
                        SELECT {_COLS_COMPLETAS}
                          FROM paciente
                         WHERE clinica_id = %(clinica_id)s AND paciente_id = %(pid)s
                        """,
                        {"clinica_id": clinica_id, "pid": paciente_id},
                    )
                    row = await cur.fetchone()
                    if row is None:
                        raise _error(404, "NO_ENCONTRADO", "El paciente no existe en esta clinica")

                    await _auditar(
                        cur,
                        clinica_id=clinica_id,
                        usuario_id=usuario_id,
                        paciente_id=paciente_id,
                        accion="LECTURA",
                        entidad="PACIENTE_CONTACTO",
                        entidad_id=paciente_id,
                    )
                    return row
    except pgerr.ForeignKeyViolation:
        raise _error(400, "USUARIO_INVALIDO", "El usuario que consulta no pertenece a esta clinica")


@router.patch("/pacientes/{paciente_id}", summary="RF14: actualizar paciente")
async def actualizar_paciente(
    paciente_id: int,
    body: PacientePatch,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    usuario_id: int = Header(..., alias="X-Usuario-Id", description="Temporal para bitacora mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    campos = body.model_dump(exclude_unset=True)
    if not campos:
        raise _error(422, "SIN_CAMBIOS", "No hay campos para actualizar")

    set_sql = ", ".join(f"{k} = %({k})s" for k in campos)

    try:
        async with db.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        f"""
                        UPDATE paciente
                           SET {set_sql}
                         WHERE clinica_id = %(clinica_id)s AND paciente_id = %(pid)s
                         RETURNING {_COLS_COMPLETAS}
                        """,
                        {**campos, "clinica_id": clinica_id, "pid": paciente_id},
                    )
                    row = await cur.fetchone()
                    if row is None:
                        raise _error(404, "NO_ENCONTRADO", "El paciente no existe en esta clinica")

                    if _CAMPOS_CONTACTO & campos.keys():
                        await _auditar(
                            cur,
                            clinica_id=clinica_id,
                            usuario_id=usuario_id,
                            paciente_id=paciente_id,
                            accion="ACTUALIZACION",
                            entidad="PACIENTE_CONTACTO",
                            entidad_id=paciente_id,
                        )
                    return row
    except pgerr.UniqueViolation:
        raise _error(409, "PACIENTE_DUPLICADO", "Ya existe un paciente con esa identificacion en la clinica")
    except pgerr.ForeignKeyViolation:
        raise _error(400, "USUARIO_INVALIDO", "El usuario que actualiza no pertenece a esta clinica")
    except pgerr.CheckViolation:
        raise _error(422, "DATOS_INVALIDOS", "La fecha de nacimiento no puede ser futura")


@router.get("/pacientes/{paciente_id}/citas", summary="RF16: historial de citas del paciente con su estado")
async def historial_paciente(
    paciente_id: int,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 AS ok FROM paciente WHERE clinica_id = %(clinica_id)s AND paciente_id = %(pid)s",
                {"clinica_id": clinica_id, "pid": paciente_id},
            )
            if await cur.fetchone() is None:
                raise _error(404, "NO_ENCONTRADO", "El paciente no existe en esta clinica")

            await cur.execute(
                f"""
                SELECT {_CITA_COLS}, e.codigo AS estado
                  FROM cita c
                  JOIN estado_cita e ON e.estado_id = c.estado_id
                 WHERE c.clinica_id = %(clinica_id)s AND c.paciente_id = %(pid)s
                 ORDER BY c.inicio DESC
                """,
                {"clinica_id": clinica_id, "pid": paciente_id},
            )
            return await cur.fetchall()