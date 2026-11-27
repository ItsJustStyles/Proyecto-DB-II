import config

import psycopg2
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, max as max_
from pyspark.sql.types import BooleanType, IntegerType, LongType, StringType, StructField, StructType, TimestampType

# Esquemas:

ESQUEMA_CITA = StructType([
    StructField("cita_id", LongType()),
    StructField("clinica_id", LongType()),
    StructField("profesional_id", LongType()),
    StructField("servicio_id", LongType()),
    StructField("estado_id", IntegerType()),
    StructField("cita_origen_id", LongType()),
    StructField("inicio", TimestampType()),
    StructField("fin", TimestampType()),
    StructField("creada_en", TimestampType()),
    StructField("actualizada_en", TimestampType()),
])

def _esquema(*campos):
    return StructType([StructField(nombre, tipo) for nombre, tipo in campos])


DIMENSIONES = {
    "clinica": _esquema(
        ("clinica_id", LongType()), ("nombre", StringType()),
        ("zona_horaria", StringType()), ("activa", BooleanType())),
    "profesional": _esquema(
        ("profesional_id", LongType()), ("clinica_id", LongType()),
        ("especialidad_id", IntegerType()), ("nombre", StringType()),
        ("activo", BooleanType())),
    "servicio": _esquema(
        ("servicio_id", LongType()), ("clinica_id", LongType()),
        ("especialidad_id", IntegerType()), ("nombre", StringType()),
        ("duracion_min", IntegerType()), ("activo", BooleanType())),
    "especialidad": _esquema(
        ("especialidad_id", IntegerType()), ("nombre", StringType())),
    "estado_cita": _esquema(
        ("estado_id", IntegerType()), ("codigo", StringType())),
}

# Conexion:

def conectar():
    return psycopg2.connect(
        host=config.DB_HOST, port=config.DB_PORT, dbname=config.DB_NAME,
        user=config.ETL_DB_USER, password=config.ETL_DB_PASSWORD)