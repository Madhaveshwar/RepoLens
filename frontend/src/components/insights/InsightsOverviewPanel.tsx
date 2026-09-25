import React from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "../../lib/api";
import {
  Loader2, FileSearch, ShieldAlert, Wrench, Boxes, Gauge,
  ArrowRight, Sparkles, Info, ListChecks,
} from "lucide-react";
import { formatDate } from "../../lib/datetime";

/**
 * INSIGHTS (simple level) — tells the user what is happening in plain
 * language. Technical details live in the Deep Insights tab.
 * All numbers come from the real /overview endpoint (persisted scan data);
 * nothing is estimated or hard-coded.
 */

interface OverviewData {
  repository: { id: string; name: string; default_branch: string | null };
  scan: null | {
    analysis_id: string;
    timestamp: string | null;
    branch: string | null;
    commit_sha: string | null;
    files_analyzed: number;
    health_score: number | null;
    risk_score: number;
  };
  counts?: {
    security_issues: number;
    critical_security: number;
    high_security: number;
    code_smells: number;
    dependencies: number;
    vulnerable_dependencies: number;
    duplicate_blocks: number;
    technical_debt: number;
    complexity_issues: number;
    high_complexity: number;
  };
  ai_summary?: string | null;
  ai_summary_source?: string | null;
  message: string | null;
}

function healthLabel(score: number | null): { text: string; cls: string } {
  if (score == null) return { text: "Not available", cls: "text-zinc-500 dark:text-zinc-400" };
  if (score >= 80) return { text: "Good", cls: "text-accent-green" };
  if (score >= 60) return { text: "Fair", cls: "text-yellow-600 dark:text-yellow-400" };
  return { text: "Needs work", cls: "text-accent-red" };
}

export const InsightsOverviewPanel: React.FC<{
  repoId: string;
  onOpenDeep: (section?: string) => void;
}> = ({ repoId, onOpenDeep }) => {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["repoOverview", repoId],
    queryFn: async () => {
      const res = await axios.get(`/repositories/${repoId}/overview`);
      return res.data as OverviewData;
    },
    enabled: !!repoId,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="glass-card p-10 flex flex-col items-center gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
        <p className="text-xs text-zinc-600 dark:text-zinc-400">Loading insights…</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="glass-card p-8 text-center">
        <FileSearch className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-800 dark:text-zinc-100">Unable to load insights.</p>
        <p className="text-xs text-zinc-600 mt-1 dark:text-zinc-400">
          {(error as any)?.response?.data?.detail || "Please try again."}
        </p>
        <button onClick={() => refetch()} className="mt-3 text-xs font-bold text-accent-blue hover:underline">
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  if (!data.scan) {
    return (
      <div className="glass-card p-8 text-center">
        <FileSearch className="w-10 h-10 text-zinc-400 mx-auto mb-3" />
        <p className="text-sm font-bold text-zinc-800 dark:text-zinc-100">No repository scan available yet.</p>
        <p className="text-xs text-zinc-600 mt-1 dark:text-zinc-400">
          Run a scan from the Overview tab to generate insights.
        </p>
      </div>
    );
  }

  const { scan, counts } = data;
  const health = healthLabel(scan.health_score);
  const secIssues = (counts?.critical_security || 0) + (counts?.high_security || 0);
  const depIssues = counts?.vulnerable_dependencies ?? 0;
  const qualityIssues = counts?.code_smells ?? 0;

  // Main areas to improve — derived from real counts, largest first.
  const areas: { label: string; value: number; section: string }[] = [
    { label: "Security configuration", value: secIssues, section: "pr" },
    { label: "Dependency updates", value: depIssues, section: "deps" },
    { label: "High-complexity functions", value: counts?.high_complexity ?? 0, section: "complexity" },
    { label: "Code quality", value: qualityIssues, section: "duplicates" },
    { label: "Duplicated code", value: counts?.duplicate_blocks ?? 0, section: "duplicates" },
    { label: "Technical debt", value: counts?.technical_debt ?? 0, section: "debt" },
  ].filter((a) => a.value > 0).sort((a, b) => b.value - a.value).slice(0, 3);

  return (
    <div className="space-y-5">
      {/* Health at a glance */}
      <div className="glass-card p-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <Gauge className={`w-10 h-10 ${health.cls}`} />
            <div>
              <p className="metric-label text-[10px]">Overall Health</p>
              <p className="text-3xl font-black text-zinc-900 dark:text-zinc-100">
                {scan.health_score != null ? `${scan.health_score}/100` : "N/A"}
              </p>
              <p className={`text-xs font-bold ${health.cls}`}>{health.text}</p>
            </div>
          </div>
          <div className="text-[11px] text-zinc-500 dark:text-zinc-400 sm:text-right">
            <p>{scan.files_analyzed} files analyzed</p>
            <p>{scan.timestamp ? formatDate(scan.timestamp) : "Date not available"}
              {scan.branch ? ` · ${scan.branch}` : ""}
              {scan.commit_sha ? ` · ${scan.commit_sha.slice(0, 7)}` : ""}
            </p>
          </div>
        </div>
      </div>

      {/* Four simple questions */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <button
          onClick={() => onOpenDeep("pr")}
          className="glass p-4 rounded-2xl text-left hover:-translate-y-0.5 transition-all"
        >
          <ShieldAlert className="w-4 h-4 text-accent-red mb-2" />
          <p className="metric-label text-[9px]">Security</p>
          <p className="text-xl font-black text-zinc-900 dark:text-zinc-100">{secIssues}</p>
          <p className="text-[10px] text-zinc-500 dark:text-zinc-400">
            {secIssues === 1 ? "issue needs review" : "issues need review"}
          </p>
        </button>
        <button
          onClick={() => onOpenDeep("deps")}
          className="glass p-4 rounded-2xl text-left hover:-translate-y-0.5 transition-all"
        >
          <Boxes className="w-4 h-4 text-accent-blue mb-2" />
          <p className="metric-label text-[9px]">Dependencies</p>
          <p className="text-xl font-black text-zinc-900 dark:text-zinc-100">{depIssues}</p>
          <p className="text-[10px] text-zinc-500 dark:text-zinc-400">with known problems</p>
        </button>
        <button
          onClick={() => onOpenDeep("duplicates")}
          className="glass p-4 rounded-2xl text-left hover:-translate-y-0.5 transition-all"
        >
          <Wrench className="w-4 h-4 text-accent-orange mb-2" />
          <p className="metric-label text-[9px]">Code Quality</p>
          <p className="text-xl font-black text-zinc-900 dark:text-zinc-100">{qualityIssues}</p>
          <p className="text-[10px] text-zinc-500 dark:text-zinc-400">smells detected</p>
        </button>
        <button
          onClick={() => onOpenDeep("health")}
          className="glass p-4 rounded-2xl text-left hover:-translate-y-0.5 transition-all"
        >
          <Gauge className="w-4 h-4 text-accent-green mb-2" />
          <p className="metric-label text-[9px]">Maintainability</p>
          <p className={`text-xl font-black ${health.cls}`}>{health.text}</p>
          <p className="text-[10px] text-zinc-500 dark:text-zinc-400">overall rating</p>
        </button>
      </div>

      {/* Main areas to improve */}
      <div className="glass-card p-6">
        <h3 className="font-bold text-zinc-900 text-sm flex items-center gap-2 dark:text-white">
          <ListChecks className="w-4 h-4 text-accent-blue" /> Main Areas to Improve
        </h3>
        {areas.length > 0 ? (
          <ol className="mt-3 space-y-2">
            {areas.map((a, i) => (
              <li key={a.label} className="flex items-center justify-between text-xs">
                <span className="text-zinc-700 font-medium dark:text-zinc-300">
                  {i + 1}. {a.label}
                </span>
                <span className="flex items-center gap-2">
                  <span className="font-bold text-zinc-900 dark:text-zinc-100">{a.value}</span>
                  <button
                    onClick={() => onOpenDeep(a.section)}
                    className="text-accent-blue hover:underline font-semibold inline-flex items-center gap-0.5"
                  >
                    View <ArrowRight className="w-3 h-3" />
                  </button>
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-xs text-zinc-600 mt-3 dark:text-zinc-400">
            The latest scan found no significant problem areas. Run a new scan after making changes to keep this up to date.
          </p>
        )}
      </div>

      {/* Simple AI summary */}
      <div className="glass-card p-6">
        <h3 className="font-bold text-zinc-900 text-sm flex items-center gap-2 dark:text-white">
          <Sparkles className="w-3.5 h-3.5 text-accent-blue" /> Summary
        </h3>
        {data.ai_summary ? (
          <p className="text-xs text-zinc-700 mt-3 leading-relaxed whitespace-pre-line dark:text-zinc-300">
            {data.ai_summary.replace(/[*_#`]/g, "").slice(0, 600)}
            {(data.ai_summary.length || 0) > 600 ? "…" : ""}
          </p>
        ) : (
          <p className="text-xs text-zinc-600 mt-3 italic dark:text-zinc-400">Summary not available for this scan.</p>
        )}
        <p className="text-[9px] text-zinc-500 mt-2 flex items-center gap-1 dark:text-zinc-400">
          <Info className="w-3 h-3" />
          {data.ai_summary_source === "deterministic"
            ? "Generated from your scan data — no AI interpretation."
            : "Based on your latest scan."}
        </p>
      </div>

      {/* Bridge to deep insights */}
      <button
        onClick={() => onOpenDeep()}
        className="w-full glass-card p-4 flex items-center justify-between group hover:border-accent-blue/40 transition-all"
      >
        <span className="text-xs font-bold text-zinc-800 dark:text-zinc-200">
          Looking for technical details? Open Deep Insights
        </span>
        <ArrowRight className="w-4 h-4 text-accent-blue group-hover:translate-x-1 transition-transform" />
      </button>
    </div>
  );
};
