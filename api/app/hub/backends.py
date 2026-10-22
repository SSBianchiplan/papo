"""Conectores de leitura do hub. Todos só listam e leem; nenhum grava em lugar algum.

local  — pastas da própria VPS do Papo montadas :ro no gateway
remote — leitor do hub em outra VPS (hubreader/), HTTPS com certificado fixado + token
sftp   — hospedagem compartilhada (site/WordPress), host key fixada no primeiro teste
Caminho no catálogo: "<raiz>/<caminho relativo>", ex.: "opt/peoples/README.md".
"""
from __future__ import annotations

import asyncio
import base64
import posixpath
import ssl
import stat as st
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from . import rules

Entry = tuple[str, int, float]        # caminho, bytes, mtime


class Backend(Protocol):
    async def scan(self) -> list[Entry]: ...
    async def read(self, path: str) -> bytes: ...
    async def health(self) -> dict[str, Any]: ...


def split(path: str) -> tuple[str, str]:
    root, _, rel = rules.clean_rel(path).partition("/")
    if not rel:
        raise ValueError("caminho sem raiz")
    return root, rel


@dataclass
class Local:
    roots: dict[str, str]
    exts: set[str]

    async def scan(self) -> list[Entry]:
        def run() -> list[Entry]:
            return [(f"{n}/{rel}", size, mt) for n, d in self.roots.items() for rel, size, mt in rules.walk(d, self.exts)]
        return await asyncio.to_thread(run)

    async def read(self, path: str) -> bytes:
        root, rel = split(path)
        if root not in self.roots or not rules.allowed(rel, self.exts):
            raise PermissionError("arquivo fora das regras de leitura")

        def run() -> bytes:
            full = rules.resolve(self.roots[root], rel)
            with open(full, "rb") as f:
                data = f.read(rules.MAX_FILE + 1)
            if len(data) > rules.MAX_FILE:
                raise ValueError("arquivo grande demais")
            return data
        return await asyncio.to_thread(run)

    async def health(self) -> dict[str, Any]:
        import os
        return {"ok": all(os.path.isdir(d) for d in self.roots.values()), "roots": sorted(self.roots)}


@dataclass
class Remote:
    url: str
    token: str
    cert_pem: str
    exts: set[str]

    def _client(self) -> httpx.AsyncClient:
        ctx = ssl.create_default_context(cadata=self.cert_pem)      # confia só neste certificado
        return httpx.AsyncClient(base_url=self.url.rstrip("/"), verify=ctx, timeout=httpx.Timeout(60, connect=10),
                                 headers={"Authorization": f"Bearer {self.token}"})

    async def scan(self) -> list[Entry]:
        async with self._client() as c:
            r = await c.get("/scan")
            r.raise_for_status()
            data: dict[str, list[list[Any]]] = r.json()
        return [(f"{root}/{rel}", int(size), float(mt)) for root, items in data.items() for rel, size, mt in items
                if rules.allowed(str(rel), self.exts)]

    async def read(self, path: str) -> bytes:
        root, rel = split(path)
        if not rules.allowed(rel, self.exts):
            raise PermissionError("arquivo fora das regras de leitura")
        async with self._client() as c, c.stream("GET", "/file", params={"root": root, "path": rel}) as r:
            if r.status_code != 200:
                raise FileNotFoundError(f"leitor respondeu {r.status_code}")
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > rules.MAX_FILE:
                    raise ValueError("arquivo grande demais")
            return bytes(buf)

    async def health(self) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.get("/health")
            r.raise_for_status()
            return dict(r.json())


@dataclass
class Sftp:
    host: str
    port: int
    user: str
    password: str
    root: str
    host_key: str            # "tipo base64"; vazio = ainda não fixada
    exts: set[str]

    def _connect(self) -> Any:
        import paramiko  # type: ignore[import-untyped]

        t = paramiko.Transport((self.host, self.port))
        t.banner_timeout = t.auth_timeout = 20
        t.start_client(timeout=20)
        key = t.get_remote_server_key()
        seen = f"{key.get_name()} {base64.b64encode(key.asbytes()).decode()}"
        if self.host_key and seen != self.host_key:
            t.close()
            raise PermissionError("a chave do servidor SFTP mudou; confira antes de confiar de novo")
        self.host_key = seen
        t.auth_password(self.user, self.password)
        return paramiko.SFTPClient.from_transport(t)

    async def scan(self) -> list[Entry]:
        def run() -> list[Entry]:
            sftp = self._connect()
            out: list[Entry] = []
            try:
                stack = [""]
                base = self.root.rstrip("/") or "."
                while stack and len(out) < rules.MAX_FILES:
                    rel_dir = stack.pop()
                    for a in sftp.listdir_attr(posixpath.join(base, rel_dir) if rel_dir else base):
                        rel = f"{rel_dir}/{a.filename}" if rel_dir else a.filename
                        mode = a.st_mode or 0
                        if st.S_ISDIR(mode):
                            if a.filename not in rules.EXCLUDED_DIRS and not a.filename.startswith("."):
                                stack.append(rel)
                        elif st.S_ISREG(mode) and rules.allowed(rel, self.exts) and 0 < (a.st_size or 0) <= rules.MAX_FILE:
                            out.append((f"site/{rel}", int(a.st_size or 0), float(a.st_mtime or 0)))
            finally:
                sftp.close()
            return out
        return await asyncio.to_thread(run)

    async def read(self, path: str) -> bytes:
        root, rel = split(path)
        if root != "site" or not rules.allowed(rel, self.exts):
            raise PermissionError("arquivo fora das regras de leitura")

        def run() -> bytes:
            sftp = self._connect()
            try:
                with sftp.open(posixpath.join(self.root.rstrip("/") or ".", rel), "rb") as f:
                    data = f.read(rules.MAX_FILE + 1)
            finally:
                sftp.close()
            if len(data) > rules.MAX_FILE:
                raise ValueError("arquivo grande demais")
            return bytes(data)
        return await asyncio.to_thread(run)

    async def health(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            sftp = self._connect()
            try:
                sftp.listdir(self.root or ".")
            finally:
                sftp.close()
            return {"ok": True, "host_key": self.host_key}
        return await asyncio.to_thread(run)

