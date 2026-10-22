"""Formatos além de PDF/Word/planilha: PowerPoint, OpenDocument, RTF, e-mail, Jupyter, EPUB, HTML e .zip com documentos.

Tudo vira seções de texto (e abas, no .ods). Pacotes zip são tratados como hostis: limite de entradas e de descompressão.
O XML é lido com a biblioteca padrão (expat não busca entidades externas e barra expansão exponencial).
"""
from __future__ import annotations

import email
import email.policy
import html as htmllib
import io
import json
import posixpath
import re
import zipfile
from email.message import EmailMessage
from typing import Any
from xml.etree import ElementTree as ET

MAX_ZIP_ENTRIES = 500
MAX_ZIP_UNPACKED = 80 * 1024 * 1024
MAX_INNER_FILES = 60

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
}


def _zip(data: bytes) -> zipfile.ZipFile:
    z = zipfile.ZipFile(io.BytesIO(data))
    infos = z.infolist()
    if len(infos) > 5000 or sum(i.file_size for i in infos) > MAX_ZIP_UNPACKED:
        raise ValueError("pacote grande demais depois de descompactado")
    return z


def _num(name: str) -> int:
    m = re.search(r"(\d+)\.xml$", name)
    return int(m.group(1)) if m else 0


def html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style|head|noscript|svg)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|section|article|table|blockquote)>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "• ", s)
    s = re.sub(r"(?i)</t[dh]>", "\t", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s)
    s = re.sub(r"[ \t\u00a0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


# ------------------------------------------------------------------ PowerPoint
def pptx_slides(data: bytes) -> list[tuple[str, str]]:
    z = _zip(data)
    names = z.namelist()
    slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=_num)
    out = []
    for n in slides:
        root = ET.fromstring(z.read(n))
        paras = []
        for p in root.iter(f"{{{NS['a']}}}p"):
            t = "".join(x.text or "" for x in p.iter(f"{{{NS['a']}}}t")).strip()
            if t:
                paras.append(t)
        note_name = f"ppt/notesSlides/notesSlide{_num(n)}.xml"
        if note_name in names:
            notes = " ".join((x.text or "") for x in ET.fromstring(z.read(note_name)).iter(f"{{{NS['a']}}}t")).strip()
            if notes and not notes.isdigit():
                paras.append(f"[notas] {notes}")
        out.append((f"slide {_num(n)}", "\n".join(paras)))
    return out


# ------------------------------------------------------------------ OpenDocument
def _odf_text(el: ET.Element) -> str:
    return "".join(el.itertext()).strip()


def odf_content(data: bytes) -> ET.Element:
    return ET.fromstring(_zip(data).read("content.xml"))


def odt_text(data: bytes) -> str:
    root = odf_content(data)
    lines = []
    for el in root.iter():
        if el.tag in (f"{{{NS['text']}}}h", f"{{{NS['text']}}}p"):
            t = _odf_text(el)
            if t:
                lines.append(("## " if el.tag.endswith("}h") else "") + t)
    return "\n".join(lines)


def odp_slides(data: bytes) -> list[tuple[str, str]]:
    root = odf_content(data)
    out = []
    for i, page in enumerate(root.iter(f"{{{NS['draw']}}}page"), start=1):
        t = "\n".join(x for x in (_odf_text(p) for p in page.iter(f"{{{NS['text']}}}p")) if x)
        out.append((f"slide {i}", t))
    return out


def ods_tables(data: bytes) -> list[tuple[str, list[list[Any]]]]:
    root = odf_content(data)
    tables: list[tuple[str, list[list[Any]]]] = []
    rep_col = f"{{{NS['table']}}}number-columns-repeated"
    rep_row = f"{{{NS['table']}}}number-rows-repeated"
    for t in root.iter(f"{{{NS['table']}}}table"):
        name = t.get(f"{{{NS['table']}}}name") or f"Aba {len(tables) + 1}"
        matrix: list[list[Any]] = []
        for r in t.iter(f"{{{NS['table']}}}table-row"):
            row: list[Any] = []
            for c in r:
                if not c.tag.endswith("}table-cell") and not c.tag.endswith("}covered-table-cell"):
                    continue
                v: Any = c.get("{urn:oasis:names:tc:opendocument:xmlns:office:1.0}value")
                if v is None:
                    v = _odf_text(c)
                else:
                    try:
                        v = float(v)
                    except ValueError:
                        pass
                row.extend([v] * min(int(c.get(rep_col, "1")), 500))
            while row and row[-1] in ("", None):
                row.pop()
            for _ in range(min(int(r.get(rep_row, "1")), 1000)):
                matrix.append(list(row))
            if len(matrix) > 200_000:
                break
        while matrix and not matrix[-1]:
            matrix.pop()
        tables.append((name, matrix))
    return tables


# ------------------------------------------------------------------ RTF
def rtf_text(data: bytes) -> str:
    s = data.decode("latin-1", "replace")
    s = re.sub(r"\{\\\*[^{}]*(\{[^{}]*\}[^{}]*)*\}", "", s)                 # grupos de destino ignoráveis
    s = re.sub(r"\{\\(fonttbl|colortbl|stylesheet|info)[^{}]*(\{[^{}]*\}[^{}]*)*\}", "", s)
    s = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", "replace"), s)
    s = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), s)
    s = re.sub(r"\\(par|line|row)\b ?", "\n", s)
    s = re.sub(r"\\tab\b ?", "\t", s)
    s = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", s)
    s = s.replace("\\{", "{").replace("\\}", "}").replace("\\\\", "\\")
    s = re.sub(r"[{}]", "", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


# ------------------------------------------------------------------ e-mail
def eml_text(data: bytes) -> str:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    assert isinstance(msg, EmailMessage)          # policy.default sempre devolve EmailMessage
    head = [f"{k}: {msg[k]}" for k in ("From", "To", "Cc", "Date", "Subject") if msg[k]]
    body, attachments = "", []
    for part in msg.walk():
        if not isinstance(part, EmailMessage) or part.is_multipart():
            continue
        fn = part.get_filename()
        if fn:
            attachments.append(fn)
            continue
        ct = part.get_content_type()
        try:
            content = part.get_content()
        except (LookupError, ValueError):
            continue
        if ct == "text/plain" and not body:
            body = str(content)
        elif ct == "text/html" and not body:
            body = html_to_text(str(content))
    tail = f"\n\nAnexos do e-mail (não lidos): {', '.join(attachments)}" if attachments else ""
    return "\n".join(head) + "\n\n" + body.strip() + tail


# ------------------------------------------------------------------ Jupyter
def ipynb_text(data: bytes) -> str:
    nb = json.loads(data.decode("utf-8", "replace"))
    out = []
    for i, c in enumerate(nb.get("cells", []), start=1):
        src = c.get("source", "")
        src = "".join(src) if isinstance(src, list) else str(src)
        kind = c.get("cell_type", "code")
        out.append(f"## célula {i} ({'markdown' if kind == 'markdown' else 'código'})\n{src}")
        for o in c.get("outputs", [])[:3]:
            txt = o.get("text") or (o.get("data") or {}).get("text/plain")
            if txt:
                txt = "".join(txt) if isinstance(txt, list) else str(txt)
                out.append(f"[saída] {txt[:2000]}")
    return "\n\n".join(out)


# ------------------------------------------------------------------ EPUB
def epub_chapters(data: bytes) -> list[tuple[str, str]]:
    z = _zip(data)
    pages = sorted(n for n in z.namelist() if re.search(r"\.x?html?$", n, re.I) and "nav" not in posixpath.basename(n).lower())
    out = []
    for i, n in enumerate(pages, start=1):
        t = html_to_text(z.read(n).decode("utf-8", "replace"))
        if t:
            out.append((f"capítulo {i}", t))
    return out


# ------------------------------------------------------------------ zip de documentos
def zip_members(data: bytes) -> list[tuple[str, bytes]]:
    """Arquivos de dentro do zip para ler um a um (sem pastas ocultas, sem caminhos maliciosos, sem zip dentro de zip)."""
    z = _zip(data)
    out = []
    for i in z.infolist():
        if i.is_dir():
            continue
        p = posixpath.normpath(i.filename.replace("\\", "/")).lstrip("/")
        base = posixpath.basename(p)
        if p.startswith("..") or p.startswith("__MACOSX") or base.startswith(".") or base.lower().endswith((".zip", ".skill")):
            continue
        if i.file_size > 30 * 1024 * 1024:
            continue
        out.append((p, z.read(i)))
        if len(out) >= MAX_INNER_FILES:
            break
    return out
