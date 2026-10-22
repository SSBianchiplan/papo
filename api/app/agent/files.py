"""Arquivos que o agente entrega na conversa: HTML no design system do Papo (ou com tema tirado do contexto) e Markdown.

O modelo escreve Markdown; o servidor monta o HTML. Assim o arquivo sempre segue o design system, e HTML cru vindo do
modelo não entra (é escapado), então o arquivo não carrega script nem estilo de terceiros.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import markdown as md

from ..costs import TZ

DEFAULT_THEME = {"primaria": "#1F8A70", "escura": "#12343B", "fundo": "#F4F7F6", "texto": "#15211F"}
FONT_STACK = 'system-ui,-apple-system,"Segoe UI",Roboto,sans-serif'


def _markdown(text: str) -> str:
    conv = md.Markdown(extensions=["tables", "fenced_code", "sane_lists", "nl2br", "toc"], output_format="html")
    conv.preprocessors.deregister("html_block")       # HTML cru do modelo vira texto
    conv.inlinePatterns.deregister("html")
    out = conv.convert(text)
    out = re.sub(r"&lt;br\s*/?&gt;", "<br>", out, flags=re.I)        # única tag crua aceita: quebra de linha (comum em tabelas)
    return re.sub(r'href="\s*(javascript|vbscript|data):[^"]*"', 'href="#"', out, flags=re.I)


def _mix(hex_a: str, hex_b: str, t: float) -> str:
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b, strict=True))


def render_html(*, titulo: str, conteudo: str, agent_name: str, tema: dict[str, str] | None = None, fonte: str | None = None,
                now: datetime | None = None) -> str:
    th = {**DEFAULT_THEME, **{k: v for k, v in (tema or {}).items() if v}}
    p, d, bg, ink = th["primaria"], th["escura"], th["fundo"], th["texto"]
    font = f'"{fonte}",{FONT_STACK}' if fonte else f'"Manrope",{FONT_STACK}'
    when = (now or datetime.now(TZ)).astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    body = _markdown(conteudo)
    t = html.escape(titulo)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="Papo · {html.escape(agent_name)}">
<title>{t}</title>
<style>
:root{{--accent:{p};--bar:{d};--bg:{bg};--panel:#FFFFFF;--ink:{ink};--sub:{_mix(ink, bg, .45)};--line:{_mix(ink, bg, .82)};
  --chip:{_mix(p, "#FFFFFF", .88)};--bar-ink:#E8F1EF;color-scheme:light dark}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0D1715;--panel:#132220;--ink:#E4ECEA;--sub:#8FA39E;--line:#22332F;
  --chip:{_mix(p, "#0D1715", .78)};--accent:{_mix(p, "#FFFFFF", .18)}}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:{font};font-size:16px;line-height:1.6}}
header{{background:var(--bar);color:var(--bar-ink);padding:28px 20px 24px}}
header .in,main{{max-width:880px;margin:0 auto}}
header h1{{margin:0;font-size:clamp(24px,4vw,34px);line-height:1.2;letter-spacing:-.02em}}
header p{{margin:8px 0 0;opacity:.75;font-size:14px}}
main{{background:var(--panel);margin:-12px auto 40px;border-radius:16px;padding:28px clamp(18px,4vw,40px);
  box-shadow:0 8px 30px rgba(0,0,0,.08)}}
h1,h2,h3,h4{{line-height:1.25;letter-spacing:-.01em;margin:1.6em 0 .5em}}
main>:first-child{{margin-top:0}}
h2{{font-size:22px;padding-bottom:6px;border-bottom:2px solid var(--chip)}}
h3{{font-size:18px}} h4{{font-size:16px;color:var(--sub)}}
a{{color:var(--accent)}}
strong{{color:var(--ink)}}
ul,ol{{padding-left:1.4em}} li{{margin:.25em 0}}
blockquote{{margin:1.2em 0;padding:12px 16px;background:var(--chip);border-left:4px solid var(--accent);border-radius:0 10px 10px 0}}
blockquote p{{margin:.3em 0}}
code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;background:var(--chip);padding:1px 6px;border-radius:5px}}
pre{{background:var(--bar);color:var(--bar-ink);padding:14px 16px;border-radius:10px;overflow-x:auto}}
pre code{{background:none;padding:0;color:inherit}}
table{{border-collapse:collapse;margin:1.2em 0;font-size:14.5px;display:block;overflow-x:auto;max-width:100%;font-variant-numeric:tabular-nums}}
th{{background:var(--bar);color:var(--bar-ink);text-align:left;font-weight:600}}
th,td{{padding:9px 12px;border-bottom:1px solid var(--line);white-space:nowrap}}
tr:nth-child(even) td{{background:color-mix(in srgb,var(--chip) 55%,transparent)}}
hr{{border:0;border-top:1px solid var(--line);margin:2em 0}}
img{{max-width:100%;border-radius:10px}}
footer{{max-width:880px;margin:-24px auto 40px;padding:0 20px;color:var(--sub);font-size:12.5px}}
@media print{{body{{background:#fff}}header{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}main{{box-shadow:none;margin:0}}}}
</style>
</head>
<body>
<header><div class="in"><h1>{t}</h1><p>Gerado por {html.escape(agent_name)} no Papo · {when}</p></div></header>
<main>
{body}
</main>
<footer>Documento gerado por IA a partir da conversa. Confira números e citações antes de usar.</footer>
</body>
</html>
"""


def render_md(*, titulo: str, conteudo: str, agent_name: str, now: datetime | None = None) -> str:
    when = (now or datetime.now(TZ)).strftime("%d/%m/%Y %H:%M")
    head = f"# {titulo}\n\n_Gerado por {agent_name} no Papo · {when}_\n\n"
    body = conteudo.strip()
    if body.startswith("# "):                 # o modelo já pôs título: não duplica
        body = body.split("\n", 1)[1].lstrip() if "\n" in body else ""
    return head + body + "\n"


def safe_filename(nome: str, ext: str) -> str:
    base = re.sub(r"[^A-Za-z0-9À-ÿ._ -]+", "", nome).strip(" .-_")[:80] or "arquivo"
    base = re.sub(r"\.(html?|md|markdown)$", "", base, flags=re.I)
    return f"{base}.{ext}"
