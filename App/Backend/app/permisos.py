"""
Matriz de permisos del enunciado (seccion 3), traducida a roles del dominio.
Los roles del token de Keycloak tienen el mismo nombre que rol.nombre en la base.
"""

ADMIN_PLATAFORMA = "ADMIN_PLATAFORMA"
ADMIN_CLINICA = "ADMIN_CLINICA"
RECEPCION = "RECEPCION"
PROFESIONAL = "PROFESIONAL"

ROL_ID_A_NOMBRE = {
    1: ADMIN_PLATAFORMA, 
    2: ADMIN_CLINICA, 
    3: RECEPCION, 
    4: PROFESIONAL
}

# rol de base de datos que se activa con SET LOCAL ROLE para cada rol del dominio
ROL_ID_A_ROL_BD = {
    1: "db_plataforma", 
    2: "db_admin_clinica", 
    3: "db_recepcion", 
    4: "db_profesional"
}

PERMISOS: dict[str, frozenset[str]] = {
    "clinica.crear": frozenset({ADMIN_PLATAFORMA}),                                    
    "clinica.listar": frozenset({ADMIN_PLATAFORMA}),
    "usuario.gestionar": frozenset({ADMIN_CLINICA}),                                   
    "servicio.gestionar": frozenset({ADMIN_CLINICA}),                                   
    "profesional.gestionar": frozenset({ADMIN_CLINICA}),                                
    "catalogo.leer": frozenset({ADMIN_CLINICA, RECEPCION, PROFESIONAL}),
    "horario.gestionar": frozenset({ADMIN_CLINICA, PROFESIONAL}),                       
    "bloqueo.gestionar": frozenset({ADMIN_CLINICA, PROFESIONAL}),                       
    "agenda.leer_config": frozenset({ADMIN_CLINICA, RECEPCION, PROFESIONAL}),
    "disponibilidad.consultar": frozenset({ADMIN_CLINICA, RECEPCION, PROFESIONAL}),     
    "cita.operar": frozenset({ADMIN_CLINICA, RECEPCION}),                              
    "cita.desenlace": frozenset({ADMIN_CLINICA, RECEPCION, PROFESIONAL}),              
    "agenda.dia": frozenset({ADMIN_CLINICA, RECEPCION, PROFESIONAL}),                   
    "agenda.clinica": frozenset({ADMIN_CLINICA, RECEPCION}),                            
    "cita.conteo": frozenset({ADMIN_CLINICA, RECEPCION}),                               
    "paciente.escribir": frozenset({ADMIN_CLINICA, RECEPCION}),                         
    "paciente.leer": frozenset({ADMIN_CLINICA, RECEPCION, PROFESIONAL}),                
    "paciente.historial": frozenset({ADMIN_CLINICA, RECEPCION, PROFESIONAL}),           
    "nota.escribir": frozenset({PROFESIONAL}),                                         
    "nota.leer": frozenset({PROFESIONAL}),
    "bitacora.consultar": frozenset({ADMIN_CLINICA}),                                   
}

def rol_permitido(permiso: str, rol: str) -> bool:
    return rol in PERMISOS.get(permiso, frozenset())