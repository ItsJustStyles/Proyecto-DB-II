import os

import config

import psycopg2
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, max as max_
from pyspark.sql.types import BooleanType, IntegerType, LongType, StringType, StructField, StructType, TimestampType

# Variables:

FORMATO_FECHA = "yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXX"

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

# Lectura:

def extraer_tabla(spark: SparkSession, consulta: str, esquema: StructType, destino: str) -> int:
    df = (
        spark.read.format("jdbc")
        .option("url", config.JDBC_URL)
        .option("driver", "org.postgresql.Driver")
        .option("user", config.ETL_DB_USER)
        .option("password", config.ETL_DB_PASSWORD)
        .option("query", consulta)
        .load()
        .select([col(c.name).cast(c.dataType).alias(c.name) for c in esquema])
    )
    df.write.mode("errorifexists").option("timestampFormat", FORMATO_FECHA).json(destino)
    return spark.read.schema(esquema).option("timestampFormat", FORMATO_FECHA).json(destino).count()

# Prueba para cuando se ejecute en el docker, esto se debe quitar despues:

conn = conectar()
print("Conexión psycopg2 OK:", conn.info.dbname)
conn.close()

spark = (
    SparkSession.builder
    .appName("prueba-etl-medicitas")
    .config("spark.jars", "/opt/jars/postgresql.jar")
    .config("spark.driver.extraClassPath", "/opt/jars/postgresql.jar")
    .getOrCreate()
)

try:
    total = extraer_tabla(
        spark=spark,
        consulta="SELECT clinica_id, nombre, zona_horaria, activa FROM clinica",
        esquema=DIMENSIONES["clinica"],
        destino="/tmp/prueba_clinica_01",
    )
    print("Filas extraídas y leídas:", total)
    spark.read.schema(DIMENSIONES["clinica"]).option("timestampFormat", FORMATO_FECHA).json("/tmp/prueba_clinica_01").show(truncate=False)
finally:
    spark.stop()