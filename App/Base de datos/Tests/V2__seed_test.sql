-- Seed de la BASE DE TEST (db_test). Misma forma que el seed de desarrollo, pero DETERMINISTA:
--   * 3 clinicas, 5 usuarios por clinica (admin, 2 recepcion, 2 profesionales), servicios,
--     horarios (jornada partida para el profesional "a"), 12 pacientes y citas de -14 a +14 dias.
--   * El estado de cada cita sale de la fecha y la posicion (d, k), no de cita_id ni de la hora a la
--     que corre el seed. Las citas pasadas se insertan ya en su estado final y las de hoy en adelante
--     quedan RESERVADA (salvo 1 de cada 10, CANCELADA). Asi el resultado no depende de la hora.
--   * Ademas hay 4 "citas ancla" por clinica, siempre en el ultimo dia habil anterior a hoy, con
--     profesional A y servicio 'Consulta general', para poder probar flujos concretos:
--         11:00  RESERVADA ya vencida   -> aun sin desenlace (probar POST /citas/{id}/desenlace)
--         11:30  ATENDIDA sin nota      -> admite crear nota clinica
--         15:00  ATENDIDA con nota      -> nota ya existente (nota 'Nota ancla de prueba')
--         15:30  AUSENTE                -> no admite nota
--   * Hay filas de bitacora por clinica (lectura/actualizacion de contacto y creacion de la nota ancla).
--
-- Los keycloak_sub son fijos y coinciden con los "id" de los usuarios en keycloak/medicitas-realm.json:
--   00000000-0000-4000-8000-0000000000NN   NN = 01 plataforma; 11..15 clinica 1;
--   21..25 clinica 2; 31..35 clinica 3 (x1 admin, x2/x3 recepcion, x4/x5 profesionales).
-- Corre como superusuario durante el init de db_test: no pasa por los roles de minimo privilegio.

INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre)
VALUES (NULL, 1, '00000000-0000-4000-8000-000000000001', 'Administrador de Plataforma');

DO $$
DECLARE
    i            int;
    cid          bigint;
    v_zona       text := 'America/Costa_Rica';
    v_nombre     text;
    uid_admin    bigint;
    uid_prof_a   bigint;
    uid_prof_b   bigint;
    pid_a        bigint;
    pid_b        bigint;
    esp_mg       smallint := (SELECT especialidad_id FROM especialidad WHERE nombre = 'Medicina General');
    esp_b        smallint;
    sv_general   bigint;
    sv_segui     bigint;
    sv_b         bigint;
    nombres      text[] := ARRAY['Ana','Luis','María','Carlos','Sofía','Jorge','Valeria','Diego','Camila','Andrés','Paula','Mateo'];
    apellidos    text[] := ARRAY['Mora Rojas','Vargas Solano','Jiménez Cruz','Araya Soto','Quesada Vega','Campos Brenes','Chaves Núñez','Salas Mena','Rojas Pineda','Barrantes León','Alfaro Porras','Murillo Sáenz'];
    d            int;
    k            int;
    base_date    date := (now() AT TIME ZONE 'America/Costa_Rica')::date;  -- "hoy" en la zona de la clinica
    v_prev       date;      -- ultimo dia habil anterior a hoy (donde van las citas ancla)
    pac_id       bigint;
    pacs         bigint[];
    v_estado     smallint;
    v_cita       bigint;
    v_nota       bigint;
BEGIN
    v_prev := base_date - 1;
    WHILE EXTRACT(ISODOW FROM v_prev) > 5 LOOP
        v_prev := v_prev - 1;
    END LOOP;

    FOR i IN 1..3 LOOP
        v_nombre := CASE i WHEN 1 THEN 'Clínica Central San José'
                           WHEN 2 THEN 'Clínica del Valle Cartago'
                           ELSE 'Centro Médico Heredia' END;
        INSERT INTO clinica (nombre, zona_horaria) VALUES (v_nombre, v_zona)
        RETURNING clinica_id INTO cid;

        -- usuarios: n=1 admin (rol 2), n=2,3 recepcion (rol 3), n=4,5 profesional (rol 4)
        INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre) VALUES
            (cid, 2, format('00000000-0000-4000-8000-0000000000%s', i*10+1)::uuid, format('Admin %s', v_nombre));
        INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre) VALUES
            (cid, 3, format('00000000-0000-4000-8000-0000000000%s', i*10+2)::uuid, format('Recepción A (%s)', i)),
            (cid, 3, format('00000000-0000-4000-8000-0000000000%s', i*10+3)::uuid, format('Recepción B (%s)', i));
        INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre) VALUES
            (cid, 4, format('00000000-0000-4000-8000-0000000000%s', i*10+4)::uuid, format('Dra. Elena Ramírez (%s)', i));
        INSERT INTO usuario (clinica_id, rol_id, keycloak_sub, nombre) VALUES
            (cid, 4, format('00000000-0000-4000-8000-0000000000%s', i*10+5)::uuid, format('Dr. Pablo Herrera (%s)', i));

        SELECT usuario_id INTO uid_admin  FROM usuario WHERE keycloak_sub = format('00000000-0000-4000-8000-0000000000%s', i*10+1)::uuid;
        SELECT usuario_id INTO uid_prof_a FROM usuario WHERE keycloak_sub = format('00000000-0000-4000-8000-0000000000%s', i*10+4)::uuid;
        SELECT usuario_id INTO uid_prof_b FROM usuario WHERE keycloak_sub = format('00000000-0000-4000-8000-0000000000%s', i*10+5)::uuid;

        esp_b := (SELECT especialidad_id FROM especialidad
                   WHERE nombre = CASE i WHEN 2 THEN 'Cardiología' ELSE 'Pediatría' END);

        INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, nombre)
        VALUES (cid, uid_prof_a, esp_mg, format('Dra. Elena Ramírez (%s)', i))
        RETURNING profesional_id INTO pid_a;
        INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, nombre)
        VALUES (cid, uid_prof_b, esp_b, format('Dr. Pablo Herrera (%s)', i))
        RETURNING profesional_id INTO pid_b;

        INSERT INTO servicio (clinica_id, nombre, duracion_min, especialidad_id)
        VALUES (cid, 'Consulta general', 30, esp_mg) RETURNING servicio_id INTO sv_general;
        INSERT INTO servicio (clinica_id, nombre, duracion_min, especialidad_id)
        VALUES (cid, 'Consulta de seguimiento', 15, esp_mg) RETURNING servicio_id INTO sv_segui;
        IF i = 2 THEN
            INSERT INTO servicio (clinica_id, nombre, duracion_min, especialidad_id)
            VALUES (cid, 'Consulta cardiológica', 45, esp_b) RETURNING servicio_id INTO sv_b;
        ELSE
            INSERT INTO servicio (clinica_id, nombre, duracion_min, especialidad_id)
            VALUES (cid, 'Control pediátrico', 30, esp_b) RETURNING servicio_id INTO sv_b;
        END IF;

        INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id) VALUES
            (cid, pid_a, sv_general), (cid, pid_a, sv_segui), (cid, pid_b, sv_b);

        -- horarios lunes a viernes: A en jornada partida, B continua
        INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin)
        SELECT cid, pid_a, dow, t.ini, t.fin
          FROM generate_series(1, 5) AS dow,
               (VALUES ('08:00'::time, '12:00'::time), ('13:00'::time, '17:00'::time)) AS t(ini, fin);
        INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin)
        SELECT cid, pid_b, dow, '09:00', '15:00' FROM generate_series(1, 5) AS dow;

        -- pacientes
        FOR k IN 1..12 LOOP
            INSERT INTO paciente (clinica_id, identificacion, nombre, apellidos, fecha_nacimiento, telefono, correo)
            VALUES (cid, format('%s-%s-%s', i, lpad((1000 + k * 7)::text, 4, '0'), lpad((k * 131 % 1000)::text, 4, '0')),
                    nombres[k], apellidos[k],
                    date '1960-03-15' + (k * 1117),
                    format('+506 8%s-%s', lpad((k * 37 % 1000)::text, 3, '0'), lpad((k * 911 % 10000)::text, 4, '0')),
                    lower(translate(nombres[k], 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) || k || '@correo.example');
        END LOOP;
        SELECT array_agg(paciente_id ORDER BY paciente_id) INTO pacs FROM paciente WHERE clinica_id = cid;

        -- citas: de -14 a +14 dias, solo dias habiles. Estado fijo segun (d, k):
        --   pasadas (d < 0): 70% ATENDIDA, 20% AUSENTE, 10% CANCELADA
        --   desde hoy      : 90% RESERVADA, 10% CANCELADA
        FOR d IN -14..14 LOOP
            IF EXTRACT(ISODOW FROM base_date + d) <= 5 THEN
                -- profesional A: 08:00, 09:30 y 14:00 (consulta general, 30 min)
                FOR k IN 0..2 LOOP
                    SELECT paciente_id INTO pac_id FROM paciente
                     WHERE clinica_id = cid ORDER BY paciente_id
                     OFFSET ((abs(d) * 3 + k) % 12) LIMIT 1;
                    v_estado := CASE
                        WHEN d < 0 THEN (CASE (abs(d) + k) % 10 WHEN 9 THEN 4 WHEN 7 THEN 3 WHEN 8 THEN 3 ELSE 2 END)
                        ELSE            (CASE (d + k) % 10 WHEN 9 THEN 4 ELSE 1 END)
                    END;
                    INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado_id,
                                      creada_por, cancelada_por, motivo_cancelacion, desenlace_registrado_por)
                    VALUES (cid, pac_id, pid_a, sv_general,
                            ((base_date + d) + (ARRAY['08:00','09:30','14:00'])[k+1]::time) AT TIME ZONE v_zona,
                            now(), v_estado, uid_admin,
                            CASE WHEN v_estado = 4 THEN uid_admin END,
                            CASE WHEN v_estado = 4 THEN 'Paciente solicitó cancelar' END,
                            CASE WHEN v_estado IN (2, 3) THEN uid_prof_a END);
                END LOOP;
                -- profesional B: 10:00
                SELECT paciente_id INTO pac_id FROM paciente
                 WHERE clinica_id = cid ORDER BY paciente_id
                 OFFSET ((abs(d) * 5 + 7) % 12) LIMIT 1;
                v_estado := CASE
                    WHEN d < 0 THEN (CASE (abs(d) + 3) % 10 WHEN 9 THEN 4 WHEN 7 THEN 3 WHEN 8 THEN 3 ELSE 2 END)
                    ELSE            (CASE (d + 3) % 10 WHEN 9 THEN 4 ELSE 1 END)
                END;
                INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado_id,
                                  creada_por, cancelada_por, motivo_cancelacion, desenlace_registrado_por)
                VALUES (cid, pac_id, pid_b, sv_b,
                        ((base_date + d) + time '10:00') AT TIME ZONE v_zona, now(), v_estado, uid_admin,
                        CASE WHEN v_estado = 4 THEN uid_admin END,
                        CASE WHEN v_estado = 4 THEN 'Paciente solicitó cancelar' END,
                        CASE WHEN v_estado IN (2, 3) THEN uid_prof_b END);
            END IF;
        END LOOP;

        -- Notas clinicas para la mitad de las citas atendidas (autor = profesional de la cita)
        INSERT INTO nota_clinica (clinica_id, cita_id, profesional_id, contenido)
        SELECT clinica_id, cita_id, profesional_id,
               'Paciente en buen estado general. Se indica control en 3 meses.'
          FROM cita WHERE clinica_id = cid AND estado_id = 2 AND cita_id % 2 = 0;

        -- Citas ancla (ver cabecera). Horas libres de la semilla masiva: 11:00, 11:30, 15:00 y 15:30.
        INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado_id, creada_por)
        VALUES (cid, pacs[1], pid_a, sv_general, (v_prev + time '11:00') AT TIME ZONE v_zona, now(), 1, uid_admin);

        INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado_id, creada_por, desenlace_registrado_por)
        VALUES (cid, pacs[2], pid_a, sv_general, (v_prev + time '11:30') AT TIME ZONE v_zona, now(), 2, uid_admin, uid_prof_a);

        INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado_id, creada_por, desenlace_registrado_por)
        VALUES (cid, pacs[3], pid_a, sv_general, (v_prev + time '15:00') AT TIME ZONE v_zona, now(), 2, uid_admin, uid_prof_a)
        RETURNING cita_id INTO v_cita;
        INSERT INTO nota_clinica (clinica_id, cita_id, profesional_id, contenido)
        VALUES (cid, v_cita, pid_a, 'Nota ancla de prueba') RETURNING nota_id INTO v_nota;

        INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado_id, creada_por, desenlace_registrado_por)
        VALUES (cid, pacs[4], pid_a, sv_general, (v_prev + time '15:30') AT TIME ZONE v_zona, now(), 3, uid_admin, uid_prof_a);

        -- Bitacora (append-only): lecturas/actualizaciones de contacto y la creacion de la nota ancla
        INSERT INTO bitacora_auditoria (clinica_id, usuario_id, paciente_id, accion, entidad, entidad_id) VALUES
            (cid, uid_admin,  pacs[1], 'LECTURA',       'PACIENTE_CONTACTO', pacs[1]),
            (cid, uid_admin,  pacs[2], 'ACTUALIZACION', 'PACIENTE_CONTACTO', pacs[2]),
            (cid, uid_prof_a, pacs[3], 'CREACION',      'NOTA_CLINICA',      v_nota);
    END LOOP;
END $$;