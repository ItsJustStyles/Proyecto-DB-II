import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("medicitas")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.open_pool()
    yield
    await db.close_pool()

app = FastAPI(
    title="MediCitas API",
    version="1.0.0",
    description="Plataforma SaaS multi-tenant de gestion de citas medicas (Etapa 1). "
    "Todas las rutas /api/v1 exigen un token de acceso OIDC de Keycloak.",
    lifespan=lifespan,
)

@app.get("/health", tags=["operacion"], summary="Estado del servicio (publico)")
async def health():
    return {"estado": "ok"}

@app.exception_handler(Exception)
async def _no_controlada(_: Request, exc: Exception):
    # Una entrada mal formada o un fallo inesperado nunca tumban el servicio.
    log.exception("Error no controlado")
    return JSONResponse(status_code=500, content={"detail": {"codigo": "ERROR_INTERNO", "mensaje": "Error interno"}})
