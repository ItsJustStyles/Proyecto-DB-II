from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# Los modelos ignoran campos extra a proposito: un `clinica_id` enviado en el cuerpo no tiene ningun efecto, 
# porque la clinica sale siempre de la identidad (I5).

class ClinicaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    zona_horaria: str = Field(default="America/Costa_Rica", max_length=64)
    admin_keycloak_sub: UUID  # el usuario ya debe existir en Keycloak
    admin_nombre: str = Field(min_length=1, max_length=150)

    @field_validator("zona_horaria")
    @classmethod
    def _tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(v)
        except Exception:
            raise ValueError("zona horaria IANA desconocida")
        return v

class UsuarioIn(BaseModel):
    keycloak_sub: UUID
    rol_id: Literal[2, 3, 4]
    nombre: str = Field(min_length=1, max_length=150)

class UsuarioPatch(BaseModel):
    rol_id: Literal[2, 3, 4] | None = None
    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    activo: bool | None = None

class ServicioIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    duracion_min: int = Field(gt=0, le=480)
    especialidad_id: int

class ServicioPatch(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    duracion_min: int | None = Field(default=None, gt=0, le=480)
    especialidad_id: int | None = None
    activo: bool | None = None

class ProfesionalIn(BaseModel):
    usuario_id: int
    especialidad_id: int
    nombre: str = Field(min_length=1, max_length=150)

class ProfesionalPatch(BaseModel):
    especialidad_id: int | None = None
    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    activo: bool | None = None


class ProfesionalServicioIn(BaseModel):
    servicio_id: int

class HorarioIn(BaseModel):
    dia_semana: int = Field(ge=1, le=7)
    hora_inicio: time
    hora_fin: time

    @field_validator("hora_fin")
    @classmethod
    def _orden(cls, v: time, info):
        ini = info.data.get("hora_inicio")
        if ini is not None and v <= ini:
            raise ValueError("hora_fin debe ser mayor que hora_inicio")
        return v

class BloqueoIn(BaseModel):
    inicio: datetime
    fin: datetime
    motivo: str | None = Field(default=None, max_length=200)

    @field_validator("inicio", "fin")
    @classmethod
    def _con_zona(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("incluya la zona horaria (ej. 2026-12-01T08:00:00-06:00)")
        return v

    @field_validator("fin")
    @classmethod
    def _rango(cls, v: datetime, info):
        ini = info.data.get("inicio")
        if ini is not None and v <= ini:
            raise ValueError("fin debe ser mayor que inicio")
        return v

class PacienteIn(BaseModel):
    identificacion: str = Field(min_length=1, max_length=30)
    nombre: str = Field(min_length=1, max_length=100)
    apellidos: str = Field(min_length=1, max_length=100)
    fecha_nacimiento: date
    telefono: str | None = Field(default=None, max_length=30)
    correo: str | None = Field(default=None, max_length=254)

class PacientePatch(BaseModel):
    identificacion: str | None = Field(default=None, min_length=1, max_length=30)
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    apellidos: str | None = Field(default=None, min_length=1, max_length=100)
    fecha_nacimiento: date | None = None
    telefono: str | None = Field(default=None, max_length=30)
    correo: str | None = Field(default=None, max_length=254)
    activo: bool | None = None

class CitaIn(BaseModel):
    paciente_id: int
    profesional_id: int
    servicio_id: int
    inicio: datetime

    @field_validator("inicio")
    @classmethod
    def _con_zona(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("incluya la zona horaria (ej. 2026-12-01T08:00:00-06:00)")
        return v

class ReprogramarIn(BaseModel):
    inicio: datetime
    profesional_id: int | None = None  # por defecto, el mismo profesional

    @field_validator("inicio")
    @classmethod
    def _con_zona(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("incluya la zona horaria")
        return v

class CancelarIn(BaseModel):
    motivo: str = Field(min_length=1, max_length=300)

class DesenlaceIn(BaseModel):
    resultado: Literal["ATENDIDA", "AUSENTE"]

class NotaIn(BaseModel):
    contenido: str = Field(min_length=1, max_length=20000)