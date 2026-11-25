## Multi-tenancy: comparación de estrategias y decisión

El tenant de MediCitas es la clínica. El aislamiento entre clínicas (invariante I5) es el requisito central del producto, ya que los datos son información personal sensible, y además la decisión condiciona qué tan costosa será la capa analítica distribuida de la Etapa 2. Se compararon cuatro estrategias bajo los mismos criterios.

### Estrategias consideradas

1. **Base de datos por clínica.** Cada clínica tiene su propia base de datos.
2. **Esquema por clínica (*schema-per-tenant*).** Una base de datos con un esquema de PostgreSQL por clínica.
3. **Tabla compartida con columna discriminadora.** Todas las clínicas comparten las tablas; cada fila lleva `clinica_id` y la aplicación filtra por él en cada consulta.
4. **Tabla compartida con Row-Level Security (RLS).** Mismas tablas compartidas, pero PostgreSQL aplica el filtro mediante políticas.

### Comparación

| Criterio | BD por clínica | Esquema por clínica | Columna discriminadora | RLS |
|---|---|---|---|---|
| Fuerza del aislamiento | Muy alta (física) | Alta (por permisos de esquema) | Media: depende de la aplicación | Alta: lo aplica el motor |
| Riesgo de fuga por error de código | Muy bajo | Bajo | Mayor: una consulta sin filtro expone otras clínicas | Bajo |
| Alta de una clínica nueva | Crear una base y migrarla | Crear un esquema y migrarlo | Insertar una fila | Insertar una fila |
| Migraciones del modelo | Se repiten en N bases | Se repiten en N esquemas | Una sola vez | Una sola vez |
| Conexiones y recursos | Un pool por base, escala mal | Pool compartido, pero el catálogo crece con cada esquema | Un pool compartido | Un pool compartido |
| Analítica de la Etapa 2 | Hay que unir N bases | Hay que unir N esquemas | Directa: una sola fuente | Directa: una sola fuente |
| Complejidad de implementación | Alta (enrutar a la base correcta) | Media (cambiar el `search_path`) | Baja | Media (fijar la clínica de la sesión y mantener políticas por tabla) |

### Decisión: tabla compartida con columna discriminadora

Se eligió la estrategia 3 por las siguientes razones:

- **Una sola estructura para todas las clínicas.** Las migraciones se ejecutan una vez y dar de alta una clínica es insertar una fila (RF1), sin crear bases ni esquemas.
- **Costo bajo en conexiones y recursos.** Un único pool atiende a todas las clínicas.
- **Preparación para la Etapa 2.** Al estar todos los datos en las mismas tablas, construir la capa analítica no exige unir información dispersa.
- **Simplicidad frente a RLS.** No requiere fijar variables de sesión en cada transacción ni mantener políticas por tabla, lo que facilita depurar y razonar sobre cada consulta.

Como la garantía recae en la aplicación, el aislamiento se refuerza con estas medidas:

- **La clínica sale de la identidad, nunca de la petición.** Se deriva del token validado (el identificador que emite Keycloak y su clínica asociada), de modo que manipular `clinica_id` en parámetros o cuerpo no tiene efecto.
- **Un único punto de acceso a datos.** Todas las consultas pasan por una capa que agrega el filtro `clinica_id` de forma centralizada, en lugar de escribirlo a mano en cada consulta.
- **Claves foráneas compuestas con `clinica_id`.** La base impide que una fila de una clínica referencie a otra (por ejemplo, una cita de A con un paciente de B).
- **Roles de base de datos con mínimo privilegio.** Limitan lo que cada perfil puede leer y escribir.
- **Pruebas automatizadas de fuga** que intentan romper el aislamiento (se documentan en el informe de pruebas).

### Alternativas descartadas

- **Base de datos por clínica:** es el aislamiento más fuerte, pero multiplica la operación (N migraciones, N respaldos, N pools) y obligaría a unir bases para la analítica. El costo no se justifica para clínicas de tamaño pequeño o mediano.
- **Esquema por clínica:** reduce el costo respecto a la opción anterior, pero cada cambio de modelo debe aplicarse a N esquemas, con riesgo de que queden desincronizados, y el catálogo del motor crece con cada clínica nueva.
- **RLS:** ofrece la garantía más fuerte entre las estrategias de tabla compartida, pero exige fijar la clínica de la sesión en cada transacción, mantener políticas por tabla y complica la depuración. Se descartó por esa complejidad adicional, aceptando que la garantía quede en la aplicación y se compense con las medidas anteriores.

### Qué se sacrifica

- **Garantía a nivel de motor.** Si una consulta omite el filtro, la base no lo corrige. Se mitiga centralizando el acceso a datos y con las pruebas de fuga.
- **Todo el riesgo de I5 queda en el código.** Un error en la capa de acceso afectaría a todas las clínicas a la vez.
- **Rendimiento.** Los índices deben comenzar por `clinica_id` donde corresponda para que el filtro no degrade las consultas.
- **Vecino ruidoso y respaldos.** Una clínica con mucha carga comparte recursos con las demás, y restaurar los datos de una sola clínica es más laborioso que restaurar una base propia.