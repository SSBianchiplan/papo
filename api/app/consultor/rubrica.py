"""Motor de rubrica do Consultor de IA (SPEC-GPS-PAPO-CIA-001 §4). Função pura: mesma entrada canônica, mesma nota.

Nenhum LLM entra aqui. A nota vem só da versão da rubrica, dos estados gravados e das respostas do usuário; o SHA-256 da
entrada canônica (JSON ordenado) é gravado com o parecer e é o gate de determinismo (G01).
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

ESTADOS = ("ATENDE", "DECLARADO", "NAO_ATENDE", "LACUNA", "NAO_SE_APLICA")
NOMES = {1: "clássica", 2: "aprendizado de máquina", 3: "redes neurais", 4: "deep learning", 5: "generativa", 6: "agêntica"}
VEREDITO_TXT = {"PRONTA_PARA_AVANCAR": "Pronta para avançar", "AVANCAR_COM_CONDICOES": "Avançar com condições",
                "NAO_AVANCAR_AINDA": "Não avançar ainda"}


def bloco(c: dict[str, Any]) -> str:
    return "nucleo" if c["camada"] == "nucleo" else str(c["camada"])


def aplicaveis(defn: dict[str, Any], camada_real: int | None, camadas_usadas: list[int]) -> list[dict[str, Any]]:
    """Núcleo sempre; critérios de camada só para a camada real e as que ela usa (§4)."""
    usadas = set(camadas_usadas) | ({camada_real} if camada_real else set())
    return [c for c in defn["criterios"] if c["camada"] == "nucleo" or int(c["camada"]) in usadas]


def ordem_entrevista(defn: dict[str, Any], camada_real: int | None, camadas_usadas: list[int], estados: dict[str, str],
                     ja: list[str]) -> list[dict[str, Any]]:
    """Só lacunas, uma vez cada: críticos primeiro, núcleo antes das camadas, depois maior peso, depois ID."""
    pend = [c for c in aplicaveis(defn, camada_real, camadas_usadas) if estados.get(c["id"], "LACUNA") == "LACUNA" and c["id"] not in ja]
    return sorted(pend, key=lambda c: (not c["critico"], c["camada"] != "nucleo", -int(c["peso"]), c["id"]))


def canonica(defn: dict[str, Any], camada_real: int | None, camadas_usadas: list[int], camada_declarada: int | None,
             camada_minima: int | None, estados: dict[str, str], respostas: list[dict[str, Any]]) -> str:
    entrada = {
        "rubrica": defn["versao"], "camada_real": camada_real, "camadas_usadas": sorted(set(camadas_usadas)),
        "camada_declarada": camada_declarada, "camada_minima": camada_minima,
        "estados": {k: estados[k] for k in sorted(estados)},
        "respostas": sorted(({"criterio": r["criterio_id"], "indice": r.get("indice"), "resposta": r["resposta"]} for r in respostas),
                            key=lambda r: (r["criterio"], json.dumps(r, sort_keys=True, ensure_ascii=False))),
    }
    return json.dumps(entrada, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _round(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def calcular(defn: dict[str, Any], *, camada_real: int | None, camadas_usadas: list[int], camada_declarada: int | None,
             camada_minima: int | None, estados: dict[str, str], respostas: list[dict[str, Any]],
             desvio_justificativa: str | None = None) -> dict[str, Any]:
    valores = {k: Decimal(str(v)) for k, v in defn["estados"].items()}
    crits = aplicaveis(defn, camada_real, camadas_usadas)
    est = {c["id"]: estados.get(c["id"], "LACUNA") for c in crits}
    blocos: dict[str, dict[str, Decimal]] = {}
    for c in crits:
        if est[c["id"]] == "NAO_SE_APLICA":
            continue
        b = blocos.setdefault(bloco(c), {"wv": Decimal(0), "w": Decimal(0)})
        w = Decimal(int(c["peso"]))
        b["wv"] += w * valores.get(est[c["id"]], Decimal(0))
        b["w"] += w
    notas = {k: (Decimal(100) * v["wv"] / v["w"]) if v["w"] else Decimal(0) for k, v in blocos.items()}
    total_w = sum((v["w"] for v in blocos.values()), Decimal(0))
    geral = _round(sum((notas[k] * blocos[k]["w"] for k in blocos), Decimal(0)) / total_w) if total_w else 0

    criticos = [c for c in crits if c["critico"] and est[c["id"]] != "NAO_SE_APLICA"]
    condicoes: list[str] = []
    if any(est[c["id"]] == "NAO_ATENDE" for c in criticos):
        veredito = "NAO_AVANCAR_AINDA"
    elif any(est[c["id"]] in ("LACUNA", "DECLARADO") for c in criticos):
        veredito = "AVANCAR_COM_CONDICOES"
    elif geral >= int(defn["veredito"]["limiar_pronta"]):
        veredito = "PRONTA_PARA_AVANCAR"
    else:
        veredito = "AVANCAR_COM_CONDICOES"
    for c in sorted(criticos, key=lambda c: (c["camada"] != "nucleo", c["id"])):     # núcleo primeiro, como na entrevista
        e = est[c["id"]]
        if e in ("NAO_ATENDE", "LACUNA", "DECLARADO"):
            motivo = {"NAO_ATENDE": "não atende", "LACUNA": "sem informação", "DECLARADO": "só declarado, sem documento"}[e]
            condicoes.append(f"{c['id']} {c['texto']} — {motivo}")
    if camada_minima and camada_real and camada_minima < camada_real and not (desvio_justificativa or "").strip():
        condicoes.append(f"Camada mínima ({camada_minima}, {NOMES[camada_minima]}) abaixo da real ({camada_real}, {NOMES[camada_real]}) "
                         "sem justificativa")

    if camada_real == 6 and (est.get("C6.3") != "ATENDE" or est.get("C6.4") != "ATENDE"):
        risco = "ALTO"
    elif camada_real in (5, 6):
        risco = "MEDIO"         # generativa ou agêntica (com C6.3 e C6.4 atendidos); a spec é silenciosa sobre generativa com crítico em aberto
    else:
        risco = "BAIXO"

    faltando = sorted((c for c in crits if est[c["id"]] in ("NAO_ATENDE", "LACUNA", "DECLARADO")),
                      key=lambda c: (not c["critico"], -int(c["peso"]), c["id"]))
    perguntas = [c["pergunta"] for c in faltando[:3]]
    entrada = canonica(defn, camada_real, camadas_usadas, camada_declarada, camada_minima, est, respostas)
    return {
        "rubrica": defn["versao"], "modelo_camadas": defn.get("modelo_camadas", "1.0.0"),
        "camada_declarada": camada_declarada, "camada_real": camada_real, "camadas_usadas": sorted(set(camadas_usadas)),
        "camada_minima": camada_minima, "divergencia_camada": bool(camada_declarada and camada_real and camada_declarada != camada_real),
        "notas_bloco": {k: str(notas[k].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) for k in sorted(notas)},
        "nota_geral": geral, "veredito": veredito, "risco": risco, "condicoes": condicoes, "perguntas_ao_fornecedor": perguntas,
        "criterios": [{"id": c["id"], "texto": c["texto"], "camada": c["camada"], "peso": c["peso"], "critico": c["critico"],
                       "estado": est[c["id"]]} for c in crits],
        "hash_entrada": hashlib.sha256(entrada.encode()).hexdigest(),
    }


# ----------------------------------------------------------------- validador de citação (plano de execução)
_Q = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", " ": " "})


def normalizar(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_Q).lower()
    s = re.sub(r"-\s*\n\s*", "", s)                # hifenização de quebra de linha do PDF
    return re.sub(r"\s+", " ", s).strip()


def citacao_valida(trecho: str, pagina_texto: str) -> tuple[bool, str]:
    """ATENDE só com trecho literal (normalizado) na página indicada; paráfrase é recusada (G06)."""
    t = normalizar(trecho)
    if len(t) < 15:
        return False, "trecho curto demais para ser evidência (mínimo 15 caracteres)"
    if t not in normalizar(pagina_texto):
        return False, "trecho não existe literalmente nesta página"
    return True, "ok"


PII = [(re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[CPF]"), (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[e-mail]"),
       (re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}\b"), "[telefone]")]
CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")


def sem_dado_pessoal(s: str) -> str:
    """Dados pessoais encontrados no documento não aparecem no parecer (§11)."""
    for rx, rep in PII:
        s = rx.sub(rep, s)
    return s
