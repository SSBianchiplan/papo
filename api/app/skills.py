"""Leitura de skills enviadas: SKILL.md (cabeçalho YAML com name/description) avulso, ou .zip/.skill com uma ou várias pastas.

Formato aceito é o mesmo das skills do Claude: pasta com SKILL.md e, opcionalmente, arquivos de referência (texto).
Zip é tratado como hostil: limite de tamanho, de entradas e de descompressão; caminhos normalizados; só arquivos de texto.
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass, field

import yaml

from .errors import Invalid

MAX_ZIP = 20 * 1024 * 1024
MAX_UNZIPPED = 60 * 1024 * 1024
MAX_ENTRIES = 3000
MAX_FILE = 1_000_000
MAX_SKILLS = 300
TEXT_EXT = re.compile(r"\.(md|markdown|txt|json|ya?ml|csv|tsv|py|js|ts|sql|html?|css|xml|ini|toml|sh)$", re.I)


@dataclass
class ParsedSkill:
    name: str
    description: str
    body: str
    files: dict[str, str] = field(default_factory=dict)


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9:_.-]+", "-", s.strip().lower()).strip("-.")
    return s[:80] or "skill"


def _decode(b: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def parse_skill_md(text: str, fallback_name: str) -> ParsedSkill:
    text = text.replace("\r\n", "\n").strip("﻿")
    meta: dict[str, object] = {}
    body = text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if m:
        try:
            loaded = yaml.safe_load(m.group(1))
            meta = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError:
            meta = {}
        body = m.group(2)
    body = body.strip()
    if not body:
        raise Invalid(f'A skill "{fallback_name}" não tem instruções (corpo do SKILL.md vazio).')
    name = slug(str(meta.get("name") or fallback_name))
    desc = str(meta.get("description") or "").strip()
    if not desc:                       # sem descrição: primeiro parágrafo que não é título
        para = next((p.strip() for p in body.split("\n\n") if p.strip() and not p.lstrip().startswith("#")), "")
        desc = para or f"Skill {name}"
    desc = re.sub(r"\s+", " ", desc)[:2000]
    return ParsedSkill(name=name, description=desc, body=body[:300_000])


def _owner_root(path: str, roots: list[str]) -> str | None:
    """A skill dona de um arquivo é a pasta com SKILL.md mais funda que o contém."""
    d = posixpath.dirname(path)
    hits = [r for r in roots if r == "" or d == r or d.startswith(r + "/")]
    return max(hits, key=len) if hits else None


def parse_upload(filename: str, data: bytes) -> list[ParsedSkill]:
    low = filename.lower()
    if low.endswith((".md", ".markdown")):
        base = re.sub(r"\.(md|markdown)$", "", posixpath.basename(filename), flags=re.I)
        return [parse_skill_md(_decode(data), "skill" if base.lower() == "skill" else base)]
    if not low.endswith((".zip", ".skill")):
        raise Invalid("Envie um SKILL.md, ou um .zip/.skill com as pastas das skills.")
    if len(data) > MAX_ZIP:
        raise Invalid(f"Pacote maior que {MAX_ZIP // 1048576} MB.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise Invalid("Arquivo .zip inválido ou corrompido.") from e
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_ENTRIES:
        raise Invalid("Pacote com arquivos demais.")
    if sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise Invalid("Pacote grande demais depois de descompactado.")
    entries: dict[str, zipfile.ZipInfo] = {}
    for i in infos:
        p = posixpath.normpath(i.filename.replace("\\", "/")).lstrip("/")
        if p.startswith("..") or "/../" in p or p.startswith("__MACOSX") or "/." in f"/{p}":
            continue                    # caminho malicioso ou lixo do macOS/arquivos ocultos
        entries[p] = i
    roots = sorted({posixpath.dirname(p) for p in entries if posixpath.basename(p).lower() == "skill.md"}, key=len)
    if not roots:
        raise Invalid("Nenhum SKILL.md encontrado no pacote.")
    if len(roots) > MAX_SKILLS:
        raise Invalid(f"No máximo {MAX_SKILLS} skills por pacote.")
    out: list[ParsedSkill] = []
    for root in roots:
        prefix = f"{root}/" if root else ""
        md_path = next(p for p in entries if posixpath.dirname(p) == root and posixpath.basename(p).lower() == "skill.md")
        fallback = posixpath.basename(root) or re.sub(r"\.(zip|skill)$", "", posixpath.basename(filename), flags=re.I)
        sk = parse_skill_md(_decode(zf.read(entries[md_path])), fallback)
        for p, info in entries.items():
            if p == md_path or not p.startswith(prefix) or not TEXT_EXT.search(p) or info.file_size > MAX_FILE:
                continue
            if _owner_root(p, roots) != root:
                continue                # pertence a uma skill mais interna, não a esta
            rel = p[len(prefix):]
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _./-]{0,199}", rel):
                sk.files[rel] = _decode(zf.read(info))
        out.append(sk)
    names = [s.name for s in out]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise Invalid("Há skills repetidas no pacote: " + ", ".join(sorted(dup)))
    return out
