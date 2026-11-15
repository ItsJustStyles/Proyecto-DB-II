"""RF1 a RF4: clinicas, usuarios, servicios, profesionales y su relacion."""
from fastapi import APIRouter, Depends

from .. import cache, db
from ..auth import requiere
from ..common import error, no_encontrado
from ..db import Principal, Tx
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


def _sets(campos: dict) -> tuple[str, dict]:
    """SET parametrizado: los nombres de columna vienen del modelo (lista cerrada), no del cliente."""
    partes = [f"{k} = %({k})s" for k in campos]
    return ", ".join(partes), campos


# ---------------------------------------------------------------- RF1 clinicas
@router.post("/clinicas", status_code=201, summary="RF1: alta de clinica con su primer administrador")
async def crear_clinica(body: ClinicaIn, p: Principal = Depends(requiere("clinica.crear"))):
    async def work(tx: Tx):
        rows = await tx.fetch_catalogo(
            "SELECT crear_clinica(%(n)s, %(z)s, %(s)s::uuid, %(a)s) AS clinica_id",
            {"n": body.nombre, "z": body.zona_horaria, "s": str(body.admin_keycloak_sub), "a": body.admin_nombre},
        )
        return rows[0]["clinica_id"]

    clinica_id = await db.run(p, work)
    return {"clinica_id": clinica_id, "nombre": body.nombre, "zona_horaria": body.zona_horaria}


@router.get("/clinicas", summary="Lista de clinicas (solo administrador de plataforma)")
async def listar_clinicas(p: Principal = Depends(requiere("clinica.listar"))):
    async def work(tx: Tx):
        return await tx.fetch_catalogo(
            "SELECT clinica_id, nombre, zona_horaria, activa, creada_en FROM clinica ORDER BY clinica_id"
        )

    return await db.run(p, work)


# ---------------------------------------------------------------- RF2 usuarios
@router.post("/usuarios", status_code=201, summary="RF2: alta de usuario en la clinica del administrador")
async def crear_usuario(body: UsuarioIn, p: Principal = Depends(requiere("usuario.gestionar"))):
    async def work(tx: Tx):
        return await tx.one(
            "INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre) "
            "VALUES (%(clinica_id)s, %(rol)s, %(sub)s::uuid, %(nombre)s) "
            "RETURNING usuario_id, clinica_id, rol_id, keycloak_sub, nombre, activo",
            {"rol": body.rol_id, "sub": str(body.keycloak_sub), "nombre": body.nombre},
        )

    return await db.run(p, work)


@router.get("/usuarios", summary="Usuarios de la clinica")
async def listar_usuarios(p: Principal = Depends(requiere("usuario.gestionar"))):
    async def work(tx: Tx):
        return await tx.fetch(
            "SELECT usuario_id, rol_id, nombre, activo, creado_en FROM usuario "
            "WHERE clinica_id = %(clinica_id)s ORDER BY usuario_id"
        )

    return await db.run(p, work)


@router.patch("/usuarios/{usuario_id}", summary="RF2: cambio de rol, nombre o baja logica")
async def actualizar_usuario(usuario_id: int, body: UsuarioPatch, p: Principal = Depends(requiere("usuario.gestionar"))):
    campos = body.model_dump(exclude_none=True)
    if not campos:
        raise error(422, "SIN_CAMBIOS", "No hay campos para actualizar")
    if usuario_id == p.usuario_id and campos.get("activo") is False:
        raise error(409, "AUTOBAJA", "Un administrador no puede darse de baja a si mismo")
    set_sql, params = _sets(campos)

    async def work(tx: Tx):
        row = await tx.one(
            f"UPDATE usuario SET {set_sql} WHERE clinica_id = %(clinica_id)s AND usuario_id = %(uid)s "
            "RETURNING usuario_id, rol_id, nombre, activo",
            {**params, "uid": usuario_id},
        )
        if row is None:
            raise no_encontrado("El usuario")
        return row

    return await db.run(p, work)


# ---------------------------------------------------------------- catalogos
@router.get("/especialidades", summary="Catalogo global de especialidades")
async def listar_especialidades(p: Principal = Depends(requiere("catalogo.leer"))):
    async def work(tx: Tx):
        return await tx.fetch_catalogo("SELECT especialidad_id, nombre FROM especialidad ORDER BY nombre")

    return await db.run(p, work)


# ---------------------------------------------------------------- RF3 servicios
@router.post("/servicios", status_code=201, summary="RF3: alta de servicio")
async def crear_servicio(body: ServicioIn, p: Principal = Depends(requiere("servicio.gestionar"))):
    async def work(tx: Tx):
        return await tx.one(
            "INSERT INTO servicio (clinica_id, nombre, duracion_min, especialidad_id) "
            "VALUES (%(clinica_id)s, %(nombre)s, %(dur)s, %(esp)s) "
            "RETURNING servicio_id, nombre, duracion_min, especialidad_id, activo",
            {"nombre": body.nombre, "dur": body.duracion_min, "esp": body.especialidad_id},
        )

    return await db.run(p, work)


@router.get("/servicios", summary="Catalogo de servicios de la clinica")
async def listar_servicios(p: Principal = Depends(requiere("catalogo.leer"))):
    async def work(tx: Tx):
        return await tx.fetch(
            "SELECT servicio_id, nombre, duracion_min, especialidad_id, activo FROM servicio "
            "WHERE clinica_id = %(clinica_id)s ORDER BY nombre"
        )

    return await db.run(p, work)


@router.patch("/servicios/{servicio_id}", summary="RF3: modificar servicio (la duracion no altera citas ya agendadas, I4)")
async def actualizar_servicio(servicio_id: int, body: ServicioPatch, p: Principal = Depends(requiere("servicio.gestionar"))):
    campos = body.model_dump(exclude_none=True)
    if not campos:
        raise error(422, "SIN_CAMBIOS", "No hay campos para actualizar")
    set_sql, params = _sets(campos)

    async def work(tx: Tx):
        row = await tx.one(
            f"UPDATE servicio SET {set_sql} WHERE clinica_id = %(clinica_id)s AND servicio_id = %(sid)s "
            "RETURNING servicio_id, nombre, duracion_min, especialidad_id, activo",
            {**params, "sid": servicio_id},
        )
        if row is None:
            raise no_encontrado("El servicio")
        return row

    return await db.run(p, work)


# ---------------------------------------------------------------- RF4 profesionales
@router.post("/profesionales", status_code=201, summary="RF4: alta de profesional ligado a un usuario con rol PROFESIONAL")
async def crear_profesional(body: ProfesionalIn, p: Principal = Depends(requiere("profesional.gestionar"))):
    async def work(tx: Tx):
        return await tx.one(
            "INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, nombre) "
            "VALUES (%(clinica_id)s, %(u)s, %(esp)s, %(nombre)s) "
            "RETURNING profesional_id, usuario_id, especialidad_id, nombre, activo",
            {"u": body.usuario_id, "esp": body.especialidad_id, "nombre": body.nombre},
        )

    return await db.run(p, work)


@router.get("/profesionales", summary="Profesionales de la clinica con los servicios que atienden")
async def listar_profesionales(p: Principal = Depends(requiere("catalogo.leer"))):
    async def work(tx: Tx):
        return await tx.fetch(
            "SELECT p.profesional_id, p.usuario_id, p.especialidad_id, p.nombre, p.activo, "
            "       COALESCE(array_agg(ps.servicio_id ORDER BY ps.servicio_id) "
            "                FILTER (WHERE ps.servicio_id IS NOT NULL), '{}') AS servicios "
            "  FROM profesional p "
            "  LEFT JOIN profesional_servicio ps ON ps.clinica_id = p.clinica_id AND ps.profesional_id = p.profesional_id "
            " WHERE p.clinica_id = %(clinica_id)s "
            " GROUP BY p.profesional_id ORDER BY p.profesional_id"
        )

    return await db.run(p, work)


@router.patch("/profesionales/{profesional_id}", summary="RF4: modificar profesional / baja logica")
async def actualizar_profesional(profesional_id: int, body: ProfesionalPatch, p: Principal = Depends(requiere("profesional.gestionar"))):
    campos = body.model_dump(exclude_none=True)
    if not campos:
        raise error(422, "SIN_CAMBIOS", "No hay campos para actualizar")
    set_sql, params = _sets(campos)

    async def work(tx: Tx):
        row = await tx.one(
            f"UPDATE profesional SET {set_sql} WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s "
            "RETURNING profesional_id, especialidad_id, nombre, activo",
            {**params, "pid": profesional_id},
        )
        if row is None:
            raise no_encontrado("El profesional")
        tx.tras_commit(lambda: cache.invalidar_profesional(tx.p.clinica_id, profesional_id))
        return row

    return await db.run(p, work)


@router.post("/profesionales/{profesional_id}/servicios", status_code=201, summary="RF4: habilita un servicio para el profesional")
async def asociar_servicio(profesional_id: int, body: ProfesionalServicioIn, p: Principal = Depends(requiere("profesional.gestionar"))):
    async def work(tx: Tx):
        await tx.execute(
            "INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id) "
            "VALUES (%(clinica_id)s, %(pid)s, %(sid)s)",
            {"pid": profesional_id, "sid": body.servicio_id},
        )
        tx.tras_commit(lambda: cache.invalidar_profesional(tx.p.clinica_id, profesional_id))
        return {"profesional_id": profesional_id, "servicio_id": body.servicio_id}

    return await db.run(p, work)


@router.delete("/profesionales/{profesional_id}/servicios/{servicio_id}", status_code=204, summary="RF4: retira un servicio del profesional")
async def desasociar_servicio(profesional_id: int, servicio_id: int, p: Principal = Depends(requiere("profesional.gestionar"))):
    async def work(tx: Tx):
        n = await tx.execute(
            "DELETE FROM profesional_servicio WHERE clinica_id = %(clinica_id)s "
            "AND profesional_id = %(pid)s AND servicio_id = %(sid)s",
            {"pid": profesional_id, "sid": servicio_id},
        )
        if n == 0:
            raise no_encontrado("La asociacion")
        tx.tras_commit(lambda: cache.invalidar_profesional(tx.p.clinica_id, profesional_id))

    await db.run(p, work)
