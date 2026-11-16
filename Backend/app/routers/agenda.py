"""RF5 a RF8: horarios, bloqueos y disponibilidad (con cache en Redis y control de permisos)."""
import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from .. import cache, db
from ..auth import requiere
from ..common import (
    ahora,
    error,
    exigir_profesional_propio,
    limites_dia,
    no_encontrado,
    zona_clinica,
)
from ..db import Principal, Tx
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
    p: Principal = Depends(requiere("horario.gestionar")),
):
    async def work(tx: Tx):
        await exigir_profesional_propio(tx, profesional_id)
        row = await tx.one(
            "INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin) "
            "VALUES (%(clinica_id)s, %(pid)s, %(d)s, %(hi)s, %(hf)s) "
            "RETURNING horario_id, profesional_id, dia_semana, hora_inicio, hora_fin",
            {
                "pid": profesional_id,
                "d": body.dia_semana,
                "hi": body.hora_inicio,
                "hf": body.hora_fin,
            },
        )
        tx.tras_commit(lambda: cache.invalidar_profesional(tx.p.clinica_id, profesional_id))
        return row

    return await db.run(p, work)


@router.get(
    "/profesionales/{profesional_id}/horarios",
    summary="Horario semanal del profesional",
)
async def listar_horarios(
    profesional_id: int,
    p: Principal = Depends(requiere("agenda.leer_config")),
):
    async def work(tx: Tx):
        return await tx.fetch(
            "SELECT horario_id, dia_semana, hora_inicio, hora_fin "
            "  FROM horario_atencion "
            " WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s "
            " ORDER BY dia_semana, hora_inicio",
            {"pid": profesional_id},
        )

    return await db.run(p, work)


@router.delete(
    "/horarios/{horario_id}",
    status_code=204,
    summary="RF5: elimina un bloque semanal",
)
async def eliminar_horario(
    horario_id: int,
    p: Principal = Depends(requiere("horario.gestionar")),
):
    async def work(tx: Tx):
        actual = await tx.one(
            "SELECT profesional_id FROM horario_atencion "
            "WHERE clinica_id = %(clinica_id)s AND horario_id = %(h)s FOR UPDATE",
            {"h": horario_id},
        )
        if actual is None:
            raise no_encontrado("El horario")
        await exigir_profesional_propio(tx, actual["profesional_id"])
        await tx.execute(
            "DELETE FROM horario_atencion WHERE clinica_id = %(clinica_id)s AND horario_id = %(h)s",
            {"h": horario_id},
        )
        pid = actual["profesional_id"]
        tx.tras_commit(lambda: cache.invalidar_profesional(tx.p.clinica_id, pid))

    await db.run(p, work)


# ---------------------------------------------------------------- RF6 bloqueos
@router.post(
    "/profesionales/{profesional_id}/bloqueos",
    status_code=201,
    summary="RF6: registra un bloqueo y lista las citas en conflicto",
)
async def crear_bloqueo(
    profesional_id: int,
    body: BloqueoIn,
    p: Principal = Depends(requiere("bloqueo.gestionar")),
):
    async def work(tx: Tx):
        await exigir_profesional_propio(tx, profesional_id)
        row = await tx.one(
            "INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo, creado_por) "
            "VALUES (%(clinica_id)s, %(pid)s, %(i)s, %(f)s, %(m)s, %(u)s) "
            "RETURNING bloqueo_id, profesional_id, inicio, fin, motivo",
            {
                "pid": profesional_id,
                "i": body.inicio,
                "f": body.fin,
                "m": body.motivo,
                "u": tx.p.usuario_id,
            },
        )
        # El bloqueo no cancela citas; devuelve las ya reservadas en conflicto para reprogramar
        conflictos = await tx.fetch(
            _CONFLICTOS_SQL,
            {"pid": profesional_id, "i": body.inicio, "f": body.fin},
        )
        tx.tras_commit(lambda: cache.invalidar_profesional(tx.p.clinica_id, profesional_id))
        return {**row, "conflictos": conflictos}

    return await db.run(p, work)


@router.get(
    "/profesionales/{profesional_id}/bloqueos",
    summary="Bloqueos del profesional",
)
async def listar_bloqueos(
    profesional_id: int,
    p: Principal = Depends(requiere("agenda.leer_config")),
):
    async def work(tx: Tx):
        return await tx.fetch(
            "SELECT bloqueo_id, inicio, fin, motivo "
            "  FROM bloqueo_agenda "
            " WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s "
            " ORDER BY inicio",
            {"pid": profesional_id},
        )

    return await db.run(p, work)


@router.get(
    "/bloqueos/{bloqueo_id}/conflictos",
    summary="RF6: citas vigentes que caen dentro del bloqueo",
)
async def conflictos_bloqueo(
    bloqueo_id: int,
    p: Principal = Depends(requiere("agenda.leer_config")),
):
    async def work(tx: Tx):
        b = await tx.one(
            "SELECT profesional_id, inicio, fin FROM bloqueo_agenda "
            "WHERE clinica_id = %(clinica_id)s AND bloqueo_id = %(b)s",
            {"b": bloqueo_id},
        )
        if b is None:
            raise no_encontrado("El bloqueo")
        return await tx.fetch(
            _CONFLICTOS_SQL,
            {"pid": b["profesional_id"], "i": b["inicio"], "f": b["fin"]},
        )

    return await db.run(p, work)


@router.delete(
    "/bloqueos/{bloqueo_id}",
    status_code=204,
    summary="Elimina un bloqueo",
)
async def eliminar_bloqueo(
    bloqueo_id: int,
    p: Principal = Depends(requiere("bloqueo.gestionar")),
):
    async def work(tx: Tx):
        actual = await tx.one(
            "SELECT profesional_id FROM bloqueo_agenda "
            "WHERE clinica_id = %(clinica_id)s AND bloqueo_id = %(b)s FOR UPDATE",
            {"b": bloqueo_id},
        )
        if actual is None:
            raise no_encontrado("El bloqueo")
        await exigir_profesional_propio(tx, actual["profesional_id"])
        await tx.execute(
            "DELETE FROM bloqueo_agenda WHERE clinica_id = %(clinica_id)s AND bloqueo_id = %(b)s",
            {"b": bloqueo_id},
        )
        pid = actual["profesional_id"]
        tx.tras_commit(lambda: cache.invalidar_profesional(tx.p.clinica_id, pid))

    await db.run(p, work)


# ---------------------------------------------------------------- RF7 / RF8 disponibilidad
async def _espacios_profesional(
    p: Principal,
    profesional_id: int,
    fecha: date,
    servicio_id: int,
    ahora_utc: datetime,
) -> list[dict]:
    assert p.clinica_id is not None
    # 1) Leer versiones y buscar en Redis ANTES de consultar PostgreSQL (I8)
    cacheado, clave = await cache.leer(p.clinica_id, profesional_id, fecha.isoformat(), servicio_id)

    if cacheado is None:
        async def work(tx: Tx):
            tz = await zona_clinica(tx)
            prof = await tx.one(
                "SELECT activo FROM profesional WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s",
                {"pid": profesional_id},
            )
            if prof is None:
                raise no_encontrado("El profesional")

            serv = await tx.one(
                "SELECT s.duracion_min, s.activo "
                "  FROM servicio s "
                "  JOIN profesional_servicio ps "
                "    ON ps.clinica_id = s.clinica_id AND ps.servicio_id = s.servicio_id "
                " WHERE s.clinica_id = %(clinica_id)s "
                "   AND s.servicio_id = %(sid)s "
                "   AND ps.profesional_id = %(pid)s",
                {"sid": servicio_id, "pid": profesional_id},
            )
            if serv is None:
                raise error(422, "SERVICIO_NO_HABILITADO", "El profesional no atiende ese servicio en esta clinica")

            if not prof["activo"] or not serv["activo"]:
                return []

            ini_dia, fin_dia = limites_dia(fecha, tz)

            bloques = await tx.fetch(
                "SELECT hora_inicio, hora_fin "
                "  FROM horario_atencion "
                " WHERE clinica_id = %(clinica_id)s "
                "   AND profesional_id = %(pid)s "
                "   AND dia_semana = %(dow)s "
                " ORDER BY hora_inicio",
                {"pid": profesional_id, "dow": fecha.isoweekday()},
            )

            ocupados = await tx.fetch(
                "SELECT inicio, fin "
                "  FROM cita "
                " WHERE clinica_id = %(clinica_id)s "
                "   AND profesional_id = %(pid)s "
                "   AND estado_id = 1 "
                "   AND inicio < %(fd)s AND fin > %(id)s",
                {"pid": profesional_id, "id": ini_dia, "fd": fin_dia},
            )

            bloqueos = await tx.fetch(
                "SELECT inicio, fin "
                "  FROM bloqueo_agenda "
                " WHERE clinica_id = %(clinica_id)s "
                "   AND profesional_id = %(pid)s "
                "   AND tstzrange(inicio, fin) && tstzrange(%(id)s, %(fd)s)",
                {"pid": profesional_id, "id": ini_dia, "fd": fin_dia},
            )

            return _calcular_slots(
                fecha=fecha,
                tz=tz,
                bloques=[(b["hora_inicio"], b["hora_fin"]) for b in bloques],
                duracion_min=serv["duracion_min"],
                ocupados=[(o["inicio"], o["fin"]) for o in ocupados],
                bloqueos=[(b["inicio"], b["fin"]) for b in bloqueos],
                ahora_utc=datetime(1970, 1, 1, tzinfo=timezone.utc),
                paso_min=_SLOT_STEP_MIN,
            )

        cacheado = await db.run(p, work)
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
    p: Principal = Depends(requiere("disponibilidad.consultar")),
):
    espacios = await _espacios_profesional(
        p=p,
        profesional_id=profesional_id,
        fecha=fecha,
        servicio_id=servicio_id,
        ahora_utc=ahora(),
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
    p: Principal = Depends(requiere("disponibilidad.consultar")),
):
    if hasta < desde:
        raise error(422, "RANGO_INVALIDO", "'hasta' debe ser mayor o igual que 'desde'")
    if (hasta - desde).days > 30:
        raise error(422, "RANGO_EXCESIVO", "El rango maximo es de 31 dias")

    ahora_utc = ahora()

    async def obtener_candidatos(tx: Tx):
        return await tx.fetch(
            "SELECT p.profesional_id, p.nombre "
            "  FROM profesional p "
            "  JOIN profesional_servicio ps "
            "    ON ps.clinica_id = p.clinica_id AND ps.profesional_id = p.profesional_id "
            " WHERE p.clinica_id = %(clinica_id)s "
            "   AND p.activo "
            "   AND ps.servicio_id = %(sid)s "
            " ORDER BY p.profesional_id",
            {"sid": servicio_id},
        )

    candidatos = await db.run(p, obtener_candidatos)

    resultado = []
    for prof in candidatos:
        dias = []
        d = desde
        while d <= hasta:
            espacios = await _espacios_profesional(
                p=p,
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