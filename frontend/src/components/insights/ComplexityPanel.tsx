import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "../../lib/api";
import { Loader2, GaugeCircle, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";

interface ComplexityFinding {
  id: string;
  file: string;
  name: string;
  kind: string;
  line_start: number;
  line_end: number | null;
  cyclomatic_complexity: number;
  nesting_depth: number | null;
  length_lines: number | null;
  language: string | null;
  severity: string;
  explanation: string | null;
  suggestion: string | null;
}

const SEVERITY_STYLES: Record<string, string> = {
  High: "bg-red-500/15 text-red-500 border border-red-500/30",
  Medium: "bg-yellow-500/15 text-yellow-600 border border-yellow-500/30",
  Low: "bg-blue-500/15 text-blue-500 border border-blue-500/30",
};

type SortKey = "complexity" | "length" | "file" | "name";

export const ComplexityPanel: React.FC<{ repoId: string }> = ({ repoId }) => {
  const [severity, setSeverity] = useState("all");
  const [language, setLanguage] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("complexity");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["complexity", repoId],
    queryFn: async () => {
      const res = await axios.get(`/repositories/${repoId}/complexity`);
      return res.data as {
        analysis_id: string | null;
        findings: ComplexityFinding[];
        languages: string[];
        summary: {
          total_reported: number;
          high: number;
          medium: number;
          average_complexity: number;
        } | null;
        message: string | null;
      };
    },
    enabled: !!repoId,
    staleTime: 120_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const findings = data?.findings || [];

  const filtered = useMemo(() => {
    const list = findings.filter((f) => {
      if (severity !== "all" && f.severity !== severity) return false;
      if (language !== "all" && (f.language || "").toLowerCase() !== language.toLowerCase()) return false;
      return true;
    });
    list.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "complexity") cmp = a.cyclomatic_complexity - b.cyclomatic_complexity;
      else if (sortKey === "length") cmp = (a.length_lines || 0) - (b.length_lines || 0);
      else if (sortKey === "file") cmp = a.file.localeCompare(b.file);
      else cmp = a.name.localeCompare(b.name);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return list;
  }, [findings, severity, language, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "file" || key === "name" ? "asc" : "desc");
    }
  };

  if (isLoading) {
    return (
      <div className="glass-card p-10 flex flex-col items-center gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
        <p className="text-xs text-zinc-600">Analyzing code complexity…</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="glass-card p-8 text-center">
        <GaugeCircle className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-800">Could not load complexity analysis</p>
        <p className="text-xs text-zinc-600 mt-1">
          {(error as any)?.response?.data?.detail || "Please try again."}
        </p>
      </div>
    );
  }

  if (!data) return null;

  const SortHeader: React.FC<{ label: string; k: SortKey }> = ({ label, k }) => (
    <th className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider py-2 px-2 whitespace-nowrap">
      <button onClick={() => toggleSort(k)} className="inline-flex items-center gap-1 hover:text-zinc-800">
        {label}
        {sortKey === k ? (
          sortDir === "asc" ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />
        ) : (
          <ArrowUpDown className="w-3 h-3 opacity-30" />
        )}
      </button>
    </th>
  );

  return (
    <div className="glass-card p-6 space-y-5">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <div>
          <h3 className="font-bold text-zinc-900 text-sm flex items-center gap-2">
            <GaugeCircle className="w-4 h-4 text-accent-blue" /> Code Complexity Analysis
          </h3>
          <p className="text-[10px] text-zinc-500 mt-0.5">
            Deterministic cyclomatic complexity from real source files (Python, JavaScript/TypeScript)
          </p>
        </div>
        {data.summary && data.summary.total_reported > 0 && (
          <div className="flex gap-2">
            <div className="glass rounded-xl px-3 py-2 text-center">
              <p className="text-lg font-black text-zinc-900 leading-none">{data.summary.total_reported}</p>
              <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">Functions</p>
            </div>
            <div className="glass rounded-xl px-3 py-2 text-center">
              <p className="text-lg font-black text-red-500 leading-none">{data.summary.high}</p>
              <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">High</p>
            </div>
            <div className="glass rounded-xl px-3 py-2 text-center">
              <p className="text-lg font-black text-zinc-900 leading-none">{data.summary.average_complexity}</p>
              <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">Avg complexity</p>
            </div>
          </div>
        )}
      </div>

      {findings.length === 0 ? (
        <div className="text-center py-8">
          <GaugeCircle className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
          <p className="text-sm font-bold text-zinc-800">
            {data.analysis_id ? "No complexity findings" : "No scan data"}
          </p>
          <p className="text-xs text-zinc-600 mt-1">{data.message}</p>
        </div>
      ) : (
        <>
          {/* Filters */}
          <div className="flex flex-wrap gap-2 items-center">
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              className="text-xs glass rounded-xl px-3 py-2 text-zinc-700 bg-transparent focus:outline-none"
            >
              <option value="all">All severities</option>
              {["High", "Medium", "Low"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="text-xs glass rounded-xl px-3 py-2 text-zinc-700 bg-transparent focus:outline-none"
            >
              <option value="all">All languages</option>
              {data.languages.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
            <span className="text-[10px] text-zinc-500 ml-auto">
              {filtered.length} of {findings.length} functions
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border/40">
                  <SortHeader label="File" k="file" />
                  <SortHeader label="Function" k="name" />
                  <SortHeader label="Complexity" k="complexity" />
                  <th className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider py-2 px-2">Nesting</th>
                  <SortHeader label="Lines" k="length" />
                  <th className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider py-2 px-2">Severity</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((f) => (
                  <tr key={f.id} className="border-b border-border/20 text-xs align-top hover:bg-zinc-50/50">
                    <td className="py-2.5 px-2 font-mono text-[11px] text-zinc-700 max-w-48 truncate" title={f.file}>
                      {f.file}
                      <span className="text-zinc-400"> :L{f.line_start}{f.line_end ? `–${f.line_end}` : ""}</span>
                    </td>
                    <td className="py-2.5 px-2">
                      <span className="font-bold text-zinc-900">{f.name}</span>
                      <span className="text-[9px] text-zinc-400 ml-1">({f.kind})</span>
                    </td>
                    <td className="py-2.5 px-2 font-black text-zinc-900">{f.cyclomatic_complexity}</td>
                    <td className="py-2.5 px-2 text-zinc-600">{f.nesting_depth ?? "—"}</td>
                    <td className="py-2.5 px-2 text-zinc-600">{f.length_lines ?? "—"}</td>
                    <td className="py-2.5 px-2">
                      <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full ${SEVERITY_STYLES[f.severity] || "glass text-zinc-500"}`}>
                        {f.severity}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Details for high severity */}
          {filtered.some((f) => f.severity === "High" && (f.explanation || f.suggestion)) && (
            <div className="space-y-2">
              <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">
                High-complexity details
              </p>
              {filtered
                .filter((f) => f.severity === "High")
                .map((f) => (
                  <div key={`d-${f.id}`} className="glass p-3 rounded-xl">
                    <p className="text-xs font-bold text-zinc-900 font-mono">
                      {f.file} · {f.name} (complexity {f.cyclomatic_complexity})
                    </p>
                    {f.explanation && <p className="text-[10px] text-zinc-600 mt-1">{f.explanation}</p>}
                    {f.suggestion && (
                      <p className="text-[10px] text-zinc-600 mt-0.5">
                        <span className="font-bold">Improvement:</span> {f.suggestion}
                      </p>
                    )}
                  </div>
                ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};
