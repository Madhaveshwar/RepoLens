import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "../../lib/api";
import { Loader2, CreditCard, Layers, Wrench, Info } from "lucide-react";

interface DebtItem {
  id: string;
  category: string;
  severity: string;
  title: string;
  evidence: string;
  file: string | null;
  line_start: number | null;
  line_end: number | null;
  estimated_effort_hours: number | null;
  remediation: string;
}

interface DebtData {
  analysis_id: string | null;
  items: DebtItem[];
  categories: string[];
  summary: {
    item_count: number;
    categories: Record<string, number>;
    severity_counts: Record<string, number>;
    total_estimated_effort_hours: number;
    effort_estimate_note: string;
  } | null;
  top_impact_areas: Array<{ file: string; estimated_effort_hours: number }>;
  message: string | null;
}

const SEVERITY_ORDER: Record<string, number> = { Critical: 0, High: 1, Medium: 2, Low: 3 };
const SEVERITY_STYLES: Record<string, string> = {
  Critical: "bg-red-500/15 text-red-500 border border-red-500/30",
  High: "bg-orange-500/15 text-orange-500 border border-orange-500/30",
  Medium: "bg-yellow-500/15 text-yellow-600 border border-yellow-500/30",
  Low: "bg-blue-500/15 text-blue-500 border border-blue-500/30",
};

export const TechnicalDebtPanel: React.FC<{ repoId: string }> = ({ repoId }) => {
  const [category, setCategory] = useState("all");
  const [severity, setSeverity] = useState("all");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["technicalDebt", repoId],
    queryFn: async () => {
      const res = await axios.get(`/repositories/${repoId}/technical-debt`);
      return res.data as DebtData;
    },
    enabled: !!repoId,
    staleTime: 120_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const items = data?.items || [];

  const filtered = useMemo(
    () =>
      [...items]
        .filter((i) => category === "all" || i.category === category)
        .filter((i) => severity === "all" || i.severity === severity)
        .sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9)),
    [items, category, severity]
  );

  const breakdown = data?.summary?.categories || {};
  const maxCount = Math.max(1, ...Object.values(breakdown));

  if (isLoading) {
    return (
      <div className="glass-card p-10 flex flex-col items-center gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
        <p className="text-xs text-zinc-600">Assessing technical debt…</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="glass-card p-8 text-center">
        <CreditCard className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-800">Could not load technical debt report</p>
        <p className="text-xs text-zinc-600 mt-1">
          {(error as any)?.response?.data?.detail || "Please try again."}
        </p>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="glass-card p-6 space-y-5">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <div>
          <h3 className="font-bold text-zinc-900 text-sm flex items-center gap-2">
            <CreditCard className="w-4 h-4 text-accent-blue" /> Technical Debt Report
          </h3>
          <p className="text-[10px] text-zinc-500 mt-0.5">
            Evidence-based: every item links to a detected issue from the deterministic analyzers
          </p>
        </div>
        {data.summary && data.summary.item_count > 0 && (
          <div className="flex gap-2">
            <div className="glass rounded-xl px-3 py-2 text-center">
              <p className="text-lg font-black text-zinc-900 leading-none">{data.summary.item_count}</p>
              <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">Debt items</p>
            </div>
            <div className="glass rounded-xl px-3 py-2 text-center">
              <p className="text-lg font-black text-zinc-900 leading-none">~{Math.round(data.summary.total_estimated_effort_hours)}h</p>
              <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">Est. effort</p>
            </div>
          </div>
        )}
      </div>

      {items.length === 0 ? (
        <div className="text-center py-8">
          <CreditCard className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
          <p className="text-sm font-bold text-zinc-800">
            {data.analysis_id ? "No technical debt detected" : "No scan data"}
          </p>
          <p className="text-xs text-zinc-600 mt-1">{data.message}</p>
        </div>
      ) : (
        <>
          {/* Category breakdown bars */}
          <div>
            <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider mb-2 flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5" /> Category breakdown
            </p>
            <div className="space-y-1.5">
              {Object.entries(breakdown)
                .sort((a, b) => b[1] - a[1])
                .map(([cat, count]) => (
                  <button
                    key={cat}
                    onClick={() => setCategory(category === cat ? "all" : cat)}
                    className={`w-full flex items-center gap-2 ${category === cat ? "opacity-100" : "opacity-90 hover:opacity-100"}`}
                  >
                    <span className={`text-[10px] font-bold text-zinc-700 w-36 truncate text-left ${category === cat ? "underline" : ""}`}>
                      {cat}
                    </span>
                    <div className="flex-1 h-2 bg-zinc-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-accent-blue rounded-full"
                        style={{ width: `${(count / maxCount) * 100}%` }}
                      />
                    </div>
                    <span className="text-[10px] font-mono text-zinc-500 w-6 text-right">{count}</span>
                  </button>
                ))}
            </div>
          </div>

          {/* Top impact areas */}
          {data.top_impact_areas.length > 0 && (
            <div>
              <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider mb-1.5">Highest-impact areas</p>
              <div className="flex flex-wrap gap-1.5">
                {data.top_impact_areas.map((t) => (
                  <span key={t.file} className="text-[10px] font-mono glass px-2 py-1 rounded-lg text-zinc-700">
                    {t.file} <span className="text-zinc-400">~{Math.round(t.estimated_effort_hours)}h</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Filters */}
          <div className="flex flex-wrap gap-2">
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="text-xs glass rounded-xl px-3 py-2 text-zinc-700 bg-transparent focus:outline-none"
            >
              <option value="all">All categories</option>
              {data.categories.map((cat) => (
                <option key={cat} value={cat}>{cat}</option>
              ))}
            </select>
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              className="text-xs glass rounded-xl px-3 py-2 text-zinc-700 bg-transparent focus:outline-none"
            >
              <option value="all">All severities</option>
              {["Critical", "High", "Medium", "Low"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          {/* Items */}
          <div className="space-y-2">
            {filtered.map((i) => (
              <div key={i.id} className="glass p-4 rounded-xl border-l-2 border-accent-orange">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full ${SEVERITY_STYLES[i.severity] || "glass text-zinc-500"}`}>
                    {i.severity}
                  </span>
                  <span className="text-[10px] font-bold text-zinc-700 uppercase">{i.category}</span>
                  <span className="text-xs font-semibold text-zinc-900">{i.title}</span>
                  {i.file && (
                    <span className="text-[10px] font-mono text-zinc-500 truncate ml-auto">
                      {i.file}
                      {i.line_start ? `:L${i.line_start}${i.line_end && i.line_end !== i.line_start ? `–${i.line_end}` : ""}` : ""}
                    </span>
                  )}
                </div>
                <p className="text-[10px] text-zinc-600 mt-2">
                  <span className="font-bold">Evidence:</span> {i.evidence}
                </p>
                <p className="text-[10px] text-zinc-600 mt-0.5">
                  <span className="font-bold">Remediation:</span> {i.remediation}
                </p>
                {i.estimated_effort_hours != null && (
                  <p className="text-[10px] text-zinc-500 mt-1 flex items-center gap-1">
                    <Wrench className="w-3 h-3" /> ~{i.estimated_effort_hours}h (heuristic estimate)
                  </p>
                )}
              </div>
            ))}
          </div>

          {data.summary && (
            <p className="text-[9px] text-zinc-400 flex items-start gap-1.5 border-t border-border/40 pt-3">
              <Info className="w-3 h-3 flex-shrink-0 mt-0.5" />
              {data.summary.effort_estimate_note}
            </p>
          )}
        </>
      )}
    </div>
  );
};
