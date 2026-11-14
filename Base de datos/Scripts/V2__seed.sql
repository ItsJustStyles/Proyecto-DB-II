-- Datos para probar el backend.

DO $$
DECLARE
    v_esp_general       smallint;
    v_esp_pediatria     smallint;
    v_esp_cardiologia   smallint;

    v_clinica_norte     bigint;
    v_clinica_sur       bigint;

    v_admin_plataforma  bigint;
    v_admin_norte       bigint;
    v_recepcion_norte   bigint;
    v_prof_usuario_1    bigint;
    v_prof_usuario_2    bigint;
    v_prof_usuario_3    bigint;
    v_admin_sur         bigint;
    v_recepcion_sur     bigint;
    v_prof_usuario_sur  bigint;

    v_prof_norte_1      bigint;
    v_prof_norte_2      bigint;
    v_prof_norte_3      bigint;
    v_prof_sur          bigint;

    v_serv_general      bigint;
    v_serv_pediatria    bigint;
    v_serv_cardiologia  bigint;
    v_serv_sur          bigint;

    v_paciente_1        bigint;
    v_paciente_2        bigint;
    v_paciente_3        bigint;
    v_paciente_4        bigint;
    v_paciente_sur      bigint;

    v_cita_reservada    bigint;
    v_cita_atendida     bigint;
    v_cita_ausente      bigint;
    v_cita_cancelada    bigint;
    v_cita_reprogramada bigint;
    v_cita_reemplazo    bigint;
    v_cita_sur          bigint;
    v_nota              bigint;
BEGIN
    SELECT especialidad_id INTO v_esp_general
      FROM especialidad WHERE nombre = 'Medicina General';

    SELECT especialidad_id INTO v_esp_pediatria
      FROM especialidad WHERE nombre = 'Pediatría';

    SELECT especialidad_id INTO v_esp_cardiologia
      FROM especialidad WHERE nombre = 'Cardiología';

    -- Administrador de plataforma: es el unico usuario sin clinica.
    INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre)
    VALUES (NULL, 1, '00000000-0000-4000-8000-000000000001', 'Administrador de plataforma')
    RETURNING usuario_id INTO v_admin_plataforma;

    -- Clinica principal de demostracion.
    SELECT crear_clinica(
        'Clinica Demo Norte',
        'America/Costa_Rica',
        '00000000-0000-4000-8000-000000000101',
        'Administrador Demo Norte'
    ) INTO v_clinica_norte;

    SELECT usuario_id INTO v_admin_norte
      FROM usuario
     WHERE clinica_id = v_clinica_norte
       AND keycloak_sub = '00000000-0000-4000-8000-000000000101';

    INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre)
    VALUES
        (v_clinica_norte, 3, '00000000-0000-4000-8000-000000000102', 'Recepcion Demo Norte'),
        (v_clinica_norte, 4, '00000000-0000-4000-8000-000000000103', 'Profesional General Demo'),
        (v_clinica_norte, 4, '00000000-0000-4000-8000-000000000104', 'Profesional Pediatria Demo'),
        (v_clinica_norte, 4, '00000000-0000-4000-8000-000000000105', 'Profesional Cardiologia Demo');

    SELECT usuario_id INTO v_recepcion_norte
      FROM usuario WHERE keycloak_sub = '00000000-0000-4000-8000-000000000102';

    SELECT usuario_id INTO v_prof_usuario_1
      FROM usuario WHERE keycloak_sub = '00000000-0000-4000-8000-000000000103';

    SELECT usuario_id INTO v_prof_usuario_2
      FROM usuario WHERE keycloak_sub = '00000000-0000-4000-8000-000000000104';

    SELECT usuario_id INTO v_prof_usuario_3
      FROM usuario WHERE keycloak_sub = '00000000-0000-4000-8000-000000000105';

    INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, nombre)
    VALUES
        (v_clinica_norte, v_prof_usuario_1, v_esp_general, 'Dra. Ana General'),
        (v_clinica_norte, v_prof_usuario_2, v_esp_pediatria, 'Dr. Luis Pediatria'),
        (v_clinica_norte, v_prof_usuario_3, v_esp_cardiologia, 'Dr. Carlos Cardiologia');

    SELECT profesional_id INTO v_prof_norte_1
      FROM profesional WHERE clinica_id = v_clinica_norte AND usuario_id = v_prof_usuario_1;

    SELECT profesional_id INTO v_prof_norte_2
      FROM profesional WHERE clinica_id = v_clinica_norte AND usuario_id = v_prof_usuario_2;

    SELECT profesional_id INTO v_prof_norte_3
      FROM profesional WHERE clinica_id = v_clinica_norte AND usuario_id = v_prof_usuario_3;

    INSERT INTO servicio (clinica_id, nombre, duracion_min, especialidad_id, activo)
    VALUES
        (v_clinica_norte, 'Consulta general', 30, v_esp_general, true),
        (v_clinica_norte, 'Consulta pediatrica', 45, v_esp_pediatria, true),
        (v_clinica_norte, 'Consulta cardiologica', 60, v_esp_cardiologia, true),
        (v_clinica_norte, 'Servicio temporalmente inactivo', 30, v_esp_general, false);

    SELECT servicio_id INTO v_serv_general
      FROM servicio WHERE clinica_id = v_clinica_norte AND nombre = 'Consulta general';

    SELECT servicio_id INTO v_serv_pediatria
      FROM servicio WHERE clinica_id = v_clinica_norte AND nombre = 'Consulta pediatrica';

    SELECT servicio_id INTO v_serv_cardiologia
      FROM servicio WHERE clinica_id = v_clinica_norte AND nombre = 'Consulta cardiologica';

    INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id)
    VALUES
        (v_clinica_norte, v_prof_norte_1, v_serv_general),
        (v_clinica_norte, v_prof_norte_2, v_serv_pediatria),
        (v_clinica_norte, v_prof_norte_3, v_serv_cardiologia);

    -- Toda la semana, para que las fechas relativas siempre tengan agenda.
    INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin)
    SELECT v_clinica_norte, profesionales.profesional_id, dias.dia_semana::smallint,
           TIME '08:00', TIME '17:00'
      FROM (VALUES (v_prof_norte_1), (v_prof_norte_2), (v_prof_norte_3))
           AS profesionales(profesional_id)
      CROSS JOIN generate_series(1, 7) AS dias(dia_semana);

    INSERT INTO paciente (
        clinica_id, identificacion, nombre, apellidos, fecha_nacimiento,
        telefono, correo, activo
    )
    VALUES (
        v_clinica_norte, 'TEST-001', 'Ana', 'Prueba Norte',
        DATE '1990-05-10', '+506-8000-0001', 'ana.norte@example.test', true
    )
    RETURNING paciente_id INTO v_paciente_1;

    INSERT INTO paciente (
        clinica_id, identificacion, nombre, apellidos, fecha_nacimiento,
        telefono, correo, activo
    )
    VALUES (
        v_clinica_norte, 'TEST-002', 'Luis', 'Prueba Norte',
        DATE '1985-02-20', NULL, NULL, true
    )
    RETURNING paciente_id INTO v_paciente_2;

    INSERT INTO paciente (
        clinica_id, identificacion, nombre, apellidos, fecha_nacimiento,
        telefono, correo, activo
    )
    VALUES (
        v_clinica_norte, 'TEST-003', 'Sara', 'Prueba Norte',
        DATE '2000-08-15', '+506-8000-0003', 'sara.norte@example.test', true
    )
    RETURNING paciente_id INTO v_paciente_3;

    INSERT INTO paciente (
        clinica_id, identificacion, nombre, apellidos, fecha_nacimiento,
        telefono, correo, activo
    )
    VALUES (
        v_clinica_norte, 'TEST-004', 'Mario', 'Prueba Norte',
        DATE '1970-12-01', '+506-8000-0004', NULL, false
    )
    RETURNING paciente_id INTO v_paciente_4;

    INSERT INTO bloqueo_agenda (
        clinica_id, profesional_id, inicio, fin, motivo, creado_por
    )
    VALUES (
        v_clinica_norte,
        v_prof_norte_3,
        ((CURRENT_DATE + 1)::timestamp + TIME '14:00') AT TIME ZONE 'America/Costa_Rica',
        ((CURRENT_DATE + 1)::timestamp + TIME '16:00') AT TIME ZONE 'America/Costa_Rica',
        'Vacaciones de demostracion',
        v_admin_norte
    );

    -- Cita reservada futura.
    INSERT INTO cita (
        clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin,
        estado_id, creada_por
    )
    VALUES (
        v_clinica_norte, v_paciente_1, v_prof_norte_1, v_serv_general,
        ((CURRENT_DATE + 1)::timestamp + TIME '09:00') AT TIME ZONE 'America/Costa_Rica',
        ((CURRENT_DATE + 1)::timestamp + TIME '09:00') AT TIME ZONE 'America/Costa_Rica',
        1, v_recepcion_norte
    )
    RETURNING cita_id INTO v_cita_reservada;

    -- Cita atendida ayer; admite nota clinica.
    INSERT INTO cita (
        clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin,
        estado_id, creada_por, desenlace_registrado_por
    )
    VALUES (
        v_clinica_norte, v_paciente_2, v_prof_norte_2, v_serv_pediatria,
        ((CURRENT_DATE - 1)::timestamp + TIME '09:00') AT TIME ZONE 'America/Costa_Rica',
        ((CURRENT_DATE - 1)::timestamp + TIME '09:00') AT TIME ZONE 'America/Costa_Rica',
        2, v_recepcion_norte, v_prof_usuario_2
    )
    RETURNING cita_id INTO v_cita_atendida;

    INSERT INTO cita (
        clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin,
        estado_id, creada_por, desenlace_registrado_por
    )
    VALUES (
        v_clinica_norte, v_paciente_3, v_prof_norte_3, v_serv_cardiologia,
        ((CURRENT_DATE - 1)::timestamp + TIME '10:00') AT TIME ZONE 'America/Costa_Rica',
        ((CURRENT_DATE - 1)::timestamp + TIME '10:00') AT TIME ZONE 'America/Costa_Rica',
        3, v_recepcion_norte, v_prof_usuario_3
    )
    RETURNING cita_id INTO v_cita_ausente;

    INSERT INTO cita (
        clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin,
        estado_id, creada_por, cancelada_por, motivo_cancelacion
    )
    VALUES (
        v_clinica_norte, v_paciente_4, v_prof_norte_1, v_serv_general,
        ((CURRENT_DATE + 2)::timestamp + TIME '09:00') AT TIME ZONE 'America/Costa_Rica',
        ((CURRENT_DATE + 2)::timestamp + TIME '09:00') AT TIME ZONE 'America/Costa_Rica',
        4, v_recepcion_norte, v_recepcion_norte, 'Cancelacion de demostracion'
    )
    RETURNING cita_id INTO v_cita_cancelada;

    -- Par reprogramado: el reemplazo conserva el vinculo con la cita original.
    INSERT INTO cita (
        clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin,
        estado_id, creada_por
    )
    VALUES (
        v_clinica_norte, v_paciente_3, v_prof_norte_2, v_serv_pediatria,
        ((CURRENT_DATE + 1)::timestamp + TIME '11:00') AT TIME ZONE 'America/Costa_Rica',
        ((CURRENT_DATE + 1)::timestamp + TIME '11:00') AT TIME ZONE 'America/Costa_Rica',
        5, v_recepcion_norte
    )
    RETURNING cita_id INTO v_cita_reprogramada;

    INSERT INTO cita (
        clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin,
        estado_id, cita_origen_id, creada_por
    )
    VALUES (
        v_clinica_norte, v_paciente_3, v_prof_norte_2, v_serv_pediatria,
        ((CURRENT_DATE + 2)::timestamp + TIME '11:00') AT TIME ZONE 'America/Costa_Rica',
        ((CURRENT_DATE + 2)::timestamp + TIME '11:00') AT TIME ZONE 'America/Costa_Rica',
        1, v_cita_reprogramada, v_recepcion_norte
    )
    RETURNING cita_id INTO v_cita_reemplazo;

    INSERT INTO nota_clinica (clinica_id, cita_id, profesional_id, contenido)
    VALUES (
        v_clinica_norte,
        v_cita_atendida,
        v_prof_norte_2,
        'Consulta de demostracion. Paciente estable. Continuar controles programados.'
    )
    RETURNING nota_id INTO v_nota;

    INSERT INTO bitacora_auditoria (
        clinica_id, usuario_id, paciente_id, accion, entidad, entidad_id
    )
    VALUES
        (v_clinica_norte, v_prof_usuario_2, v_paciente_2, 'CREACION', 'NOTA_CLINICA', v_nota),
        (v_clinica_norte, v_admin_norte, v_paciente_1, 'LECTURA', 'PACIENTE_CONTACTO', v_paciente_1),
        (v_clinica_norte, v_admin_norte, v_paciente_1, 'ACTUALIZACION', 'PACIENTE_CONTACTO', v_paciente_1);

    -- Segunda clinica: escenario minimo para comprobar aislamiento por clinica.
    SELECT crear_clinica(
        'Clinica Demo Sur',
        'America/Costa_Rica',
        '00000000-0000-4000-8000-000000000201',
        'Administrador Demo Sur'
    ) INTO v_clinica_sur;

    SELECT usuario_id INTO v_admin_sur
      FROM usuario
     WHERE clinica_id = v_clinica_sur
       AND keycloak_sub = '00000000-0000-4000-8000-000000000201';

    INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre)
    VALUES
        (v_clinica_sur, 3, '00000000-0000-4000-8000-000000000202', 'Recepcion Demo Sur'),
        (v_clinica_sur, 4, '00000000-0000-4000-8000-000000000203', 'Profesional General Demo Sur');

    SELECT usuario_id INTO v_recepcion_sur
      FROM usuario WHERE keycloak_sub = '00000000-0000-4000-8000-000000000202';

    SELECT usuario_id INTO v_prof_usuario_sur
      FROM usuario WHERE keycloak_sub = '00000000-0000-4000-8000-000000000203';

    INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, nombre)
    VALUES (
        v_clinica_sur, v_prof_usuario_sur, v_esp_general, 'Dra. Sofia General Sur'
    )
    RETURNING profesional_id INTO v_prof_sur;

    INSERT INTO servicio (clinica_id, nombre, duracion_min, especialidad_id)
    VALUES (v_clinica_sur, 'Consulta general', 30, v_esp_general)
    RETURNING servicio_id INTO v_serv_sur;

    INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id)
    VALUES (v_clinica_sur, v_prof_sur, v_serv_sur);

    INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin)
    SELECT v_clinica_sur, v_prof_sur, dias.dia_semana::smallint, TIME '08:00', TIME '17:00'
      FROM generate_series(1, 7) AS dias(dia_semana);

    INSERT INTO paciente (
        clinica_id, identificacion, nombre, apellidos, fecha_nacimiento,
        telefono, correo, activo
    )
    VALUES (
        v_clinica_sur, 'TEST-001', 'Ana', 'Prueba Sur',
        DATE '1990-05-10', '+506-8000-1001', 'ana.sur@example.test', true
    )
    RETURNING paciente_id INTO v_paciente_sur;

    INSERT INTO cita (
        clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin,
        estado_id, creada_por
    )
    VALUES (
        v_clinica_sur, v_paciente_sur, v_prof_sur, v_serv_sur,
        ((CURRENT_DATE + 1)::timestamp + TIME '09:00') AT TIME ZONE 'America/Costa_Rica',
        ((CURRENT_DATE + 1)::timestamp + TIME '09:00') AT TIME ZONE 'America/Costa_Rica',
        1, v_recepcion_sur
    )
    RETURNING cita_id INTO v_cita_sur;

    RAISE NOTICE 'Demo Norte | clinica_id=%, admin_usuario_id=%, recepcion_usuario_id=%, prof_general_usuario_id=%, prof_pediatria_usuario_id=%, prof_cardiologia_usuario_id=%',
        v_clinica_norte, v_admin_norte, v_recepcion_norte, v_prof_usuario_1, v_prof_usuario_2, v_prof_usuario_3;
    RAISE NOTICE 'Demo Norte | paciente_1_id=%, paciente_2_id=%, cita_reservada_id=%, cita_atendida_id=%, nota_id=%',
        v_paciente_1, v_paciente_2, v_cita_reservada, v_cita_atendida, v_nota;
    RAISE NOTICE 'Demo Sur | clinica_id=%, admin_usuario_id=%, recepcion_usuario_id=%, prof_usuario_id=%, paciente_id=%, cita_reservada_id=%',
        v_clinica_sur, v_admin_sur, v_recepcion_sur, v_prof_usuario_sur, v_paciente_sur, v_cita_sur;
    RAISE NOTICE 'Plataforma | usuario_id=%', v_admin_plataforma;
END $$;
