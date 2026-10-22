// Formatação das respostas no balão: Markdown leve + estilo WhatsApp, sempre sobre texto já escapado.
// Blocos: título, lista (com um nível de recuo), tabela, citação, código, linha; inline: negrito, itálico, riscado, código, link.
// Nada do modelo entra como HTML: o texto é escapado antes e só estas marcações viram tags.

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

function inline(s: string): string {
  const codes: string[] = [];
  let t = s.replace(/`([^`\n]+)`/g, (_, c: string) => `\u0000${codes.push(c) - 1}\u0000`);          // protege código
  t = t.replace(/\[([^\]\n]{1,200})\]\((https?:\/\/[^\s)]+)\)/g, (_, txt: string, url: string) =>
    `<a href="${url}" target="_blank" rel="noopener noreferrer">${txt}</a>`);
  t = t.replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?])/g, (_, pre: string, url: string) =>
    `${pre}<a href="${url}" target="_blank" rel="noopener noreferrer">${url.length > 60 ? url.slice(0, 57) + "…" : url}</a>`);
  t = t.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>").replace(/__([^_\n]+)__/g, "<b>$1</b>");
  t = t.replace(/(^|[^\w*])\*([^*\n]+)\*(?=[^\w*]|$)/g, "$1<b>$2</b>");                                // *negrito* do WhatsApp
  t = t.replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,;:!?]|$)/g, "$1<i>$2</i>");
  t = t.replace(/~~([^~\n]+)~~/g, "<s>$1</s>").replace(/(^|\s)~([^~\n]+)~(?=\s|$|[.,!?])/g, "$1<s>$2</s>");
  return t.replace(/\u0000(\d+)\u0000/g, (_, i: string) => `<code>${codes[Number(i)]}</code>`);
}

const isRow = (l: string) => /^\s*\|.*\|\s*$/.test(l);
const isSep = (l: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
const cells = (l: string) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const LIST = /^(\s*)([-*•]|\d{1,3}[.)])\s+(.*)$/;

function table(rows: string[], align: string[]): string {
  const [head, ...body] = rows.map(cells);
  const a = (i: number) => (align[i] ? ` style="text-align:${align[i]}"` : "");
  return `<div class="mt"><table><thead><tr>${head!.map((c, i) => `<th${a(i)}>${inline(c)}</th>`).join("")}</tr></thead><tbody>${
    body.map((r) => `<tr>${head!.map((_, i) => `<td${a(i)}>${inline(r[i] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function list(lines: string[]): string {
  const ordered = /^\s*\d/.test(lines[0]!);
  const base = (LIST.exec(lines[0]!)?.[1] ?? "").length;
  let html = "", sub: string[] = [];
  const flush = () => { if (sub.length) { html = html.replace(/<\/li>$/, `${list(sub)}</li>`); sub = []; } };
  for (const l of lines) {
    const m = LIST.exec(l);
    if (m && m[1]!.length <= base) { flush(); html += `<li>${inline(m[3]!)}</li>`; }
    else if (m) sub.push(l);
    else html = html.replace(/<\/li>$/, `<br>${inline(l.trim())}</li>`);               // continuação do item
  }
  flush();
  return ordered ? `<ol>${html}</ol>` : `<ul>${html}</ul>`;
}

export function formatMessage(raw: string): string {
  const src = esc(raw.replace(/\r\n/g, "\n"));
  const out: string[] = [];
  const lines = src.split("\n");
  let para: string[] = [];
  const endPara = () => { if (para.length) { out.push(`<p>${para.map(inline).join("<br>")}</p>`); para = []; } };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i]!;
    const fence = /^\s*```(\S*)\s*$/.exec(l);
    if (fence) {                                                      // bloco de código (até o fechamento, ou o fim no streaming)
      endPara();
      const code: string[] = [];
      while (++i < lines.length && !/^\s*```\s*$/.test(lines[i]!)) code.push(lines[i]!);
      out.push(`<pre><code>${code.join("\n")}</code></pre>`);
      continue;
    }
    if (!l.trim()) { endPara(); continue; }
    const h = /^\s*(#{1,4})\s+(.+?)\s*#*\s*$/.exec(l);
    if (h) { endPara(); out.push(`<div class="mh mh${h[1]!.length}">${inline(h[2]!)}</div>`); continue; }
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(l)) { endPara(); out.push("<hr>"); continue; }
    if (isRow(l) && i + 1 < lines.length && isSep(lines[i + 1]!)) {
      endPara();
      const align = cells(lines[i + 1]!).map((c) => (c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : ""));
      const rows = [l];
      i += 2;
      while (i < lines.length && isRow(lines[i]!)) rows.push(lines[i++]!);
      i--;
      out.push(table(rows, align));
      continue;
    }
    if (/^\s*&gt;\s?/.test(l)) {
      endPara();
      const q: string[] = [];
      while (i < lines.length && /^\s*&gt;\s?/.test(lines[i]!)) q.push(lines[i++]!.replace(/^\s*&gt;\s?/, ""));
      i--;
      out.push(`<blockquote>${q.map(inline).join("<br>")}</blockquote>`);
      continue;
    }
    if (LIST.test(l)) {
      endPara();
      const items: string[] = [];
      while (i < lines.length && lines[i]!.trim() && (LIST.test(lines[i]!) || /^\s{2,}\S/.test(lines[i]!))) items.push(lines[i++]!);
      i--;
      out.push(list(items));
      continue;
    }
    para.push(l.trim());
  }
  endPara();
  return out.join("");
}
