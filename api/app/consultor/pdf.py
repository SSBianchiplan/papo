"""PDF do parecer, renderizado a partir do registro selado (nunca do texto do LLM). Determinístico: mesmo registro, mesmos bytes."""
from __future__ import annotations

import io
from typing import Any

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .rubrica import NOMES, VEREDITO_TXT, sem_dado_pessoal

rl_config.invariant = 1           # sem data de criação nem ID aleatório: o hash do PDF é reproduzível (G12)
BAR, ACCENT, INK, SUB, LINE, CHIP = (colors.HexColor(c) for c in ("#12343B", "#1F8A70", "#15211F", "#5E6F6B", "#DDE5E3", "#E9F2EF"))
ESTADO_TXT = {"ATENDE": "Atende", "DECLARADO": "Declarado", "NAO_ATENDE": "Não atende", "LACUNA": "Lacuna", "NAO_SE_APLICA": "Não se aplica"}
RISCO_TXT = {"ALTO": "Alto", "MEDIO": "Médio", "BAIXO": "Baixo"}


def _esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(p: dict[str, Any], *, titulo: str, versao: int, hash_parecer: str, evidencias: dict[str, dict[str, Any]],
           respostas: dict[str, str], emitido: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Parecer · {titulo}", author="Consultor de IA · Papo")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=17, leading=21, textColor=BAR, alignment=0, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, leading=15, textColor=BAR, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13, textColor=INK)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10.5, textColor=SUB)
    cell = ParagraphStyle("c", parent=body, fontSize=8.3, leading=10.5)

    def camada(n: int | None) -> str:
        return f"{n} · {NOMES[n]}" if n else "—"

    story: list[Any] = [
        Paragraph(f"Parecer do Consultor de IA · versão {versao}", small),
        Paragraph(_esc(titulo), h1),
        Paragraph(f"Emitido em {emitido} · rubrica {p['rubrica']} · modelo de camadas {p['modelo_camadas']}", small),
        Spacer(1, 6),
    ]
    resumo = [["Nota geral", "Veredito", "Risco"], [str(p["nota_geral"]), VEREDITO_TXT[p["veredito"]], RISCO_TXT[p["risco"]]]]
    t = Table(resumo, colWidths=[40 * mm, 80 * mm, 54 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BAR), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, 0), 8.5),
                           ("FONTSIZE", (0, 1), (-1, 1), 15), ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"), ("TEXTCOLOR", (0, 1), (-1, 1), BAR),
                           ("TOPPADDING", (0, 1), (-1, 1), 7), ("BOTTOMPADDING", (0, 1), (-1, 1), 8), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                           ("BACKGROUND", (0, 1), (-1, 1), CHIP)]))
    story += [t, Paragraph("Camadas", h2)]
    cam = [["Declarada", "Real (pela evidência)", "Usadas", "Mínima"],
           [camada(p["camada_declarada"]), camada(p["camada_real"]), ", ".join(str(c) for c in p["camadas_usadas"]) or "—",
            camada(p["camada_minima"])]]
    t = Table(cam, colWidths=[40 * mm, 54 * mm, 30 * mm, 50 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), CHIP), ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                           ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE)]))
    story.append(t)
    if p["divergencia_camada"]:
        story.append(Paragraph("A camada declarada pela proposta é diferente da camada real confirmada por evidência.", small))
    ordem = sorted(p["notas_bloco"], key=lambda k: (k != "nucleo", k))          # núcleo primeiro, depois camadas em ordem
    notas = [["Bloco", "Nota"]] + [["Núcleo" if k == "nucleo" else f"Camada {camada(int(k))}", p["notas_bloco"][k].replace(".", ",")] for k in ordem]
    t = Table(notas, colWidths=[124 * mm, 50 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), CHIP), ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                           ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE)]))
    story += [Paragraph("Notas por bloco", h2), t]
    if p["condicoes"]:
        story.append(Paragraph("Condições", h2))
        story += [Paragraph(f"• {_esc(c)}", body) for c in p["condicoes"]]
    if p["perguntas_ao_fornecedor"]:
        story.append(Paragraph("Perguntas para levar ao fornecedor", h2))
        story += [Paragraph(f"{i}. {_esc(q)}", body) for i, q in enumerate(p["perguntas_ao_fornecedor"], start=1)]
    story.append(Paragraph("Critérios", h2))
    rows = [[Paragraph("<b>ID</b>", cell), Paragraph("<b>Critério</b>", cell), Paragraph("<b>Estado</b>", cell), Paragraph("<b>Base</b>", cell)]]
    for c in p["criterios"]:
        ev = evidencias.get(c["id"])
        base = (f"p. {ev['pagina']}: “{_esc(sem_dado_pessoal(ev['trecho']))[:220]}”" if ev else
                f"Resposta: {_esc(respostas[c['id']])}" if c["id"] in respostas else "—")
        rows.append([Paragraph(c["id"] + (" *" if c["critico"] else ""), cell), Paragraph(_esc(c["texto"]), cell),
                     Paragraph(ESTADO_TXT[c["estado"]], cell), Paragraph(base, cell)])
    t = Table(rows, colWidths=[14 * mm, 64 * mm, 22 * mm, 74 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), CHIP), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                           ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F9F8")])]))
    story += [t, Paragraph("* critério crítico: bloqueia o veredito.", small), Spacer(1, 8),
              Paragraph("Parecer técnico emitido pelo Consultor de IA do Papo. A IA propõe, o humano decide: este documento é insumo, "
                        "não aprova contratação e não avalia preço, contrato, aspectos jurídicos ou fiscais.", small),
              Paragraph(f"Hash da entrada: {p['hash_entrada']}<br/>Hash do parecer: {hash_parecer}", small)]
    doc.build(story)
    return buf.getvalue()
