"""
RF15: nota clinica. Solo la escribe y lee el profesional que atendio la cita; toda lectura y
escritura queda en la bitacora (RF18) dentro de la misma transaccion."""
from fastapi import APIRouter, Depends

from .. import db
from ..auth import requiere
from ..common import auditar, error, mi_profesional_id, no_encontrado
from ..db import Principal, Tx
from ..schemas import NotaIn

router = APIRouter(prefix="/api/v1", tags=["notas clinicas"])


async def _cita_propia(tx: Tx, cita_id: int) -> dict:
    cita = await tx.one(
        "SELECT cita_id, paciente_id, profesional_id, estado_id FROM cita "
        "WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s",
        {"c": cita_id},
    )
    if cita is None:
        raise no_encontrado("La cita")
    if await mi_profesional_id(tx) != cita["profesional_id"]:
        raise error(403, "SIN_PERMISO", "Solo puede acceder a notas de sus propias citas")
    return cita


@router.post("/citas/{cita_id}/nota", status_code=201, summary="RF15: adjuntar nota a una cita atendida")
async def crear_nota(cita_id: int, body: NotaIn, p: Principal = Depends(requiere("nota.escribir"))):
    async def work(tx: Tx):
        cita = await _cita_propia(tx, cita_id)
        if cita["estado_id"] != 2:
            raise error(409, "CITA_NO_ATENDIDA", "La nota solo se adjunta a una cita atendida")
        row = await tx.one(
            "INSERT INTO nota_clinica (clinica_id, cita_id, profesional_id, contenido) "
            "VALUES (%(clinica_id)s, %(c)s, %(pid)s, %(t)s) "
            "RETURNING nota_id, cita_id, profesional_id, contenido, creada_en, actualizada_en",
            {"c": cita_id, "pid": cita["profesional_id"], "t": body.contenido},
        )
        await auditar(tx, "CREACION", "NOTA_CLINICA", row["nota_id"], cita["paciente_id"])
        return row

    return await db.run(p, work)


@router.put("/citas/{cita_id}/nota", summary="RF15: editar el contenido de la nota")
async def actualizar_nota(cita_id: int, body: NotaIn, p: Principal = Depends(requiere("nota.escribir"))):
    async def work(tx: Tx):
        cita = await _cita_propia(tx, cita_id)
        row = await tx.one(
            "UPDATE nota_clinica SET contenido = %(t)s WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s "
            "RETURNING nota_id, cita_id, profesional_id, contenido, creada_en, actualizada_en",
            {"t": body.contenido, "c": cita_id},
        )
        if row is None:
            raise no_encontrado("La nota")
        await auditar(tx, "ACTUALIZACION", "NOTA_CLINICA", row["nota_id"], cita["paciente_id"])
        return row

    return await db.run(p, work)


@router.get("/citas/{cita_id}/nota", summary="RF15: leer la nota (queda en la bitacora)")
async def leer_nota(cita_id: int, p: Principal = Depends(requiere("nota.leer"))):
    async def work(tx: Tx):
        cita = await _cita_propia(tx, cita_id)
        row = await tx.one(
            "SELECT nota_id, cita_id, profesional_id, contenido, creada_en, actualizada_en FROM nota_clinica "
            "WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s",
            {"c": cita_id},
        )
        if row is None:
            raise no_encontrado("La nota")
        await auditar(tx, "LECTURA", "NOTA_CLINICA", row["nota_id"], cita["paciente_id"])
        return row

    return await db.run(p, work)
