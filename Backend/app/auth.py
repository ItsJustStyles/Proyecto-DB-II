"""
Identidad delegada en Keycloak (RF17).

- El token de acceso OIDC se valida con las llaves publicas del proveedor (JWKS): firma,
  expiracion, emisor y client autorizado (azp). No se emite ni firma nada aqui.
- La clinica NO viene del token ni de la peticion: se resuelve en la tabla `usuario`
  a partir del claim `sub` (I5).
- El rol efectivo es el de la base; el token debe llevar ese mismo rol de realm, de lo
  contrario es 403 (rol no autorizado), aunque el token sea valido.
- Sin token o token invalido: 401. Token valido sin rol requerido: 403.
"""

import asyncio

import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient

from . import db
from .config import settings
from .db import Principal
from .permisos import rol_permitido

_jwks = PyJWKClient(settings.oidc_jwks_url, cache_keys=True, lifespan=3600)


def _no_autenticado(msg: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"codigo": "NO_AUTENTICADO", "mensaje": msg},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _validar_token(token: str) -> dict:
    signing_key = _jwks.get_signing_key_from_jwt(token)  # sincrono: se llama en un hilo
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=settings.oidc_issuer,
        options={"require": ["exp", "iss", "sub"], "verify_aud": False},
    )
    if claims.get("azp") != settings.oidc_client_id:
        raise jwt.InvalidTokenError("client no autorizado (azp)")
    return claims


async def get_principal(request: Request) -> Principal:
    header = request.headers.get("Authorization", "")
    esquema, _, token = header.partition(" ")
    if esquema.lower() != "bearer" or not token:
        raise _no_autenticado("Se requiere un token Bearer")
    try:
        claims = await asyncio.to_thread(_validar_token, token)
    except jwt.PyJWTError:
        raise _no_autenticado("Token invalido o expirado")
    except Exception:  # JWKS inalcanzable u otro fallo del proveedor
        raise HTTPException(
            status_code=503, detail={"codigo": "PROVEEDOR_NO_DISPONIBLE", "mensaje": "No se pudo validar el token"}
        )
    p = await db.resolver_identidad(claims["sub"])
    if p is None:
        raise HTTPException(
            status_code=403,
            detail={"codigo": "USUARIO_NO_REGISTRADO", "mensaje": "El usuario no esta registrado o esta inactivo"},
        )
    roles_token = set((claims.get("realm_access") or {}).get("roles", []))
    if p.rol not in roles_token:
        raise HTTPException(
            status_code=403, detail={"codigo": "ROL_NO_AUTORIZADO", "mensaje": "El token no lleva el rol del usuario"}
        )
    request.state.principal = p
    return p


def requiere(permiso: str):
    """Dependencia de FastAPI: exige un permiso de la matriz (app/permisos.py)."""

    async def _dep(p: Principal = Depends(get_principal)) -> Principal:
        if not rol_permitido(permiso, p.rol):
            raise HTTPException(
                status_code=403, detail={"codigo": "SIN_PERMISO", "mensaje": f"El rol {p.rol} no puede realizar esta operacion"}
            )
        return p

    return _dep