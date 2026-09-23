import React from "react";

/**
 * Shared, XSS-safe Markdown renderer for all AI-generated content
 * (AI Assistant, Explain Issue, Generated Tests, Insights).
 *
 * Renders to React elements only — no dangerouslySetInnerHTML — so AI output
 * can never inject HTML/scripts. Supports: headings, bold, italic, inline
 * code, code blocks, bullet/numbered lists, tables, links, blockquotes and
 * horizontal rules. Also strips escaping artifacts ("\\---", "\\*\\*",
 * "\\|") that some models emit.
 */

// Strip escape artifacts models sometimes emit ("\---", "\**", "\|", "\`").
const cleanEscapeArtifacts = (text: string): string =>
  text
    .replace(/\\([_*`#|\-[>])/g, "$1") // backslash-escaped markdown chars
    .replace(/^\\{2}/gm, ""); // stray double backslashes at line starts

// Inline formatting: code, bold, italic, links → React nodes.
const renderInline = (text: string, keyPrefix: string): React.ReactNode[] => {
  const nodes: React.ReactNode[] = [];
  // Order matters: inline code first (its content is not further formatted),
  // then links, then bold, then italic.
  const pattern = /(`[^`]+`)|(\[[^\]]+\]\((?:https?:\/\/|\/)[^)\s]+\))|(\*\*[^*]+\*\*)|(\*[^*\n]+\*)|(__[^_]+__)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let i = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    const key = `${keyPrefix}-i${i++}`;
    if (token.startsWith("`")) {
      nodes.push(
        <code key={key} className="bg-zinc-100 text-accent-blue px-1 py-0.5 rounded text-[0.92em] font-mono">
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith("[")) {
      const m = token.match(/\[([^\]]+)\]\(([^)]+)\)/);
      if (m) {
        nodes.push(
          <a key={key} href={m[2]} target="_blank" rel="noopener noreferrer" className="text-accent-blue hover:underline font-medium">
            {m[1]}
          </a>
        );
      }
    } else if (token.startsWith("**") || token.startsWith("__")) {
      nodes.push(<strong key={key} className="font-bold text-zinc-900">{token.slice(2, -2)}</strong>);
    } else {
      nodes.push(<em key={key} className="italic">{token.slice(1, -1)}</em>);
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
};

type Block =
  | { kind: "p"; text: string }
  | { kind: "h1" | "h2" | "h3" | "h4"; text: string }
  | { kind: "code"; lang: string; text: string }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] }
  | { kind: "table"; header: string[]; rows: string[][] }
  | { kind: "hr" }
  | { kind: "quote"; text: string };

const isTableRow = (line: string) => line.trim().startsWith("|") && line.trim().endsWith("|");
const splitRow = (line: string) =>
  line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(c => c.trim());

const parseBlocks = (raw: string): Block[] => {
  const text = cleanEscapeArtifacts(raw);
  const lines = text.split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Code block
    if (line.trim().startsWith("```")) {
      const lang = line.trim().slice(3).trim();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      i++; // skip closing fence
      blocks.push({ kind: "code", lang, text: buf.join("\n") });
      continue;
    }

    // Horizontal rule (---, ***, ___ possibly with spaces)
    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) {
      blocks.push({ kind: "hr" });
      i++;
      continue;
    }

    // Headings (# to ####)
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      const level = h[1].length;
      blocks.push({ kind: (`h${level}` as "h1" | "h2" | "h3" | "h4"), text: h[2].trim() });
      i++;
      continue;
    }

    // Table: header row, then a separator row of |---|---|
    if (isTableRow(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1])) {
      const header = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && isTableRow(lines[i])) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      blocks.push({ kind: "table", header, rows });
      continue;
    }

    // Blockquote
    if (line.trim().startsWith(">")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        buf.push(lines[i].trim().replace(/^>\s?/, ""));
        i++;
      }
      blocks.push({ kind: "quote", text: buf.join(" ") });
      continue;
    }

    // Ordered list
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
        i++;
      }
      blocks.push({ kind: "ol", items });
      continue;
    }

    // Bullet list (-, *, +)
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
        i++;
      }
      blocks.push({ kind: "ul", items });
      continue;
    }

    // Blank line
    if (!line.trim()) {
      i++;
      continue;
    }

    // Paragraph: accumulate consecutive non-special lines
    const buf: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,4})\s/.test(lines[i]) &&
      !lines[i].trim().startsWith("```") &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+[.)]\s+/.test(lines[i]) &&
      !isTableRow(lines[i]) &&
      !/^\s*([-*_])\s*(\1\s*){2,}$/.test(lines[i]) &&
      !lines[i].trim().startsWith(">")
    ) {
      buf.push(lines[i]);
      i++;
    }
    if (buf.length) {
      blocks.push({ kind: "p", text: buf.join("\n") });
    } else {
      i++; // safety: never stall
    }
  }

  return blocks;
};

const HEADING_CLASS: Record<"h1" | "h2" | "h3" | "h4", string> = {
  h1: "text-lg font-bold text-zinc-900 mt-4 mb-2",
  h2: "text-base font-bold text-zinc-900 mt-4 mb-2",
  h3: "text-sm font-bold text-zinc-900 mt-3 mb-1.5",
  h4: "text-xs font-bold text-zinc-800 mt-2.5 mb-1",
};

export const Markdown: React.FC<{ content: string; className?: string }> = ({ content, className = "" }) => {
  const blocks = parseBlocks(content || "");

  return (
    <div className={`space-y-2 ${className}`}>
      {blocks.map((b, idx) => {
        const key = `b${idx}`;
        switch (b.kind) {
          case "h1":
          case "h2":
          case "h3":
          case "h4": {
            const Tag = b.kind as keyof React.HTMLAttributes<HTMLDivElement> extends never ? never : "h1" | "h2" | "h3" | "h4";
            return <Tag key={key} className={HEADING_CLASS[b.kind]}>{renderInline(b.text, key)}</Tag>;
          }
          case "code":
            return (
              <pre key={key} className="bg-zinc-100 border border-zinc-200 rounded-xl p-3 my-1.5 overflow-x-auto text-[11px] font-mono text-zinc-800 leading-relaxed">
                {b.lang ? <div className="text-[9px] uppercase tracking-wider text-zinc-500 mb-1">{b.lang}</div> : null}
                <code>{b.text}</code>
              </pre>
            );
          case "ul":
            return (
              <ul key={key} className="list-disc pl-5 space-y-1">
                {b.items.map((it, j) => (
                  <li key={`${key}-${j}`} className="text-xs text-zinc-700 leading-relaxed">{renderInline(it, `${key}-${j}`)}</li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={key} className="list-decimal pl-5 space-y-1">
                {b.items.map((it, j) => (
                  <li key={`${key}-${j}`} className="text-xs text-zinc-700 leading-relaxed">{renderInline(it, `${key}-${j}`)}</li>
                ))}
              </ol>
            );
          case "table":
            return (
              <div key={key} className="overflow-x-auto my-2 border border-zinc-200 rounded-xl">
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="bg-zinc-100">
                      {b.header.map((h, j) => (
                        <th key={`${key}-h${j}`} className="text-left font-bold text-zinc-800 px-3 py-2 border-b border-zinc-200">
                          {renderInline(h, `${key}-h${j}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, ri) => (
                      <tr key={`${key}-r${ri}`} className={ri % 2 ? "bg-zinc-50" : "bg-white"}>
                        {r.map((c, ci) => (
                          <td key={`${key}-r${ri}c${ci}`} className="px-3 py-1.5 text-zinc-700 border-b border-zinc-100 align-top">
                            {renderInline(c, `${key}-r${ri}c${ci}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "hr":
            return <hr key={key} className="border-zinc-200 my-3" />;
          case "quote":
            return (
              <blockquote key={key} className="border-l-4 border-accent-blue/40 bg-accent-blue/5 pl-3 pr-2 py-1.5 rounded-r-lg text-xs text-zinc-700 italic">
                {renderInline(b.text, key)}
              </blockquote>
            );
          case "p":
          default:
            return (
              <p key={key} className="text-xs text-zinc-700 leading-relaxed whitespace-pre-line">
                {renderInline(b.text, key)}
              </p>
            );
        }
      })}
    </div>
  );
};

export default Markdown;
