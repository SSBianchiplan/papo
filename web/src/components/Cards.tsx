// Cartões tipados do Consultor de IA no balão (JSON do servidor → componentes; nenhum HTML vindo do agente).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError, downloadDocument, ok } from "../api/client";
import { useApp } from "../store";
import { Modal } from "./ui";

type Card = Record<string, unknown> & { tipo: string };
const full = (e: Error) => (e instanceof ApiError && e.hint ? `${e.message} ${e.hint}` : e.message);
const NOMES: Record<number, string> = { 1: "clássica", 2: "aprendizado de máquina", 3: "redes neurais", 4: "deep learning", 5: "generativa", 6: "agêntica" };
const VEREDITO: Record<string, [string, string]> = { PRONTA_PARA_AVANCAR: ["Pronta para avançar", "ok"], AVANCAR_COM_CONDICOES: ["Avançar com condições", "warn"],
  NAO_AVANCAR_AINDA: ["Não avançar ainda", "bad"] };
const RISCO: Record<string, string> = { ALTO: "Risco alto", MEDIO: "Risco médio", BAIXO: "Risco baixo" };
const ESTADO: Record<string, [string, string]> = { ATENDE: ["Atende", "ok"], DECLARADO: ["Declarado", "warn"], NAO_ATENDE: ["Não atende", "bad"],
  LACUNA: ["Lacuna", "bad"], NAO_SE_APLICA: ["Não se aplica", ""] };

function useResponder(card: Card) {
  const notify = useApp((s) => s.notify);
  const qc = useQueryClient();
  const [busy, setBusy] = useState<number | null>(null);
  const send = async (body: { criterio_id: string; indice?: number; confirmar?: boolean }, i: number) => {
    setBusy(i);
    try {
      await ok(api.POST("/api/governanca/consultor/avaliacoes/{aid}/respostas", { params: { path: { aid: String(card.avaliacao_id) } }, body }));
      void qc.invalidateQueries({ queryKey: ["messages"] });
    } catch (e) { notify(full(e as Error)); setBusy(null); }
  };
  return { busy, send };
}

function Pergunta({ card, live }: { card: Card; live: boolean }) {
  const { busy, send } = useResponder(card);
  const opcoes = card.opcoes as string[];
  return (
    <div className="qcard">
      <div className="qmeta">{card.critico ? <span className="tag bad">crítico</span> : null}<code>{String(card.criterio_id)}</code>
        {card.restantes ? <small className="muted">{String(card.restantes)} pergunta(s) pendente(s)</small> : null}</div>
      <div className="qbtns">{opcoes.map((o, i) => (
        <button key={i} className="qbtn" disabled={!live || busy !== null} aria-busy={busy === i}
          onClick={() => void send(card.tipo === "confirmacao" ? { criterio_id: String(card.criterio_id), confirmar: i === 0 } : { criterio_id: String(card.criterio_id), indice: i }, i)}>{o}</button>))}</div>
      {live && <small className="muted">Ou responda com suas palavras; eu confirmo antes de registrar.</small>}
    </div>
  );
}

type Rub = { versao: string; definicao: { criterios: { id: string; respostas_rapidas: string[] }[] } };

function Contestar({ card, crit, onClose }: { card: Card; crit: { id: string; texto: string }; onClose: () => void }) {
  const notify = useApp((s) => s.notify);
  const qc = useQueryClient();
  const { data: rubs = [] } = useQuery({ queryKey: ["gov-rubricas"], queryFn: () => ok(api.GET("/api/governanca/rubricas")) as Promise<unknown> as Promise<Rub[]> });
  const opcoes = rubs.find((r) => r.versao === card.rubrica)?.definicao.criterios.find((c) => c.id === crit.id)?.respostas_rapidas ?? [];
  const [idx, setIdx] = useState<number | null>(null);
  const [just, setJust] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    if (idx === null) return;
    setBusy(true);
    try {
      await ok(api.POST("/api/governanca/consultor/avaliacoes/{aid}/contestacoes", { params: { path: { aid: String(card.avaliacao_id) } },
        body: { criterio_id: crit.id, indice: idx, justificativa: just } }));
      void qc.invalidateQueries({ queryKey: ["messages"] });
      notify("Contestação registrada. Nova versão do parecer selada; a anterior fica intacta.");
      onClose();
    } catch (e) { notify(full(e as Error)); setBusy(false); }
  };
  return (
    <Modal title={`Contestar ${crit.id}`} onClose={onClose}
      footer={<><span className="muted">Contestação vira resposta; nunca vira "atende" sem documento.</span><button className="btn" disabled={idx === null || busy} onClick={() => void go()}>Contestar</button></>}>
      <p>{crit.texto}</p>
      <div className="pick">{opcoes.map((o, i) => <label key={i}><input type="radio" name="ct" checked={idx === i} onChange={() => setIdx(i)} />{o}</label>)}</div>
      <div className="field"><label htmlFor="ctj">Justificativa</label><textarea id="ctj" maxLength={500} value={just} onChange={(e) => setJust(e.target.value)} /></div>
    </Modal>
  );
}

function Parecer({ card }: { card: Card }) {
  const notify = useApp((s) => s.notify);
  const [open, setOpen] = useState(false);
  const [contest, setContest] = useState<{ id: string; texto: string } | null>(null);
  const [vt, vc] = VEREDITO[String(card.veredito)] ?? ["—", ""];
  const dec = card.camada_declarada as number | null, real = card.camada_real as number, min = card.camada_minima as number | null;
  const crits = card.criterios as { id: string; texto: string; estado: string; critico: boolean }[];
  const condicoes = card.condicoes as string[], perguntas = card.perguntas_ao_fornecedor as string[];
  return (
    <div className="pcard">
      <div className="ph"><small className="muted">Parecer v{String(card.versao)} · rubrica {String(card.rubrica ?? "")}</small><b>{String(card.titulo)}</b></div>
      <div className="pnums">
        <div className="pnota"><b>{String(card.nota_geral)}</b><small>nota</small></div>
        <div className="pver"><span className={`badge ${vc}`}>{vt}</span><span className={`badge ${card.risco === "ALTO" ? "bad" : card.risco === "MEDIO" ? "warn" : "ok"}`}>{RISCO[String(card.risco)]}</span></div>
      </div>
      <div className="pcam">Camada real <b>{real} · {NOMES[real]}</b>{dec && dec !== real ? <> (declarada {dec} · {NOMES[dec]})</> : null}{min ? <> · mínima {min} · {NOMES[min]}</> : null}</div>
      {condicoes.length > 0 && <><div className="psec">Condições</div><ul>{condicoes.map((c, i) => <li key={i}>{c}</li>)}</ul></>}
      {perguntas.length > 0 && <><div className="psec">Leve ao fornecedor</div><ol>{perguntas.map((q, i) => <li key={i}>{q}</li>)}</ol></>}
      <button className="linkbtn" onClick={() => setOpen(!open)}>{open ? "Ocultar critérios" : `Ver os ${crits.length} critérios`}</button>
      {open && <ul className="pcrit">{crits.map((c) => {
        const [et, ec] = ESTADO[c.estado] ?? [c.estado, ""];
        return <li key={c.id}><code>{c.id}</code><span className="ellip" title={c.texto}>{c.texto}{c.critico ? " *" : ""}</span><span className={`badge ${ec}`}>{et}</span>
          {c.estado !== "NAO_SE_APLICA" && <button className="linkbtn" onClick={() => setContest(c)}>Contestar</button>}</li>;
      })}</ul>}
      <div className="pact"><button className="btn sm" onClick={() => void downloadDocument(String(card.pdf_document_id), `parecer-ia-v${card.versao}.pdf`).catch((e: Error) => notify(e.message))}>Baixar PDF</button>
        <small className="muted ellip" title={String(card.hash_parecer)}>selo {String(card.hash_parecer).slice(0, 12)}…</small></div>
      {contest && <Contestar card={card} crit={contest} onClose={() => setContest(null)} />}
    </div>
  );
}

export function MessageCard({ card, live }: { card: Card; live: boolean }) {
  if (card.tipo === "pergunta_rapida" || card.tipo === "confirmacao") return <Pergunta card={card} live={live} />;
  if (card.tipo === "cartao_parecer") return <Parecer card={card} />;
  return null;
}
