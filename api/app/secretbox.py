"""Cifra de segredos guardados no banco (chave da Anthropic). A chave de cifra vem do ambiente, nunca do banco."""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings
from .errors import Invalid

_AAD = b"papo:anthropic-key:v1"


def _key() -> bytes:
    raw = get_settings().secrets_key
    if not raw:
        raise Invalid("O servidor não tem SECRETS_KEY configurada.", hint="Rode ops/gen-secrets.sh e acrescente SECRETS_KEY ao .env.")
    return hashlib.sha256(raw.encode()).digest()


def seal(plain: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_key()).encrypt(nonce, plain.encode(), _AAD)


def open_(blob: bytes) -> str:
    return AESGCM(_key()).decrypt(blob[:12], blob[12:], _AAD).decode()


def hint(key: str) -> str:
    """Prefixo e final, o bastante para reconhecer a chave sem expô-la."""
    head = key.split("-", 3)
    prefix = "-".join(head[:3]) if len(head) > 3 else key[:6]
    return f"{prefix}-…{key[-4:]}"


def fingerprint(key: str, workspace: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(f"{key}\0{workspace}".encode()).digest()[:9]).decode()
