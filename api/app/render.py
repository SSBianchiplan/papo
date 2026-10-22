"""Pré-visualização formatada de documentos (hub e arquivos do Papo): bytes → página HTML legível, no tema do app.

Markdown é renderizado com HTML cru desativado (o mesmo conversor dos arquivos gerados); os demais formatos viram
parágrafos, listas, tabelas e páginas reconstruídos a partir do texto extraído. Nada vem do arquivo como HTML ativo,
e a página é exibida num iframe sandbox (sem script).
"""
from __future__ import annotations

import html
import re
from typing import Any, Literal

from .agent.files import _markdown
from .extract.parsers import Extracted, decode_text, parse

Theme = Literal["light", "dark"]
CODE_EXT = {"txt", "log", "json", "yaml", "yml", "xml", "sql", "py", "js", "ts", "tsx", "jsx", "css", "ini", "cfg", "conf", "sh", "toml",
            "java", "c", "cpp", "cs", "go", "rs", "rb", "php"}
LABELED = {"pdf", "pptx", "ppsx", "potx", "odp", "epub", "zip", "skill"}
MAX_ROWS = 300

THEMES = {
    "light": {"bg": "#FFFFFF", "ink": "#15211F", "sub": "#5E6F6B", "line": "#DDE5E3", "chip": "#E9F2EF", "accent": "#1F8A70",
              "head": "#12343B", "head_ink": "#E8F1EF", "code": "#F4F7F6"},
    "dark": {"bg": "#132220", "ink": "#E4ECEA", "sub": "#8FA39E", "line": "#22332F", "chip": "#1B2E2A", "accent": "#2FA584",
             "head": "#1E4A3B", "head_ink": "#E3EEEB", "code": "#0D1715"},
}


def _inline(s: str) -> str:
    t = html.escape(s)
    t = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", t)
    return re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)


def _table(rows: list[list[str]], head: bool = True) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    th = "".join(f"<th>{_inline(c)}</th>" for c in rows[0]) if head else ""
    body = rows[1:] if head else rows
    tb = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body)
    return f'<div class="tw"><table>{f"<thead><tr>{th}</tr></thead>" if th else ""}<tbody>{tb}</tbody></table></div>'


def paragraphs(text: str) -> str:
    """Texto extraído (Word, ODT, RTF, e-mail…) → parágrafos, títulos, listas e tabelas."""
    out: list[str] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        piped = [ln for ln in lines if " | " in ln or ln.count("\t") >= 1]
        if len(lines) >= 2 and len(piped) == len(lines):
            sep = " | " if " | " in lines[0] else "\t"
            out.append(_table([[c.strip() for c in ln.split(sep)] for ln in lines]))
            continue
        bullets = [re.match(r"^\s*(?:[•\-–*]|\d{1,3}[.)])\s+(.*)$", ln) for ln in lines]
        if all(bullets):
            tag = "ol" if re.match(r"^\s*\d", lines[0]) else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(m.group(1))}</li>" for m in bullets if m) + f"</{tag}>")
            continue
        m = re.match(r"^(#{1,4})\s+(.+)$", lines[0])
        if m:                                  # título no começo do bloco (ODT marca com ##)
            level = max(2, len(m.group(1)))      # ## → h2 (o h1 da página é o nome do arquivo)
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            lines = lines[1:]
        if lines:
            out.append("<p>" + "<br>".join(_inline(ln) for ln in lines) + "</p>")
    return "\n".join(out)


def _sheets(ex: Extracted) -> str:
    out = []
    for sh in ex.sheets:
        rows = [[str(c) if c is not None else "" for c in r] for r in sh.rows[:MAX_ROWS]]
        shown = len(rows)
        cap = f'<p class="cap"><b>{html.escape(sh.name)}</b> · {sh.total:,} linhas'.replace(",", ".") \
            + (f" · mostrando as primeiras {shown}" if sh.total > shown else "") + "</p>"
        out.append(cap + _table([list(sh.columns)] + rows))
    return "\n".join(out)


def body_html(data: bytes, filename: str) -> tuple[str, str | None]:
    """Conteúdo formatado (sem o invólucro) e uma observação, se houver."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("md", "markdown"):
        return _markdown(decode_text(data)), None
    if ext in CODE_EXT:
        return f"<pre><code>{html.escape(decode_text(data)[:400_000])}</code></pre>", None
    ex = parse(data, filename, "")
    if ex.sheets:
        return _sheets(ex), ex.note
    if ext == "ipynb":
        return _markdown("\n\n".join(t for _, t in ex.parts)), ex.note
    if not ex.parts:
        return f'<p class="cap">{html.escape(ex.note or "Sem texto legível neste arquivo.")}</p>', None
    if ext in LABELED:
        secs = []
        for label, txt in ex.parts:
            nice = re.sub(r"^(slide|capítulo) (\d+)$", lambda m: f"{m.group(1).capitalize()} {m.group(2)}", label)
            nice = re.sub(r"^página (\d+)$", r"Página \1", nice)
            secs.append(f'<section><div class="plabel">{html.escape(nice)}</div>{paragraphs(txt)}</section>')
        return "\n".join(secs), ex.note
    return paragraphs("\n\n".join(t for _, t in ex.parts)), ex.note


def _soft_breaks(body: str) -> str:
    """Código inline longo (caminhos, nomes de teste) quebra em / :: _ . em vez de no meio da palavra."""
    def wbr(m: re.Match[str]) -> str:
        inner = m.group(1)
        if len(inner) < 24:
            return m.group(0)
        return "<code>" + re.sub(r"(::|/|_|\.)", r"\1<wbr>", inner) + "</code>"
    return re.sub(r"(?<!<pre>)<code>([^<]*)</code>", wbr, body)


def page(body: str, title: str, theme: Theme = "light", note: str | None = None) -> str:
    c = THEMES.get(theme, THEMES["light"])
    body = _soft_breaks(body)
    banner = f'<p class="note">{html.escape(note)}</p>' if note else ""
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
:root{{color-scheme:{theme}}}
*{{box-sizing:border-box}}
body{{margin:0;background:{c['bg']};color:{c['ink']};font:15.5px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  padding:22px clamp(16px,4vw,44px) 40px}}
main{{max-width:860px;margin:0 auto}}
h1,h2,h3,h4,h5{{line-height:1.3;margin:1.4em 0 .5em;letter-spacing:-.01em}}
main>:first-child{{margin-top:0}}
h1{{font-size:26px}} h2{{font-size:21px;padding-bottom:6px;border-bottom:2px solid {c['chip']}}} h3{{font-size:18px}} h4,h5{{font-size:16px}}
p{{margin:.55em 0}} ul,ol{{padding-left:1.4em;margin:.5em 0}} li{{margin:.2em 0}}
a{{color:{c['accent']}}}
blockquote{{margin:1em 0;padding:10px 14px;background:{c['chip']};border-left:4px solid {c['accent']};border-radius:0 10px 10px 0}}
code{{font:13.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:{c['chip']};padding:1px 6px;border-radius:5px;word-break:break-word}}
pre{{background:{c['code']};border:1px solid {c['line']};padding:14px 16px;border-radius:10px;overflow-x:auto;white-space:pre}}
pre code{{background:none;padding:0;word-break:normal}}
.tw{{overflow-x:auto;margin:1em 0;border:1px solid {c['line']};border-radius:10px}}
table{{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}}
th{{background:{c['head']};color:{c['head_ink']};text-align:left;font-weight:600;position:sticky;top:0}}
th,td{{padding:8px 12px;border-bottom:1px solid {c['line']};vertical-align:top}}
tr:nth-child(even) td{{background:{c['chip']}}}
tr:last-child td{{border-bottom:0}}
main>table{{display:block;overflow-x:auto;border:1px solid {c['line']};border-radius:10px;margin:1em 0}}
td code,th code{{overflow-wrap:break-word;word-break:normal}}
tr:nth-child(even) td code{{background:{c['bg']}}}
td:first-child{{min-width:5.5em}}
hr{{border:0;border-top:1px solid {c['line']};margin:2em 0}}
img{{max-width:100%}}
section{{padding:14px 0 6px;border-top:1px solid {c['line']}}}
section:first-of-type{{border-top:0;padding-top:0}}
.plabel{{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:{c['sub']};
  background:{c['chip']};padding:2px 9px;border-radius:999px;margin-bottom:6px}}
.cap{{color:{c['sub']};font-size:13.5px;margin:1.2em 0 .3em}}
.note{{background:{c['chip']};border-radius:10px;padding:8px 12px;font-size:13.5px;color:{c['sub']}}}
</style></head><body><main>{banner}{body}</main></body></html>"""


def preview(data: bytes, filename: str, theme: Theme = "light") -> dict[str, Any]:
    body, note = body_html(data, filename)
    return {"name": filename, "html": page(body, filename, theme, note), "note": note}
