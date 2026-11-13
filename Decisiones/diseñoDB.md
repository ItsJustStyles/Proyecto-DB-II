Solución multi-tenancy:

Para cumplir con los requerimientos del proyecto **MediCitas** —donde el aislamiento de datos médicos sensibles es un requisito estrictamente verificable y se debe preparar el terreno para la capa analítica distribuida de la Etapa 2—, la elección de **Tabla compartida con Row-Level Security (RLS)** se justifica frente a otras alternativas que fueron descartadas en el diseño.

### Razones detalladas de la elección

* **Eficiencia transaccional y de recursos:** Permite utilizar un único *pool* de conexiones eficiente (mediante herramientas como PgBouncer), evitando agotar la memoria y los descriptores del motor con cientos de bases de datos o esquemas independientes.


* **Preparación nativa para la Etapa 2:** Al mantener los registros en las mismas estructuras físicas pero segregados lógicamente, la futura construcción de la capa analítica y distribuida se simplifica drásticamente al no tener que unificar información fragmentada en múltiples instancias.


* **Seguridad delegada en el motor:** El aislamiento no queda a merced de un posible descuido humano en el código de la aplicación. Es el propio motor de base de datos (PostgreSQL) el que aplica de forma intransigente las políticas de seguridad en cada consulta.



### Alternativas descartadas y sus trade-offs

* **Bases de datos separadas por clínica:** Se descartó porque multiplica la complejidad operativa, satura el manejo de conexiones concurrentes y vuelve extremadamente costosa y compleja la integración de datos para la analítica global de la Etapa 2.


* **Esquemas separados por clínica (*Schema-per-tenant*):** Se descartó porque cada evolución del modelo de datos o migración de esquema obligaría a ejecutar scripts iterativos sobre $N$ esquemas diferentes, aumentando el riesgo de fallos de sincronización y degradando el catálogo del motor conforme la plataforma incorpore más clientes.


* **Tabla compartida basada exclusivamente en la aplicación (sin RLS):** Se descartó porque confiar el aislamiento únicamente a que el desarrollador escriba siempre el filtro `WHERE clinic_id = ?` es un enfoque frágil; un error en una consulta compleja o un parámetro manipulado rompe el Invariante 15 y expone información personal sensible.