from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.slots import calcular_slots

TZ = ZoneInfo("America/Costa_Rica")
FECHA = date(2030, 1, 7)  # lunes
PASADO = datetime(2020, 1, 1, tzinfo=TZ)


def dt(h, m=0):
    return datetime.combine(FECHA, time(h, m), tzinfo=TZ)


def horas(slots):
    return [s.strftime("%H:%M") for s in slots]


def test_bloque_simple_sin_ocupacion():
    slots = calcular_slots(FECHA, TZ, [(time(8), time(9))], 30, [], [], PASADO, paso_min=30)
    assert horas(slots) == ["08:00", "08:30"]


def test_un_espacio_que_no_cabe_antes_del_fin_del_bloque_no_se_ofrece():
    slots = calcular_slots(FECHA, TZ, [(time(8), time(9))], 45, [], [], PASADO, paso_min=15)
    assert horas(slots) == ["08:00", "08:15"]  # 08:30 + 45 min se pasaria de las 09:00


def test_jornada_partida_no_ofrece_el_receso():
    slots = calcular_slots(FECHA, TZ, [(time(8), time(9)), (time(13), time(14))], 30, [], [], PASADO, paso_min=30)
    assert horas(slots) == ["08:00", "08:30", "13:00", "13:30"]


def test_cita_vigente_ocupa_su_intervalo_semiabierto():
    # La cita 08:30-09:00 deja libre 08:00-08:30 y 09:00 en adelante (rangos [inicio, fin))
    slots = calcular_slots(FECHA, TZ, [(time(8), time(10))], 30, [(dt(8, 30), dt(9))], [], PASADO, paso_min=30)
    assert horas(slots) == ["08:00", "09:00", "09:30"]


def test_bloqueo_retira_disponibilidad():
    slots = calcular_slots(FECHA, TZ, [(time(8), time(10))], 30, [], [(dt(8, 45), dt(9, 15))], PASADO, paso_min=30)
    assert horas(slots) == ["08:00", "09:30"]


def test_no_se_ofrecen_espacios_pasados():
    slots = calcular_slots(FECHA, TZ, [(time(8), time(10))], 30, [], [], dt(8, 30), paso_min=30)
    assert horas(slots) == ["09:00", "09:30"]


def test_sin_bloques_no_hay_espacios():
    assert calcular_slots(FECHA, TZ, [], 30, [], [], PASADO) == []


def test_el_fin_de_cada_espacio_respeta_la_duracion():
    slots = calcular_slots(FECHA, TZ, [(time(8), time(9))], 20, [], [], PASADO, paso_min=20)
    assert [s + timedelta(minutes=20) for s in slots][-1] == dt(9)
