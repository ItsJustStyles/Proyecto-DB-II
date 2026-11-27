Por el momento se usa "usa actualizada_en"
Habra que hacer un V4, para corregir los campos que faltan en la db

Para hacer una prueba se debe levantar la app:

docker compose up --build -d

y luego se da este:

docker compose --profile etl up --build etl

Deberia dar algo parecido a esto:
```text
etl-1  | WARNING: Using incubator modules: jdk.incubator.vector
etl-1  | 26/11/27 03:23:29 WARN NativeCodeLoader: Unable to load native-hadoop library for your platform... using builtin-java classes where applicable
etl-1  | Using Spark's default log4j profile: org/apache/spark/log4j2-defaults.properties
etl-1  | Setting default log level to "WARN".
etl-1  | To adjust logging level use sc.setLogLevel(newLevel). For SparkR, use setLogLevel(newLevel).
etl-1  | Conexión psycopg2 OK: MediCitas
etl-1  | Filas extraídas y leídas: 2
etl-1  | +----------+------------------+------------------+------+
etl-1  | |clinica_id|nombre            |zona_horaria      |activa|
etl-1  | +----------+------------------+------------------+------+
etl-1  | |1         |Clinica Demo Norte|America/Costa_Rica|true  |
etl-1  | |2         |Clinica Demo Sur  |America/Costa_Rica|true  |
etl-1  | +----------+------------------+------------------+------+
etl-1  | 
                                                                                
etl-1 exited with code 0
```