import React, { useEffect, useState } from "react";
import axios from "../lib/api";
import { useRepositoryStore } from "../store/repositoryStore";
import { useAuthStore } from "../store/authStore";
import {
  Plus, Search, Loader2, BookOpen, AlertTriangle, Shield, Wrench,
  Boxes, Gauge, ArrowRight, Clock, GitBranch, GitCommitHorizontal,
  TrendingUp, Siren, Lightbulb,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { useQuery } from "@tanstack/react-query";
import { useThemeStore } from "../store/themeStore";
import { formatDateTime } from "../lib/datetime";

/**
 * SIMPLIFIED DASHBOARD — answers only:
 *   1. How healthy is my repository?      (hero card)
 *   2. What problems were found?          (what needs attention)
 *   3. What should I fix first?           (top recommendations)
 *   4. Has the repository improved?       (security trend — real history only)
 *   5. When was it last analyzed?         (hero card freshness row)
 *
 * REMOVED per graph audit (no meaningful user purpose on the dashboard):
 *   - Token Consumption chart  (AI usage metric, not repository quality)
 *   - Model Usage chart        (AI configuration metric, not repository insight)
 *   - Health Score Trends      (redundant with Security Trend + per-repo health)
 * The remaining trend chart renders only when >= 2 real scans exist.
 */

interface LatestScanSummary {
  repository_id: string;
  repository: string;
  analysis_id: string;
  timestamp: string | null;
  branch: string | null;
  commit_sha: string | null;
  health_score: number | null;
  risk_score: number | null;
  files_analyzed: number;
  attention: {
    critical_security: number;
    high_security: number;
    medium_security: number;
    code_quality: number;
    dependencies: number;
  };
  recommendations: string[];
}

interface DashboardMetricsType {
  repositories_count: number;
  prs_count: number;
  vulnerabilities_count: number;
  avg_health_score: number;
  security_score: number;
  security_score_history: Array<{ repo: string; date: string; score: number }>;
  severity_distribution: Record<string, number>;
  vulnerability_trends: Array<{ date: string; count: number }>;
  health_history: Array<{ repo: string; date: string; score: number }>;
  recent_activity: Array<{ repo: string; status: string; timestamp: string; analysis_id: string }>;
  top_risky_repositories: Array<{ repo_id: string; name: string; risk_score: number }>;
  average_scan_duration: number;
  token_consumption: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  model_usage: Record<string, number>;
  latest_scan_summary?: LatestScanSummary | null;
}

interface DashboardProps {
  onSelectRepoId: (id: string) => void;
}

// Theme-aware chart chrome: readable in BOTH light and dark mode.
function useChartChrome() {
  const { theme } = useThemeStore();
  const vars =
    theme === "dark"
      ? {
          grid: "rgba(255,255,255,0.08)",
          axis: "#A1A1AA",
          tooltipBg: "#18181B",
          tooltipText: "#F4F4F5",
          tooltipBorder: "rgba(255,255,255,0.12)",
        }
      : {
          grid: "rgba(0,0,0,0.07)",
          axis: "#525863",
          tooltipBg: "#FFFFFF",
          tooltipText: "#18181B",
          tooltipBorder: "rgba(0,0,0,0.1)",
        };
  const tooltipStyle = {
    backgroundColor: vars.tooltipBg,
    color: vars.tooltipText,
    border: `1px solid ${vars.tooltipBorder}`,
    borderRadius: "16px",
  } as const;
  return { ...vars, tooltipStyle };
}

function healthTone(score: number | null): string {
  if (score == null) return "text-zinc-500 dark:text-zinc-400";
  if (score >= 80) return "text-accent-green";
  if (score >= 60) return "text-yellow-600 dark:text-yellow-400";
  return "text-accent-red";
}

export const Dashboard: React.FC<DashboardProps> = ({ onSelectRepoId }) => {
  const { repositories, connectRepository } = useRepositoryStore();
  const { user } = useAuthStore();
  const chartChrome = useChartChrome();

  const hasLlmKey = user ? (
    user.has_groq_api_key || user.has_openai_api_key ||
    user.has_claude_api_key || user.has_gemini_api_key || user.has_openrouter_api_key
  ) : false;

  const [searchQuery, setSearchQuery] = useState("");
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  const { data: dashboardMetrics, isLoading: loadingMetrics } = useQuery({
    queryKey: ["dashboardMetrics"],
    queryFn: async () => {
      const res = await axios.get("/users/me/dashboard");
      return res.data as DashboardMetricsType;
    },
    staleTime: 30_000,
    gcTime: 120_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const { data: reposData } = useQuery({
    queryKey: ["repositories"],
    queryFn: async () => {
      const res = await axios.get("/repositories");
      return res.data;
    },
    staleTime: 60_000,
    gcTime: 300_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const metrics = dashboardMetrics || null;
  const latest = metrics?.latest_scan_summary || null;

  useEffect(() => {
    if (reposData) {
      useRepositoryStore.setState({ repositories: reposData });
    }
  }, [reposData]);

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    setConnecting(true);
    setConnectError(null);
    try {
      const newRepo = await connectRepository(repoUrl);
      setShowConnectModal(false);
      setRepoUrl("");
      onSelectRepoId(newRepo.id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to connect repository";
      setConnectError(msg);
    } finally {
      setConnecting(false);
    }
  };

  const filteredRepos = repositories.filter(repo =>
    repo.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Security trend — real scan history only. A trend needs >= 2 scans.
  const securityHistory = metrics?.security_score_history || [];
  const hasTrendData = securityHistory.length >= 2;

  const attentionRows = latest ? [
    { label: "Critical Security Issues", value: latest.attention.critical_security, tone: "text-accent-red", icon: Siren },
    { label: "High Security Issues", value: latest.attention.high_security, tone: "text-accent-red", icon: Shield },
    { label: "Code Quality Issues", value: latest.attention.code_quality, tone: "text-accent-orange", icon: Wrench },
    { label: "Dependency Issues", value: latest.attention.dependencies, tone: "text-accent-blue", icon: Boxes },
  ] : [];

  const totalAttention = attentionRows.reduce((acc, r) => acc + r.value, 0);

  return (
    <div className="flex-1 p-8 overflow-y-auto max-h-screen">
      {/* Header */}
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold text-zinc-900 dark:text-white">Dashboard</h1>
          <p className="text-base text-zinc-700 font-medium mt-1 dark:text-zinc-300">
            Your repository health, problems and next steps — from real scan data.
          </p>
        </div>
        <button
          onClick={() => {
            if (!hasLlmKey) {
              return;
            }
            setShowConnectModal(true);
          }}
          title={!hasLlmKey ? "Please configure an LLM API key in Settings first before connecting a repository." : "Connect a GitHub repository to scan"}
          className={`btn-primary flex items-center gap-2 ${!hasLlmKey ? "cursor-not-allowed opacity-70" : ""}`}
        >
          {!hasLlmKey ? <AlertTriangle className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
          {!hasLlmKey ? "Configure API Key First" : "Connect Repository"}
        </button>
      </div>

      {loadingMetrics ? (
        <div className="flex flex-col items-center justify-center h-96 gap-4">
          <div className="w-12 h-12 rounded-2xl bg-accent-gradient/30 flex items-center justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
          </div>
          <p className="text-base text-zinc-600 dark:text-zinc-300">Loading your repository health...</p>
        </div>
      ) : (
        <>
          {/* ── 1. Repository Health hero ─────────────────────────── */}
          <div className="glass-hero p-8 mb-8 relative overflow-hidden">
            <div className="absolute inset-0 bg-card-glow-blue pointer-events-none" />
            <div className="relative z-10 grid grid-cols-1 lg:grid-cols-3 gap-8 items-center">
              <div>
                <p className="metric-label text-[10px]">Repository Health</p>
                <div className="flex items-baseline gap-3 mt-1">
                  <span className={`text-6xl font-black ${healthTone(latest?.health_score ?? null)}`}>
                    {latest?.health_score != null ? latest.health_score : "—"}
                  </span>
                  {latest?.health_score != null && (
                    <span className="text-lg text-zinc-500 font-bold dark:text-zinc-400">/100</span>
                  )}
                </div>
                {latest ? (
                  <p className="text-xs text-zinc-600 mt-2 dark:text-zinc-300">
                    Latest scan of <strong className="text-zinc-800 dark:text-zinc-100">{latest.repository}</strong>
                  </p>
                ) : (
                  <p className="text-xs text-zinc-600 mt-2 dark:text-zinc-300">
                    Run a scan to see your repository health here.
                  </p>
                )}
              </div>

              {/* Freshness: when / what was analyzed */}
              <div className="glass p-4 rounded-2xl text-xs space-y-2.5">
                <p className="metric-label text-[9px] mb-1">Last Analyzed</p>
                {latest ? (
                  <>
                    <p className="flex items-center gap-2 text-zinc-700 font-semibold dark:text-zinc-200">
                      <Clock className="w-3.5 h-3.5 text-zinc-500" />
                      {formatDateTime(latest.timestamp)}
                    </p>
                    <p className="flex items-center gap-2 text-zinc-700 font-semibold dark:text-zinc-200">
                      <GitBranch className="w-3.5 h-3.5 text-zinc-500" />
                      {latest.branch || "Branch not available"}
                    </p>
                    <p className="flex items-center gap-2 text-zinc-700 font-semibold font-mono dark:text-zinc-200">
                      <GitCommitHorizontal className="w-3.5 h-3.5 text-zinc-500" />
                      {latest.commit_sha ? latest.commit_sha.slice(0, 7) : "Commit not recorded"}
                    </p>
                    <p className="text-[10px] text-zinc-500 dark:text-zinc-400">
                      {latest.files_analyzed} files analyzed · results reflect this exact commit
                    </p>
                  </>
                ) : (
                  <p className="text-zinc-600 dark:text-zinc-300">No completed scans yet.</p>
                )}
              </div>

              {/* Quick stats */}
              <div className="grid grid-cols-3 gap-3">
                <div className="glass p-4 rounded-2xl text-center">
                  <p className="metric-label text-[9px]">Repositories</p>
                  <p className="text-2xl font-black text-zinc-900 dark:text-zinc-100">{metrics?.repositories_count || 0}</p>
                </div>
                <div className="glass p-4 rounded-2xl text-center">
                  <p className="metric-label text-[9px]">Security Issues</p>
                  <p className="text-2xl font-black text-accent-red">{metrics?.vulnerabilities_count || 0}</p>
                </div>
                <div className="glass p-4 rounded-2xl text-center">
                  <p className="metric-label text-[9px]">Avg Scan Time</p>
                  <p className="text-2xl font-black text-zinc-900 dark:text-zinc-100">
                    {metrics?.average_scan_duration ? `${metrics.average_scan_duration.toFixed(0)}s` : "—"}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* ── 2. What needs attention ───────────────────────────── */}
          <div className="glass-card p-6 mb-8">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-sm font-bold text-zinc-900 flex items-center gap-2 dark:text-white">
                <Siren className="w-4 h-4 text-accent-red" /> What Needs Attention
              </h3>
              {latest && (
                <span className={`text-[10px] font-bold px-2.5 py-1 rounded-full border ${
                  totalAttention === 0
                    ? "bg-green-500/10 text-green-600 border-green-500/30"
                    : "bg-orange-500/10 text-orange-600 border-orange-500/30"
                }`}>
                  {totalAttention === 0 ? "All clear in the latest scan" : `${totalAttention} item(s) to review`}
                </span>
              )}
            </div>
            {latest ? (
              <>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  {attentionRows.map((row) => {
                    const Icon = row.icon;
                    return (
                      <div key={row.label} className="glass p-4 rounded-2xl">
                        <Icon className={`w-4 h-4 mb-2 ${row.tone}`} />
                        <p className="metric-label text-[9px] leading-tight">{row.label}</p>
                        <p className={`text-2xl font-black mt-1 ${row.value > 0 ? row.tone : "text-zinc-400 dark:text-zinc-500"}`}>
                          {row.value}
                        </p>
                      </div>
                    );
                  })}
                </div>

                {/* ── 3. Top recommendations ─────────────────────── */}
                {latest.recommendations.length > 0 && (
                  <div className="mt-6 pt-5 border-t border-border/40">
                    <h4 className="text-xs font-bold text-zinc-900 flex items-center gap-2 mb-3 dark:text-zinc-100">
                      <Lightbulb className="w-3.5 h-3.5 text-accent-blue" /> Top Recommendations
                    </h4>
                    <ol className="space-y-2">
                      {latest.recommendations.map((rec, i) => (
                        <li key={i} className="flex items-start gap-2 text-xs text-zinc-700 dark:text-zinc-300">
                          <span className="w-5 h-5 rounded-full bg-accent-blue/10 text-accent-blue font-black text-[10px] flex items-center justify-center shrink-0 mt-0.5">
                            {i + 1}
                          </span>
                          <span className="font-medium mt-0.5">{rec}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

                <button
                  onClick={() => onSelectRepoId(latest.repository_id)}
                  className="mt-5 text-xs font-bold text-accent-blue hover:underline flex items-center gap-1"
                >
                  View full analysis for {latest.repository} <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </>
            ) : (
              <div className="text-center py-6">
                <p className="text-sm font-bold text-zinc-800 dark:text-zinc-100">No scans yet</p>
                <p className="text-xs text-zinc-600 mt-1 dark:text-zinc-400">
                  Connect a repository and run your first scan to see what needs attention.
                </p>
              </div>
            )}
          </div>

          {/* ── 4. Security Trend (only with real history) ────────── */}
          <div className="glass-card p-6 mb-8">
            <h3 className="text-sm font-bold text-zinc-900 dark:text-white">Security Trend</h3>
            <p className="text-[11px] text-zinc-500 mt-0.5 mb-4 dark:text-zinc-400">
              Shows how your security score changed across your recent scans (higher is better).
            </p>
            <div className="h-56">
              {hasTrendData ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={securityHistory}>
                    <CartesianGrid strokeDasharray="3 3" stroke={chartChrome.grid} />
                    <XAxis dataKey="date" stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                    <YAxis domain={[0, 100]} stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                    <Tooltip contentStyle={chartChrome.tooltipStyle} itemStyle={{ color: chartChrome.tooltipText }} labelStyle={{ color: chartChrome.tooltipText }} />
                    <Line type="monotone" dataKey="score" stroke="#EF4444" strokeWidth={2.5} dot={{ r: 3, fill: "#EF4444" }} activeDot={{ r: 6 }} name="Security score" />
                  </LineChart>
                </ResponsiveContainer>
              ) : securityHistory.length === 1 ? (
                <div className="h-full flex flex-col items-center justify-center text-center">
                  <TrendingUp className="w-8 h-8 text-zinc-400 mb-2" />
                  <p className="text-sm font-bold text-zinc-800 dark:text-zinc-100">Not enough scan history for a trend.</p>
                  <p className="text-xs text-zinc-600 mt-1 dark:text-zinc-400">
                    Run another scan after making changes to compare security over time.
                  </p>
                </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-center">
                  <Gauge className="w-8 h-8 text-zinc-400 mb-2" />
                  <p className="text-sm font-bold text-zinc-800 dark:text-zinc-100">No scan history yet.</p>
                  <p className="text-xs text-zinc-600 mt-1 dark:text-zinc-400">
                    Your security trend appears here after your first scans.
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* ── Repositories ──────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <div className="lg:col-span-2 space-y-6">
              <div className="flex justify-between items-center">
                <h3 className="text-sm font-bold text-zinc-900 dark:text-white">Connected Repositories</h3>
                <div className="relative w-64">
                  <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-zinc-500">
                    <Search className="w-4 h-4" />
                  </span>
                  <input
                    aria-label="Search repositories"
                    type="text"
                    placeholder="Search repos..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="input-glass pl-9 text-xs"
                  />
                </div>
              </div>

              {filteredRepos.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {filteredRepos.map((repo) => (
                    <div
                      key={repo.id}
                      onClick={() => onSelectRepoId(repo.id)}
                      className="glass-card-hover p-5 cursor-pointer"
                    >
                      <div className="flex items-center gap-2.5 mb-3">
                        <div className="w-8 h-8 rounded-xl bg-accent-blue/10 flex items-center justify-center">
                          <BookOpen className="w-4 h-4 text-accent-blue" />
                        </div>
                        <h4 className="font-bold text-sm text-zinc-900 truncate dark:text-zinc-100">{repo.name}</h4>
                      </div>
                      <p className="text-xs text-zinc-600 line-clamp-2 mb-4 dark:text-zinc-400">{repo.description || "No description"}</p>
                      <div className="flex justify-between items-center border-t border-border/40 pt-3 text-[10px] text-zinc-500 dark:text-zinc-400">
                        <span className="bg-white/5 px-2 py-0.5 rounded-full text-zinc-600 font-semibold dark:text-zinc-300">
                          {repo.default_branch}
                        </span>
                        <div className="flex items-center gap-3">
                          <span>⭐ {repo.stars}</span>
                          <span>⑂ {repo.forks}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="glass-card p-12 text-center">
                  <div className="w-12 h-12 rounded-2xl bg-white/5 flex items-center justify-center mx-auto mb-4">
                    <BookOpen className="w-6 h-6 text-zinc-500" />
                  </div>
                  <p className="text-base text-zinc-800 font-semibold dark:text-zinc-100">No repositories found</p>
                  <button onClick={() => setShowConnectModal(true)} className="btn-primary mt-4">
                    Connect Repository
                  </button>
                </div>
              )}
            </div>

            {/* Sidebar: risky repos + recent activity */}
            <div className="space-y-6">
              <div className="glass-card p-6">
                <h3 className="text-sm font-bold text-zinc-900 mb-1 dark:text-white">Risky Repositories</h3>
                <p className="text-[10px] text-zinc-500 mb-4 dark:text-zinc-400">Highest risk score from the latest scan of each repository.</p>
                {(metrics?.top_risky_repositories?.length ?? 0) > 0 ? (
                  <div className="space-y-4">
                    {metrics!.top_risky_repositories.map((repo, idx) => {
                      const isHigh = repo.risk_score >= 70;
                      const isMid = repo.risk_score >= 35;
                      return (
                        <div key={repo.repo_id} className="flex justify-between items-center text-xs border-b border-border/30 pb-3 last:border-0 last:pb-0">
                          <div className="flex items-center gap-3 min-w-0">
                            <span className="font-extrabold text-sm text-zinc-500 w-4">{idx + 1}</span>
                            <p className="text-zinc-900 font-semibold hover:underline cursor-pointer truncate dark:text-zinc-100" onClick={() => onSelectRepoId(repo.repo_id)}>
                              {repo.name}
                            </p>
                          </div>
                          <span className={`badge ${isHigh ? "badge-critical" : isMid ? "badge-high" : "badge-low"}`}>
                            Risk: {repo.risk_score}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-center text-zinc-700 font-semibold text-xs py-4 dark:text-zinc-300">No scanned repositories yet</div>
                )}
              </div>

              <div className="glass-card p-6">
                <h3 className="text-sm font-bold text-zinc-900 mb-1 dark:text-white">Recent Activity</h3>
                <p className="text-[10px] text-zinc-500 mb-4 dark:text-zinc-400">Your latest scans and their status.</p>
                {(metrics?.recent_activity?.length ?? 0) > 0 ? (
                  <div className="space-y-4">
                    {metrics!.recent_activity.map((act, idx) => (
                      <div key={idx} className="flex gap-3 text-xs border-b border-border/30 pb-3 last:border-0 last:pb-0">
                        <div className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${
                          act.status === "completed" ? "bg-green-500" : act.status === "failed" ? "bg-accent-red" : "bg-amber-500 animate-pulse"
                        }`} />
                        <div className="flex-1 min-w-0">
                          <p className="text-zinc-900 font-medium truncate dark:text-zinc-100">{act.repo}</p>
                          <p className="text-zinc-600 mt-0.5 dark:text-zinc-400">Scan: <span className="font-semibold capitalize">{act.status}</span></p>
                          <span className="text-[10px] text-zinc-500 block mt-1 dark:text-zinc-400" title={formatDateTime(act.timestamp, "datetime-seconds")}>
                            {formatDateTime(act.timestamp)}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center text-zinc-700 font-semibold text-xs py-4 dark:text-zinc-300">No recent activity</div>
                )}
              </div>
            </div>
          </div>
        </>
      )}

      {/* Connect Repo Modal */}
      {showConnectModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="glass-card w-full max-w-md p-8 animate-scale-in">
            <h3 className="text-lg font-bold text-zinc-900 mb-2 dark:text-white">Connect Repository</h3>
            <p className="text-xs text-zinc-600 mb-5 dark:text-zinc-400">Enter a GitHub repository URL or slug</p>

            {connectError && (
              <div className="mb-4 bg-accent-red/10 border border-accent-red/20 text-accent-red p-3 rounded-2xl text-xs">{connectError}</div>
            )}

            <form onSubmit={handleConnect} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-zinc-600 mb-2 dark:text-zinc-300">Repository URL</label>
                <input type="text" required placeholder="https://github.com/owner/repo" value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)} aria-label="GitHub repository URL" className="input-glass text-sm" />
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button type="button" onClick={() => setShowConnectModal(false)} className="btn-secondary">Cancel</button>
                <button type="submit" disabled={connecting} className="btn-primary flex items-center gap-2">
                  {connecting ? <><Loader2 className="w-3 h-3 animate-spin" /> Connecting...</> : "Connect"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
