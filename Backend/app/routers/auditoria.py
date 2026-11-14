"""RF19: consulta de la bitacora (solo administrador de clinica). La bitacora es append-only:
no existen rutas de modificacion ni borrado, y el motor tampoco las permite (I6)."""
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Query

from .. import db

router = APIRouter(prefix="/api/v1", tags=["auditoria"])


@router.get(
    "/bitacora",
    summary="RF19: bitacora de auditoria con filtros por usuario, paciente y fechas",
)
async def consultar_bitacora(
    clinica_id: int = Header(..., alias="X-Clinica-Id", description="Temporal mientras se integra Keycloak"),
    usuario_id: int | None = None,
    paciente_id: int | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Pool de base de datos no disponible")

    query = """
        SELECT bitacora_id, usuario_id, paciente_id, accion, entidad, entidad_id, ocurrido_en
          FROM bitacora_auditoria
         WHERE clinica_id = %(clinica_id)s
           AND (%(u)s::bigint IS NULL OR usuario_id = %(u)s::bigint)
           AND (%(pa)s::bigint IS NULL OR paciente_id = %(pa)s::bigint)
           AND (%(d)s::timestamptz IS NULL OR ocurrido_en >= %(d)s::timestamptz)
           AND (%(h)s::timestamptz IS NULL OR ocurrido_en <= %(h)s::timestamptz)
         ORDER BY ocurrido_en DESC, bitacora_id DESC
         LIMIT %(lim)s OFFSET %(off)s
    """
    params = {
        "clinica_id": clinica_id,
        "u": usuario_id,
        "pa": paciente_id,
        "d": desde,
        "h": hasta,
        "lim": limit,
        "off": offset,
    }

    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchall()