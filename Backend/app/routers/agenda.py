"""RF5 a RF8: horarios, bloqueos y disponibilidad (con cache en Redis)."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query

from .. import cache, db
from ..auth import requiere
from ..common import ahora, error, exigir_profesional_propio, limites_dia, no_encontrado, zona_clinica
from ..config import settings
from ..db import Principal, Tx
from ..schemas import BloqueoIn, HorarioIn
from ..slots import calcular_slots

router = APIRouter(prefix="/api/v1", tags=["agenda"])


# ---------------------------------------------------------------- RF5 horarios
@router.post("/profesionales/{profesional_id}/horarios", status_code=201, summary="RF5: agrega un bloque semanal de atencion")
async def crear_horario(profesional_id: int, body: HorarioIn, p: Principal = Depends(requiere("horario.gestionar"))):
    async def work(tx: Tx):
        await exigir_profesional_propio(tx, profesional_id)
        row = await tx.one(
            "INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin) "
            "VALUES (%(clinica_id)s, %(pid)s, %(d)s, %(hi)s, %(hf)s) "
            "RETURNING horario_id, profesional_id, dia_semana, hora_inicio, hora_fin",
            {"pid": profesional_id, "d": body.dia_semana, "hi": body.hora_inicio, "hf": body.hora_fin},
        )
        tx.tras_commit(lambda: cache.invalidar_profesional(tx.p.clinica_id, profesional_id))
        return row

    return await db.run(p, work)


@router.get("/profesionales/{profesional_id}/horarios", summary="Horario semanal del profesional")
async def listar_horarios(profesional_id: int, p: Principal = Depends(requiere("agenda.leer_config"))):
    async def work(tx: Tx):
        return await tx.fetch(
            "SELECT horario_id, dia_semana, hora_inicio, hora_fin FROM horario_atencion "
            "WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s ORDER BY dia_semana, hora_inicio",
            {"pid": profesional_id},
        )

    return await db.run(p, work)


@router.delete("/horarios/{horario_id}", status_code=204, summary="RF5: elimina un bloque semanal")
async def eliminar_horario(horario_id: int, p: Principal = Depends(requiere("horario.gestionar"))):
    async def work(tx: Tx):
        h = await tx.one(
            "SELECT profesional_id FROM horario_atencion WHERE clinica_id = %(clinica_id)s AND horario_id = %(h)s",
            {"h": horario_id},
        )
        if h is None:
            raise no_encontrado("El horario")
        await exigir_profesional_propio(tx, h["profesional_id"])
        await tx.execute(
            "DELETE FROM horario_atencion WHERE clinica_id = %(clinica_id)s AND horario_id = %(h)s", {"h": horario_id}
        )
        tx.tras_commit(lambda: cache.invalidar_profesional(tx.p.clinica_id, h["profesional_id"]))

    await db.run(p, work)


# ---------------------------------------------------------------- RF6 bloqueos
_CONFLICTOS_SQL = (
    "SELECT cita_id, paciente_id, inicio, fin FROM cita "
    "WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s AND estado_id = 1 "
    "  AND tstzrange(inicio, fin) && tstzrange(%(i)s, %(f)s) ORDER BY inicio"
)


@router.post("/profesionales/{profesional_id}/bloqueos", status_code=201, summary="RF6: registra un bloqueo y lista las citas en conflicto")
async def crear_bloqueo(profesional_id: int, body: BloqueoIn, p: Principal = Depends(requiere("bloqueo.gestionar"))):
    async def work(tx: Tx):
        await exigir_profesional_propio(tx, profesional_id)
        row = await tx.one(
            "INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo, creado_por) "
            "VALUES (%(clinica_id)s, %(pid)s, %(i)s, %(f)s, %(m)s, %(u)s) "
            "RETURNING bloqueo_id, profesional_id, inicio, fin, motivo",
            {"pid": profesional_id, "i": body.inicio, "f": body.fin, "m": body.motivo, "u": tx.p.usuario_id},
        )
        # El bloqueo no cancela citas: las ya reservadas se devuelven como conflictos para reprogramar.
        conflictos = await tx.fetch(_CONFLICTOS_SQL, {"pid": profesional_id, "i": body.inicio, "f": body.fin})
        tx.tras_commit(lambda: cache.invalidar_profesional(tx.p.clinica_id, profesional_id))
        return {**row, "conflictos": conflictos}

    return await db.run(p, work)


@router.get("/profesionales/{profesional_id}/bloqueos", summary="Bloqueos del profesional")
async def listar_bloqueos(profesional_id: int, p: Principal = Depends(requiere("agenda.leer_config"))):
    async def work(tx: Tx):
        return await tx.fetch(
            "SELECT bloqueo_id, inicio, fin, motivo FROM bloqueo_agenda "
            "WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s ORDER BY inicio",
            {"pid": profesional_id},
        )

    return await db.run(p, work)


@router.get("/bloqueos/{bloqueo_id}/conflictos", summary="RF6: citas vigentes que caen dentro del bloqueo")
async def conflictos_bloqueo(bloqueo_id: int, p: Principal = Depends(requiere("agenda.leer_config"))):
    async def work(tx: Tx):
        b = await tx.one(
            "SELECT profesional_id, inicio, fin FROM bloqueo_agenda WHERE clinica_id = %(clinica_id)s AND bloqueo_id = %(b)s",
            {"b": bloqueo_id},
        )
        if b is None:
            raise no_encontrado("El bloqueo")
        await exigir_profesional_propio(tx, b["profesional_id"])
        return await tx.fetch(_CONFLICTOS_SQL, {"pid": b["profesional_id"], "i": b["inicio"], "f": b["fin"]})

    return await db.run(p, work)


@router.delete("/bloqueos/{bloqueo_id}", status_code=204, summary="Elimina un bloqueo")
async def eliminar_bloqueo(bloqueo_id: int, p: Principal = Depends(requiere("bloqueo.gestionar"))):
    async def work(tx: Tx):
        b = await tx.one(
            "SELECT profesional_id FROM bloqueo_agenda WHERE clinica_id = %(clinica_id)s AND bloqueo_id = %(b)s",
            {"b": bloqueo_id},
        )
        if b is None:
            raise no_encontrado("El bloqueo")
        await exigir_profesional_propio(tx, b["profesional_id"])
        await tx.execute(
            "DELETE FROM bloqueo_agenda WHERE clinica_id = %(clinica_id)s AND bloqueo_id = %(b)s", {"b": bloqueo_id}
        )
        tx.tras_commit(lambda: cache.invalidar_profesional(tx.p.clinica_id, b["profesional_id"]))

    await db.run(p, work)


# ---------------------------------------------------------------- RF7 / RF8 disponibilidad
async def espacios_profesional(p: Principal, profesional_id: int, fecha: date, servicio_id: int) -> list[dict]:
    """Espacios libres de un profesional en una fecha local de la clinica para un servicio (RF7).

    1) intenta Redis (sin tocar la base); 2) en fallo calcula desde la base y guarda bajo la
    clave versionada leida ANTES de consultar (ver app/cache.py).
    """
    clinica_id = p.clinica_id
    cacheado, clave = await cache.leer(clinica_id, profesional_id, fecha.isoformat(), servicio_id)
    if cacheado is None:

        async def work(tx: Tx) -> list[dict]:
            tz = await zona_clinica(tx)
            prof = await tx.one(
                "SELECT activo FROM profesional WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s",
                {"pid": profesional_id},
            )
            if prof is None:
                raise no_encontrado("El profesional")
            serv = await tx.one(
                "SELECT s.duracion_min, s.activo FROM servicio s "
                "JOIN profesional_servicio ps ON ps.clinica_id = s.clinica_id AND ps.servicio_id = s.servicio_id "
                "WHERE s.clinica_id = %(clinica_id)s AND s.servicio_id = %(sid)s AND ps.profesional_id = %(pid)s",
                {"sid": servicio_id, "pid": profesional_id},
            )
            if serv is None:
                raise error(422, "SERVICIO_NO_HABILITADO", "El profesional no atiende ese servicio en esta clinica")
            if not prof["activo"] or not serv["activo"]:
                return []
            ini_dia, fin_dia = limites_dia(fecha, tz)
            bloques = await tx.fetch(
                "SELECT hora_inicio, hora_fin FROM horario_atencion "
                "WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s AND dia_semana = %(dow)s",
                {"pid": profesional_id, "dow": fecha.isoweekday()},
            )
            ocupados = await tx.fetch(
                "SELECT inicio, fin FROM cita WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s "
                "AND estado_id = 1 AND inicio < %(fd)s AND fin > %(id)s",
                {"pid": profesional_id, "id": ini_dia, "fd": fin_dia},
            )
            bloqueos = await tx.fetch(
                "SELECT inicio, fin FROM bloqueo_agenda WHERE clinica_id = %(clinica_id)s AND profesional_id = %(pid)s "
                "AND tstzrange(inicio, fin) && tstzrange(%(id)s, %(fd)s)",
                {"pid": profesional_id, "id": ini_dia, "fd": fin_dia},
            )
            inicios = calcular_slots(
                fecha=fecha,
                tz=tz,
                bloques=[(b["hora_inicio"], b["hora_fin"]) for b in bloques],
                duracion_min=serv["duracion_min"],
                ocupados=[(o["inicio"], o["fin"]) for o in ocupados],
                bloqueos=[(b["inicio"], b["fin"]) for b in bloqueos],
                ahora=datetime(1970, 1, 1, tzinfo=tz),  # el filtro de "pasado" se aplica al servir
                paso_min=settings.slot_step_min,
            )
            return [
                {"inicio": i.isoformat(), "fin": (i + timedelta(minutes=serv["duracion_min"])).isoformat()}
                for i in inicios
            ]

        cacheado = await db.run(p, work)
        await cache.guardar(clave, cacheado)
    ahora_utc = ahora()
    return [s for s in cacheado if datetime.fromisoformat(s["inicio"]) > ahora_utc]


@router.get("/profesionales/{profesional_id}/disponibilidad", summary="RF7: espacios libres de un profesional en una fecha")
async def disponibilidad_profesional(
    profesional_id: int,
    fecha: date,
    servicio_id: int,
    p: Principal = Depends(requiere("disponibilidad.consultar")),
):
    espacios = await espacios_profesional(p, profesional_id, fecha, servicio_id)
    return {"profesional_id": profesional_id, "fecha": fecha, "servicio_id": servicio_id, "espacios": espacios}


@router.get("/disponibilidad", summary="RF8: profesionales con espacio para un servicio en un rango de fechas")
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

    async def candidatos(tx: Tx):
        return await tx.fetch(
            "SELECT p.profesional_id, p.nombre FROM profesional p "
            "JOIN profesional_servicio ps ON ps.clinica_id = p.clinica_id AND ps.profesional_id = p.profesional_id "
            "WHERE p.clinica_id = %(clinica_id)s AND p.activo AND ps.servicio_id = %(sid)s ORDER BY p.profesional_id",
            {"sid": servicio_id},
        )

    resultado = []
    for prof in await db.run(p, candidatos):
        dias = []
        d = desde
        while d <= hasta:
            espacios = await espacios_profesional(p, prof["profesional_id"], d, servicio_id)
            if espacios:
                dias.append({"fecha": d, "espacios": espacios})
            d += timedelta(days=1)
        if dias:
            resultado.append({"profesional_id": prof["profesional_id"], "nombre": prof["nombre"], "dias": dias})
    return {"servicio_id": servicio_id, "desde": desde, "hasta": hasta, "profesionales": resultado}
