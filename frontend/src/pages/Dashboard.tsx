import React, { useEffect, useState, useRef } from "react";
import { motion } from "framer-motion";
import axios from "../lib/api";
import { useRepositoryStore } from "../store/repositoryStore";
import { useAuthStore } from "../store/authStore";
import {
  Shield, GitPullRequest, Database, Trophy, Activity,
  Plus, Search, Loader2, BookOpen, Clock, TrendingUp, TrendingDown, AlertTriangle
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell
} from "recharts";
import { useAnalysisStore } from "../store/analysisStore";
import { useQuery } from "@tanstack/react-query";
import type { Analysis } from "../store/analysisStore";
import { useThemeStore } from "../store/themeStore";

interface ComparisonData {
  status: string;
  security: { a: number; b: number; improvement_pct: number };
  code_smells: { a: number; b: number; improvement_pct: number };
  tests: { a: number; b: number; improvement_pct: number };
  risk_score: { a: number; b: number; improvement_pct: number };
  fixed: Array<{ id: string; issue: string; type: string; file: string; line: number }>;
  new: Array<{ id: string; issue: string; type: string; file: string; line: number }>;
  remaining: Array<{ id: string; issue: string; type: string; file: string; line: number }>;
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
  top_risky_repositories: Array<{ repo_id: string; name: string; risk_score: number; vulnerabilities_count?: number }>;
  average_scan_duration: number;
  token_consumption: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  model_usage: Record<string, number>;
}

interface DashboardProps {
  onSelectRepoId: (id: string) => void;
}

const staggerContainer = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.08, delayChildren: 0.1 }
  }
};

const staggerItem = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.25, 0.4, 0.25, 1] } }
};

// ── Animated Metric Card ──

// Theme-aware chart chrome: reads the CSS variables set in index.css so the
// grid, axes and tooltips stay readable in BOTH light and dark mode.
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

const MetricCard: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string | number;
  trend?: { value: number; positive: boolean };
  glowColor?: string;
}> = ({ icon, label, value, trend, glowColor = "blue" }) => {
  const glowClass = glowColor === "purple" ? "glass-card-glow-purple" : 
                     glowColor === "cyan" ? "glass-card-glow-cyan" : 
                     glowColor === "green" ? "glass-card-glow-green" : "glass-card-glow";
  return (
    <motion.div
      className={`${glowClass} p-6 cursor-default`}
      variants={staggerItem}
      whileHover={{ y: -6, scale: 1.02, transition: { duration: 0.25 } }}
      whileTap={{ scale: 0.98 }}
    >
      <div className="flex items-center justify-between mb-3">
        <motion.div
          className="w-10 h-10 rounded-xl bg-white/5 flex items-center justify-center"
          whileHover={{ scale: 1.1, rotate: 5 }}
          transition={{ type: "spring", stiffness: 300, damping: 10 }}
        >
          {icon}
        </motion.div>
        {trend && (
          <div className={`flex items-center gap-1 text-xs font-semibold ${trend.positive ? 'text-accent-green' : 'text-accent-red'}`}>
            {trend.positive ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
            {trend.value}%
          </div>
        )}
      </div>
      <p className="metric-label">{label}</p>
      <p className="metric-value mt-1">{value}</p>
    </motion.div>
  );
};

export const Dashboard: React.FC<DashboardProps> = ({ onSelectRepoId }) => {
  const { repositories, connectRepository } = useRepositoryStore();
  const { compareScans } = useAnalysisStore();
  const { user } = useAuthStore();
  const chartChrome = useChartChrome();

  const hasLlmKey = user ? (
    user.has_groq_api_key || user.has_openai_api_key ||
    user.has_claude_api_key || user.has_gemini_api_key || user.has_openrouter_api_key
  ) : false;

  const [selectedRepoId, setSelectedRepoId] = useState<string>("");
  const [repoScans, setRepoScans] = useState<Analysis[]>([]);
  const [scanA, setScanA] = useState<string>("");
  const [scanB, setScanB] = useState<string>("");
  const [comparison, setComparison] = useState<ComparisonData | null>(null);
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  const prevSelectedRepoScansRef = useRef<Analysis[] | undefined>(undefined);
  const prevSelectedRepoIdRef = useRef<string>("");

  const { data: dashboardMetrics, isLoading: loadingMetrics, refetch: refetchMetrics } = useQuery({
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

  const { data: deletedScansData, isLoading: loadingDeleted, refetch: refetchDeleted } = useQuery({
    queryKey: ["deletedScans"],
    queryFn: async () => {
      const res = await axios.get("/analysis/deleted");
      return res.data;
    },
    staleTime: 60_000,
    gcTime: 300_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const { data: reposData, refetch: refetchRepos } = useQuery({
    queryKey: ["repositories"],
    queryFn: async () => {
      const res = await axios.get("/repositories");
      return res.data;
    },
    staleTime: 60_000,
    gcTime: 300_000,
    refetchInterval: 120_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const { data: selectedRepoScans } = useQuery({
    queryKey: ["repoScans", selectedRepoId],
    queryFn: async () => {
      if (!selectedRepoId) return [];
      const res = await axios.get(`/analysis/repo/${selectedRepoId}`);
      return res.data;
    },
    enabled: !!selectedRepoId,
    staleTime: 30_000,
    gcTime: 120_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const metrics = (dashboardMetrics as DashboardMetricsType) || null;
  const deletedScans = deletedScansData || [];

  useEffect(() => {
    if (reposData) {
      useRepositoryStore.setState({ repositories: reposData });
    }
  }, [reposData]);

  useEffect(() => {
    if (selectedRepoScans && selectedRepoScans !== prevSelectedRepoScansRef.current) {
      prevSelectedRepoScansRef.current = selectedRepoScans;
      prevSelectedRepoIdRef.current = selectedRepoId;
      const completed = selectedRepoScans.filter((an: Analysis) => an.status === "completed");
      setRepoScans(completed);
      if (completed.length >= 2) {
        setScanA(completed[0].id);
        setScanB(completed[1].id);
      } else {
        setScanA("");
        setScanB("");
      }
      setComparison(null);
      setCompareError(null);
    } else if (!selectedRepoScans && prevSelectedRepoScansRef.current !== undefined) {
      prevSelectedRepoScansRef.current = undefined;
      prevSelectedRepoIdRef.current = "";
      setRepoScans([]);
      setScanA("");
      setScanB("");
      setComparison(null);
    }
  }, [selectedRepoScans, selectedRepoId]);

  const handleCompare = async () => {
    if (!scanA || !scanB) return;
    setComparing(true);
    setCompareError(null);
    try {
      const res = await compareScans(scanA, scanB);
      setComparison(res as ComparisonData);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to compare scans";
      setCompareError(msg);
    } finally {
      setComparing(false);
    }
  };

  const handleRestore = async (scanId: string) => {
    try {
      await axios.post(`/analysis/${scanId}/restore`);
      refetchDeleted();
      refetchMetrics();
    } catch {
      alert("Failed to restore scan history.");
    }
  };

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    setConnecting(true);
    setConnectError(null);
    try {
      const newRepo = await connectRepository(repoUrl);
      refetchRepos();
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

  const sevChartData = metrics
    ? Object.keys(metrics.severity_distribution).map((key) => ({
        name: key,
        count: metrics.severity_distribution[key]
      }))
    : [];

  const SEV_COLORS: Record<string, string> = {
    Critical: "#ef4444",
    High: "#f97316",
    Medium: "#eab308",
    Low: "#3b82f6",
    Info: "#6b7280"
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto max-h-screen">
      {/* Header */}
      <div className="flex justify-between items-center mb-10">
        <div>
          <h1 className="text-4xl font-bold text-zinc-900">Dashboard</h1>
          <p className="text-base text-zinc-700 font-medium mt-1">SaaS repository review analytics and scan center</p>
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
          <p className="text-base text-zinc-600">Loading metrics...</p>
        </div>
      ) : (
        <>
          {/* KPI Metrics Row (animated with stagger) */}
          <motion.div
            className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-10"
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
          >
            <MetricCard
              icon={<Database className="w-5 h-5 text-accent-blue" />}
              label="Repositories"
              value={metrics?.repositories_count || 0}
              glowColor="blue"
            />
            <MetricCard
              icon={<GitPullRequest className="w-5 h-5 text-accent-cyan" />}
              label="PRs Reviewed"
              value={metrics?.prs_count || 0}
              glowColor="cyan"
            />
            <MetricCard
              icon={<Shield className="w-5 h-5 text-accent-red" />}
              label="Vulnerabilities"
              value={metrics?.vulnerabilities_count || 0}
              glowColor="blue"
            />
            <MetricCard
              icon={<Activity className="w-5 h-5 text-accent-purple" />}
              label="Security Score"
              value={metrics?.security_score !== undefined ? `${metrics.security_score.toFixed(1)}%` : "-"}
              trend={metrics?.security_score ? { value: Math.round(metrics.security_score / 10), positive: metrics.security_score > 50 } : undefined}
              glowColor="purple"
            />
            <MetricCard
              icon={<Trophy className="w-5 h-5 text-accent-green" />}
              label="Health Score"
              value={metrics?.health_history?.length > 0
                ? `${metrics.avg_health_score.toFixed(1)}%`
                : "No scans yet"}
              glowColor="green"
            />
            <MetricCard
              icon={<Clock className="w-5 h-5 text-accent-cyan" />}
              label="Avg Scan Time"
              value={metrics?.average_scan_duration !== undefined ? `${metrics.average_scan_duration.toFixed(1)}s` : "0.0s"}
              glowColor="cyan"
            />
          </motion.div>

          {/* Charts Section */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
            {/* Vulnerability Trends */}
            <div className="glass-card p-6">
              <h3 className="text-sm font-bold text-zinc-900 mb-5">Vulnerability Detection Trends</h3>
              <div className="h-64">
                {metrics?.vulnerability_trends.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={metrics.vulnerability_trends}>
                      <CartesianGrid strokeDasharray="3 3" stroke={chartChrome.grid} />
                      <XAxis dataKey="date" stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                      <YAxis stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                      <Tooltip contentStyle={chartChrome.tooltipStyle} itemStyle={{ color: chartChrome.tooltipText }} labelStyle={{ color: chartChrome.tooltipText }} />
                      <Line type="monotone" dataKey="count" stroke="#4F7CFF" strokeWidth={2.5} dot={{ r: 3, fill: "#4F7CFF" }} activeDot={{ r: 6 }} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-zinc-700 font-semibold text-base">
                    No scanning history available. Run a repository scan first.
                  </div>
                )}
              </div>
            </div>

            {/* Severity Distribution */}
            <div className="glass-card p-6">
              <h3 className="text-sm font-bold text-zinc-900 mb-5">Severity Distribution</h3>
              <div className="h-64">
                {metrics?.vulnerabilities_count > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={sevChartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke={chartChrome.grid} />
                      <XAxis dataKey="name" stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                      <YAxis stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                      <Tooltip contentStyle={chartChrome.tooltipStyle} itemStyle={{ color: chartChrome.tooltipText }} labelStyle={{ color: chartChrome.tooltipText }} />
                      <Bar dataKey="count" radius={[8, 8, 0, 0]} barSize={36}>
                        {sevChartData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={SEV_COLORS[entry.name] || "#4F7CFF"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-zinc-700 font-semibold text-base">
                    No vulnerabilities detected
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Second Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
            <div className="glass-card p-6">
              <h3 className="text-sm font-bold text-zinc-900 mb-5">Health Score Trends</h3>
              <div className="h-64">
                {metrics?.health_history?.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={metrics.health_history}>
                      <CartesianGrid strokeDasharray="3 3" stroke={chartChrome.grid} />
                      <XAxis dataKey="date" stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                      <YAxis stroke={chartChrome.axis} fontSize={11} domain={[0, 100]} tick={{ fill: chartChrome.axis }} />
                      <Tooltip contentStyle={chartChrome.tooltipStyle} itemStyle={{ color: chartChrome.tooltipText }} labelStyle={{ color: chartChrome.tooltipText }} />
                      <Line type="monotone" dataKey="score" stroke="#22C55E" strokeWidth={2.5} dot={{ r: 3, fill: "#22C55E" }} activeDot={{ r: 6 }} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-zinc-700 font-semibold text-base">No health history. Run a repository scan first.</div>
                )}
              </div>
            </div>
            <div className="glass-card p-6">
              <h3 className="text-sm font-bold text-zinc-900 mb-5">Security Score Trends</h3>
              <div className="h-64">
                {metrics?.security_score_history?.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={metrics.security_score_history}>
                      <CartesianGrid strokeDasharray="3 3" stroke={chartChrome.grid} />
                      <XAxis dataKey="date" stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                      <YAxis stroke={chartChrome.axis} fontSize={11} domain={[0, 100]} tick={{ fill: chartChrome.axis }} />
                      <Tooltip contentStyle={chartChrome.tooltipStyle} itemStyle={{ color: chartChrome.tooltipText }} labelStyle={{ color: chartChrome.tooltipText }} />
                      <Line type="monotone" dataKey="score" stroke="#EF4444" strokeWidth={2.5} dot={{ r: 3, fill: "#EF4444" }} activeDot={{ r: 6 }} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-zinc-700 font-semibold text-base">No security history. Run a repository scan first.</div>
                )}
              </div>
            </div>
          </div>

          {/* Third Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
            <div className="glass-card p-6">
              <h3 className="text-sm font-bold text-zinc-900 mb-5">Token Consumption</h3>
              <div className="h-64">
                {metrics?.token_consumption && Object.keys(metrics.token_consumption).length > 0 ? (
                  <>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={[{ name: "Tokens", Prompt: metrics.token_consumption.prompt_tokens || 0, Completion: metrics.token_consumption.completion_tokens || 0 }]}>
                        <CartesianGrid strokeDasharray="3 3" stroke={chartChrome.grid} />
                        <XAxis dataKey="name" stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                        <YAxis stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                        <Tooltip contentStyle={chartChrome.tooltipStyle} itemStyle={{ color: chartChrome.tooltipText }} labelStyle={{ color: chartChrome.tooltipText }} formatter={(value: number) => [value.toLocaleString(), undefined]} />
                        <Bar dataKey="Prompt" fill="#4F7CFF" stackId="a" name="Prompt Tokens" radius={[0, 0, 0, 0]} />
                        <Bar dataKey="Completion" fill="#7C5CFF" stackId="a" radius={[8, 8, 0, 0]} name="Completion Tokens" />
                      </BarChart>
                    </ResponsiveContainer>                      <div className="flex justify-between mt-4 text-xs text-zinc-600">
                      <span>Total: <strong className="text-zinc-950">{(metrics?.token_consumption?.total_tokens || 0).toLocaleString()}</strong></span>
                      <span>Prompt: <strong className="text-accent-blue">{(metrics?.token_consumption?.prompt_tokens || 0).toLocaleString()}</strong></span>
                      <span>Completion: <strong className="text-accent-purple">{(metrics?.token_consumption?.completion_tokens || 0).toLocaleString()}</strong></span>
                    </div>
                  </>
                ) : (
                  <div className="h-full flex items-center justify-center text-zinc-700 font-semibold text-base">No token data</div>
                )}
              </div>
            </div>
            <div className="glass-card p-6">
              <h3 className="text-sm font-bold text-zinc-900 mb-5">Model Usage</h3>
              <div className="h-64">
                {metrics?.model_usage && Object.keys(metrics.model_usage).length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={Object.entries(metrics.model_usage).map(([name, count]) => ({ name, count }))} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" stroke={chartChrome.grid} />
                      <XAxis type="number" stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                      <YAxis dataKey="name" type="category" stroke={chartChrome.axis} fontSize={10} width={100} tick={{ fill: chartChrome.axis }} />
                      <Tooltip contentStyle={chartChrome.tooltipStyle} itemStyle={{ color: chartChrome.tooltipText }} labelStyle={{ color: chartChrome.tooltipText }} />
                      <Bar dataKey="count" fill="#7C5CFF" radius={[0, 8, 8, 0]} barSize={20} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-zinc-700 font-semibold text-base">No model data</div>
                )}
              </div>
            </div>
          </div>

          {/* Scan Comparison */}
          <div className="glass-card p-6 mb-8">
            <div className="flex flex-col md:flex-row md:justify-between md:items-center mb-6 gap-2">
              <div className="flex items-center gap-3">
                <h3 className="text-sm font-bold text-zinc-900">Scan Comparison</h3>
                {comparison && (
                  <span className={`badge ${
                    comparison.status === "Improved" ? "badge-critical" :
                    comparison.status === "Regressed" ? "bg-accent-red/10 text-accent-red border-accent-red/20" :
                    "badge-info"
                  }`}>
                    {comparison.status}
                  </span>
                )}
              </div>
              <p className="text-xs text-zinc-600">Compare two historical scans to verify improvements</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
              <div>
                <label className="block text-[10px] uppercase font-bold text-zinc-600 mb-1.5">1. Repository</label>
                <select
                  value={selectedRepoId}
                  onChange={(e) => setSelectedRepoId(e.target.value)}
                  className="select-glass"
                >
                  <option value="">Select Repository</option>
                  {repositories.map(repo => (
                    <option key={repo.id} value={repo.id}>{repo.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[10px] uppercase font-bold text-zinc-600 mb-1.5">2. Scan A (Before)</label>
                <select
                  value={scanA}
                  onChange={(e) => setScanA(e.target.value)}
                  disabled={repoScans.length < 2}
                  className="select-glass disabled:opacity-40"
                >
                  <option value="">Select Scan</option>
                  {repoScans.map(an => (
                    <option key={an.id} value={an.id}>{new Date(an.timestamp).toLocaleDateString()} (Risk: {an.risk_score})</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[10px] uppercase font-bold text-zinc-600 mb-1.5">3. Scan B (After)</label>
                <select
                  value={scanB}
                  onChange={(e) => setScanB(e.target.value)}
                  disabled={repoScans.length < 2}
                  className="select-glass disabled:opacity-40"
                >
                  <option value="">Select Scan</option>
                  {repoScans.map(an => (
                    <option key={an.id} value={an.id}>{new Date(an.timestamp).toLocaleDateString()} (Risk: {an.risk_score})</option>
                  ))}
                </select>
              </div>
              <button
                onClick={handleCompare}
                disabled={comparing || !scanA || !scanB}
                className="btn-primary w-full flex items-center justify-center gap-1.5"
              >
                {comparing ? (
                  <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Comparing...</>
                ) : "Compare Scans"}
              </button>
            </div>

            {/* Comparison results */}
            {comparison && (
              <div className="space-y-6 mt-8 animate-fade-in">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {[
                    { label: "Security", data: comparison.security },
                    { label: "Code Smells", data: comparison.code_smells },
                    { label: "Tests", data: comparison.tests },
                    { label: "Risk Score", data: comparison.risk_score },
                  ].map(({ label, data }) => (
                    <div key={label} className="bg-white/40 backdrop-blur-glass border border-border/60 rounded-2xl p-5">
                      <span className="text-[10px] font-bold text-zinc-600 uppercase tracking-wider block">{label}</span>
                      <div className="flex items-baseline gap-2 mt-2">
                        <span className="text-lg font-bold text-zinc-900">{data.a} → {data.b}</span>
                        <span className={`text-xs font-extrabold ${data.improvement_pct >= 0 ? "text-accent-green" : "text-accent-red"}`}>
                          {data.improvement_pct >= 0 ? `+${data.improvement_pct}%` : `${data.improvement_pct}%`}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={[
                      { name: "Risk Score", before: comparison.risk_score.a, after: comparison.risk_score.b },
                      { name: "Security", before: comparison.security.a, after: comparison.security.b },
                      { name: "Code Smells", before: comparison.code_smells.a, after: comparison.code_smells.b }
                    ]}>
                      <CartesianGrid strokeDasharray="3 3" stroke={chartChrome.grid} />
                      <XAxis dataKey="name" stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                      <YAxis stroke={chartChrome.axis} fontSize={11} tick={{ fill: chartChrome.axis }} />
                      <Tooltip contentStyle={chartChrome.tooltipStyle} itemStyle={{ color: chartChrome.tooltipText }} labelStyle={{ color: chartChrome.tooltipText }} />
                      <Bar dataKey="before" fill="#EF4444" radius={[8, 8, 0, 0]} name="Before" />
                      <Bar dataKey="after" fill="#22C55E" radius={[8, 8, 0, 0]} name="After" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {selectedRepoId && repoScans.length < 2 && (
              <p className="text-xs text-amber-500 mt-3">
                This repository has {repoScans.length} completed scan(s). Need at least 2.
              </p>
            )}

            {compareError && (
              <div className="mt-4 bg-accent-red/10 border border-accent-red/20 text-accent-red p-3 rounded-2xl text-xs">
                {compareError}
              </div>
            )}
          </div>

          {/* Repositories & Sidebar */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Repos Grid */}
            <div className="lg:col-span-2 space-y-6">
              <div className="flex justify-between items-center">
                <h3 className="text-sm font-bold text-zinc-900">Connected Repositories</h3>
                <div className="relative w-64">
                  <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-zinc-500">
                    <Search className="w-4 h-4" />
                  </span>
                  <input
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
                        <h4 className="font-bold text-sm text-zinc-900 truncate">{repo.name}</h4>
                      </div>
                      <p className="text-xs text-zinc-600 line-clamp-2 mb-4">{repo.description || "No description"}</p>
                      <div className="flex justify-between items-center border-t border-border/40 pt-3 text-[10px] text-zinc-500">
                        <span className="bg-white/5 px-2 py-0.5 rounded-full text-zinc-600 font-semibold">
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
                  <p className="text-base text-zinc-800 font-semibold">No repositories found</p>
                  <button onClick={() => setShowConnectModal(true)} className="btn-primary mt-4">
                    Connect Repository
                  </button>
                </div>
              )}
            </div>

            {/* Sidebar */}
            <div className="space-y-6">
              {/* Risky Repos */}
              <div className="glass-card p-6">
                <h3 className="text-sm font-bold text-zinc-900 mb-4">Risky Repositories</h3>
                {metrics?.top_risky_repositories?.length > 0 ? (
                  <div className="space-y-4">
                    {metrics.top_risky_repositories.map((repo: any, idx: number) => {
                      const isHigh = repo.risk_score >= 70;
                      const isMid = repo.risk_score >= 35;
                      return (
                        <div key={repo.repo_id} className="flex justify-between items-center text-xs border-b border-border/30 pb-3 last:border-0 last:pb-0">
                          <div className="flex items-center gap-3 min-w-0">
                            <span className="font-extrabold text-sm text-zinc-500 w-4">{idx + 1}</span>
                            <div className="min-w-0">
                              <p className="text-zinc-900 font-semibold hover:underline cursor-pointer truncate" onClick={() => onSelectRepoId(repo.repo_id)}>
                                {repo.name}
                              </p>
                            </div>
                          </div>
                          <span className={`badge ${isHigh ? 'badge-critical' : isMid ? 'badge-high' : 'badge-low'}`}>
                            Risk: {repo.risk_score}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-center text-zinc-700 font-semibold text-xs py-4">No scanned repositories yet</div>
                )}
              </div>

              {/* Recent Activity */}
              <div className="glass-card p-6">
                <h3 className="text-sm font-bold text-zinc-900 mb-4">Recent Activity</h3>
                {metrics?.recent_activity?.length > 0 ? (
                  <div className="space-y-4">
                    {metrics.recent_activity.map((act: any, idx: number) => (
                      <div key={idx} className="flex gap-3 text-xs border-b border-border/30 pb-3 last:border-0 last:pb-0">
                        <div className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${
                          act.status === "completed" ? "bg-green-500" : act.status === "failed" ? "bg-accent-red" : "bg-amber-500 animate-pulse"
                        }`} />
                        <div className="flex-1 min-w-0">
                          <p className="text-zinc-900 font-medium truncate">{act.repo}</p>
                          <p className="text-zinc-600 mt-0.5">Scan: <span className="font-semibold capitalize">{act.status}</span></p>
                          <span className="text-[10px] text-zinc-500 block mt-1">{act.timestamp}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center text-zinc-700 font-semibold text-xs py-4">No recent activity</div>
                )}
              </div>

              {/* Restoration Center */}
              <div className="glass-card p-6">
                <h3 className="text-sm font-bold text-zinc-900 mb-2">Restoration Center</h3>
                <p className="text-xs text-zinc-600 mb-4">Recover soft-deleted scan histories</p>
                {loadingDeleted ? (
                  <div className="flex items-center justify-center py-4">
                    <Loader2 className="w-5 h-5 animate-spin text-accent-blue" />
                  </div>
                ) : deletedScans.length > 0 ? (
                  <div className="space-y-3 max-h-[250px] overflow-y-auto">
                    {deletedScans.map((scan: any) => (
                      <div key={scan.id} className="flex justify-between items-center text-xs bg-white/30 rounded-2xl p-3">
                        <div className="min-w-0 pr-2">
                          <p className="text-zinc-900 font-medium truncate">Scan {scan.id.slice(0, 8)}</p>
                          <p className="text-zinc-500 text-[10px] mt-0.5">{new Date(scan.timestamp).toLocaleString()}</p>
                        </div>
                        <button onClick={() => handleRestore(scan.id)}
                          className="px-3 py-1.5 border border-accent-blue/30 hover:bg-accent-blue/10 text-accent-blue rounded-2xl text-[10px] font-bold transition-all"
                        >Restore</button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center text-zinc-700 font-semibold text-xs py-4">No deleted scans found</div>
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
            <h3 className="text-lg font-bold text-zinc-900 mb-2">Connect Repository</h3>
            <p className="text-xs text-zinc-600 mb-5">Enter a GitHub repository URL or slug</p>
            
            {connectError && (
              <div className="mb-4 bg-accent-red/10 border border-accent-red/20 text-accent-red p-3 rounded-2xl text-xs">{connectError}</div>
            )}

            <form onSubmit={handleConnect} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-zinc-600 mb-2">Repository URL</label>
                <input type="text" required placeholder="https://github.com/owner/repo" value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)} className="input-glass text-sm" />
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
