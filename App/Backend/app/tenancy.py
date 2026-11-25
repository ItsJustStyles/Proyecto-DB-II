"""
Guarda de aislamiento entre clinicas (I5), sin dependencias externas.

La estrategia elegida es tabla compartida con columna discriminadora: el motor no
filtra por si solo, asi que la garantia vive en la capa de acceso. Toda consulta
sobre tablas de negocio pasa por Tx (app/db.py), que:

  1. exige que el SQL contenga el marcador %(clinica_id)s, y
  2. inyecta ese parametro desde la identidad validada, sobrescribiendo cualquier
     valor que el llamador hubiera intentado pasar.

Es una barrera contra el olvido (una consulta sin filtro falla de inmediato en las
pruebas); no analiza semantica SQL, por eso la complementan las FK compuestas, los
roles de minimo privilegio y las pruebas de fuga.
"""
import re

_MARCADOR = re.compile(r"%\(clinica_id\)s")


class TenantGuardError(RuntimeError):
    """Consulta de negocio sin filtro por clinica: es un error de programacion."""


def asegurar_filtro_clinica(sql: str) -> None:
    if not _MARCADOR.search(sql):
        raise TenantGuardError(
            "La consulta no referencia %(clinica_id)s; toda consulta de negocio debe filtrar por clinica"
        )


def parametros_con_clinica(params: dict | None, clinica_id: int | None) -> dict:
    if clinica_id is None:
        raise TenantGuardError("La identidad no tiene clinica: no puede consultar tablas de negocio")
    # La clinica viene siempre de la identidad; se sobrescribe lo que traiga el llamador.
    return {**(params or {}), "clinica_id": clinica_id}
