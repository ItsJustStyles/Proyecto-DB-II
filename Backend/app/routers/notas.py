"""RF15: nota clinica. Solo la escribe y lee el profesional que atendio la cita; toda lectura y
escritura queda en la bitacora (RF18) dentro de la misma transaccion."""
from fastapi import APIRouter, Header, HTTPException
from psycopg import errors as pgerr

from .. import db
from ..schemas import NotaIn

router = APIRouter(prefix="/api/v1", tags=["notas clinicas"])

_NOTA_COLS = "nota_id, cita_id, profesional_id, contenido, creada_en, actualizada_en"


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
    entidad_id: int,
) -> None:
    await cur.execute(
        """
        INSERT INTO bitacora_auditoria (clinica_id, usuario_id, paciente_id, accion, entidad, entidad_id)
        VALUES (%(clinica_id)s, %(usuario_id)s, %(paciente_id)s, %(accion)s, 'NOTA_CLINICA', %(entidad_id)s)
        """,
        {
            "clinica_id": clinica_id,
            "usuario_id": usuario_id,
            "paciente_id": paciente_id,
            "accion": accion,
            "entidad_id": entidad_id,
        },
    )


async def _cita_propia(cur, clinica_id: int, usuario_id: int, cita_id: int) -> dict:
    await cur.execute(
        """
        SELECT cita_id, paciente_id, profesional_id, estado_id
          FROM cita
         WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s
        """,
        {"clinica_id": clinica_id, "c": cita_id},
    )
    cita = await cur.fetchone()
    if cita is None:
        raise _error(404, "NO_ENCONTRADO", "La cita no existe en esta clinica")

    await cur.execute(
        """
        SELECT profesional_id
          FROM profesional
         WHERE clinica_id = %(clinica_id)s AND usuario_id = %(uid)s
        """,
        {"clinica_id": clinica_id, "uid": usuario_id},
    )
    prof = await cur.fetchone()
    if prof is None or prof["profesional_id"] != cita["profesional_id"]:
        raise _error(403, "SIN_PERMISO", "Solo puede acceder a notas de sus propias citas")

    return cita


@router.post("/citas/{cita_id}/nota", status_code=201, summary="RF15: adjuntar nota a una cita atendida")
async def crear_nota(
    cita_id: int,
    body: NotaIn,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    usuario_id: int = Header(..., alias="X-Usuario-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    try:
        async with db.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    cita = await _cita_propia(cur, clinica_id, usuario_id, cita_id)
                    if cita["estado_id"] != 2:
                        raise _error(409, "CITA_NO_ATENDIDA", "La nota solo se adjunta a una cita atendida")

                    await cur.execute(
                        f"""
                        INSERT INTO nota_clinica (clinica_id, cita_id, profesional_id, contenido)
                        VALUES (%(clinica_id)s, %(c)s, %(pid)s, %(t)s)
                        RETURNING {_NOTA_COLS}
                        """,
                        {
                            "clinica_id": clinica_id,
                            "c": cita_id,
                            "pid": cita["profesional_id"],
                            "t": body.contenido,
                        },
                    )
                    row = await cur.fetchone()
                    await _auditar(
                        cur,
                        clinica_id=clinica_id,
                        usuario_id=usuario_id,
                        paciente_id=cita["paciente_id"],
                        accion="CREACION",
                        entidad_id=row["nota_id"],
                    )
                    return row
    except pgerr.UniqueViolation:
        raise _error(409, "NOTA_EXISTENTE", "Esta cita ya tiene una nota clinica adjunta")
    except pgerr.CheckViolation:
        raise _error(409, "CITA_NO_ATENDIDA", "La nota solo se adjunta a una cita atendida")


@router.put("/citas/{cita_id}/nota", summary="RF15: editar el contenido de la nota")
async def actualizar_nota(
    cita_id: int,
    body: NotaIn,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    usuario_id: int = Header(..., alias="X-Usuario-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                cita = await _cita_propia(cur, clinica_id, usuario_id, cita_id)
                await cur.execute(
                    f"""
                    UPDATE nota_clinica
                       SET contenido = %(t)s
                     WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s
                     RETURNING {_NOTA_COLS}
                    """,
                    {"t": body.contenido, "clinica_id": clinica_id, "c": cita_id},
                )
                row = await cur.fetchone()
                if row is None:
                    raise _error(404, "NO_ENCONTRADO", "La nota clinica no existe")

                await _auditar(
                    cur,
                    clinica_id=clinica_id,
                    usuario_id=usuario_id,
                    paciente_id=cita["paciente_id"],
                    accion="ACTUALIZACION",
                    entidad_id=row["nota_id"],
                )
                return row


@router.get("/citas/{cita_id}/nota", summary="RF15: leer la nota (queda en la bitacora)")
async def leer_nota(
    cita_id: int,
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    usuario_id: int = Header(..., alias="X-Usuario-Id", description="Temporal mientras se integra Keycloak"),
):
    if db.pool is None:
        raise _error(503, "DB_NO_DISPONIBLE", "Pool de base de datos no disponible")

    async with db.pool.connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                cita = await _cita_propia(cur, clinica_id, usuario_id, cita_id)
                await cur.execute(
                    f"""
                    SELECT {_NOTA_COLS}
                      FROM nota_clinica
                     WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s
                    """,
                    {"clinica_id": clinica_id, "c": cita_id},
                )
                row = await cur.fetchone()
                if row is None:
                    raise _error(404, "NO_ENCONTRADO", "La nota clinica no existe")

                await _auditar(
                    cur,
                    clinica_id=clinica_id,
                    usuario_id=usuario_id,
                    paciente_id=cita["paciente_id"],
                    accion="LECTURA",
                    entidad_id=row["nota_id"],
                )
                return row