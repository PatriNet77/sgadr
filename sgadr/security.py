"""Primitivas de seguridad basadas solo en la biblioteca estándar."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N, _R, _P = 2**15, 8, 1          # costo scrypt (memoria ~32 MiB por hash)
_MAXMEM = 2**26                   # 64 MiB: límite explícito para OpenSSL
_SALT_BYTES, _KEY_BYTES = 16, 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    """Devuelve 'scrypt$N$r$p$salt$hash' (parámetros embebidos para poder migrar costos)."""
    if len(password) < 12:
        raise ValueError("La contraseña debe tener al menos 12 caracteres.")
    salt = secrets.token_bytes(_SALT_BYTES)
    key = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P,
                         maxmem=_MAXMEM, dklen=_KEY_BYTES)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    """Verificación en tiempo constante; ante formato inválido devuelve False."""
    try:
        scheme, n, r, p, salt_b64, key_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(key_b64)
        candidate = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64),
                                   n=int(n), r=int(r), p=int(p), maxmem=_MAXMEM,
                                   dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)
