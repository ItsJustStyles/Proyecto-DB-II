"""
Cache de disponibilidad (RF7) en Redis. La fuente de verdad sigue siendo PostgreSQL.

Clave y alcance
  disp:{clinica}:{profesional}:{fecha}:{servicio}:p{ver_prof}:d{ver_dia}
  Una entrada = los espacios de UN profesional, UNA fecha local de la clinica y UN servicio
  (la duracion del servicio cambia los espacios). La clinica va en la clave: no hay
  entradas compartidas entre tenants.

Invalidacion por version (cierra la carrera "lector con datos viejos")
  Dos contadores en Redis:
    ver:dia:{clinica}:{profesional}:{fecha}   cambia al reservar/cancelar/reprogramar/desenlace
    ver:prof:{clinica}:{profesional}          cambia al editar horarios/bloqueos/servicios del profesional
  La version forma parte de la clave. Un escritor hace INCR DESPUES del commit; el lector
  lee las versiones ANTES de consultar la base. Si un lector con datos anteriores al commit
  guarda su resultado, lo guarda bajo la version vieja, que nadie vuelve a pedir. Asi, una
  reserva concedida invalida de inmediato toda copia previa (I8) sin depender del TTL
  (el TTL solo limpia llaves huerfanas).

Si Redis falla, se responde desde la base: la cache nunca puede dar una respuesta falsa.
"""
import json
import logging

import redis.asyncio as redis

from .config import settings

log = logging.getLogger("medicitas.cache")

_r: redis.Redis | None = None


def cliente() -> redis.Redis:
    global _r
    if _r is None:
        _r = redis.from_url(settings.redis_url, decode_responses=True)
    return _r


async def cerrar() -> None:
    if _r is not None:
        await _r.aclose()


def _k_dia(c: int, p: int, fecha: str) -> str:
    return f"ver:dia:{c}:{p}:{fecha}"


def _k_prof(c: int, p: int) -> str:
    return f"ver:prof:{c}:{p}"


async def leer(c: int, p: int, fecha: str, servicio: int) -> tuple[list | None, str | None]:
    """Devuelve (espacios, clave). Si es un fallo de cache, (None, None) y no se vuelve a escribir."""
    try:
        r = cliente()
        vp, vd = await r.mget(_k_prof(c, p), _k_dia(c, p, fecha))
        clave = f"disp:{c}:{p}:{fecha}:{servicio}:p{vp or 0}:d{vd or 0}"
        valor = await r.get(clave)
        return (json.loads(valor) if valor is not None else None), clave
    except Exception:
        log.warning("Redis no disponible al leer; se responde desde la base")
        return None, None


async def guardar(clave: str | None, espacios: list) -> None:
    if clave is None:
        return
    try:
        await cliente().set(clave, json.dumps(espacios), ex=settings.cache_ttl_seconds)
    except Exception:
        log.warning("Redis no disponible al escribir")


async def invalidar_dia(c: int, p: int, fecha: str) -> None:
    await cliente().incr(_k_dia(c, p, fecha))


async def invalidar_profesional(c: int, p: int) -> None:
    await cliente().incr(_k_prof(c, p))
