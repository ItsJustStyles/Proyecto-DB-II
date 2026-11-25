import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import psycopg
from fastapi import HTTPException
from psycopg import errors as pgerr
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings
from .permisos import ROL_ID_A_NOMBRE, ROL_ID_A_ROL_BD
from .tenancy import asegurar_filtro_clinica, parametros_con_clinica
log = logging.getLogger("medicitas.db")

pool: AsyncConnectionPool | None = None

async def open_pool() -> None:
    global pool
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=2,
        max_size=int(__import__("os").environ.get("DB_POOL_MAX", "20")),
        kwargs={"row_factory": dict_row, "autocommit": True},
        open=False,
    )
    await pool.open(wait=True, timeout=30)


async def close_pool() -> None:
    if pool is not None:
        await pool.close()

@dataclass
class Principal:
    """Identidad ya validada. La clinica sale de la fila de `usuario`, nunca de la peticion."""

    sub: str
    usuario_id: int
    clinica_id: int | None
    rol_id: int
    nombre: str = ""

    @property
    def rol(self) -> str:
        return ROL_ID_A_NOMBRE[self.rol_id]

    @property
    def rol_bd(self) -> str:
        return ROL_ID_A_ROL_BD[self.rol_id]

async def resolver_identidad(sub: str) -> Principal | None:
    """keycloak_sub -> (usuario, clinica, rol). Corre con el login base (medicitas_app)."""
    assert pool is not None
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT u.usuario_id, u.clinica_id, u.rol_id, u.activo, "
            "       COALESCE(c.activa, true) AS clinica_activa "
            "  FROM usuario u LEFT JOIN clinica c ON c.clinica_id = u.clinica_id "
            " WHERE u.keycloak_sub = %(sub)s::uuid",
            {"sub": sub},
        )
        row = await cur.fetchone()
    if row is None or not row["activo"] or not row["clinica_activa"]:
        return None
    return Principal(sub=sub, usuario_id=row["usuario_id"], clinica_id=row["clinica_id"], rol_id=row["rol_id"])

class Tx:
    """Operaciones dentro de la transaccion. Todo acceso a tablas de negocio pasa por aqui."""

    def __init__(self, conn: psycopg.AsyncConnection, principal: Principal):
        self.conn = conn
        self.p = principal
        self.after_commit: list[Callable[[], Awaitable[None]]] = []

    async def fetch(self, query: str, params: dict | None = None) -> list[dict]:
        asegurar_filtro_clinica(query)
        cur = await self.conn.execute(query, parametros_con_clinica(params, self.p.clinica_id))
        return await cur.fetchall() if cur.description else []

    async def one(self, query: str, params: dict | None = None) -> dict | None:
        rows = await self.fetch(query, params)
        return rows[0] if rows else None

    async def execute(self, query: str, params: dict | None = None) -> int:
        asegurar_filtro_clinica(query)
        cur = await self.conn.execute(query, parametros_con_clinica(params, self.p.clinica_id))
        return cur.rowcount

    async def fetch_catalogo(self, query: str, params: dict | None = None) -> list[dict]:
        """Solo para catalogos globales (rol, especialidad, estado_cita) y funciones de plataforma."""
        cur = await self.conn.execute(query, params or {})
        return await cur.fetchall() if cur.description else []

    def tras_commit(self, cb: Callable[[], Awaitable[None]]) -> None:
        self.after_commit.append(cb)

def _http(status: int, codigo: str, mensaje: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"codigo": codigo, "mensaje": mensaje})

def traducir_error_bd(e: psycopg.Error) -> HTTPException:
    """Convierte un error del motor en la respuesta HTTP que corresponde, sin filtrar detalles internos."""
    code = getattr(e, "sqlstate", None)
    constraint = getattr(getattr(e, "diag", None), "constraint_name", None)
    msg = getattr(getattr(e, "diag", None), "message_primary", None) or "Error de base de datos"
    if code == "23P01":  # exclusion_violation: I1 / I2 / horarios solapados
        if constraint == "ex_cita_profesional_sin_solape":
            return _http(409, "ESPACIO_TOMADO", "El espacio ya fue tomado por otra cita del profesional")
        if constraint == "ex_cita_paciente_sin_solape":
            return _http(409, "PACIENTE_OCUPADO", "El paciente ya tiene una cita vigente en ese horario")
        if constraint == "ex_horario_sin_solape":
            return _http(409, "HORARIO_SOLAPADO", "El bloque se solapa con otro del mismo profesional")
        return _http(409, "CONFLICTO", "Conflicto de solapamiento")
    if code == "23505":
        return _http(409, "DUPLICADO", "Ya existe un registro con esos datos")
    if code == "23503":
        return _http(422, "REFERENCIA_INVALIDA", "Una referencia no existe en esta clinica")
    if code in ("23514", "23502", "22P02", "22007", "22008", "22003", "22001"):
        return _http(422, "DATO_INVALIDO", msg if code == "23514" else "Dato invalido")
    if code == "MC001":
        return _http(409, "TRANSICION_INVALIDA", msg)
    if code == "MC002":
        return _http(422, "CITA_INVALIDA", msg)
    if code == "42501":
        return _http(403, "SIN_PERMISO", "Operacion no permitida para este rol")
    if code in ("40P01", "40001"):
        return _http(503, "REINTENTAR", "Conflicto transitorio, reintente la operacion")
    log.exception("Error de base de datos no mapeado: sqlstate=%s", code)
    return _http(500, "ERROR_INTERNO", "Error interno")

async def run(principal: Principal, fn: Callable[[Tx], Awaitable[Any]]) -> Any:
    """
    Ejecuta `fn` en una transaccion READ COMMITTED con el rol de BD del usuario.

    Reintenta deadlocks (40P01) y fallos de serializacion (40001). Si `fn` lanza
    HTTPException la transaccion se revierte y la excepcion se propaga.
    """
    assert pool is not None
    intento = 0
    while True:
        tx: Tx | None = None
        try:
            async with pool.connection() as conn:
                async with conn.transaction():
                    await conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                    await conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(principal.rol_bd)))
                    tx = Tx(conn, principal)
                    result = await fn(tx)
            break
        except psycopg.Error as e:
            if getattr(e, "sqlstate", None) in ("40P01", "40001") and intento < settings.max_retries:
                intento += 1
                await asyncio.sleep(random.uniform(0.01, 0.05) * intento)
                continue
            raise traducir_error_bd(e)
    for cb in tx.after_commit if tx else []:
        try:
            await cb()
        except Exception:  # la invalidacion de cache nunca debe romper una operacion ya confirmada
            log.exception("Fallo en accion posterior al commit")
    return result