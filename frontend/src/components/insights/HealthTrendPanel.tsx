import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "../../lib/api";
import { Loader2, Gauge, ArrowUpRight, ArrowDownRight, Minus } from "lucide-react";
import { formatDateTime, formatDate } from "../../lib/datetime";

interface TrendPoint {
  analysis_id: string;
  timestamp: string | null;
  branch: string | null;
  commit_sha: string | null;
  health_score: number;
  security_score: number | null;
  code_quality_score: number | null;
  code_smell_count: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  total_issue_count: number;
}

interface HealthTrendData {
  snapshot_count: number;
  available_snapshots: number;
  range: string;
  sufficient_data: boolean;
  message: string | null;
  trend_status: "improved" | "declined" | "mixed" | "no_change" | null;
  deltas: Record<string, { from: number; to: number; direction: number }> | null;
  points: TrendPoint[];
}

const RANGES = [
  { label: "Last 7", value: "7" },
  { label: "Last 30", value: "30" },
  { label: "All", value: "all" },
] as const;

function Delta({ from, to, invert = false }: { from: number; to: number; invert?: boolean }) {
  if (from == null || to == null || from === to)
    return <span className="inline-flex items-center gap-0.5 text-[10px] text-zinc-500"><Minus className="w-3 h-3" /> 0</span>;
  const diff = to - from;
  const improved = invert ? diff < 0 : diff > 0;
  const Icon = improved ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={`inline-flex items-center gap-0.5 text-[10px] font-bold ${improved ? "text-green-500" : "text-red-500"}`}>
      <Icon className="w-3 h-3" /> {diff > 0 ? "+" : ""}{diff}
    </span>
  );
}

const TREND_BADGE: Record<string, { label: string; cls: string }> = {
  improved: { label: "Improved", cls: "bg-green-500/15 text-green-600 border border-green-500/30" },
  declined: { label: "Declined", cls: "bg-red-500/15 text-red-500 border border-red-500/30" },
  mixed: { label: "Mixed", cls: "bg-yellow-500/15 text-yellow-600 border border-yellow-500/30" },
  no_change: { label: "No change", cls: "bg-zinc-500/15 text-zinc-500 border border-zinc-500/30" },
};

export const HealthTrendPanel: React.FC<{ repoId: string }> = ({ repoId }) => {
  const [range, setRange] = useState<string>("all");

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["healthTrend", repoId, range],
    queryFn: async () => {
      const res = await axios.get(`/repositories/${repoId}/health-trend`, {
        params: { range },
      });
      return res.data as HealthTrendData;
    },
    enabled: !!repoId,
    staleTime: 120_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const points = useMemo(() => data?.points || [], [data]);

  if (isLoading) {
    return (
      <div className="glass-card p-10 flex flex-col items-center gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
        <p className="text-xs text-zinc-600">Loading health history…</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="glass-card p-8 text-center">
        <Gauge className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-800">Could not load health trend</p>
        <p className="text-xs text-zinc-600 mt-1">
          {(error as any)?.response?.data?.detail || "Please try again."}
        </p>
        <button
          onClick={() => refetch()}
          className="mt-3 text-xs font-bold text-accent-blue hover:underline"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  // ── Empty state: no scans recorded ─────────────────────────────
  if (data.snapshot_count === 0) {
    return (
      <div className="glass-card p-8 text-center">
        <Gauge className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-800">No health history yet</p>
        <p className="text-xs text-zinc-600 mt-1">
          A health snapshot is recorded every time a repository scan completes. Run a scan to start tracking.
        </p>
      </div>
    );
  }

  const first = points[0];
  const last = points[points.length - 1];
  const badge = data.trend_status ? TREND_BADGE[data.trend_status] : null;

  // ── Single snapshot: trend not possible ────────────────────────
  if (!data.sufficient_data) {
    return (
      <div className="glass-card p-8 text-center">
        <Gauge className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-800">{data.message}</p>
        <p className="text-xs text-zinc-600 mt-1">
          Rescan this repository to build a health trend over time.
        </p>
        <div className="glass p-4 rounded-xl mt-4 inline-block text-left">
          <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Latest snapshot</p>
          <div className="flex items-baseline gap-3 mt-1">
            <span className="text-2xl font-black text-zinc-900">{last.health_score}</span>
            <span className="text-[10px] text-zinc-500">/100 health</span>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 mt-2 text-[10px] text-zinc-600">
            <span>Security: {last.security_score ?? "—"}</span>
            <span>Quality: {last.code_quality_score ?? "—"}</span>
            <span>Smells: {last.code_smell_count}</span>
            <span>Issues: {last.total_issue_count}</span>
          </div>
          <p className="text-[9px] text-zinc-400 mt-1.5">
            {last.timestamp ? formatDateTime(last.timestamp) : ""}
            {last.branch ? ` · ${last.branch}` : ""}
          </p>
        </div>
      </div>
    );
  }

  // ── Sparkline geometry ─────────────────────────────────────────
  const W = 100;
  const H = 30;
  const linePoints = points
    .map((p, i) => `${points.length > 1 ? (i * W) / (points.length - 1) : 0},${H - (p.health_score / 100) * H}`)
    .join(" ");

  const metricCards = [
    { label: "Security", from: data.deltas?.security_score?.from, to: data.deltas?.security_score?.to, invert: false, suffix: "/100" },
    { label: "Code Quality", from: data.deltas?.code_quality_score?.from, to: data.deltas?.code_quality_score?.to, invert: false, suffix: "/100" },
    { label: "Issues", from: data.deltas?.total_issue_count?.from, to: data.deltas?.total_issue_count?.to, invert: true, suffix: "" },
  ];

  return (
    <div className="glass-card p-6 space-y-5">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <div>
          <h3 className="font-bold text-zinc-900 text-sm flex items-center gap-2">
            <Gauge className="w-4 h-4 text-accent-blue" /> Repository Health Trend
          </h3>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-[10px] text-zinc-500">
              {data.snapshot_count} snapshot{data.snapshot_count !== 1 ? "s" : ""}
              {first.timestamp ? ` · since ${formatDate(first.timestamp)}` : ""}
            </p>
            {badge && (
              <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full ${badge.cls}`}>
                {badge.label}
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-1 glass rounded-xl p-1">
          {RANGES.map((r) => (
            <button
              key={r.value}
              onClick={() => setRange(r.value)}
              className={`text-[10px] font-bold px-3 py-1.5 rounded-lg transition-colors ${
                range === r.value ? "bg-accent-blue text-white" : "text-zinc-600 hover:text-zinc-900"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Main chart */}
      <div className="glass p-4 rounded-xl">
        <div className="flex justify-between items-baseline mb-2">
          <span className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Overall Health Score</span>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-black text-zinc-900">{last.health_score}</span>
            <Delta from={data.deltas?.health_score?.from ?? first.health_score} to={data.deltas?.health_score?.to ?? last.health_score} />
          </div>
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-24">
          <defs>
            <linearGradient id="healthGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgb(59,130,246)" stopOpacity="0.3" />
              <stop offset="100%" stopColor="rgb(59,130,246)" stopOpacity="0" />
            </linearGradient>
          </defs>
          <polygon points={`0,${H} ${linePoints} ${W},${H}`} fill="url(#healthGrad)" />
          <polyline
            points={linePoints}
            fill="none"
            stroke="rgb(59,130,246)"
            strokeWidth="0.75"
            vectorEffect="non-scaling-stroke"
            strokeLinejoin="round"
          />
          {points.length > 1 &&
            points.map((p, i) => (
              <circle
                key={p.analysis_id}
                cx={(i * W) / (points.length - 1)}
                cy={H - (p.health_score / 100) * H}
                r="0.6"
                fill="rgb(59,130,246)"
              />
            ))}
        </svg>
        <div className="flex justify-between text-[9px] text-zinc-400 mt-1">
          <span>{first.timestamp ? formatDate(first.timestamp) : ""}</span>
          <span>{last.timestamp ? formatDate(last.timestamp) : ""}</span>
        </div>
      </div>

      {/* Metric deltas */}
      <div className="grid grid-cols-3 gap-2">
        {metricCards.map((m) => (
          <div key={m.label} className="glass p-3 rounded-xl">
            <span className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider">{m.label}</span>
            <div className="flex items-baseline gap-1.5 mt-1">
              <span className="text-lg font-black text-zinc-900">{m.to ?? "—"}{m.to != null ? m.suffix : ""}</span>
              {m.from != null && m.to != null && <Delta from={m.from} to={m.to} invert={m.invert} />}
            </div>
          </div>
        ))}
      </div>

      {/* Severity progression (last vs first) */}
      <div className="glass p-4 rounded-xl">
        <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider mb-2">
          Severity counts — first scan vs latest
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-center">
          {[
            { label: "Critical", a: first.critical_count, b: last.critical_count, cls: "text-red-500" },
            { label: "High", a: first.high_count, b: last.high_count, cls: "text-orange-500" },
            { label: "Medium", a: first.medium_count, b: last.medium_count, cls: "text-yellow-600" },
            { label: "Low", a: first.low_count, b: last.low_count, cls: "text-blue-500" },
            { label: "Smells", a: first.code_smell_count, b: last.code_smell_count, cls: "text-zinc-700" },
          ].map((s) => (
            <div key={s.label}>
              <p className={`text-base font-black ${s.cls}`}>{s.b}</p>
              <p className="text-[9px] uppercase font-bold text-zinc-500">{s.label}</p>
              <p className="text-[9px] text-zinc-400">was {s.a}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Per-scan table */}
      <div className="overflow-x-auto max-h-64 overflow-y-auto">
        <table className="w-full text-left">
          <thead className="sticky top-0 bg-white/90 backdrop-blur">
            <tr className="border-b border-border/40">
              {["Date", "Branch", "Health", "Security", "Quality", "Smells", "Crit", "High", "Med", "Low", "Total"].map((h) => (
                <th key={h} className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider py-2 px-2 whitespace-nowrap bg-white/80">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...points].reverse().map((p) => (
              <tr key={p.analysis_id} className="border-b border-border/20 text-xs">
                <td className="py-2 px-2 text-zinc-600 whitespace-nowrap">
                  {p.timestamp ? formatDate(p.timestamp) : "—"}
                </td>
                <td className="py-2 px-2 font-mono text-[10px] text-zinc-500 max-w-24 truncate" title={p.branch || undefined}>
                  {p.branch || "—"}
                </td>
                <td className="py-2 px-2 font-bold text-zinc-900">{p.health_score}</td>
                <td className="py-2 px-2 text-zinc-700">{p.security_score ?? "—"}</td>
                <td className="py-2 px-2 text-zinc-700">{p.code_quality_score ?? "—"}</td>
                <td className="py-2 px-2 text-zinc-700">{p.code_smell_count}</td>
                <td className={`py-2 px-2 font-bold ${p.critical_count > 0 ? "text-red-500" : "text-zinc-400"}`}>{p.critical_count}</td>
                <td className={`py-2 px-2 font-bold ${p.high_count > 0 ? "text-orange-500" : "text-zinc-400"}`}>{p.high_count}</td>
                <td className="py-2 px-2 text-zinc-500">{p.medium_count}</td>
                <td className="py-2 px-2 text-zinc-500">{p.low_count}</td>
                <td className="py-2 px-2 font-semibold text-zinc-700">{p.total_issue_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {isFetching && <p className="text-[10px] text-zinc-400 text-center">Refreshing…</p>}
    </div>
  );
};
