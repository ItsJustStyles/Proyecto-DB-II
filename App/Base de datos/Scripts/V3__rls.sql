-- RLS

-- 1. Permitir que el login base (medicitas_app) lea `usuario` en resolver_identidad()
--    antes de ejecutar SET LOCAL ROLE. Como medicitas_app tiene NOINHERIT,
--    los roles de negocio NO heredan BYPASSRLS.
ALTER ROLE medicitas_app BYPASSRLS;

-- 2. Habilitar RLS en las 10 tablas de negocio con clinica_id
ALTER TABLE usuario              ENABLE ROW LEVEL SECURITY;
ALTER TABLE profesional          ENABLE ROW LEVEL SECURITY;
ALTER TABLE servicio             ENABLE ROW LEVEL SECURITY;
ALTER TABLE profesional_servicio ENABLE ROW LEVEL SECURITY;
ALTER TABLE horario_atencion     ENABLE ROW LEVEL SECURITY;
ALTER TABLE bloqueo_agenda       ENABLE ROW LEVEL SECURITY;
ALTER TABLE paciente             ENABLE ROW LEVEL SECURITY;
ALTER TABLE cita                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE nota_clinica         ENABLE ROW LEVEL SECURITY;
ALTER TABLE bitacora_auditoria   ENABLE ROW LEVEL SECURITY;

-- 3. Crear politicas de aislamiento por tenant usando app.clinica_id
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'usuario',
        'profesional',
        'servicio',
        'profesional_servicio',
        'horario_atencion',
        'bloqueo_agenda',
        'paciente',
        'cita',
        'nota_clinica',
        'bitacora_auditoria'
    ]
    LOOP
        EXECUTE format(
            'CREATE POLICY aislamiento_clinica_%I ON %I '
            'USING (clinica_id = NULLIF(current_setting(''app.clinica_id'', true), '''')::bigint) '
            'WITH CHECK (clinica_id = NULLIF(current_setting(''app.clinica_id'', true), '''')::bigint);',
            t, t
        );
    END LOOP;
END $$;