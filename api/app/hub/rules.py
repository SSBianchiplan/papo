"""Regras de leitura do hub, iguais no gateway do Papo e no leitor remoto (hubreader/). Sem dependência externa.

Só documento entra; segredo, código de terceiros, backup e dado de banco ficam de fora — por extensão permitida
(lista fechada) e por nome bloqueado (mesmo que a extensão seja de documento).
"""
from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Iterator

DEFAULT_EXT = ("pdf", "md", "markdown", "docx", "xlsx", "xlsm", "csv", "tsv", "pptx", "odt", "ods", "odp", "rtf", "epub", "txt", "skill")
EXCLUDED_DIRS = {
    "node_modules", ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__", "site-packages", "dist-packages", ".cache", ".npm",
    ".next", ".nuxt", "dist", "build", "target", "vendor", "backups", "backup", "pgdata", "postgres-data", "mysql", "redis", "minio",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage", "htmlcov", "logs", "tmp", ".terraform", "segredos", "secrets", ".ssh",
    ".gnupg", "letsencrypt", "certs", "ssl",
}
DENY_NAME = re.compile(r"(^\.env|\.env$|secret|segredo|senha|password|passwd|credential|token|\.pem$|\.key$|\.p12$|\.pfx$|id_rsa|id_ed25519|"
                       r"\.kdbx$|shadow|htpasswd)", re.I)
# ruído de projeto que não é documento: dependências, licenças, metadados de pacote
NOISE_NAME = re.compile(r"^(requirements[\w.-]*\.txt|constraints[\w.-]*\.txt|(un)?license[\w.-]*|copying[\w.-]*|notice[\w.-]*|"
                        r"[\w-]*ofl[\w.-]*\.txt|robots\.txt|sources\.txt|dependency_links\.txt|top_level\.txt|requires\.txt|"
                        r"changelog[\w.-]*|pull_request_template\.md|code_of_conduct\.md)$", re.I)
MAX_FILE = 60 * 1024 * 1024
MAX_FILES = 50_000


def ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def allowed(rel: str, exts: tuple[str, ...] | set[str]) -> bool:
    parts = rel.split("/")
    if any(p in EXCLUDED_DIRS or p.startswith(".") or p.endswith(".egg-info") for p in parts[:-1]):
        return False
    name = parts[-1]
    return bool(name) and not name.startswith(".") and not DENY_NAME.search(name) and not NOISE_NAME.match(name) and ext_of(name) in exts


def clean_rel(rel: str) -> str:
    """Caminho relativo à raiz, sem .., sem barra inicial, sem caracteres de controle."""
    rel = posixpath.normpath("/" + rel.replace("\\", "/")).lstrip("/")
    if rel in ("", ".") or rel.startswith("..") or "\x00" in rel or any(ord(c) < 32 for c in rel):
        raise ValueError("caminho inválido")
    return rel


def resolve(root: str, rel: str) -> str:
    """Caminho absoluto dentro da raiz, seguindo symlinks e recusando qualquer fuga."""
    base = os.path.realpath(root)
    full = os.path.realpath(os.path.join(base, clean_rel(rel)))
    if not (full == base or full.startswith(base + os.sep)):
        raise PermissionError("fora da raiz")
    return full


def walk(root: str, exts: tuple[str, ...] | set[str]) -> Iterator[tuple[str, int, float]]:
    """(caminho relativo, bytes, mtime) dos documentos permitidos sob a raiz. Não segue symlink de pasta."""
    base = os.path.realpath(root)
    count = 0
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".") and not d.endswith(".egg-info"))
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            if not allowed(rel, exts) or os.path.islink(full):
                continue
            try:
                st = os.stat(full)
            except OSError:
                continue
            if st.st_size == 0 or st.st_size > MAX_FILE:
                continue
            yield rel, st.st_size, st.st_mtime
            count += 1
            if count >= MAX_FILES:
                return
