import React from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "../../lib/api";
import {
  Loader2, FileSearch, RefreshCw, GitCommitHorizontal, GitBranch,
  Clock, FileCode2, ShieldAlert, AlertTriangle, Copy, Boxes,
  Layers, Sparkles, Info,
} from "lucide-react";
import { Markdown } from "../Markdown";
import { formatDateTime } from "../../lib/datetime";

interface OverviewData {
  repository: {
    id: string;
    name: string;
    description: string | null;
    default_branch: string | null;
  };
  scan: null | {
    analysis_id: string;
    status: string;
    timestamp: string | null;
    branch: string | null;
    commit_sha: string | null;
    files_analyzed: number;
    health_score: number | null;
    risk_score: number;
    model_name: string | null;
    scan_duration_seconds: number | null;
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

const METRICS = [
  { key: "security_issues", label: "Security Issues", icon: ShieldAlert, tone: "text-accent-red" },
  { key: "code_smells", label: "Code Smells", icon: AlertTriangle, tone: "text-accent-orange" },
  { key: "dependencies", label: "Dependencies", icon: Boxes, tone: "text-accent-blue" },
  { key: "high_complexity", label: "Complexity Issues", icon: Layers, tone: "text-purple-500" },
  { key: "technical_debt", label: "Technical Debt", icon: FileCode2, tone: "text-yellow-600" },
  { key: "duplicate_blocks", label: "Duplicate Code", icon: Copy, tone: "text-zinc-600" },
] as const;

function healthTone(score: number | null | undefined): string {
  if (score == null) return "text-zinc-500 dark:text-zinc-400";
  if (score >= 80) return "text-accent-green";
  if (score >= 60) return "text-yellow-600 dark:text-yellow-400";
  return "text-accent-red";
}

export const RepositoryOverviewPanel: React.FC<{ repoId: string }> = ({ repoId }) => {
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
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
        <p className="text-xs text-zinc-600 dark:text-zinc-400">Loading repository overview…</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="glass-card p-8 text-center">
        <FileSearch className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-800 dark:text-zinc-100">Unable to load the repository overview.</p>
        <p className="text-xs text-zinc-600 mt-1 dark:text-zinc-400">
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

  // ── No scan yet: honest empty state ─────────────────────────────
  if (!data.scan) {
    return (
      <div className="glass-card p-8 text-center">
        <FileSearch className="w-10 h-10 text-zinc-400 mx-auto mb-3" />
        <p className="text-sm font-bold text-zinc-800 dark:text-zinc-100">
          No repository scan available yet.
        </p>
        <p className="text-xs text-zinc-600 mt-1 dark:text-zinc-400">
          {data.message || "Run a repository scan to generate the overview."}
        </p>
      </div>
    );
  }

  const { scan, counts } = data;

  return (
    <div className="glass-card p-6 space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <div>
          <h3 className="font-bold text-zinc-900 text-sm flex items-center gap-2 dark:text-white">
            <FileSearch className="w-4 h-4 text-accent-blue" /> Repository Overview
          </h3>
          <p className="text-[10px] text-zinc-500 mt-0.5 dark:text-zinc-400">
            Executive summary of the latest completed scan — all figures come from real scan data.
          </p>
        </div>
        <button
          onClick={() => refetch()}
          title="Refresh overview"
          className="text-zinc-500 hover:text-zinc-900 transition-colors p-1.5 rounded-lg hover:bg-zinc-100 dark:text-zinc-400 dark:hover:text-white dark:hover:bg-zinc-800"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* Scan freshness / commit info — real values only */}
      <div className="glass p-4 rounded-xl grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div>
          <span className="metric-label text-[9px] block">Last Analyzed</span>
          <span className="flex items-center gap-1.5 text-zinc-700 font-semibold mt-1 dark:text-zinc-200">
            <Clock className="w-3.5 h-3.5 text-zinc-500" />
            {scan.timestamp ? formatDateTime(scan.timestamp) : "Not available"}
          </span>
        </div>
        <div>
          <span className="metric-label text-[9px] block">Branch</span>
          <span className="flex items-center gap-1.5 text-zinc-700 font-semibold mt-1 dark:text-zinc-200">
            <GitBranch className="w-3.5 h-3.5 text-zinc-500" />
            {scan.branch || "Not available"}
          </span>
        </div>
        <div>
          <span className="metric-label text-[9px] block">Commit</span>
          <span className="flex items-center gap-1.5 text-zinc-700 font-semibold mt-1 font-mono dark:text-zinc-200">
            <GitCommitHorizontal className="w-3.5 h-3.5 text-zinc-500" />
            {scan.commit_sha ? scan.commit_sha.slice(0, 7) : "Not available"}
          </span>
        </div>
        <div>
          <span className="metric-label text-[9px] block">Repository</span>
          <span className="flex items-center gap-1.5 text-zinc-700 font-semibold mt-1 truncate dark:text-zinc-200" title={data.repository.name}>
            <FileCode2 className="w-3.5 h-3.5 text-zinc-500" />
            {data.repository.name}
          </span>
        </div>
      </div>

      {/* Headline metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 stagger-children">
        <div className="glass p-4 rounded-2xl text-center">
          <p className="metric-label text-[10px]">Health Score</p>
          <h4 className={`text-2xl font-bold mt-1.5 ${healthTone(scan.health_score)}`}>
            {scan.health_score != null ? `${scan.health_score}/100` : "Not available"}
          </h4>
        </div>
        <div className="glass p-4 rounded-2xl text-center">
          <p className="metric-label text-[10px]">Files Analyzed</p>
          <h4 className="text-2xl font-bold mt-1.5 text-zinc-900 dark:text-zinc-100">
            {scan.files_analyzed}
          </h4>
        </div>
        <div className="glass p-4 rounded-2xl text-center">
          <p className="metric-label text-[10px]">Risk Score</p>
          <h4 className={`text-2xl font-bold mt-1.5 ${scan.risk_score > 60 ? "text-accent-red" : "text-accent-green"}`}>
            {scan.risk_score}/100
          </h4>
        </div>
        <div className="glass p-4 rounded-2xl text-center">
          <p className="metric-label text-[10px]">Scan Duration</p>
          <h4 className="text-2xl font-bold mt-1.5 text-zinc-900 dark:text-zinc-100">
            {scan.scan_duration_seconds ? `${scan.scan_duration_seconds}s` : "Not available"}
          </h4>
        </div>
      </div>

      {/* Insight counts */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {METRICS.map((m) => {
          const value = counts ? counts[m.key] : undefined;
          const Icon = m.icon;
          return (
            <div key={m.key} className="glass p-3.5 rounded-xl text-center">
              <Icon className={`w-4 h-4 mx-auto mb-1.5 ${m.tone}`} />
              <p className="metric-label text-[9px] leading-tight">{m.label}</p>
              <p className={`text-lg font-black mt-1 ${value === undefined ? "text-zinc-400" : "text-zinc-900 dark:text-zinc-100"}`}>
                {value === undefined ? "N/A" : value}
              </p>
            </div>
          );
        })}
      </div>

      {/* Grounded AI summary */}
      <div className="glass p-5 rounded-xl">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-bold text-zinc-900 flex items-center gap-2 dark:text-zinc-100">
            <Sparkles className="w-3.5 h-3.5 text-accent-blue" /> AI Summary
          </h4>
          <span className="text-[9px] font-bold uppercase tracking-wider text-zinc-500 flex items-center gap-1 dark:text-zinc-400">
            <Info className="w-3 h-3" />
            {data.ai_summary_source === "deterministic"
              ? "Generated from persisted scan data"
              : data.ai_summary_source === "scan_report"
                ? "From the scan's analysis report"
                : "Grounded in this scan"}
          </span>
        </div>
        {data.ai_summary ? (
          <Markdown content={data.ai_summary} className="text-xs" />
        ) : (
          <p className="text-xs text-zinc-600 italic dark:text-zinc-400">
            Summary not available for this scan.
          </p>
        )}
      </div>
    </div>
  );
};
