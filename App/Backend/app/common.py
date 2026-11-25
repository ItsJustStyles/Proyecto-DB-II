"""Utilidades compartidas por los routers."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from .db import Tx

ESTADO_RESERVADA, ESTADO_ATENDIDA, ESTADO_AUSENTE, ESTADO_CANCELADA, ESTADO_REPROGRAMADA = 1, 2, 3, 4, 5
ESTADO_POR_NOMBRE = {"ATENDIDA": ESTADO_ATENDIDA, "AUSENTE": ESTADO_AUSENTE}

CITA_COLS = (
    "c.cita_id, c.paciente_id, c.profesional_id, c.servicio_id, c.inicio, c.fin, "
    "c.estado_id, c.cita_origen_id, c.creada_por, c.cancelada_por, c.motivo_cancelacion, "
    "c.desenlace_registrado_por, c.creada_en, c.actualizada_en"
)


def error(status: int, codigo: str, mensaje: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"codigo": codigo, "mensaje": mensaje})


def no_encontrado(recurso: str) -> HTTPException:
    return error(404, "NO_ENCONTRADO", f"{recurso} no existe en esta clinica")


async def zona_clinica(tx: Tx) -> ZoneInfo:
    row = await tx.one("SELECT zona_horaria FROM clinica WHERE clinica_id = %(clinica_id)s")
    return ZoneInfo(row["zona_horaria"] if row else "UTC")


def limites_dia(fecha: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    ini = datetime.combine(fecha, time.min, tzinfo=tz)
    fin = datetime.combine(fecha + timedelta(days=1), time.min, tzinfo=tz)
    return ini, fin


def fecha_local(instante: datetime, tz: ZoneInfo) -> date:
    return instante.astimezone(tz).date()


def ahora() -> datetime:
    return datetime.now(timezone.utc)


async def mi_profesional_id(tx: Tx) -> int | None:
    """profesional_id del usuario autenticado (solo tiene sentido para el rol PROFESIONAL)."""
    row = await tx.one(
        "SELECT profesional_id FROM profesional WHERE clinica_id = %(clinica_id)s AND usuario_id = %(u)s",
        {"u": tx.p.usuario_id},
    )
    return row["profesional_id"] if row else None


async def exigir_profesional_propio(tx: Tx, profesional_id: int) -> None:
    """El rol PROFESIONAL solo opera sobre su propio profesional ("solo los propios" de la matriz).

    Sin RLS el motor no distingue filas propias, asi que esta restriccion vive en la capa de acceso.
    """
    if tx.p.rol == "PROFESIONAL" and await mi_profesional_id(tx) != profesional_id:
        raise error(403, "SIN_PERMISO", "Solo puede operar sobre sus propios datos")


async def auditar(tx: Tx, accion: str, entidad: str, entidad_id: int, paciente_id: int) -> None:
    """RF18: registro append-only dentro de la MISMA transaccion que el acceso."""
    await tx.execute(
        "INSERT INTO bitacora_auditoria (clinica_id, usuario_id, paciente_id, accion, entidad, entidad_id) "
        "VALUES (%(clinica_id)s, %(u)s, %(pac)s, %(a)s, %(e)s, %(eid)s)",
        {"u": tx.p.usuario_id, "pac": paciente_id, "a": accion, "e": entidad, "eid": entidad_id},
    )
