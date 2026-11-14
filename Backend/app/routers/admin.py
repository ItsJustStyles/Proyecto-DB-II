"""RF1 a RF4: clinicas, usuarios, servicios, profesionales y su relacion."""
from fastapi import APIRouter, Header, HTTPException, Response
from psycopg import errors as pgerr

from .. import db
from ..schemas import (
    ClinicaIn,
    ProfesionalIn,
    ProfesionalPatch,
    ProfesionalServicioIn,
    ServicioIn,
    ServicioPatch,
    UsuarioIn,
    UsuarioPatch,
)

router = APIRouter(prefix="/api/v1", tags=["administracion"])


def _error(status_code: int, codigo: str, mensaje: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"codigo": codigo, "mensaje": mensaje},
    )


def _sets(campos: dict) -> tuple[str, dict]:
    """SET parametrizado: los nombres de columna vienen del modelo (lista cerrada), no del cliente."""
    partes = [f"{k} = %({k})s" for k in campos]
    return ", ".join(partes), campos


# ---------------------------------------------------------------- RF1 clinicas
@router.post("/clinicas", status_code=201, summary="RF1: alta de clinica con su primer administrador")
async def crear_clinica(body: ClinicaIn):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    try:
        async with db.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT crear_clinica(%(n)s, %(z)s, %(s)s::uuid, %(a)s) AS clinica_id",
                    {
                        "n": body.nombre,
                        "z": body.zona_horaria,
                        "s": str(body.admin_keycloak_sub),
                        "a": body.admin_nombre,
                    },
                )
                row = await cur.fetchone()
                return {
                    "clinica_id": row["clinica_id"],
                    "nombre": body.nombre,
                    "zona_horaria": body.zona_horaria,
                }
    except pgerr.UniqueViolation:
        raise _error(409, "CONFLICTO", "Ya existe una clinica con ese nombre o un usuario con ese keycloak_sub")


@router.get("/clinicas", summary="Lista de clinicas (solo administrador de plataforma)")
async def listar_clinicas():
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT clinica_id, nombre, zona_horaria, activa, creada_en FROM clinica ORDER BY clinica_id"
            )
            return await cur.fetchall()


# ---------------------------------------------------------------- RF2 usuarios
@router.post("/usuarios", status_code=201, summary="RF2: alta de usuario en la clinica del administrador")
async def crear_usuario(
    body: UsuarioIn,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    try:
        async with db.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre)
                    VALUES (%(clinica_id)s, %(rol)s, %(sub)s::uuid, %(nombre)s)
                    RETURNING usuario_id, clinica_id, rol_id, keycloak_sub, nombre, activo
                    """,
                    {
                        "clinica_id": clinica_id,
                        "rol": body.rol_id,
                        "sub": str(body.keycloak_sub),
                        "nombre": body.nombre,
                    },
                )
                return await cur.fetchone()
    except pgerr.UniqueViolation:
        raise _error(409, "USUARIO_DUPLICADO", "Ya existe un usuario con ese keycloak_sub")
    except pgerr.ForeignKeyViolation:
        raise _error(404, "REFERENCIA_INVALIDA", "La clinica o el rol indicado no existen")


@router.get("/usuarios", summary="Usuarios de la clinica")
async def listar_usuarios(
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT usuario_id, rol_id, nombre, activo, creado_en
                  FROM usuario
                 WHERE clinica_id = %(clinica_id)s
                 ORDER BY usuario_id
                """,
                {"clinica_id": clinica_id},
            )
            return await cur.fetchall()


@router.patch("/usuarios/{usuario_id}", summary="RF2: cambio de rol, nombre o baja logica")
async def actualizar_usuario(
    usuario_id: int,
    body: UsuarioPatch,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    actor_usuario_id: int | None = Header(
        default=None,
        alias="X-Usuario-Id",
        description="Temporal para evitar autobaja mientras se integra Keycloak",
    ),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    campos = body.model_dump(exclude_none=True)
    if not campos:
        raise _error(422, "SIN_CAMBIOS", "No hay campos para actualizar")
    if actor_usuario_id is not None and usuario_id == actor_usuario_id and campos.get("activo") is False:
        raise _error(409, "AUTOBAJA", "Un administrador no puede darse de baja a si mismo")

    set_sql, params = _sets(campos)

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                UPDATE usuario
                   SET {set_sql}
                 WHERE clinica_id = %(clinica_id)s AND usuario_id = %(uid)s
                 RETURNING usuario_id, rol_id, nombre, activo
                """,
                {**params, "clinica_id": clinica_id, "uid": usuario_id},
            )
            row = await cur.fetchone()
            if row is None:
                raise _error(404, "NO_ENCONTRADO", "El usuario no existe en esta clinica")
            return row


# ---------------------------------------------------------------- catalogos
@router.get("/especialidades", summary="Catalogo global de especialidades")
async def listar_especialidades():
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT especialidad_id, nombre FROM especialidad ORDER BY nombre")
            return await cur.fetchall()


# ---------------------------------------------------------------- RF3 servicios
@router.post("/servicios", status_code=201, summary="RF3: alta de servicio")
async def crear_servicio(
    body: ServicioIn,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    try:
        async with db.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO servicio (clinica_id, nombre, duracion_min, especialidad_id)
                    VALUES (%(clinica_id)s, %(nombre)s, %(dur)s, %(esp)s)
                    RETURNING servicio_id, nombre, duracion_min, especialidad_id, activo
                    """,
                    {
                        "clinica_id": clinica_id,
                        "nombre": body.nombre,
                        "dur": body.duracion_min,
                        "esp": body.especialidad_id,
                    },
                )
                return await cur.fetchone()
    except pgerr.UniqueViolation:
        raise _error(409, "SERVICIO_DUPLICADO", "Ya existe un servicio con ese nombre en la clinica")
    except pgerr.ForeignKeyViolation:
        raise _error(422, "REFERENCIA_INVALIDA", "La clinica o la especialidad indicada no existen")


@router.get("/servicios", summary="Catalogo de servicios de la clinica")
async def listar_servicios(
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT servicio_id, nombre, duracion_min, especialidad_id, activo
                  FROM servicio
                 WHERE clinica_id = %(clinica_id)s
                 ORDER BY nombre
                """,
                {"clinica_id": clinica_id},
            )
            return await cur.fetchall()


@router.patch("/servicios/{servicio_id}", summary="RF3: modificar servicio (la duracion no altera citas ya agendadas, I4)")
async def actualizar_servicio(
    servicio_id: int,
    body: ServicioPatch,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    campos = body.model_dump(exclude_none=True)
    if not campos:
        raise _error(422, "SIN_CAMBIOS", "No hay campos para actualizar")

    set_sql, params = _sets(campos)

    try:
        async with db.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    UPDATE servicio
                       SET {set_sql}
                     WHERE clinica_id = %(clinica_id)s AND servicio_id = %(sid)s
                     RETURNING servicio_id, nombre, duracion_min, especialidad_id, activo
                    """,
                    {**params, "clinica_id": clinica_id, "sid": servicio_id},
                )
                row = await cur.fetchone()
                if row is None:
                    raise _error(404, "NO_ENCONTRADO", "El servicio no existe en esta clinica")
                return row
    except pgerr.UniqueViolation:
        raise _error(409, "SERVICIO_DUPLICADO", "Ya existe un servicio con ese nombre en la clinica")
    except pgerr.ForeignKeyViolation:
        raise _error(422, "REFERENCIA_INVALIDA", "La especialidad indicada no existe")


# ---------------------------------------------------------------- RF4 profesionales
@router.post("/profesionales", status_code=201, summary="RF4: alta de profesional ligado a un usuario con rol PROFESIONAL")
async def crear_profesional(
    body: ProfesionalIn,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    try:
        async with db.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, nombre)
                    VALUES (%(clinica_id)s, %(u)s, %(esp)s, %(nombre)s)
                    RETURNING profesional_id, usuario_id, especialidad_id, nombre, activo
                    """,
                    {
                        "clinica_id": clinica_id,
                        "u": body.usuario_id,
                        "esp": body.especialidad_id,
                        "nombre": body.nombre,
                    },
                )
                return await cur.fetchone()
    except pgerr.UniqueViolation:
        raise _error(409, "PROFESIONAL_DUPLICADO", "Ese usuario ya esta registrado como profesional")
    except pgerr.ForeignKeyViolation:
        raise _error(422, "REFERENCIA_INVALIDA", "El usuario o la especialidad no existen en esta clinica")
    except pgerr.CheckViolation:
        raise _error(422, "ROL_INVALIDO", "El usuario asignado debe tener rol PROFESIONAL")


@router.get("/profesionales", summary="Profesionales de la clinica con los servicios que atienden")
async def listar_profesionales(
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT p.profesional_id, p.usuario_id, p.especialidad_id, p.nombre, p.activo,
                       COALESCE(
                           array_agg(ps.servicio_id ORDER BY ps.servicio_id)
                           FILTER (WHERE ps.servicio_id IS NOT NULL),
                           '{}'
                       ) AS servicios
                  FROM profesional p
                  LEFT JOIN profesional_servicio ps
                    ON ps.clinica_id = p.clinica_id AND ps.profesional_id = p.profesional_id
                 WHERE p.clinica_id = %(clinica_id)s
                 GROUP BY p.profesional_id
                 ORDER BY p.profesional_id
                """,
                {"clinica_id": clinica_id},
            )
            return await cur.fetchall()


@router.patch("/profesionales/{profesional_id}", summary="RF4: modificar profesional / baja logica")
async def actualizar_profesional(
    profesional_id: int,
    body: ProfesionalPatch,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    campos = body.model_dump(exclude_none=True)
    if not campos:
        raise _error(422, "SIN_CAMBIOS", "No hay campos para actualizar")

    set_sql, params = _sets(campos)

    try:
        async with db.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    UPDATE profesional
                       SET {set_sql}
                     WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s
                     RETURNING profesional_id, especialidad_id, nombre, activo
                    """,
                    {**params, "clinica_id": clinica_id, "pid": profesional_id},
                )
                row = await cur.fetchone()
                if row is None:
                    raise _error(404, "NO_ENCONTRADO", "El profesional no existe en esta clinica")
                return row
    except pgerr.ForeignKeyViolation:
        raise _error(422, "REFERENCIA_INVALIDA", "La especialidad indicada no existe")


@router.post("/profesionales/{profesional_id}/servicios", status_code=201, summary="RF4: habilita un servicio para el profesional")
async def asociar_servicio(
    profesional_id: int,
    body: ProfesionalServicioIn,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    try:
        async with db.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id)
                    VALUES (%(clinica_id)s, %(pid)s, %(sid)s)
                    """,
                    {"clinica_id": clinica_id, "pid": profesional_id, "sid": body.servicio_id},
                )
                return {"profesional_id": profesional_id, "servicio_id": body.servicio_id}
    except pgerr.UniqueViolation:
        raise _error(409, "ASOCIACION_DUPLICADA", "El profesional ya tiene asociado ese servicio")
    except pgerr.ForeignKeyViolation:
        raise _error(422, "REFERENCIA_INVALIDA", "Profesional o servicio inexistente en esta clinica")
    except pgerr.CheckViolation:
        raise _error(422, "ESPECIALIDAD_INCOMPATIBLE", "La especialidad del profesional no coincide con la del servicio")


@router.delete("/profesionales/{profesional_id}/servicios/{servicio_id}", status_code=204, summary="RF4: retira un servicio del profesional")
async def desasociar_servicio(
    profesional_id: int,
    servicio_id: int,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM profesional_servicio
                 WHERE clinica_id = %(clinica_id)s
                   AND profesional_id = %(pid)s
                   AND servicio_id = %(sid)s
                RETURNING servicio_id
                """,
                {"clinica_id": clinica_id, "pid": profesional_id, "sid": servicio_id},
            )
            if await cur.fetchone() is None:
                raise _error(404, "NO_ENCONTRADO", "La asociacion no existe en esta clinica")
    return Response(status_code=204)