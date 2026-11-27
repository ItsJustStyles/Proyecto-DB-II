
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- =====================================================================
-- TABLAS
-- =====================================================================

CREATE TABLE clinica (
    clinica_id    bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre        varchar(150) NOT NULL UNIQUE,
    zona_horaria  varchar(64)  NOT NULL DEFAULT 'America/Costa_Rica',
    activa        boolean      NOT NULL DEFAULT true,
    creada_en     timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE rol (
    rol_id  smallint    PRIMARY KEY,
    nombre  varchar(30) NOT NULL UNIQUE
);

CREATE TABLE especialidad (
    especialidad_id  smallint    GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre           varchar(80) NOT NULL UNIQUE
);

CREATE TABLE estado_cita (
    estado_id  smallint    PRIMARY KEY,
    codigo     varchar(20) NOT NULL UNIQUE,
    es_final   boolean     NOT NULL,
    CONSTRAINT ck_estado_cita_es_final CHECK (es_final = (estado_id <> 1))
);

CREATE TABLE usuario (
    usuario_id    bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clinica_id    bigint       REFERENCES clinica (clinica_id),
    rol_id        smallint     NOT NULL REFERENCES rol (rol_id),
    keycloak_sub  uuid         NOT NULL UNIQUE,
    nombre        varchar(150) NOT NULL,
    activo        boolean      NOT NULL DEFAULT true,
    creado_en     timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_usuario_clinica UNIQUE (clinica_id, usuario_id),
    -- Solo el administrador de plataforma (rol 1) carece de clinica
    CONSTRAINT ck_usuario_clinica_rol CHECK ((rol_id = 1) = (clinica_id IS NULL))
);

CREATE TABLE profesional (
    profesional_id   bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clinica_id       bigint       NOT NULL REFERENCES clinica (clinica_id),
    usuario_id       bigint       NOT NULL UNIQUE,
    especialidad_id  smallint     NOT NULL REFERENCES especialidad (especialidad_id),
    nombre           varchar(150) NOT NULL,
    activo           boolean      NOT NULL DEFAULT true,
    CONSTRAINT uq_profesional_clinica UNIQUE (clinica_id, profesional_id),
    CONSTRAINT fk_profesional_usuario FOREIGN KEY (clinica_id, usuario_id)
        REFERENCES usuario (clinica_id, usuario_id)
);

CREATE TABLE servicio (
    servicio_id      bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clinica_id       bigint       NOT NULL REFERENCES clinica (clinica_id),
    nombre           varchar(120) NOT NULL,
    duracion_min     smallint     NOT NULL,
    especialidad_id  smallint     NOT NULL REFERENCES especialidad (especialidad_id),
    activo           boolean      NOT NULL DEFAULT true,
    CONSTRAINT uq_servicio_clinica UNIQUE (clinica_id, servicio_id),
    CONSTRAINT uq_servicio_nombre UNIQUE (clinica_id, nombre),
    CONSTRAINT ck_servicio_duracion CHECK (duracion_min > 0 AND duracion_min <= 480)
);

CREATE TABLE profesional_servicio (
    clinica_id      bigint NOT NULL REFERENCES clinica (clinica_id),
    profesional_id  bigint NOT NULL,
    servicio_id     bigint NOT NULL,
    PRIMARY KEY (clinica_id, profesional_id, servicio_id),
    CONSTRAINT fk_ps_profesional FOREIGN KEY (clinica_id, profesional_id)
        REFERENCES profesional (clinica_id, profesional_id),
    CONSTRAINT fk_ps_servicio FOREIGN KEY (clinica_id, servicio_id)
        REFERENCES servicio (clinica_id, servicio_id)
);

CREATE TABLE horario_atencion (
    horario_id      bigint   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clinica_id      bigint   NOT NULL REFERENCES clinica (clinica_id),
    profesional_id  bigint   NOT NULL,
    dia_semana      smallint NOT NULL,
    hora_inicio     time     NOT NULL,
    hora_fin        time     NOT NULL,
    CONSTRAINT fk_horario_profesional FOREIGN KEY (clinica_id, profesional_id)
        REFERENCES profesional (clinica_id, profesional_id),
    CONSTRAINT ck_horario_dia CHECK (dia_semana BETWEEN 1 AND 7),
    CONSTRAINT ck_horario_horas CHECK (hora_fin > hora_inicio),
    -- PostgreSQL no tiene timerange: se usa tsrange sobre una fecha fija
    CONSTRAINT ex_horario_sin_solape EXCLUDE USING gist (
        profesional_id WITH =,
        dia_semana WITH =,
        tsrange(DATE '2000-01-01' + hora_inicio, DATE '2000-01-01' + hora_fin) WITH &&
    )
);

CREATE TABLE bloqueo_agenda (
    bloqueo_id      bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clinica_id      bigint       NOT NULL REFERENCES clinica (clinica_id),
    profesional_id  bigint       NOT NULL,
    inicio          timestamptz  NOT NULL,
    fin             timestamptz  NOT NULL,
    motivo          varchar(200),
    creado_por      bigint       NOT NULL,
    creado_en       timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT fk_bloqueo_profesional FOREIGN KEY (clinica_id, profesional_id)
        REFERENCES profesional (clinica_id, profesional_id),
    CONSTRAINT fk_bloqueo_creado_por FOREIGN KEY (clinica_id, creado_por)
        REFERENCES usuario (clinica_id, usuario_id),
    CONSTRAINT ck_bloqueo_rango CHECK (fin > inicio)
);

CREATE TABLE paciente (
    paciente_id       bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clinica_id        bigint       NOT NULL REFERENCES clinica (clinica_id),
    identificacion    varchar(30)  NOT NULL,
    nombre            varchar(100) NOT NULL,
    apellidos         varchar(100) NOT NULL,
    fecha_nacimiento  date         NOT NULL,
    telefono          varchar(30),
    correo            varchar(254),
    activo            boolean      NOT NULL DEFAULT true,
    creado_en         timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_paciente_clinica UNIQUE (clinica_id, paciente_id),
    CONSTRAINT uq_paciente_identificacion UNIQUE (clinica_id, identificacion),
    CONSTRAINT ck_paciente_nacimiento CHECK (fecha_nacimiento <= current_date)
);

CREATE TABLE cita (
    cita_id                   bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clinica_id                bigint       NOT NULL REFERENCES clinica (clinica_id),
    paciente_id               bigint       NOT NULL,
    profesional_id            bigint       NOT NULL,
    servicio_id               bigint       NOT NULL,
    inicio                    timestamptz  NOT NULL,
    -- fin lo calcula el trigger a partir de la duracion del servicio (I4);
    -- el INSERT no necesita enviarlo
    fin                       timestamptz  NOT NULL,
    estado_id                 smallint     NOT NULL DEFAULT 1 REFERENCES estado_cita (estado_id),
    cita_origen_id            bigint,
    creada_por                bigint       NOT NULL,
    cancelada_por             bigint,
    motivo_cancelacion        varchar(300),
    desenlace_registrado_por  bigint,
    creada_en                 timestamptz  NOT NULL DEFAULT now(),
    actualizada_en            timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_cita_clinica UNIQUE (clinica_id, cita_id),
    CONSTRAINT uq_cita_clinica_profesional UNIQUE (clinica_id, cita_id, profesional_id),
    CONSTRAINT fk_cita_paciente FOREIGN KEY (clinica_id, paciente_id)
        REFERENCES paciente (clinica_id, paciente_id),
    CONSTRAINT fk_cita_profesional FOREIGN KEY (clinica_id, profesional_id)
        REFERENCES profesional (clinica_id, profesional_id),
    CONSTRAINT fk_cita_servicio FOREIGN KEY (clinica_id, servicio_id)
        REFERENCES servicio (clinica_id, servicio_id),
    CONSTRAINT fk_cita_origen FOREIGN KEY (clinica_id, cita_origen_id)
        REFERENCES cita (clinica_id, cita_id),
    CONSTRAINT fk_cita_creada_por FOREIGN KEY (clinica_id, creada_por)
        REFERENCES usuario (clinica_id, usuario_id),
    CONSTRAINT fk_cita_cancelada_por FOREIGN KEY (clinica_id, cancelada_por)
        REFERENCES usuario (clinica_id, usuario_id),
    CONSTRAINT fk_cita_desenlace_por FOREIGN KEY (clinica_id, desenlace_registrado_por)
        REFERENCES usuario (clinica_id, usuario_id),
    CONSTRAINT ck_cita_rango CHECK (fin > inicio),
    -- Toda cancelacion deja registrado quien y por que (RF11)
    CONSTRAINT ck_cita_cancelacion CHECK (
        (estado_id = 4) = (cancelada_por IS NOT NULL AND motivo_cancelacion IS NOT NULL)
    ),
    -- I1: un profesional nunca tiene dos citas vigentes solapadas.
    -- Los rangos son [inicio, fin): una cita puede empezar justo cuando otra termina.
    -- Reprogramar: primero pasar la cita vieja a REPROGRAMADA y luego insertar la
    -- nueva, dentro de la misma transaccion.
    CONSTRAINT ex_cita_profesional_sin_solape EXCLUDE USING gist (
        profesional_id WITH =,
        tstzrange(inicio, fin) WITH &&
    ) WHERE (estado_id = 1),
    -- I2: un paciente nunca tiene dos citas vigentes solapadas
    CONSTRAINT ex_cita_paciente_sin_solape EXCLUDE USING gist (
        paciente_id WITH =,
        tstzrange(inicio, fin) WITH &&
    ) WHERE (estado_id = 1)
);

CREATE TABLE nota_clinica (
    nota_id         bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clinica_id      bigint       NOT NULL REFERENCES clinica (clinica_id),
    cita_id         bigint       NOT NULL UNIQUE,
    profesional_id  bigint       NOT NULL,
    contenido       text         NOT NULL,
    creada_en       timestamptz  NOT NULL DEFAULT now(),
    actualizada_en  timestamptz  NOT NULL DEFAULT now(),
    -- La FK compuesta obliga a que el autor sea el profesional de la cita
    CONSTRAINT fk_nota_cita FOREIGN KEY (clinica_id, cita_id, profesional_id)
        REFERENCES cita (clinica_id, cita_id, profesional_id)
);

CREATE TABLE bitacora_auditoria (
    bitacora_id  bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clinica_id   bigint       NOT NULL REFERENCES clinica (clinica_id),
    usuario_id   bigint       NOT NULL,
    paciente_id  bigint       NOT NULL,
    accion       varchar(15)  NOT NULL,
    entidad      varchar(20)  NOT NULL,
    -- sin FK a proposito: la bitacora debe sobrevivir a cambios en las tablas de negocio
    entidad_id   bigint       NOT NULL,
    ocurrido_en  timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT fk_bitacora_usuario FOREIGN KEY (clinica_id, usuario_id)
        REFERENCES usuario (clinica_id, usuario_id),
    CONSTRAINT fk_bitacora_paciente FOREIGN KEY (clinica_id, paciente_id)
        REFERENCES paciente (clinica_id, paciente_id),
    CONSTRAINT ck_bitacora_accion CHECK (accion IN ('LECTURA', 'CREACION', 'ACTUALIZACION')),
    CONSTRAINT ck_bitacora_entidad CHECK (entidad IN ('NOTA_CLINICA', 'PACIENTE_CONTACTO'))
);

-- =====================================================================
-- INDICES
-- (las exclusion constraints de cita y horario_atencion crean los suyos)
-- =====================================================================

CREATE INDEX ix_cita_prof_inicio       ON cita (profesional_id, inicio) WHERE estado_id = 1;
CREATE INDEX ix_cita_clinica_inicio    ON cita (clinica_id, inicio);
CREATE INDEX ix_cita_paciente_inicio   ON cita (paciente_id, inicio);
CREATE INDEX ix_horario_prof_dia       ON horario_atencion (profesional_id, dia_semana);
CREATE INDEX ix_bloqueo_prof_rango     ON bloqueo_agenda USING gist (profesional_id, tstzrange(inicio, fin));
CREATE INDEX ix_paciente_busqueda      ON paciente (clinica_id, apellidos, nombre);
CREATE INDEX ix_bitacora_clinica_fecha ON bitacora_auditoria (clinica_id, ocurrido_en);
CREATE INDEX ix_bitacora_paciente      ON bitacora_auditoria (clinica_id, paciente_id);
CREATE INDEX ix_bitacora_usuario       ON bitacora_auditoria (clinica_id, usuario_id);

-- =====================================================================
-- FUNCIONES Y TRIGGERS DE INTEGRIDAD
-- Las funciones que consultan otras tablas son SECURITY DEFINER para no
-- depender de los permisos de lectura del rol que ejecuta la operacion.
-- =====================================================================

-- Mantiene actualizada_en
CREATE FUNCTION fn_set_actualizada_en() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.actualizada_en := now();
    RETURN NEW;
END $$;

CREATE TRIGGER trg_cita_actualizada_en
    BEFORE UPDATE ON cita
    FOR EACH ROW EXECUTE FUNCTION fn_set_actualizada_en();

CREATE TRIGGER trg_nota_actualizada_en
    BEFORE UPDATE ON nota_clinica
    FOR EACH ROW EXECUTE FUNCTION fn_set_actualizada_en();

-- I4: fin = inicio + duracion del servicio; nada la altera por su cuenta.
-- Orden de ejecucion (alfabetico): este trigger corre antes que trg_cita_valida_agenda.
CREATE FUNCTION fn_cita_fin_por_servicio() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_duracion smallint;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.inicio = OLD.inicio AND NEW.servicio_id = OLD.servicio_id THEN
        NEW.fin := OLD.fin;
        RETURN NEW;
    END IF;

    SELECT duracion_min INTO v_duracion
      FROM servicio
     WHERE clinica_id = NEW.clinica_id AND servicio_id = NEW.servicio_id;

    IF v_duracion IS NULL THEN
        RAISE EXCEPTION 'Servicio inexistente en la clinica' USING ERRCODE = 'foreign_key_violation';
    END IF;

    NEW.fin := NEW.inicio + make_interval(mins => v_duracion);
    RETURN NEW;
END $$;

CREATE TRIGGER trg_cita_fin_por_servicio
    BEFORE INSERT OR UPDATE ON cita
    FOR EACH ROW EXECUTE FUNCTION fn_cita_fin_por_servicio();

-- I3: la cita vigente cae dentro del horario y fuera de los bloqueos;
-- el profesional esta activo y tiene asociado el servicio.
CREATE FUNCTION fn_cita_valida_agenda() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_activo boolean;
    v_zona   varchar;
    v_ini    timestamp;
    v_fin    timestamp;
BEGIN
    IF NEW.estado_id <> 1 THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE'
       AND NEW.inicio = OLD.inicio
       AND NEW.profesional_id = OLD.profesional_id
       AND NEW.servicio_id = OLD.servicio_id THEN
        RETURN NEW;
    END IF;

    SELECT activo INTO v_activo
      FROM profesional
     WHERE clinica_id = NEW.clinica_id AND profesional_id = NEW.profesional_id;
    IF NOT COALESCE(v_activo, false) THEN
        RAISE EXCEPTION 'El profesional no existe o esta inactivo' USING ERRCODE = 'MC002';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM profesional_servicio
                    WHERE clinica_id = NEW.clinica_id
                      AND profesional_id = NEW.profesional_id
                      AND servicio_id = NEW.servicio_id) THEN
        RAISE EXCEPTION 'El profesional no atiende ese servicio' USING ERRCODE = 'MC002';
    END IF;

    SELECT zona_horaria INTO v_zona FROM clinica WHERE clinica_id = NEW.clinica_id;
    v_ini := NEW.inicio AT TIME ZONE v_zona;
    v_fin := NEW.fin    AT TIME ZONE v_zona;

    IF v_ini::date <> v_fin::date
       OR NOT EXISTS (SELECT 1 FROM horario_atencion h
                       WHERE h.clinica_id = NEW.clinica_id
                         AND h.profesional_id = NEW.profesional_id
                         AND h.dia_semana = EXTRACT(ISODOW FROM v_ini)::smallint
                         AND h.hora_inicio <= v_ini::time
                         AND h.hora_fin >= v_fin::time) THEN
        RAISE EXCEPTION 'La cita queda fuera del horario de atencion' USING ERRCODE = 'MC002';
    END IF;

    IF EXISTS (SELECT 1 FROM bloqueo_agenda b
                WHERE b.clinica_id = NEW.clinica_id
                  AND b.profesional_id = NEW.profesional_id
                  AND tstzrange(b.inicio, b.fin) && tstzrange(NEW.inicio, NEW.fin)) THEN
        RAISE EXCEPTION 'La cita cae dentro de un bloqueo de agenda' USING ERRCODE = 'MC002';
    END IF;

    RETURN NEW;
END $$;

CREATE TRIGGER trg_cita_valida_agenda
    BEFORE INSERT OR UPDATE ON cita
    FOR EACH ROW EXECUTE FUNCTION fn_cita_valida_agenda();

-- RF13 / RF12: maquina de estados de la cita
CREATE FUNCTION fn_cita_transicion_estado() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.estado_id = OLD.estado_id THEN
        RETURN NEW;
    END IF;
    IF OLD.estado_id <> 1 THEN
        RAISE EXCEPTION 'Una cita en estado final no admite cambios de estado' USING ERRCODE = 'MC001';
    END IF;
    IF NEW.estado_id NOT IN (2, 3, 4, 5) THEN
        RAISE EXCEPTION 'Transicion de estado no permitida' USING ERRCODE = 'MC001';
    END IF;
    IF NEW.estado_id IN (2, 3) AND now() < OLD.inicio THEN
        RAISE EXCEPTION 'El desenlace solo se registra una vez pasada la hora de inicio' USING ERRCODE = 'MC001';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_cita_transicion_estado
    BEFORE UPDATE OF estado_id ON cita
    FOR EACH ROW EXECUTE FUNCTION fn_cita_transicion_estado();

-- RF15: la nota solo se adjunta a una cita atendida
CREATE FUNCTION fn_nota_cita_atendida() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM cita
                    WHERE clinica_id = NEW.clinica_id
                      AND cita_id = NEW.cita_id
                      AND estado_id = 2) THEN
        RAISE EXCEPTION 'La nota clinica solo se adjunta a una cita atendida' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_nota_cita_atendida
    BEFORE INSERT ON nota_clinica
    FOR EACH ROW EXECUTE FUNCTION fn_nota_cita_atendida();

-- El usuario ligado a un profesional debe tener rol PROFESIONAL (4)
CREATE FUNCTION fn_profesional_usuario_rol() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rol smallint;
BEGIN
    SELECT rol_id INTO v_rol
      FROM usuario
     WHERE clinica_id = NEW.clinica_id AND usuario_id = NEW.usuario_id;
    IF v_rol IS DISTINCT FROM 4 THEN
        RAISE EXCEPTION 'El usuario del profesional debe tener rol PROFESIONAL' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_profesional_usuario_rol
    BEFORE INSERT OR UPDATE OF usuario_id ON profesional
    FOR EACH ROW EXECUTE FUNCTION fn_profesional_usuario_rol();

-- La especialidad del profesional debe coincidir con la que requiere el servicio
CREATE FUNCTION fn_servicio_especialidad() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_esp_prof smallint;
    v_esp_serv smallint;
BEGIN
    SELECT especialidad_id INTO v_esp_prof
      FROM profesional
     WHERE clinica_id = NEW.clinica_id AND profesional_id = NEW.profesional_id;
    SELECT especialidad_id INTO v_esp_serv
      FROM servicio
     WHERE clinica_id = NEW.clinica_id AND servicio_id = NEW.servicio_id;
    IF v_esp_prof IS DISTINCT FROM v_esp_serv THEN
        RAISE EXCEPTION 'La especialidad del profesional no coincide con la del servicio' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_servicio_especialidad
    BEFORE INSERT OR UPDATE ON profesional_servicio
    FOR EACH ROW EXECUTE FUNCTION fn_servicio_especialidad();

-- I6: bitacora append-only (segunda barrera; la primera son los permisos)
CREATE FUNCTION fn_bitacora_inmutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'bitacora_auditoria es append-only';
END $$;

CREATE TRIGGER trg_bitacora_no_update_delete
    BEFORE UPDATE OR DELETE ON bitacora_auditoria
    FOR EACH ROW EXECUTE FUNCTION fn_bitacora_inmutable();

CREATE TRIGGER trg_bitacora_no_truncate
    BEFORE TRUNCATE ON bitacora_auditoria
    FOR EACH STATEMENT EXECUTE FUNCTION fn_bitacora_inmutable();

-- RF1: alta de clinica + primer administrador en una sola transaccion.
-- El administrador de plataforma no puede hacer INSERT directo en usuario:
-- solo ejecuta esta funcion.
CREATE FUNCTION crear_clinica(
    p_nombre        varchar,
    p_zona_horaria  varchar,
    p_admin_sub     uuid,
    p_admin_nombre  varchar
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_clinica_id bigint;
BEGIN
    INSERT INTO clinica (nombre, zona_horaria)
    VALUES (p_nombre, p_zona_horaria)
    RETURNING clinica_id INTO v_clinica_id;

    INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre)
    VALUES (v_clinica_id, 2, p_admin_sub, p_admin_nombre);

    RETURN v_clinica_id;
END $$;

-- =====================================================================
-- ROLES DE BASE DE DATOS (minimo privilegio, alineados con la matriz)
-- medicitas_app es el login de la aplicacion: NOINHERIT, de modo que no
-- tiene los permisos de los otros roles hasta ejecutar SET LOCAL ROLE.
-- CAMBIAR la contrasena (idealmente tomarla del .env al desplegar).
-- =====================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'db_plataforma') THEN
        CREATE ROLE db_plataforma NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'db_admin_clinica') THEN
        CREATE ROLE db_admin_clinica NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'db_recepcion') THEN
        CREATE ROLE db_recepcion NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'db_profesional') THEN
        CREATE ROLE db_profesional NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'medicitas_app') THEN
        EXECUTE format('CREATE ROLE medicitas_app LOGIN NOINHERIT PASSWORD %L', '${medicitas_app_password}');
    END IF;
END $$;

GRANT db_plataforma, db_admin_clinica, db_recepcion, db_profesional TO medicitas_app;
REVOKE ALL ON FUNCTION crear_clinica(varchar, varchar, uuid, varchar) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION crear_clinica(varchar, varchar, uuid, varchar) TO db_plataforma;

-- Todos los roles: catalogos y datos de la clinica (zona horaria)
GRANT SELECT ON rol, especialidad, estado_cita, clinica
    TO db_plataforma, db_admin_clinica, db_recepcion, db_profesional, medicitas_app;

-- Resolucion de identidad: keycloak_sub -> (usuario, clinica, rol), antes de elegir rol
GRANT SELECT (usuario_id, clinica_id, rol_id, keycloak_sub, activo) ON usuario TO medicitas_app;

-- ---- Administrador de clinica ---------------------------------------
-- UPDATE por columnas: ningun rol puede cambiar clinica_id de una fila existente.
GRANT SELECT, INSERT ON usuario, profesional, servicio, paciente, cita TO db_admin_clinica;
GRANT UPDATE (rol_id, nombre, activo) ON usuario  TO db_admin_clinica;
GRANT UPDATE (especialidad_id, nombre, activo) ON profesional TO db_admin_clinica;
GRANT UPDATE (nombre, duracion_min, especialidad_id, activo) ON servicio TO db_admin_clinica;
GRANT UPDATE (identificacion, nombre, apellidos, fecha_nacimiento, telefono, correo, activo) ON paciente TO db_admin_clinica;
GRANT UPDATE (estado_id, cancelada_por, motivo_cancelacion, desenlace_registrado_por) ON cita TO db_admin_clinica;
-- Tablas de configuracion (sin datos clinicos): se admite borrar
GRANT SELECT, INSERT, DELETE ON profesional_servicio, horario_atencion, bloqueo_agenda TO db_admin_clinica;
GRANT UPDATE (dia_semana, hora_inicio, hora_fin) ON horario_atencion TO db_admin_clinica;
GRANT UPDATE (inicio, fin, motivo) ON bloqueo_agenda TO db_admin_clinica;
-- Sin acceso a nota_clinica (la matriz no se lo concede)

-- ---- Recepcion --------------------------------------------------------
GRANT SELECT ON profesional, servicio, profesional_servicio, horario_atencion, bloqueo_agenda TO db_recepcion;
GRANT SELECT, INSERT ON paciente, cita TO db_recepcion;
GRANT UPDATE (identificacion, nombre, apellidos, fecha_nacimiento, telefono, correo, activo) ON paciente TO db_recepcion;
GRANT UPDATE (estado_id, cancelada_por, motivo_cancelacion, desenlace_registrado_por) ON cita TO db_recepcion;
-- Sin acceso a nota_clinica

-- ---- Profesional de salud ---------------------------------------------
-- "Solo los propios" (horarios, bloqueos, notas de citas propias) lo aplica la capa
-- de acceso de la aplicacion; sin RLS el motor no puede distinguir las filas propias.
GRANT SELECT ON cita, paciente, profesional, servicio, profesional_servicio,
                horario_atencion, bloqueo_agenda TO db_profesional;
GRANT INSERT, DELETE ON horario_atencion, bloqueo_agenda TO db_profesional;
GRANT UPDATE (dia_semana, hora_inicio, hora_fin) ON horario_atencion TO db_profesional;
GRANT UPDATE (inicio, fin, motivo) ON bloqueo_agenda  TO db_profesional;
GRANT UPDATE (estado_id, desenlace_registrado_por) ON cita TO db_profesional;
GRANT SELECT, INSERT ON nota_clinica TO db_profesional;
GRANT UPDATE (contenido) ON nota_clinica TO db_profesional;

-- ---- Bitacora: append-only protegida en el motor (I6) --------------------
REVOKE ALL ON bitacora_auditoria FROM PUBLIC;
GRANT INSERT ON bitacora_auditoria TO db_admin_clinica, db_recepcion, db_profesional;
GRANT SELECT ON bitacora_auditoria TO db_admin_clinica;   -- RF19: solo el admin de clinica consulta
-- ningun rol recibe UPDATE, DELETE ni TRUNCATE

-- =====================================================================
-- DATOS INICIALES DE CATALOGOS
-- =====================================================================

INSERT INTO rol (rol_id, nombre) VALUES
    (1, 'ADMIN_PLATAFORMA'),
    (2, 'ADMIN_CLINICA'),
    (3, 'RECEPCION'),
    (4, 'PROFESIONAL')
ON CONFLICT DO NOTHING;

INSERT INTO estado_cita (estado_id, codigo, es_final) VALUES
    (1, 'RESERVADA',    false),
    (2, 'ATENDIDA',     true),
    (3, 'AUSENTE',      true),
    (4, 'CANCELADA',    true),
    (5, 'REPROGRAMADA', true)
ON CONFLICT DO NOTHING;

INSERT INTO especialidad (nombre) VALUES
    ('Medicina General'),
    ('Pediatría'),
    ('Cardiología'),
    ('Dermatología'),
    ('Ginecología'),
    ('Ortopedia')
ON CONFLICT DO NOTHING;