import React, { useEffect, useState, useRef } from "react";
import axios from "../lib/api";
import { useRepositoryStore } from "../store/repositoryStore";
import {
  ShieldAlert, GitPullRequest, Database, Trophy,
  Plus, Search, Loader2, BookOpen, Clock
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell
} from "recharts";
import { useAnalysisStore } from "../store/analysisStore";
import { useQuery } from "@tanstack/react-query";
import type { Analysis } from "../store/analysisStore";

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
  top_risky_repositories: Array<{ id: string; repo_id?: string; name: string; risk_score: number; vulnerabilities_count?: number }>;
  average_scan_duration: number;
  token_consumption: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  model_usage: Record<string, number>;
}

interface DashboardProps {
  onSelectRepoId: (id: string) => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ onSelectRepoId }) => {
  const { repositories, connectRepository } = useRepositoryStore();
  const { compareScans } = useAnalysisStore();

  const [selectedRepoId, setSelectedRepoId] = useState<string>("");
  const [repoScans, setRepoScans] = useState<Analysis[]>([]);
  const [scanA, setScanA] = useState<string>("");
  const [scanB, setScanB] = useState<string>("");
  const [comparison, setComparison] = useState<ComparisonData | null>(null);
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  
  // Connection modal/card state
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  const prevSelectedRepoScansRef = useRef<Analysis[] | undefined>(undefined);
  const prevSelectedRepoIdRef = useRef<string>("");

  // React Query definitions
  const { data: dashboardMetrics, isLoading: loadingMetrics, refetch: refetchMetrics } = useQuery({
    queryKey: ["dashboardMetrics"],
    queryFn: async () => {
      const res = await axios.get("/users/me/dashboard");
      return res.data as DashboardMetricsType;
    },
    staleTime: 300_000,   // 5 minutes – prevents repeated dashboard API calls
    gcTime: 600_000,      // 10 minutes
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const { data: deletedScansData, isLoading: loadingDeleted, refetch: refetchDeleted } = useQuery({
    queryKey: ["deletedScans"],
    queryFn: async () => {
      const res = await axios.get("/analysis/deleted");
      return res.data;
    },
    staleTime: 300_000,
    gcTime: 600_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const { data: reposData, refetch: refetchRepos } = useQuery({
    queryKey: ["repositories"],
    queryFn: async () => {
      const res = await axios.get("/repositories");
      return res.data;
    },
    staleTime: 300_000,
    gcTime: 600_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const { data: selectedRepoScans } = useQuery({
    queryKey: ["repoScans", selectedRepoId],
    queryFn: async () => {
      if (!selectedRepoId) return [];
      const res = await axios.get(`/analysis/repo/${selectedRepoId}`);
      return res.data;
    },
    enabled: !!selectedRepoId,
    staleTime: 300_000,
    gcTime: 600_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
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
    High: "#f87171",
    Medium: "#f97316",
    Low: "#3b82f6",
    Info: "#71717a"
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto max-h-screen">
      {/* Top Header */}
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight">Dashboard</h1>
          <p className="text-muted mt-1">SaaS repository review analytics and scan center</p>
        </div>
        <button
          onClick={() => setShowConnectModal(true)}
          className="flex items-center gap-2 bg-accent-blue hover:bg-blue-600 active:bg-blue-700 text-white font-semibold text-sm px-4 py-2.5 rounded-lg transition-colors duration-150 shadow-lg shadow-accent-blue/10"
        >
          <Plus className="w-4 h-4" />
          Connect Repository
        </button>
      </div>

      {loadingMetrics ? (
        <div className="flex flex-col items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-accent-blue mb-2" />
          <p className="text-sm text-muted">Retrieving metrics...</p>
        </div>
      ) : (
        <>
          {/* Top KPI Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-6 gap-6 mb-8">
            <div className="bg-surface border border-border rounded-xl p-6 flex items-center gap-4">
              <div className="bg-zinc-800 p-3 rounded-lg text-zinc-300">
                <Database className="w-6 h-6" />
              </div>
              <div>
                <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Repositories</p>
                <h3 className="text-2xl font-bold mt-1 text-white">{metrics?.repositories_count}</h3>
              </div>
            </div>

            <div className="bg-surface border border-border rounded-xl p-6 flex items-center gap-4">
              <div className="bg-blue-500/10 p-3 rounded-lg text-accent-blue">
                <GitPullRequest className="w-6 h-6" />
              </div>
              <div>
                <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">PRs Reviewed</p>
                <h3 className="text-2xl font-bold mt-1 text-white">{metrics?.prs_count}</h3>
              </div>
            </div>

            <div className="bg-surface border border-border rounded-xl p-6 flex items-center gap-4">
              <div className="bg-red-500/10 p-3 rounded-lg text-accent-red">
                <ShieldAlert className="w-6 h-6" />
              </div>
              <div>
                <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Vulnerabilities</p>
                <h3 className="text-2xl font-bold mt-1 text-white">{metrics?.vulnerabilities_count}</h3>
              </div>
            </div>

            <div className="bg-surface border border-border rounded-xl p-6 flex items-center gap-4">
              <div className="bg-red-500/10 p-3 rounded-lg text-accent-red">
                <ShieldAlert className="w-6 h-6" />
              </div>
              <div>                    <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Avg Security Score</p>
                <h3 className="text-2xl font-bold mt-1 text-white">
                  {metrics?.security_score !== undefined && metrics.security_score > 0
                    ? `${metrics.security_score.toFixed(1)}%`
                    : metrics?.security_score === 0
                      ? "0.0%"
                      : "N/A"}
                </h3>
              </div>
            </div>

            <div className="bg-surface border border-border rounded-xl p-6 flex items-center gap-4">
              <div className="bg-green-500/10 p-3 rounded-lg text-accent-green">
                <Trophy className="w-6 h-6" />
              </div>
              <div>                    <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Avg Health Score</p>
                <h3 className="text-2xl font-bold mt-1 text-white">
                  {metrics?.avg_health_score !== undefined && metrics?.avg_health_score !== null
                    ? `${metrics.avg_health_score.toFixed(1)}%`
                    : "N/A"}
                </h3>
              </div>
            </div>

            <div className="bg-surface border border-border rounded-xl p-6 flex items-center gap-4">
              <div className="bg-amber-500/10 p-3 rounded-lg text-amber-400">
                <Clock className="w-6 h-6" />
              </div>
              <div>
                <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Avg Scan Duration</p>
                <h3 className="text-2xl font-bold mt-1 text-white">
                  {metrics?.average_scan_duration !== undefined ? `${metrics.average_scan_duration.toFixed(1)}s` : "0.0s"}
                </h3>
              </div>
            </div>
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
            {/* Vulnerability Timeline */}
            <div className="bg-surface border border-border rounded-xl p-6">
              <h3 className="text-md font-bold text-white mb-4">Vulnerability Detection Trends</h3>
              <div className="h-64">
                {metrics?.vulnerability_trends.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={metrics.vulnerability_trends}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="date" stroke="#71717a" fontSize={11} />
                      <YAxis stroke="#71717a" fontSize={11} />
                      <Tooltip contentStyle={{ backgroundColor: "#18181b", border: "1px solid #27272a" }} />
                      <Line type="monotone" dataKey="count" stroke="#3b82f6" strokeWidth={2.5} activeDot={{ r: 6 }} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-muted text-sm">
                    No scanning history over the past 30 days.
                  </div>
                )}
              </div>
            </div>

            {/* Severity Distribution */}
            <div className="bg-surface border border-border rounded-xl p-6">
              <h3 className="text-md font-bold text-white mb-4">Vulnerability Severity Distribution</h3>
              <div className="h-64">
                {metrics?.vulnerabilities_count > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={sevChartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="name" stroke="#71717a" fontSize={11} />
                      <YAxis stroke="#71717a" fontSize={11} />
                      <Tooltip contentStyle={{ backgroundColor: "#18181b", border: "1px solid #27272a" }} />
                      <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                        {sevChartData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={SEV_COLORS[entry.name] || "#3b82f6"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-muted text-sm">
                    No vulnerabilities detected.
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Second Charts Row (Health & Security Trends) */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
            {/* Repository Health Trends */}
            <div className="bg-surface border border-border rounded-xl p-6">
              <h3 className="text-md font-bold text-white mb-4">Repository Health Trends</h3>
              <div className="h-64">
                {metrics?.health_history?.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={metrics.health_history}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="date" stroke="#71717a" fontSize={11} />
                      <YAxis stroke="#71717a" fontSize={11} domain={[0, 100]} />
                      <Tooltip contentStyle={{ backgroundColor: "#18181b", border: "1px solid #27272a" }} />
                      <Line type="monotone" dataKey="score" stroke="#10b981" strokeWidth={2.5} activeDot={{ r: 6 }} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-muted text-sm">
                    No health history available yet.
                  </div>
                )}
              </div>
            </div>

            {/* Security Score Trends */}
            <div className="bg-surface border border-border rounded-xl p-6">
              <h3 className="text-md font-bold text-white mb-4">Security Score Trends</h3>
              <div className="h-64">
                {metrics?.security_score_history?.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={metrics.security_score_history}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="date" stroke="#71717a" fontSize={11} />
                      <YAxis stroke="#71717a" fontSize={11} domain={[0, 100]} />
                      <Tooltip contentStyle={{ backgroundColor: "#18181b", border: "1px solid #27272a" }} />
                      <Line type="monotone" dataKey="score" stroke="#ef4444" strokeWidth={2.5} activeDot={{ r: 6 }} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-muted text-sm">
                    No security score history available yet.
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Third Charts Row (Token Consumption & Model Usage) */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-10">
            {/* Token Consumption */}
            <div className="bg-surface border border-border rounded-xl p-6">
              <h3 className="text-md font-bold text-white mb-4">LLM Token Consumption</h3>
              <div className="h-64">
                {metrics?.token_consumption && Object.keys(metrics.token_consumption).length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={[
                        {
                          name: "Tokens",
                          Prompt: metrics.token_consumption.prompt_tokens || 0,
                          Completion: metrics.token_consumption.completion_tokens || 0,
                        }
                      ]}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="name" stroke="#71717a" fontSize={11} />
                      <YAxis stroke="#71717a" fontSize={11} />
                      <Tooltip contentStyle={{ backgroundColor: "#18181b", border: "1px solid #27272a" }} />
                      <Bar dataKey="Prompt" fill="#3b82f6" stackId="a" />
                      <Bar dataKey="Completion" fill="#f43f5e" stackId="a" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-muted text-sm">
                    No token consumption data available.
                  </div>
                )}
              </div>
            </div>

            {/* AI Model Usage Breakdown */}
            <div className="bg-surface border border-border rounded-xl p-6">
              <h3 className="text-md font-bold text-white mb-4">AI Model Usage Breakdown</h3>
              <div className="h-64">
                {metrics?.model_usage && Object.keys(metrics.model_usage).length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={Object.entries(metrics.model_usage).map(([name, count]) => ({ name, count }))}
                      layout="vertical"
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis type="number" stroke="#71717a" fontSize={11} />
                      <YAxis dataKey="name" type="category" stroke="#71717a" fontSize={10} width={90} />
                      <Tooltip contentStyle={{ backgroundColor: "#18181b", border: "1px solid #27272a" }} />
                      <Bar dataKey="count" fill="#a855f7" radius={[0, 4, 4, 0]} barSize={20} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-muted text-sm">
                    No AI model usage data recorded.
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Scan Comparison Widget */}
          <div className="bg-surface border border-border rounded-xl p-6 mb-8 font-sans">
            <div className="flex flex-col md:flex-row md:justify-between md:items-center mb-4 gap-2">
              <div className="flex items-center gap-2">
                <h3 className="text-md font-bold text-white">Scan Comparison</h3>
                {comparison && (
                  <span className={`px-2.5 py-0.5 text-[10px] font-extrabold uppercase rounded-full border ${
                    comparison.status === "Improved" ? "bg-accent-green/10 text-accent-green border-accent-green/20" :
                    comparison.status === "Regressed" ? "bg-accent-red/10 text-accent-red border-accent-red/20 animate-pulse" :
                    "bg-zinc-800 text-zinc-400 border-zinc-700"
                  }`}>
                    {comparison.status}
                  </span>
                )}
              </div>
              <p className="text-xs text-muted">Compare two historical scans of a repository to verify security remediation and code quality improvements.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
              <div>
                <label className="block text-[10px] uppercase font-bold text-zinc-400 mb-1.5">1. Select Repository</label>
                <select
                  value={selectedRepoId}
                  onChange={(e) => setSelectedRepoId(e.target.value)}
                  className="w-full bg-zinc-900 border border-border rounded-lg text-white text-xs px-3 py-2.5 focus:outline-none focus:border-accent-blue"
                >
                  <option value="">-- Choose Repository --</option>
                  {repositories.map(repo => (
                    <option key={repo.id} value={repo.id}>{repo.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-[10px] uppercase font-bold text-zinc-400 mb-1.5">2. Scan A (Before)</label>
                <select
                  value={scanA}
                  onChange={(e) => setScanA(e.target.value)}
                  disabled={repoScans.length < 2}
                  className="w-full bg-zinc-900 border border-border rounded-lg text-white text-xs px-3 py-2.5 focus:outline-none focus:border-accent-blue disabled:opacity-40"
                >
                  <option value="">-- Select Scan A --</option>
                  {repoScans.map(an => (
                    <option key={an.id} value={an.id}>
                      {new Date(an.timestamp).toLocaleDateString()} (Risk: {an.risk_score})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-[10px] uppercase font-bold text-zinc-400 mb-1.5">3. Scan B (After)</label>
                <select
                  value={scanB}
                  onChange={(e) => setScanB(e.target.value)}
                  disabled={repoScans.length < 2}
                  className="w-full bg-zinc-900 border border-border rounded-lg text-white text-xs px-3 py-2.5 focus:outline-none focus:border-accent-blue disabled:opacity-40"
                >
                  <option value="">-- Select Scan B --</option>
                  {repoScans.map(an => (
                    <option key={an.id} value={an.id}>
                      {new Date(an.timestamp).toLocaleDateString()} (Risk: {an.risk_score})
                    </option>
                  ))}
                </select>
              </div>

              <button
                onClick={handleCompare}
                disabled={comparing || !scanA || !scanB}
                className="w-full bg-accent-blue hover:bg-blue-600 active:bg-blue-700 disabled:opacity-50 text-white font-bold text-xs py-3 rounded-lg transition-colors flex items-center justify-center gap-1.5"
              >
                {comparing ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Comparing...
                  </>
                ) : (
                  "Compare Scans"
                )}
              </button>
            </div>

            {selectedRepoId && repoScans.length < 2 && (
              <p className="text-[11px] text-accent-orange font-semibold mt-3">
                This repository has {repoScans.length} completed scan(s). You need at least 2 completed scans to run a comparison.
              </p>
            )}

            {compareError && (
              <div className="mt-4 bg-red-500/10 border border-red-500/20 text-red-400 p-3 rounded-lg text-xs font-semibold">
                {compareError}
              </div>
            )}

            {comparison && (
              <div className="space-y-6 mt-6 animate-in fade-in slide-in-from-top-2 duration-300">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="bg-background border border-border p-4 rounded-xl">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider block">Security Findings</span>
                    <div className="flex items-baseline gap-2 mt-1.5">
                      <span className="text-lg font-bold text-white">{comparison.security.a} â†’ {comparison.security.b}</span>
                      <span className={`text-xs font-extrabold ${
                        comparison.security.improvement_pct >= 0 ? "text-accent-green" : "text-accent-red"
                      }`}>
                        {comparison.security.improvement_pct >= 0 ? `+${comparison.security.improvement_pct}%` : `${comparison.security.improvement_pct}%`}
                      </span>
                    </div>
                    <span className="text-[9px] text-zinc-500 block mt-0.5">Improvement</span>
                  </div>

                  <div className="bg-background border border-border p-4 rounded-xl">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider block">Code Smells</span>
                    <div className="flex items-baseline gap-2 mt-1.5">
                      <span className="text-lg font-bold text-white">{comparison.code_smells.a} â†’ {comparison.code_smells.b}</span>
                      <span className={`text-xs font-extrabold ${
                        comparison.code_smells.improvement_pct >= 0 ? "text-accent-green" : "text-accent-red"
                      }`}>
                        {comparison.code_smells.improvement_pct >= 0 ? `+${comparison.code_smells.improvement_pct}%` : `${comparison.code_smells.improvement_pct}%`}
                      </span>
                    </div>
                    <span className="text-[9px] text-zinc-500 block mt-0.5">Improvement</span>
                  </div>

                  <div className="bg-background border border-border p-4 rounded-xl">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider block">Tests Generated</span>
                    <div className="flex items-baseline gap-2 mt-1.5">
                      <span className="text-lg font-bold text-white">{comparison.tests.a} â†’ {comparison.tests.b}</span>
                      <span className={`text-xs font-extrabold ${
                        comparison.tests.improvement_pct >= 0 ? "text-accent-green" : "text-accent-red"
                      }`}>
                        {comparison.tests.improvement_pct >= 0 ? `+${comparison.tests.improvement_pct}%` : `${comparison.tests.improvement_pct}%`}
                      </span>
                    </div>
                    <span className="text-[9px] text-zinc-500 block mt-0.5">Improvement</span>
                  </div>

                  <div className="bg-background border border-border p-4 rounded-xl">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider block">Risk Score</span>
                    <div className="flex items-baseline gap-2 mt-1.5">
                      <span className="text-lg font-bold text-white">{comparison.risk_score.a} â†’ {comparison.risk_score.b}</span>
                      <span className={`text-xs font-extrabold ${
                        comparison.risk_score.improvement_pct >= 0 ? "text-accent-green" : "text-accent-red"
                      }`}>
                        {comparison.risk_score.improvement_pct >= 0 ? `+${comparison.risk_score.improvement_pct}%` : `${comparison.risk_score.improvement_pct}%`}
                      </span>
                    </div>
                    <span className="text-[9px] text-zinc-500 block mt-0.5 font-semibold">Improvement</span>
                  </div>
                </div>

                {/* Recharts Comparison Trend */}
                <div className="bg-background/40 border border-border/80 rounded-xl p-5">
                  <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-4">Comparison Matrix Trend</h4>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={[
                        {
                          name: "Risk Score",
                          "Scan A (Before)": comparison.risk_score.a,
                          "Scan B (After)": comparison.risk_score.b
                        },
                        {
                          name: "Security Findings",
                          "Scan A (Before)": comparison.security.a,
                          "Scan B (After)": comparison.security.b
                        },
                        {
                          name: "Code Smells",
                          "Scan A (Before)": comparison.code_smells.a,
                          "Scan B (After)": comparison.code_smells.b
                        }
                      ]}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                        <XAxis dataKey="name" stroke="#71717a" fontSize={11} />
                        <YAxis stroke="#71717a" fontSize={11} />
                        <Tooltip contentStyle={{ backgroundColor: "#18181b", border: "1px solid #27272a" }} />
                        <Bar dataKey="Scan A (Before)" fill="#ef4444" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="Scan B (After)" fill="#10b981" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Detailed Findings list */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 border-t border-border/40 pt-5">
                  {/* Fixed Findings */}
                  <div>
                    <h4 className="text-xs font-bold text-accent-green mb-3 flex items-center gap-1.5 uppercase tracking-wider">
                      <span className="w-2 h-2 rounded-full bg-accent-green" />
                      Fixed Findings ({comparison.fixed.length})
                    </h4>
                    <div className="space-y-2.5 max-h-[250px] overflow-y-auto pr-1">
                      {comparison.fixed.length > 0 ? comparison.fixed.map((f: any) => (
                        <div key={f.id} className="bg-zinc-900/60 border border-zinc-800 p-3 rounded-lg text-xs">
                          <div className="flex justify-between items-start gap-2">
                            <span className="font-semibold text-white block truncate">{f.issue}</span>
                            <span className="text-[9px] bg-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded font-mono uppercase">{f.type}</span>
                          </div>
                          <p className="text-[10px] text-zinc-500 mt-1 font-mono">{f.file}:{f.line}</p>
                        </div>
                      )) : (
                        <p className="text-[11px] text-zinc-500 italic">No findings fixed in Scan B.</p>
                      )}
                    </div>
                  </div>

                  {/* New Findings */}
                  <div>
                    <h4 className="text-xs font-bold text-accent-red mb-3 flex items-center gap-1.5 uppercase tracking-wider">
                      <span className="w-2 h-2 rounded-full bg-accent-red animate-pulse" />
                      New Findings ({comparison.new.length})
                    </h4>
                    <div className="space-y-2.5 max-h-[250px] overflow-y-auto pr-1">
                      {comparison.new.length > 0 ? comparison.new.map((f: any) => (
                        <div key={f.id} className="bg-zinc-900/60 border border-zinc-800 p-3 rounded-lg text-xs">
                          <div className="flex justify-between items-start gap-2">
                            <span className="font-semibold text-white block truncate">{f.issue}</span>
                            <span className="text-[9px] bg-red-500/10 text-red-400 px-1.5 py-0.5 rounded font-mono uppercase">{f.type}</span>
                          </div>
                          <p className="text-[10px] text-zinc-500 mt-1 font-mono">{f.file}:{f.line}</p>
                        </div>
                      )) : (
                        <p className="text-[11px] text-zinc-500 italic">No new findings in Scan B.</p>
                      )}
                    </div>
                  </div>

                  {/* Remaining Findings */}
                  <div>
                    <h4 className="text-xs font-bold text-accent-orange mb-3 flex items-center gap-1.5 uppercase tracking-wider">
                      <span className="w-2 h-2 rounded-full bg-accent-orange" />
                      Remaining Findings ({comparison.remaining.length})
                    </h4>
                    <div className="space-y-2.5 max-h-[250px] overflow-y-auto pr-1">
                      {comparison.remaining.length > 0 ? comparison.remaining.map((f: any) => (
                        <div key={f.id} className="bg-zinc-900/60 border border-zinc-800 p-3 rounded-lg text-xs">
                          <div className="flex justify-between items-start gap-2">
                            <span className="font-semibold text-white block truncate">{f.issue}</span>
                            <span className="text-[9px] bg-orange-500/10 text-orange-400 px-1.5 py-0.5 rounded font-mono uppercase">{f.type}</span>
                          </div>
                          <p className="text-[10px] text-zinc-500 mt-1 font-mono">{f.file}:{f.line}</p>
                        </div>
                      )) : (
                        <p className="text-[11px] text-zinc-500 italic">No remaining findings.</p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Connected Repositories Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Repos Cards List */}
            <div className="lg:col-span-2 space-y-6">
              <div className="flex justify-between items-center">
                <h3 className="text-lg font-bold text-white">Connected Repositories</h3>
                {/* Search */}
                <div className="relative w-64">
                  <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-muted">
                    <Search className="w-4 h-4" />
                  </span>
                  <input
                    type="text"
                    placeholder="Search connected repos..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-9 pr-4 py-1.5 bg-surface border border-border rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue text-xs"
                  />
                </div>
              </div>

              {filteredRepos.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {filteredRepos.map((repo) => (
                    <div
                      key={repo.id}
                      onClick={() => onSelectRepoId(repo.id)}
                      className="bg-surface border border-border hover:border-zinc-500 rounded-xl p-5 cursor-pointer transition-all duration-150 flex flex-col justify-between"
                    >
                      <div>
                        <div className="flex items-center gap-2 mb-2">
                          <BookOpen className="w-4 h-4 text-accent-blue" />
                          <h4 className="font-bold text-sm text-white hover:underline truncate">{repo.name}</h4>
                        </div>
                        <p className="text-xs text-muted line-clamp-2 mb-4">{repo.description || "No description provided."}</p>
                      </div>

                      <div className="flex justify-between items-center border-t border-border/50 pt-3 text-[10px] text-zinc-400">
                        <span className="bg-zinc-800 px-2 py-0.5 rounded-full text-zinc-300 font-semibold uppercase">
                          {repo.default_branch}
                        </span>
                        <div className="flex items-center gap-3">
                          <span>â­ {repo.stars}</span>
                          <span>ðŸ´ {repo.forks}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="bg-surface border border-border border-dashed rounded-xl p-8 text-center text-muted text-sm">
                  No repositories matching search connected yet. Get started by clicking "Connect Repository" at the top.
                </div>
              )}
            </div>

            {/* Sidebar Column */}
            <div className="space-y-6">
              {/* Leaderboard for Top Risky Repositories */}
              <div className="bg-surface border border-border rounded-xl p-6">
                <h3 className="text-sm font-bold text-white mb-4 uppercase tracking-wider">Risky Repositories Leaderboard</h3>
                {metrics?.top_risky_repositories?.length > 0 ? (
                  <div className="space-y-4">
                    {metrics.top_risky_repositories.map((repo: any, idx: number) => {
                      let badgeColor = "bg-green-500/10 text-accent-green border-green-500/20";
                      if (repo.risk_score >= 70) badgeColor = "bg-red-500/10 text-accent-red border-red-500/20";
                      else if (repo.risk_score >= 35) badgeColor = "bg-orange-500/10 text-accent-orange border-orange-500/20";
                      
                      const repoId = repo.repo_id || repo.id;
                      return (
                        <div key={repoId} className="flex justify-between items-center text-xs border-b border-border/50 pb-3 last:border-0 last:pb-0">
                          <div className="flex items-center gap-3 min-w-0">
                            <span className="font-extrabold text-sm text-zinc-500 w-4">{idx + 1}</span>
                            <div className="min-w-0">
                              <p className="text-white font-semibold hover:underline cursor-pointer truncate" onClick={() => onSelectRepoId(repoId)}>
                                {repo.name}
                              </p>
                              <p className="text-zinc-500 text-[10px] mt-0.5">Vulnerabilities: {repo.vulnerabilities_count || 0}</p>
                            </div>
                          </div>
                          <span className={`px-2 py-0.5 border rounded-full text-[10px] font-bold ${badgeColor}`}>
                            Risk: {repo.risk_score}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-center text-muted text-xs py-4 italic">
                    No repositories scanned.
                  </div>
                )}
              </div>

              {/* Recent Activity Panel */}
              <div className="bg-surface border border-border rounded-xl p-6">
                <h3 className="text-sm font-bold text-white mb-4 uppercase tracking-wider">Recent Activity Logs</h3>
                {metrics?.recent_activity?.length > 0 ? (
                  <div className="space-y-4">
                    {metrics.recent_activity.map((act: any, idx: number) => (
                      <div key={idx} className="flex gap-3 text-xs border-b border-border/50 pb-3 last:border-0 last:pb-0">
                        <div className={`w-2 h-2 rounded-full mt-1.5 ${
                          act.status === "completed" ? "bg-accent-green" : act.status === "failed" ? "bg-accent-red" : "bg-accent-orange animate-pulse"
                        }`} />
                        <div className="flex-1 min-w-0">
                          <p className="text-white font-medium truncate">{act.repo}</p>
                          <p className="text-muted mt-0.5">Scan status: <span className="font-semibold">{act.status}</span></p>
                          <span className="text-[10px] text-zinc-500 block mt-1">{act.timestamp}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center text-muted text-xs py-4 italic">
                    No recent scan activity found.
                  </div>
                )}
              </div>

              {/* Restoration Center Panel */}
              <div className="bg-surface border border-border rounded-xl p-6">
                <h3 className="text-sm font-bold text-white mb-2 uppercase tracking-wider">Restoration Center</h3>
                <p className="text-[11px] text-muted mb-4">Soft-deleted scan histories can be recovered here.</p>
                
                {loadingDeleted ? (
                  <div className="flex items-center justify-center py-4">
                    <Loader2 className="w-5 h-5 animate-spin text-accent-blue" />
                  </div>
                ) : deletedScans.length > 0 ? (
                  <div className="space-y-4 max-h-[250px] overflow-y-auto pr-1">
                    {deletedScans.map((scan: any) => (
                      <div key={scan.id} className="flex justify-between items-center text-xs border-b border-border/50 pb-3 last:border-0 last:pb-0">
                        <div className="min-w-0 pr-2">
                          <p className="text-white font-medium truncate">Scan ID: {scan.id.slice(0, 8)}</p>
                          <p className="text-zinc-500 text-[10px] mt-0.5">{new Date(scan.timestamp).toLocaleString()}</p>
                        </div>
                        <button
                          onClick={() => handleRestore(scan.id)}
                          className="px-2.5 py-1 border border-accent-blue hover:bg-accent-blue/10 text-accent-blue rounded text-[10px] font-bold uppercase transition-all"
                        >
                          Restore
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center text-muted text-xs py-4 italic">
                    No soft-deleted scans found.
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}

      {/* Connect Repo Modal */}
      {showConnectModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-surface border border-border w-full max-w-md rounded-xl p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-2">Connect New GitHub Repository</h3>
            <p className="text-xs text-muted mb-4">Input the target public or private repository URL. Private repositories require configured GitHub PAT settings.</p>
            
            {connectError && (
              <div className="mb-4 bg-red-500/10 border border-red-500/20 text-red-400 p-2.5 rounded-lg text-xs">
                {connectError}
              </div>
            )}

            <form onSubmit={handleConnect} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Repository URL / Slug</label>
                <input
                  type="text"
                  required
                  placeholder="https://github.com/owner/repository"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  className="w-full px-3 py-2 bg-background border border-border rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue text-sm"
                />
              </div>
              
              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowConnectModal(false)}
                  className="px-4 py-2 border border-border text-xs rounded-lg text-zinc-400 hover:bg-zinc-800 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={connecting}
                  className="px-4 py-2 bg-accent-blue hover:bg-blue-600 disabled:opacity-50 text-xs font-semibold text-white rounded-lg flex items-center gap-2"
                >
                  {connecting ? (
                    <>
                      <Loader2 className="w-3 h-3 animate-spin" />
                      Connecting...
                    </>
                  ) : (
                    "Connect"
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

