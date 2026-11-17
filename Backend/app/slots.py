"""
Calculo de espacios disponibles (RF7). Funcion pura: no toca la base ni Redis.

Los intervalos son semiabiertos [inicio, fin), igual que en las exclusion constraints:
una cita puede empezar justo cuando otra termina.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

Intervalo = tuple[datetime, datetime]


def _solapa(a_ini: datetime, a_fin: datetime, b_ini: datetime, b_fin: datetime) -> bool:
    return a_ini < b_fin and b_ini < a_fin


def calcular_slots(
    fecha: date,
    tz: ZoneInfo,
    bloques: list[tuple[time, time]],
    duracion_min: int,
    ocupados: list[Intervalo],
    bloqueos: list[Intervalo],
    ahora: datetime,
    paso_min: int = 15,
) -> list[datetime]:
    """Inicios posibles de una cita de `duracion_min` el dia `fecha` (hora local de la clinica)."""
    if duracion_min <= 0 or paso_min <= 0:
        return []
    duracion = timedelta(minutes=duracion_min)
    paso = timedelta(minutes=paso_min)
    resultado: list[datetime] = []
    for ini_local, fin_local in sorted(bloques):
        cursor = datetime.combine(fecha, ini_local, tzinfo=tz)
        limite = datetime.combine(fecha, fin_local, tzinfo=tz)
        while cursor + duracion <= limite:
            fin = cursor + duracion
            if (
                cursor > ahora
                and not any(_solapa(cursor, fin, o_ini, o_fin) for o_ini, o_fin in ocupados)
                and not any(_solapa(cursor, fin, b_ini, b_fin) for b_ini, b_fin in bloqueos)
            ):
                resultado.append(cursor)
            cursor += paso
    return resultado
