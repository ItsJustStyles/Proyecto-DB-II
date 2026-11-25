"""
RF9 a RF13, RF20 y RF21: ciclo de vida de la cita.

Reserva (RF9): un INSERT en una transaccion. La carrera por el ultimo espacio la decide la
exclusion constraint ex_cita_profesional_sin_solape (I1): la transaccion que llega segunda
espera al commit de la primera y recibe 23P01, que la API responde como 409 ESPACIO_TOMADO.
No hay "SELECT para verificar y luego INSERT": esa comprobacion previa seria una carrera.

Reprogramacion (RF10): en UNA transaccion, bloquea la cita vigente (SELECT ... FOR UPDATE),
la pasa a REPROGRAMADA e inserta la nueva. Si la insercion falla, todo se revierte y la cita
original sigue vigente; nunca queda duplicada ni con los dos espacios ocupados.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query

from .. import cache, db
from ..auth import requiere
from ..common import (
    CITA_COLS,
    ESTADO_CANCELADA,
    ESTADO_POR_NOMBRE,
    ESTADO_REPROGRAMADA,
    ahora,
    error,
    exigir_profesional_propio,
    fecha_local,
    limites_dia,
    mi_profesional_id,
    no_encontrado,
    zona_clinica,
)
from ..db import Principal, Tx
from ..schemas import CancelarIn, CitaIn, DesenlaceIn, ReprogramarIn

router = APIRouter(prefix="/api/v1", tags=["citas"])


def _invalidar(tx: Tx, profesional_id: int, *instantes_y_tz: tuple[datetime, "object"]) -> None:
    """Registra la invalidacion de las agendas afectadas para DESPUES del commit."""
    for instante, tz in instantes_y_tz:
        f = fecha_local(instante, tz).isoformat()
        tx.tras_commit(lambda f=f: cache.invalidar_dia(tx.p.clinica_id, profesional_id, f))


# ---------------------------------------------------------------- RF9 reservar
@router.post("/citas", status_code=201, summary="RF9: reservar una cita (201 concedida, 409 espacio tomado, 422 invalida)")
async def reservar(body: CitaIn, p: Principal = Depends(requiere("cita.operar"))):
    if body.inicio <= ahora():
        raise error(422, "CITA_INVALIDA", "La cita debe iniciar en el futuro")

    async def work(tx: Tx):
        tz = await zona_clinica(tx)
        # `fin` lo calcula el trigger a partir de la duracion del servicio (I4); el valor enviado es de relleno.
        row = await tx.one(
            "INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, creada_por) "
            "VALUES (%(clinica_id)s, %(pac)s, %(pid)s, %(sid)s, %(i)s, %(i)s, %(u)s) "
            f"RETURNING {CITA_COLS.replace('c.', '')}",
            {"pac": body.paciente_id, "pid": body.profesional_id, "sid": body.servicio_id, "i": body.inicio, "u": tx.p.usuario_id},
        )
        _invalidar(tx, body.profesional_id, (row["inicio"], tz))
        return row

    return await db.run(p, work)


# ---------------------------------------------------------------- RF10 reprogramar
@router.post("/citas/{cita_id}/reprogramar", status_code=201, summary="RF10: reprogramar una cita vigente a otro espacio")
async def reprogramar(cita_id: int, body: ReprogramarIn, p: Principal = Depends(requiere("cita.operar"))):
    if body.inicio <= ahora():
        raise error(422, "CITA_INVALIDA", "La nueva cita debe iniciar en el futuro")

    async def work(tx: Tx):
        tz = await zona_clinica(tx)
        vieja = await tx.one(
            "SELECT cita_id, paciente_id, profesional_id, servicio_id, inicio, estado_id FROM cita "
            "WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s FOR UPDATE",
            {"c": cita_id},
        )
        if vieja is None:
            raise no_encontrado("La cita")
        if vieja["estado_id"] != 1:
            raise error(409, "TRANSICION_INVALIDA", "Solo una cita vigente puede reprogramarse")
        nuevo_prof = body.profesional_id or vieja["profesional_id"]
        # 1) la vieja pasa a REPROGRAMADA (libera el espacio dentro de la misma transaccion)
        await tx.execute(
            "UPDATE cita SET estado_id = %(e)s WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s",
            {"e": ESTADO_REPROGRAMADA, "c": cita_id},
        )
        # 2) se inserta la nueva; si el espacio esta tomado, 23P01 revierte TODO
        nueva = await tx.one(
            "INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, cita_origen_id, creada_por) "
            "VALUES (%(clinica_id)s, %(pac)s, %(pid)s, %(sid)s, %(i)s, %(i)s, %(orig)s, %(u)s) "
            f"RETURNING {CITA_COLS.replace('c.', '')}",
            {
                "pac": vieja["paciente_id"],
                "pid": nuevo_prof,
                "sid": vieja["servicio_id"],
                "i": body.inicio,
                "orig": cita_id,
                "u": tx.p.usuario_id,
            },
        )
        _invalidar(tx, vieja["profesional_id"], (vieja["inicio"], tz))  # I7: el espacio liberado
        _invalidar(tx, nuevo_prof, (nueva["inicio"], tz))
        return nueva

    return await db.run(p, work)


# ---------------------------------------------------------------- RF11 cancelar
@router.post("/citas/{cita_id}/cancelar", summary="RF11: cancelar una cita vigente (registra motivo y usuario)")
async def cancelar(cita_id: int, body: CancelarIn, p: Principal = Depends(requiere("cita.operar"))):
    async def work(tx: Tx):
        tz = await zona_clinica(tx)
        actual = await tx.one(
            "SELECT profesional_id, inicio, estado_id FROM cita "
            "WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s FOR UPDATE",
            {"c": cita_id},
        )
        if actual is None:
            raise no_encontrado("La cita")
        # El trigger de transicion deja pasar "mismo estado -> mismo estado"; aqui se exige vigente (RF13).
        if actual["estado_id"] != 1:
            raise error(409, "TRANSICION_INVALIDA", "Una cita en estado final no admite cambios de estado")
        row = await tx.one(
            "UPDATE cita SET estado_id = %(e)s, cancelada_por = %(u)s, motivo_cancelacion = %(m)s "
            "WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s "
            f"RETURNING {CITA_COLS.replace('c.', '')}",
            {"e": ESTADO_CANCELADA, "u": tx.p.usuario_id, "m": body.motivo, "c": cita_id},
        )
        _invalidar(tx, actual["profesional_id"], (actual["inicio"], tz))  # I7
        return row

    return await db.run(p, work)


# ---------------------------------------------------------------- RF12 desenlace
@router.post("/citas/{cita_id}/desenlace", summary="RF12: registrar atendida o ausente (solo pasada la hora de inicio)")
async def desenlace(cita_id: int, body: DesenlaceIn, p: Principal = Depends(requiere("cita.desenlace"))):
    async def work(tx: Tx):
        tz = await zona_clinica(tx)
        actual = await tx.one(
            "SELECT profesional_id, inicio, estado_id FROM cita "
            "WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s FOR UPDATE",
            {"c": cita_id},
        )
        if actual is None:
            raise no_encontrado("La cita")
        await exigir_profesional_propio(tx, actual["profesional_id"])
        if actual["estado_id"] != 1:
            raise error(409, "TRANSICION_INVALIDA", "Una cita en estado final no admite cambios de estado")
        row = await tx.one(
            "UPDATE cita SET estado_id = %(e)s, desenlace_registrado_por = %(u)s "
            "WHERE clinica_id = %(clinica_id)s AND cita_id = %(c)s "
            f"RETURNING {CITA_COLS.replace('c.', '')}",
            {"e": ESTADO_POR_NOMBRE[body.resultado], "u": tx.p.usuario_id, "c": cita_id},
        )
        _invalidar(tx, actual["profesional_id"], (actual["inicio"], tz))
        return row

    return await db.run(p, work)


@router.get("/citas/{cita_id}", summary="Detalle de una cita de la clinica")
async def obtener_cita(cita_id: int, p: Principal = Depends(requiere("agenda.dia"))):
    async def work(tx: Tx):
        row = await tx.one(
            f"SELECT {CITA_COLS} FROM cita c WHERE c.clinica_id = %(clinica_id)s AND c.cita_id = %(c)s", {"c": cita_id}
        )
        if row is None:
            raise no_encontrado("La cita")
        if tx.p.rol == "PROFESIONAL" and await mi_profesional_id(tx) != row["profesional_id"]:
            raise no_encontrado("La cita")  # no se revela la existencia de citas ajenas
        return row

    return await db.run(p, work)


# ---------------------------------------------------------------- RF20 agenda del dia
@router.get("/agenda", summary="RF20: agenda del dia (de un profesional o de toda la clinica)")
async def agenda_del_dia(
    fecha: date,
    profesional_id: int | None = Query(default=None),
    p: Principal = Depends(requiere("agenda.dia")),
):
    async def work(tx: Tx):
        tz = await zona_clinica(tx)
        ini, fin = limites_dia(fecha, tz)
        filtro_prof = profesional_id
        if tx.p.rol == "PROFESIONAL":
            propio = await mi_profesional_id(tx)
            if profesional_id is not None and profesional_id != propio:
                raise error(403, "SIN_PERMISO", "Solo puede consultar su propia agenda")
            filtro_prof = propio  # el profesional siempre ve solo la suya
        return await tx.fetch(
            "SELECT c.cita_id, c.profesional_id, c.paciente_id, c.servicio_id, c.inicio, c.fin, c.estado_id, "
            "       pa.nombre || ' ' || pa.apellidos AS paciente "
            "  FROM cita c "
            "  JOIN paciente pa ON pa.clinica_id = c.clinica_id AND pa.paciente_id = c.paciente_id "
            " WHERE c.clinica_id = %(clinica_id)s AND c.inicio >= %(i)s AND c.inicio < %(f)s "
            "   AND (%(pid)s::bigint IS NULL OR c.profesional_id = %(pid)s::bigint) "
            " ORDER BY c.inicio, c.profesional_id",
            {"i": ini, "f": fin, "pid": filtro_prof},
        )

    return await db.run(p, work)


# ---------------------------------------------------------------- RF21 conteo por estado
@router.get("/citas/conteo/por-estado", summary="RF21: conteo de citas por estado en un rango de fechas")
async def conteo_por_estado(desde: date, hasta: date, p: Principal = Depends(requiere("cita.conteo"))):
    if hasta < desde:
        raise error(422, "RANGO_INVALIDO", "'hasta' debe ser mayor o igual que 'desde'")

    async def work(tx: Tx):
        tz = await zona_clinica(tx)
        ini, _ = limites_dia(desde, tz)
        _, fin = limites_dia(hasta, tz)
        return await tx.fetch(
            "SELECT e.codigo AS estado, count(c.cita_id) AS total "
            "  FROM estado_cita e "
            "  LEFT JOIN cita c ON c.estado_id = e.estado_id AND c.clinica_id = %(clinica_id)s "
            "                  AND c.inicio >= %(i)s AND c.inicio < %(f)s "
            " GROUP BY e.estado_id, e.codigo ORDER BY e.estado_id",
            {"i": ini, "f": fin},
        )

    return await db.run(p, work)
