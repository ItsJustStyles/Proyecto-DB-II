- Database engine: PostgreSQL 16
- Database name: MediCitas
- Context: Plataforma SaaS multi-tenant de gestión de citas médicas (MediCitas). Cada clínica es un tenant con sus datos estrictamente aislados mediante tabla compartida: todas las tablas de negocio llevan `clinica_id` y el motor filtra cada consulta según la clínica de la sesión. Incluye profesionales, servicios, horarios, bloqueos de agenda, pacientes, citas, notas clínicas y bitácora de auditoría append-only. La identidad se delega en Keycloak (la base solo guarda el `sub` del token) y la caché de disponibilidad vive en Redis (la base es la fuente de verdad).

---


# Tables

---

### clinica
Tenant de la plataforma. Cada fila es una clínica cliente. La crea el administrador de plataforma (RF1).

- clinica_id
    - tipo: bigint identity
    - pk: si
    - null: no
    - descripcion: Identificador de la clínica; es el valor que discrimina el tenant en todas las demás tablas.
- nombre
    - tipo: varchar(150)
    - unique: si
    - null: no
    - descripcion: Nombre comercial de la clínica.
- zona_horaria
    - tipo: varchar(64)
    - null: no
    - default: 'America/Costa_Rica'
    - descripcion: Zona horaria IANA de la clínica (ej. America/Costa_Rica). Se usa para interpretar los horarios semanales de los profesionales.
- activa
    - tipo: boolean
    - null: no
    - default: true
    - descripcion: Baja lógica de la clínica.
- creada_en
    - tipo: timestamptz
    - null: no
    - default: now()
    - descripcion: Fecha y hora de alta.

---

### rol
Catálogo global de roles del sistema. Se corresponde con los roles definidos en el realm de Keycloak.

- rol_id
    - tipo: smallint
    - pk: si
    - null: no
    - descripcion: Identificador del rol (1 ADMIN_PLATAFORMA, 2 ADMIN_CLINICA, 3 RECEPCION, 4 PROFESIONAL).
- codigo
    - tipo: varchar(30)
    - unique: si
    - null: no
    - descripcion: Código del rol, idéntico al nombre del rol en Keycloak.
- descripcion
    - tipo: varchar(200)
    - null: no
    - descripcion: Descripción de las responsabilidades del rol.

---

### especialidad
Catálogo global de especialidades médicas. Evita repetir texto libre en servicios y profesionales.

- especialidad_id
    - tipo: smallint identity
    - pk: si
    - null: no
    - descripcion: Identificador de la especialidad.
- nombre
    - tipo: varchar(80)
    - unique: si
    - null: no
    - descripcion: Nombre de la especialidad (ej. Medicina General, Pediatría, Cardiología).

---

### usuario
Usuarios del sistema. No guarda credenciales: solo el identificador que emite Keycloak, la clínica y el rol (RF2).

- usuario_id
    - tipo: bigint identity
    - pk: si
    - null: no
    - descripcion: Identificador interno del usuario.
- clinica_id
    - tipo: bigint
    - fk: clinica(clinica_id)
    - null: si
    - descripcion: Clínica a la que pertenece. NULL únicamente para el administrador de plataforma.
- rol_id
    - tipo: smallint
    - fk: rol(rol_id)
    - null: no
    - descripcion: Rol del usuario dentro de su clínica.
- keycloak_sub
    - tipo: uuid
    - unique: si
    - null: no
    - descripcion: Claim `sub` del token OIDC. Es el vínculo entre la identidad del proveedor y la clínica; la clínica se deriva de esta fila, nunca de la petición.
- nombre
    - tipo: varchar(150)
    - null: no
    - descripcion: Nombre para mostrar.
- activo
    - tipo: boolean
    - null: no
    - default: true
    - descripcion: Baja lógica del usuario.
- creado_en
    - tipo: timestamptz
    - null: no
    - default: now()
    - descripcion: Fecha y hora de alta.
- check: `(rol_id = 1) = (clinica_id IS NULL)`
    - descripcion: Solo el administrador de plataforma carece de clínica; cualquier otro rol exige clínica.

---

### profesional
Profesional de salud de una clínica. Está ligado a un usuario porque consulta su agenda y escribe notas (RF4).

- profesional_id
    - tipo: bigint identity
    - pk: si
    - null: no
    - descripcion: Identificador del profesional.
- clinica_id
    - tipo: bigint
    - fk: clinica(clinica_id)
    - null: no
    - descripcion: Clínica del profesional.
- usuario_id
    - tipo: bigint
    - fk: usuario(clinica_id, usuario_id) (compuesta)
    - unique: si
    - null: no
    - descripcion: Usuario con el que el profesional inicia sesión; debe ser de la misma clínica y tener rol PROFESIONAL.
- especialidad_id
    - tipo: smallint
    - fk: especialidad(especialidad_id)
    - null: no
    - descripcion: Especialidad del profesional.
- nombre
    - tipo: varchar(150)
    - null: no
    - descripcion: Nombre completo.
- activo
    - tipo: boolean
    - null: no
    - default: true
    - descripcion: Baja lógica; un profesional inactivo no ofrece disponibilidad.

---

### servicio
Catálogo de servicios de la clínica. Su duración determina el tamaño del espacio que ocupa una cita (RF3, I4).

- servicio_id
    - tipo: bigint identity
    - pk: si
    - null: no
    - descripcion: Identificador del servicio.
- clinica_id
    - tipo: bigint
    - fk: clinica(clinica_id)
    - null: no
    - descripcion: Clínica dueña del servicio.
- nombre
    - tipo: varchar(120)
    - null: no
    - descripcion: Nombre del tipo de consulta. Único por clínica.
- duracion_min
    - tipo: smallint
    - null: no
    - check: duracion_min > 0 AND duracion_min <= 480
    - descripcion: Duración en minutos del espacio que ocupa la cita.
- especialidad_id
    - tipo: smallint
    - fk: especialidad(especialidad_id)
    - null: no
    - descripcion: Especialidad que requiere el servicio.
- activo
    - tipo: boolean
    - null: no
    - default: true
    - descripcion: Baja lógica del servicio.
- unique: (clinica_id, nombre)

---

### profesional_servicio
Tabla asociativa N:M. Un profesional atiende solo los servicios que tiene asociados (RF4).

- clinica_id
    - tipo: bigint
    - pk: si
    - fk: clinica(clinica_id)
    - null: no
    - descripcion: Clínica (parte de las claves compuestas que garantizan que ambos extremos son del mismo tenant).
- profesional_id
    - tipo: bigint
    - pk: si
    - fk: profesional(clinica_id, profesional_id) (compuesta)
    - null: no
    - descripcion: Profesional habilitado.
- servicio_id
    - tipo: bigint
    - pk: si
    - fk: servicio(clinica_id, servicio_id) (compuesta)
    - null: no
    - descripcion: Servicio que puede atender.

---

### horario_atencion
Bloques semanales de atención de cada profesional. Admite varios bloques por día (RF5).

- horario_id
    - tipo: bigint identity
    - pk: si
    - null: no
    - descripcion: Identificador del bloque horario.
- clinica_id
    - tipo: bigint
    - fk: clinica(clinica_id)
    - null: no
    - descripcion: Clínica del profesional.
- profesional_id
    - tipo: bigint
    - fk: profesional(clinica_id, profesional_id) (compuesta)
    - null: no
    - descripcion: Profesional al que pertenece el bloque.
- dia_semana
    - tipo: smallint
    - null: no
    - check: dia_semana BETWEEN 1 AND 7
    - descripcion: Día de la semana ISO (1 lunes ... 7 domingo).
- hora_inicio
    - tipo: time
    - null: no
    - descripcion: Hora local de inicio del bloque (zona horaria de la clínica).
- hora_fin
    - tipo: time
    - null: no
    - check: hora_fin > hora_inicio
    - descripcion: Hora local de fin del bloque.
- exclude: `USING gist (profesional_id WITH =, dia_semana WITH =, timerange(hora_inicio, hora_fin) WITH &&)`
    - descripcion: Impide bloques solapados del mismo profesional el mismo día.

---

### bloqueo_agenda
Vacaciones o permisos. Retira disponibilidad hacia adelante; no cancela citas ya reservadas (RF6).

- bloqueo_id
    - tipo: bigint identity
    - pk: si
    - null: no
    - descripcion: Identificador del bloqueo.
- clinica_id
    - tipo: bigint
    - fk: clinica(clinica_id)
    - null: no
    - descripcion: Clínica del profesional.
- profesional_id
    - tipo: bigint
    - fk: profesional(clinica_id, profesional_id) (compuesta)
    - null: no
    - descripcion: Profesional bloqueado.
- inicio
    - tipo: timestamptz
    - null: no
    - descripcion: Inicio del bloqueo.
- fin
    - tipo: timestamptz
    - null: no
    - check: fin > inicio
    - descripcion: Fin del bloqueo.
- motivo
    - tipo: varchar(200)
    - null: si
    - descripcion: Motivo (vacaciones, permiso, etc.).
- creado_por
    - tipo: bigint
    - fk: usuario(clinica_id, usuario_id) (compuesta)
    - null: no
    - descripcion: Usuario que registró el bloqueo.
- creado_en
    - tipo: timestamptz
    - null: no
    - default: now()
    - descripcion: Fecha de registro.

---

### paciente
Pacientes de la clínica. No son usuarios del sistema; los atiende recepción (RF14). Sus datos de contacto están sujetos a auditoría (RF18).

- paciente_id
    - tipo: bigint identity
    - pk: si
    - null: no
    - descripcion: Identificador del paciente.
- clinica_id
    - tipo: bigint
    - fk: clinica(clinica_id)
    - null: no
    - descripcion: Clínica que atiende al paciente. La misma persona en dos clínicas son dos filas independientes.
- identificacion
    - tipo: varchar(30)
    - null: no
    - descripcion: Número de identificación (cédula, pasaporte). Único por clínica.
- nombre
    - tipo: varchar(100)
    - null: no
    - descripcion: Nombre(s).
- apellidos
    - tipo: varchar(100)
    - null: no
    - descripcion: Apellidos.
- fecha_nacimiento
    - tipo: date
    - null: no
    - check: fecha_nacimiento <= current_date
    - descripcion: Fecha de nacimiento.
- telefono
    - tipo: varchar(30)
    - null: si
    - descripcion: Teléfono de contacto (dato sensible auditado).
- correo
    - tipo: varchar(254)
    - null: si
    - descripcion: Correo de contacto (dato sensible auditado).
- activo
    - tipo: boolean
    - null: no
    - default: true
    - descripcion: Baja lógica del paciente.
- creado_en
    - tipo: timestamptz
    - null: no
    - default: now()
    - descripcion: Fecha de registro.
- unique: (clinica_id, identificacion)

---

### estado_cita
Catálogo global de estados de la cita (RF13).

- estado_id
    - tipo: smallint
    - pk: si
    - null: no
    - descripcion: Identificador del estado (1 RESERVADA, 2 ATENDIDA, 3 AUSENTE, 4 CANCELADA, 5 REPROGRAMADA).
- codigo
    - tipo: varchar(20)
    - unique: si
    - null: no
    - descripcion: Código del estado.
- es_final
    - tipo: boolean
    - null: no
    - descripcion: Verdadero para ATENDIDA, AUSENTE, CANCELADA y REPROGRAMADA, que no admiten salida. Solo RESERVADA es vigente.
    - CHECK (es_final = (estado_id <> 1))
---

### cita
Núcleo transaccional. Una cita ocupa un intervalo de la agenda de un profesional para un paciente (RF9 a RF13).

- cita_id
    - tipo: bigint identity
    - pk: si
    - null: no
    - descripcion: Identificador de la cita.
- clinica_id
    - tipo: bigint
    - fk: clinica(clinica_id)
    - null: no
    - descripcion: Clínica de la cita.
- paciente_id
    - tipo: bigint
    - fk: paciente(clinica_id, paciente_id) (compuesta)
    - null: no
    - descripcion: Paciente atendido.
- profesional_id
    - tipo: bigint
    - fk: profesional(clinica_id, profesional_id) (compuesta)
    - null: no
    - descripcion: Profesional que atiende.
- servicio_id
    - tipo: bigint
    - fk: servicio(clinica_id, servicio_id) (compuesta)
    - null: no
    - descripcion: Servicio solicitado. El profesional debe tenerlo asociado (valida el trigger).
- inicio
    - tipo: timestamptz
    - null: no
    - descripcion: Instante de inicio de la cita.
- fin
    - tipo: timestamptz
    - null: no
    - check: fin > inicio
    - descripcion: Instante de fin. Desnormalización deliberada: es igual a `inicio + servicio.duracion_min` (I4, lo fuerza un trigger) y se guarda para poder aplicar la exclusion constraint y para que cambios futuros en la duración del servicio no alteren citas ya agendadas.
- estado_id
    - tipo: smallint
    - fk: estado_cita(estado_id)
    - null: no
    - default: 1
    - descripcion: Estado actual de la cita. Las transiciones inválidas las rechaza un trigger.
- cita_origen_id
    - tipo: bigint
    - fk: cita(clinica_id, cita_id) (compuesta)
    - null: si
    - descripcion: En una reprogramación, la cita anterior (marcada REPROGRAMADA) de la que proviene esta.
- creada_por
    - tipo: bigint
    - fk: usuario(clinica_id, usuario_id) (compuesta)
    - null: no
    - descripcion: Usuario que reservó la cita.
- cancelada_por
    - tipo: bigint
    - fk: usuario(clinica_id, usuario_id) (compuesta)
    - null: si
    - descripcion: Usuario que canceló (RF11). Obligatorio si el estado es CANCELADA.
- motivo_cancelacion
    - tipo: varchar(300)
    - null: si
    - descripcion: Motivo de la cancelación (RF11). Obligatorio si el estado es CANCELADA.
- desenlace_registrado_por
    - tipo: bigint
    - fk: usuario(clinica_id, usuario_id) (compuesta)
    - null: si
    - descripcion: Usuario que marcó la cita como ATENDIDA o AUSENTE (RF12).
- creada_en
    - tipo: timestamptz
    - null: no
    - default: now()
    - descripcion: Fecha de creación.
- actualizada_en
    - tipo: timestamptz
    - null: no
    - default: now()
    - descripcion: Última modificación.
- exclude (I1): `USING gist (profesional_id WITH =, tstzrange(inicio, fin) WITH &&) WHERE (estado_id = 1)`
    - descripcion: Un profesional nunca tiene dos citas vigentes solapadas. Es el mecanismo que decide la carrera: la segunda transacción recibe `exclusion_violation` (SQLSTATE 23P01), que la API traduce a "espacio ya tomado".
- exclude (I2): `USING gist (paciente_id WITH =, tstzrange(inicio, fin) WITH &&) WHERE (estado_id = 1)`
    - descripcion: Un paciente nunca tiene dos citas vigentes solapadas en su clínica.
- check: `(estado_id = 4) = (cancelada_por IS NOT NULL AND motivo_cancelacion IS NOT NULL)`
    - descripcion: Toda cancelación deja registrado quién y por qué.

---

### nota_clinica
Dato más sensible del sistema (RF15). Una nota por cita atendida, escrita solo por el profesional que la atendió.

- nota_id
    - tipo: bigint identity
    - pk: si
    - null: no
    - descripcion: Identificador de la nota.
- clinica_id
    - tipo: bigint
    - fk: clinica(clinica_id)
    - null: no
    - descripcion: Clínica de la nota.
- cita_id
    - tipo: bigint
    - fk: cita(clinica_id, cita_id, profesional_id) (compuesta)
    - unique: si
    - null: no
    - descripcion: Cita atendida a la que se adjunta (una nota por cita). Un trigger verifica que la cita esté en estado ATENDIDA.
- profesional_id
    - tipo: bigint
    - fk: cita(clinica_id, cita_id, profesional_id) (compuesta, misma FK que cita_id)
    - null: no
    - descripcion: Autor de la nota. La FK compuesta obliga a que sea el profesional de la cita.
- contenido
    - tipo: text
    - null: no
    - descripcion: Texto de la nota clínica.
- creada_en
    - tipo: timestamptz
    - null: no
    - default: now()
    - descripcion: Fecha de creación.
- actualizada_en
    - tipo: timestamptz
    - null: no
    - default: now()
    - descripcion: Fecha de la última edición.

---

### bitacora_auditoria
Registro append-only de toda lectura y escritura de notas clínicas y de datos de contacto de pacientes (RF18, RF19, I6).

- bitacora_id
    - tipo: bigint identity
    - pk: si
    - null: no
    - descripcion: Identificador secuencial del registro.
- clinica_id
    - tipo: bigint
    - fk: clinica(clinica_id)
    - null: no
    - descripcion: Clínica donde ocurrió el acceso.
- usuario_id
    - tipo: bigint
    - fk: usuario(clinica_id, usuario_id) (compuesta)
    - null: no
    - descripcion: Quién realizó la operación.
- paciente_id
    - tipo: bigint
    - fk: paciente(clinica_id, paciente_id) (compuesta)
    - null: no
    - descripcion: Sobre cuál paciente.
- accion
    - tipo: varchar(15)
    - null: no
    - check: accion IN ('LECTURA', 'CREACION', 'ACTUALIZACION')
    - descripcion: Qué se hizo.
- entidad
    - tipo: varchar(20)
    - null: no
    - check: entidad IN ('NOTA_CLINICA', 'PACIENTE_CONTACTO')
    - descripcion: Tipo de dato accedido.
- entidad_id
    - tipo: bigint
    - null: no
    - descripcion: Identificador de la nota o del paciente accedido (sin FK a propósito, para que la bitácora sobreviva a cualquier cambio en las tablas de negocio).
- ocurrido_en
    - tipo: timestamptz
    - null: no
    - default: now()
    - descripcion: Cuándo ocurrió.

---

# Índices

| Índice | Tabla | Columnas | Para qué |
|---|---|---|---|
| ix_cita_prof_inicio | cita | `(profesional_id, inicio)` solo citas vigentes | Disponibilidad (RF7, RF8) y agenda del profesional (RF20) |
| ix_cita_clinica_inicio | cita | `(clinica_id, inicio)` | Agenda de la clínica (RF20) y conteo por estado (RF21) |
| ix_cita_paciente_inicio | cita | `(paciente_id, inicio)` | Historial del paciente (RF16) |
| ix_horario_prof_dia | horario_atencion | `(profesional_id, dia_semana)` | Bloques del profesional en un día (RF7) |
| ix_bloqueo_prof_rango | bloqueo_agenda | `(profesional_id, rango de fechas)` (gist) | Bloqueos de una fecha y conflictos (RF6, RF7) |
| ix_paciente_busqueda | paciente | `(clinica_id, apellidos, nombre)` | Búsqueda de pacientes (RF14) |
| ix_bitacora_clinica_fecha | bitacora_auditoria | `(clinica_id, ocurrido_en)` | Consulta de bitácora por fechas (RF19) |
| ix_bitacora_paciente | bitacora_auditoria | `(clinica_id, paciente_id)` | Consulta de bitácora por paciente (RF19) |
| ix_bitacora_usuario | bitacora_auditoria | `(clinica_id, usuario_id)` | Consulta de bitácora por usuario (RF19) |

Las restricciones de no solapamiento de `cita` y `horario_atencion` crean sus propios índices. Requiere `CREATE EXTENSION btree_gist;`.

# Claves compuestas para integridad entre tenants

Para que ninguna FK pueda apuntar a una fila de otra clínica (refuerza I5 incluso si hubiera un error en la aplicación), cada tabla padre expone una restricción `UNIQUE (clinica_id, <pk>)` y las tablas hijas la referencian con FK compuesta que incluye `clinica_id`:

- `usuario`: UNIQUE (clinica_id, usuario_id)
- `profesional`: UNIQUE (clinica_id, profesional_id)
- `servicio`: UNIQUE (clinica_id, servicio_id)
- `paciente`: UNIQUE (clinica_id, paciente_id)
- `cita`: UNIQUE (clinica_id, cita_id) y UNIQUE (clinica_id, cita_id, profesional_id)

---


# Roles de base de datos (mínimo privilegio)

Roles `NOLOGIN` alineados con la matriz de permisos; el login `medicitas_app` es miembro de todos y cambia con `SET LOCAL ROLE` según el rol del token.

| Rol de BD | Corresponde a | Privilegios |
|---|---|---|
| `db_plataforma` | Administrador de plataforma | INSERT/SELECT en `clinica`; INSERT en `usuario` (solo `rol_id = 2`). Sin acceso a pacientes, citas, notas ni bitácora. |
| `db_admin_clinica` | Administrador de clínica | SELECT/INSERT/UPDATE en `usuario`, `profesional`, `servicio`, `profesional_servicio`, `horario_atencion`, `bloqueo_agenda`, `paciente`, `cita`; SELECT/INSERT en `bitacora_auditoria`. Sin acceso a `nota_clinica` (la matriz no se lo concede) y sin DELETE (bajas lógicas). |
| `db_recepcion` | Recepción | SELECT/INSERT/UPDATE en `paciente` y `cita`; SELECT en catálogos, `profesional`, `servicio`, `horario_atencion`, `bloqueo_agenda`; INSERT en `bitacora_auditoria`. Sin acceso a `nota_clinica`. |
| `db_profesional` | Profesional de salud | SELECT en `cita`, `paciente`, `horario_atencion`, `bloqueo_agenda` (+ INSERT/UPDATE en sus propios `horario_atencion` y `bloqueo_agenda`); UPDATE de `estado_id` en `cita`; SELECT/INSERT/UPDATE en `nota_clinica`; INSERT en `bitacora_auditoria`. |

Notas:
- La restricción "solo los propios" y "solo de citas propias" se refuerza con políticas RLS adicionales en `horario_atencion`, `bloqueo_agenda`, `cita` y `nota_clinica` para `db_profesional` (`profesional_id` = profesional del `app.usuario_id`).
- Ningún rol tiene DELETE ni TRUNCATE sobre tablas de negocio.
- Cualquier ampliación de la matriz mínima debe documentarse y justificarse.

---

# Bitácora append-only (I6) protegida en el motor

```sql
REVOKE ALL ON bitacora_auditoria FROM PUBLIC;
GRANT SELECT, INSERT ON bitacora_auditoria TO db_admin_clinica, db_recepcion, db_profesional;
-- ningún rol recibe UPDATE, DELETE ni TRUNCATE

CREATE FUNCTION bitacora_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'bitacora_auditoria es append-only';
END $$;

CREATE TRIGGER trg_bitacora_no_update_delete
    BEFORE UPDATE OR DELETE ON bitacora_auditoria
    FOR EACH ROW EXECUTE FUNCTION bitacora_inmutable();

CREATE TRIGGER trg_bitacora_no_truncate
    BEFORE TRUNCATE ON bitacora_auditoria
    FOR EACH STATEMENT EXECUTE FUNCTION bitacora_inmutable();
```

Doble barrera: privilegios (el motor niega la operación) y triggers (por si en el futuro se otorgara un permiso por error). Solo el dueño del esquema podría eliminar los triggers, y ese rol no lo usa la aplicación.

---

# Triggers de integridad

| Trigger | Tabla | Qué garantiza |
|---|---|---|
| trg_cita_fin_por_servicio | cita (BEFORE INSERT/UPDATE) | `fin = inicio + servicio.duracion_min` (I4); rechaza cualquier cambio de `fin` que no provenga de un cambio de `inicio` en reprogramación. |
| trg_cita_valida_agenda | cita (BEFORE INSERT/UPDATE de inicio/profesional) | La cita cae dentro de un bloque de `horario_atencion` del profesional (interpretado en la zona de la clínica) y no intersecta ningún `bloqueo_agenda` (I3); el profesional tiene asociado el servicio. |
| trg_cita_transicion_estado | cita (BEFORE UPDATE OF estado_id) | Solo se permite RESERVADA → ATENDIDA / AUSENTE / CANCELADA / REPROGRAMADA; los estados finales no admiten salida (RF13). ATENDIDA y AUSENTE solo si `now() >= inicio` (RF12). |
| trg_nota_cita_atendida | nota_clinica (BEFORE INSERT) | La cita referenciada está en estado ATENDIDA (RF15). |
| trg_profesional_usuario_rol | profesional (BEFORE INSERT/UPDATE) | El usuario ligado tiene `rol_id = 4` (PROFESIONAL). |
| trg_servicio_especialidad | profesional_servicio (BEFORE INSERT) | La especialidad del profesional coincide con la que requiere el servicio. |

---

# Normalización y desnormalizaciones

- **1FN**: todos los atributos son atómicos; los horarios con varios bloques por día son filas de `horario_atencion`, no listas.
- **2FN**: en las tablas con clave compuesta (`profesional_servicio`) no hay atributos descriptivos, solo la clave.
- **3FN**: no hay dependencias transitivas; especialidad, rol y estado viven en catálogos, y los datos de la clínica no se repiten en sus entidades hijas.
- **Desnormalización deliberada 1 (`cita.fin`)**: derivable de `inicio` y la duración del servicio, pero necesaria para las exclusion constraints I1/I2, y además congela la duración de citas ya agendadas ante cambios del catálogo. Se mantiene consistente con un trigger (I4).
- **Desnormalización deliberada 2 (`clinica_id` en tablas hijas)**: es redundante respecto a la cadena de FKs, pero es lo que permite RLS directa (sin joins en las políticas) y las FK compuestas que impiden referencias entre tenants.