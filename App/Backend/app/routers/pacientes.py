"""RF14 y RF16: pacientes e historial. Los datos de contacto se auditan (RF18)."""
from fastapi import APIRouter, Depends, Query

from .. import db
from ..auth import requiere
from ..common import CITA_COLS, auditar, no_encontrado
from ..db import Principal, Tx
from ..schemas import PacienteIn, PacientePatch

router = APIRouter(prefix="/api/v1", tags=["pacientes"])

_COLS_COMPLETAS = "paciente_id, identificacion, nombre, apellidos, fecha_nacimiento, telefono, correo, activo, creado_en"
_CAMPOS_CONTACTO = {"telefono", "correo"}


@router.post("/pacientes", status_code=201, summary="RF14: registrar paciente")
async def crear_paciente(body: PacienteIn, p: Principal = Depends(requiere("paciente.escribir"))):
    async def work(tx: Tx):
        row = await tx.one(
            "INSERT INTO paciente (clinica_id, identificacion, nombre, apellidos, fecha_nacimiento, telefono, correo) "
            "VALUES (%(clinica_id)s, %(identificacion)s, %(nombre)s, %(apellidos)s, %(fecha_nacimiento)s, %(telefono)s, %(correo)s) "
            f"RETURNING {_COLS_COMPLETAS}",
            body.model_dump(),
        )
        await auditar(tx, "CREACION", "PACIENTE_CONTACTO", row["paciente_id"], row["paciente_id"])
        return row

    return await db.run(p, work)


@router.get("/pacientes", summary="RF14: busqueda de pacientes (sin datos de contacto)")
async def buscar_pacientes(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    p: Principal = Depends(requiere("paciente.leer")),
):
    # Nota: cualquier `clinica_id` que llegue como parametro de consulta se ignora: no esta declarado
    # y la clinica sale de la identidad.
    async def work(tx: Tx):
        patron = f"%{q}%" if q else None
        return await tx.fetch(
            "SELECT paciente_id, identificacion, nombre, apellidos, fecha_nacimiento, activo FROM paciente "
            "WHERE clinica_id = %(clinica_id)s "
            "  AND (%(q)s::text IS NULL OR apellidos ILIKE %(q)s OR nombre ILIKE %(q)s OR identificacion ILIKE %(q)s) "
            "ORDER BY apellidos, nombre LIMIT %(lim)s OFFSET %(off)s",
            {"q": patron, "lim": limit, "off": offset},
        )

    return await db.run(p, work)


@router.get("/pacientes/{paciente_id}", summary="RF14: detalle con datos de contacto (queda en la bitacora)")
async def obtener_paciente(paciente_id: int, p: Principal = Depends(requiere("paciente.leer"))):
    async def work(tx: Tx):
        row = await tx.one(
            f"SELECT {_COLS_COMPLETAS} FROM paciente WHERE clinica_id = %(clinica_id)s AND paciente_id = %(pid)s",
            {"pid": paciente_id},
        )
        if row is None:
            raise no_encontrado("El paciente")
        await auditar(tx, "LECTURA", "PACIENTE_CONTACTO", paciente_id, paciente_id)
        return row

    return await db.run(p, work)


@router.patch("/pacientes/{paciente_id}", summary="RF14: actualizar paciente")
async def actualizar_paciente(paciente_id: int, body: PacientePatch, p: Principal = Depends(requiere("paciente.escribir"))):
    campos = body.model_dump(exclude_unset=True)
    if not campos:
        from ..common import error

        raise error(422, "SIN_CAMBIOS", "No hay campos para actualizar")
    set_sql = ", ".join(f"{k} = %({k})s" for k in campos)  # nombres de columna: lista cerrada del modelo

    async def work(tx: Tx):
        row = await tx.one(
            f"UPDATE paciente SET {set_sql} WHERE clinica_id = %(clinica_id)s AND paciente_id = %(pid)s "
            f"RETURNING {_COLS_COMPLETAS}",
            {**campos, "pid": paciente_id},
        )
        if row is None:
            raise no_encontrado("El paciente")
        if _CAMPOS_CONTACTO & campos.keys():
            await auditar(tx, "ACTUALIZACION", "PACIENTE_CONTACTO", paciente_id, paciente_id)
        return row

    return await db.run(p, work)


@router.get("/pacientes/{paciente_id}/citas", summary="RF16: historial de citas del paciente con su estado")
async def historial_paciente(paciente_id: int, p: Principal = Depends(requiere("paciente.historial"))):
    async def work(tx: Tx):
        existe = await tx.one(
            "SELECT 1 AS ok FROM paciente WHERE clinica_id = %(clinica_id)s AND paciente_id = %(pid)s", {"pid": paciente_id}
        )
        if existe is None:
            raise no_encontrado("El paciente")
        return await tx.fetch(
            f"SELECT {CITA_COLS}, e.codigo AS estado FROM cita c "
            "JOIN estado_cita e ON e.estado_id = c.estado_id "
            "WHERE c.clinica_id = %(clinica_id)s AND c.paciente_id = %(pid)s ORDER BY c.inicio DESC",
            {"pid": paciente_id},
        )

    return await db.run(p, work)
