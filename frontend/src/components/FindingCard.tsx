import React from "react";
import { ExternalLink, Lightbulb, FileWarning } from "lucide-react";

/**
 * Redacts obvious secret literals for display only (never mutates stored data).
 * Only masks string values on lines that look like credential assignments, so
 * normal code evidence stays fully readable.
 */
function redactSecrets(code: string): string {
  const CRED_NAME = /(password|passwd|secret|token|api_?key|access_?key|auth|credential)/i;
  return code
    .split("\n")
    .map((line) => {
      if (!CRED_NAME.test(line)) return line;
      // Mask the value part of assignments like: API_KEY = "sk-xxxx"
      return line.replace(
        /(\s*[:=]\s*)(["'`])(?:(?!\2).){6,}\2/g,
        (_m, prefix: string, quote: string) => `${prefix}${quote}••••••••${quote}`
      );
    })
    .join("\n");
}

const SEVERITY_STYLES: Record<string, string> = {
  Critical: "text-accent-red bg-red-500/10 border-red-500/20",
  High: "text-accent-red bg-red-500/10 border-red-500/20",
  Medium: "text-accent-orange bg-orange-500/10 border-orange-500/20",
  Low: "text-accent-blue bg-blue-500/10 border-blue-500/20",
  Info: "text-zinc-600 bg-zinc-500/10 border-zinc-500/20 dark:text-zinc-300 dark:border-zinc-600",
};

function detectionLabel(source?: string | null): string {
  switch ((source || "").toLowerCase()) {
    case "static_analysis":
    case "deterministic":
      return "Static Analysis";
    case "ai_analysis":
      return "AI Analysis";
    default:
      return "Not recorded";
  }
}

export interface FindingCardProps {
  severity: string;
  issue: string;
  file: string;
  line: number;
  startLine?: number | null;
  endLine?: number | null;
  /** Real code snippet from the scan, if one was captured. */
  evidence?: string | null;
  /** Remediation snippet produced by the scan, if available. */
  suggestedFix?: string | null;
  whyItMatters?: string | null;
  suggestion: string;
  source?: string | null;
  onJumpToLine: () => void;
  onExplain: () => void;
}

/**
 * Evidence-based finding card: shows Issue, Evidence, Why This Matters and
 * Suggested Action using only the data persisted for this finding. When a
 * snippet was not captured, it says so instead of inventing one.
 */
export const FindingCard: React.FC<FindingCardProps> = ({
  severity,
  issue,
  file,
  line,
  startLine,
  endLine,
  evidence,
  suggestedFix,
  whyItMatters,
  suggestion,
  source,
  onJumpToLine,
  onExplain,
}) => {
  const sevStyle = SEVERITY_STYLES[severity] || SEVERITY_STYLES.Info;
  const lineLabel =
    startLine != null && endLine != null && endLine !== startLine
      ? `${startLine}–${endLine}`
      : String(line);
  const detection = detectionLabel(source);
  const redactedEvidence = evidence ? redactSecrets(evidence) : null;

  return (
    <div className="glass p-5 rounded-2xl flex flex-col">
      {/* Header: severity, detection, issue */}
      <div className="flex flex-wrap justify-between items-start gap-2 mb-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ${sevStyle}`}>
              {severity}
            </span>
            <span className="text-[9px] font-bold uppercase tracking-wider text-zinc-500 px-2 py-0.5 bg-zinc-500/5 border border-border rounded-full dark:text-zinc-400">
              Detection: {detection}
            </span>
          </div>
          <h4 className="font-bold text-sm text-zinc-900 mt-2 dark:text-zinc-100">{issue}</h4>
        </div>
      </div>

      {/* Location */}
      <p className="text-xs text-zinc-600 mt-1 mb-3 dark:text-zinc-400">
        <span className="font-bold text-zinc-800 dark:text-zinc-200">File:</span>{" "}
        <span className="font-mono">{file}</span>
        {" · "}
        <span className="font-bold text-zinc-800 dark:text-zinc-200">Line:</span> {lineLabel}
      </p>

      {/* Evidence — real snippet or honest fallback */}
      <div className="mb-3">
        <span className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block mb-1.5 dark:text-zinc-400">
          Evidence
        </span>
        {redactedEvidence ? (
          <>
            <pre className="p-3 bg-zinc-100 border border-border rounded-lg text-zinc-800 font-mono text-[11px] overflow-x-auto whitespace-pre-wrap dark:bg-zinc-900 dark:text-zinc-200">
              {redactedEvidence}
            </pre>
            {redactedEvidence !== evidence && (
              <p className="text-[9px] text-zinc-500 mt-1 dark:text-zinc-400">
                Note: values on credential-like lines are masked for display.
              </p>
            )}
          </>
        ) : (
          <div className="flex items-start gap-2 p-3 bg-background/50 border border-dashed border-border rounded-lg text-[11px] text-zinc-600 dark:bg-zinc-900/40 dark:text-zinc-400">
            <FileWarning className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>
              No code snippet was captured for this finding. Open the file in the Code
              Explorer at line {lineLabel} to view the actual source.
            </span>
          </div>
        )}
      </div>

      {/* Why this matters / Suggested action */}
      <div className="text-xs text-zinc-700 space-y-2 dark:text-zinc-300">
        <p>
          <span className="font-bold text-zinc-900 block mb-0.5 dark:text-zinc-100">Why This Matters:</span>
          {whyItMatters || "Not available for this finding."}
        </p>
        <p>
          <span className="font-bold text-zinc-900 block mb-0.5 dark:text-zinc-100">Suggested Action:</span>
          {suggestion || "Not available for this finding."}
        </p>
      </div>

      {/* Suggested remediation code, when the scan produced one */}
      {suggestedFix && (
        <div className="mt-4">
          <span className="text-[10px] font-bold uppercase tracking-widest text-accent-green block mb-2">
            Suggested Fix
          </span>
          <pre className="p-3 bg-green-50 border border-green-200 rounded-lg text-zinc-800 font-mono text-[11px] overflow-x-auto whitespace-pre-wrap dark:bg-green-950/30 dark:border-green-800 dark:text-green-200">
            {suggestedFix}
          </pre>
        </div>
      )}

      {/* Actions */}
      <div className="mt-4 pt-4 border-t border-border/40 flex justify-between items-center font-sans">
        <div className="flex gap-2">
          <button
            onClick={onJumpToLine}
            className="px-3 py-1.5 border border-border hover:bg-zinc-100 text-zinc-700 hover:text-zinc-900 rounded-lg text-xs font-semibold transition-colors flex items-center gap-1.5 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
          >
            <ExternalLink className="w-3 h-3" /> Open in Editor
          </button>
          <button
            onClick={onExplain}
            className="px-3 py-1.5 border border-border hover:bg-zinc-100 text-zinc-700 hover:text-zinc-900 rounded-lg text-xs font-semibold transition-colors flex items-center gap-1.5 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
          >
            <Lightbulb className="w-3 h-3" /> Explain Issue
          </button>
        </div>
      </div>
    </div>
  );
};
