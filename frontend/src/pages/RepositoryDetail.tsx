import React, { useEffect, useRef, useState } from "react";
import axios from "../lib/api";
import { useRepositoryStore } from "../store/repositoryStore";
import { useAuthStore } from "../store/authStore";
import type { PullRequest } from "../store/repositoryStore";
import { formatDateTime } from "../lib/datetime";
import { toast } from "../components/Toast";
import { Pagination, usePagination } from "../components/Pagination";
import { useAnalysisStore } from "../store/analysisStore";
import {
  ArrowLeft, GitPullRequest, BookOpen,
  Play, Loader2, Download, Clock, Check, RefreshCw, CheckCircle2,
  Folder, File, ChevronRight, ChevronDown, Save, X, Code,
  AlertTriangle, ShieldCheck, Sparkles, BarChart3
} from "lucide-react";
import Editor from "@monaco-editor/react";
import { Markdown } from "../components/Markdown";
import { useQuery } from "@tanstack/react-query";
import { HealthTrendPanel } from "../components/insights/HealthTrendPanel";
import { DependenciesPanel } from "../components/insights/DependenciesPanel";
import { DuplicatesPanel } from "../components/insights/DuplicatesPanel";
import { TechnicalDebtPanel } from "../components/insights/TechnicalDebtPanel";
import { ArchitecturePanel } from "../components/insights/ArchitecturePanel";
import { ComplexityPanel } from "../components/insights/ComplexityPanel";
import { PRReviewPanel } from "../components/insights/PRReviewPanel";
import { CommitAnalysisPanel } from "../components/insights/CommitAnalysisPanel";
import { RepositoryOverviewPanel } from "../components/insights/RepositoryOverviewPanel";
import { InsightsOverviewPanel } from "../components/insights/InsightsOverviewPanel";
import { ScanSummaryModal } from "../components/insights/ScanSummaryModal";
import { FindingCard } from "../components/FindingCard";

interface RepositoryDetailProps {
  onBack: () => void;
  onSelectPr: (pr: PullRequest) => void;
}

interface TreeNode {
  name: string;
  type: "file" | "dir";
  path: string;
  children?: TreeNode[];
}

const VALID_TAB_IDS = ["overview", "explorer", "prs", "security", "quality", "tests", "insights", "deep"] as const;
type RepoTabId = (typeof VALID_TAB_IDS)[number];

/** Read the initial tab from the URL hash (#repo/<id>/overview) so refresh
 *  and deep links restore the exact tab the user was viewing. */
function readTabFromHash(repoId: string | undefined): RepoTabId {
  if (!repoId) return "overview";
  const hash = window.location.hash;
  const prefix = `#/repo/${repoId}/`;
  if (hash.startsWith(prefix)) {
    const tab = hash.slice(prefix.length).split("?")[0] as RepoTabId;
    if ((VALID_TAB_IDS as readonly string[]).includes(tab)) return tab;
  }
  return "overview";
}

const FileTreeItem: React.FC<{
  node: TreeNode;
  onSelectFile: (path: string) => void;
  selectedPath: string | null;
}> = ({ node, onSelectFile, selectedPath }) => {
  const [expanded, setExpanded] = useState(false);
  
  if (node.type === "file") {
    const isSelected = selectedPath === node.path;
    return (
      <button
        onClick={() => onSelectFile(node.path)}
        className={`w-full flex items-center gap-2 px-2 py-1 text-[11px] text-left rounded-md transition-colors truncate ${
          isSelected ? "bg-accent-blue/15 text-accent-blue font-bold border-l-2 border-accent-blue" : "text-zinc-700 hover:text-zinc-950 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:text-white dark:hover:bg-zinc-800"
        }`}
      >
        <File className="w-3.5 h-3.5 shrink-0 text-zinc-500 dark:text-zinc-400" />
        <span className="truncate">{node.name}</span>
      </button>
    );
  }
  
  return (
    <div className="space-y-0.5">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-1.5 px-2 py-1 text-[11px] text-left text-zinc-800 font-semibold hover:text-zinc-950 hover:bg-zinc-100 rounded-md transition-colors dark:text-zinc-200 dark:hover:text-white dark:hover:bg-zinc-800"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 shrink-0 text-zinc-500 dark:text-zinc-400" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 shrink-0 text-zinc-500 dark:text-zinc-400" />
        )}
        <Folder className="w-3.5 h-3.5 shrink-0 text-amber-500/80 fill-amber-500/10" />
        <span className="truncate font-medium">{node.name}</span>
      </button>
      
      {expanded && node.children && (
        <div className="pl-3.5 border-l border-border ml-2.5 space-y-0.5">
          {node.children.map((child, idx) => (
            <FileTreeItem
              key={idx}
              node={child}
              onSelectFile={onSelectFile}
              selectedPath={selectedPath}
            />
          ))}
        </div>
      )}
    </div>
  );
};

const DEEP_INSIGHT_SECTIONS = [
  { id: "health", name: "Health Trend", component: HealthTrendPanel },
  { id: "deps", name: "Dependencies", component: DependenciesPanel },
  { id: "duplicates", name: "Duplicates", component: DuplicatesPanel },
  { id: "complexity", name: "Complexity", component: ComplexityPanel },
  { id: "architecture", name: "Architecture", component: ArchitecturePanel },
  { id: "debt", name: "Technical Debt", component: TechnicalDebtPanel },
  { id: "pr", name: "Pull Requests", component: PRReviewPanel },
  { id: "commits", name: "Commits", component: CommitAnalysisPanel },
] as const;

/** DEEP INSIGHTS — the technical level. Detailed analysis panels organized
 *  by section; lazy-loaded when the user opens this tab. */
const DeepInsightsTab: React.FC<{ repoId: string; initialSection?: string }> = ({ repoId, initialSection }) => {
  const [section, setSection] = useState<string>(initialSection || "health");
  const ActiveSection = DEEP_INSIGHT_SECTIONS.find((s) => s.id === section)?.component ?? HealthTrendPanel;

  return (
    <div className="space-y-5">
      <div className="flex gap-2 flex-wrap glass rounded-2xl p-1.5">
        {DEEP_INSIGHT_SECTIONS.map((s) => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            aria-pressed={section === s.id}
            className={`text-[11px] font-bold px-3.5 py-2 rounded-xl transition-all ${
              section === s.id
                ? "bg-accent-blue text-white shadow"
                : "text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:text-white dark:hover:bg-zinc-800"
            }`}
          >
            {s.name}
          </button>
        ))}
      </div>
      <ActiveSection repoId={repoId} />
    </div>
  );
};

/** Empty-state card used when a scan has not been run/completed yet. */
const ScanRequiredEmptyState: React.FC<{ icon?: React.ReactNode; message?: string }> = ({
  icon,
  message,
}) => (
  <div className="text-center py-10 px-6 bg-background/50 border border-dashed border-border rounded-lg dark:bg-zinc-900/40">
    <div className="w-12 h-12 rounded-2xl bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center mx-auto mb-4">
      {icon || <Sparkles className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />}
    </div>
    <p className="text-sm font-bold text-zinc-800 dark:text-zinc-100">
      {message || "Run a repository scan to generate insights."}
    </p>
    <p className="text-xs text-zinc-600 dark:text-zinc-400 mt-1">
      Results shown here come from real scans — no sample data is displayed.
    </p>
  </div>
);

export const RepositoryDetail: React.FC<RepositoryDetailProps> = ({ onBack, onSelectPr }) => {
  const { activeRepo, prs } = useRepositoryStore();
  const { user } = useAuthStore();
  const hasLlmKey = user ? (
    user.has_groq_api_key || user.has_openai_api_key ||
    user.has_claude_api_key || user.has_gemini_api_key || user.has_openrouter_api_key
  ) : false;
  const {
    analyses, activeAnalysis, securityFindings, codeSmells, testSuggestions,
    progress, progressDetailed, triggerAnalysis, error: analysisError,
    fetchAnalysisDetails, resetProgress, deleteAnalysis, deleteAllHistory
  } = useAnalysisStore();

  const showProgress = progress > 0 && progress < 100;
  const scanFailed = !!activeAnalysis && activeAnalysis.status === "failed";

  const [activeTab, setActiveTab] = useState<RepoTabId>(() => readTabFromHash(activeRepo?.id));

  // Keep the URL hash in sync so refresh/deep-links restore the active tab.
  useEffect(() => {
    if (!activeRepo) return;
    const expected = `#/repo/${activeRepo.id}/${activeTab}`;
    if (window.location.hash !== expected) {
      window.history.replaceState(null, "", expected);
    }
  }, [activeTab, activeRepo?.id]);

  // React to browser back/forward navigation between tabs
  useEffect(() => {
    const onHashChange = () => {
      const tab = readTabFromHash(activeRepo?.id);
      setActiveTab(tab);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [activeRepo?.id]);

  // Explorer States
  const [explorerTree, setExplorerTree] = useState<TreeNode[]>([]);
  // React Query definitions for caching and rate-limiting avoidance
  // staleTime=300s prevents repeated requests within 5 minutes (avoids 429 spam)
  const { data: prsData } = useQuery({
    queryKey: ["prs", activeRepo?.id],
    queryFn: async () => {
      if (!activeRepo) return [];
      const res = await axios.get(`/repositories/${activeRepo.id}/prs`);
      return res.data;
    },
    enabled: !!activeRepo,
    staleTime: 300_000,   // 5 minutes
    gcTime: 600_000,      // 10 minutes
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const { data: analysesData } = useQuery({
    queryKey: ["analyses", activeRepo?.id],
    queryFn: async () => {
      if (!activeRepo) return [];
      const res = await axios.get(`/analysis/repo/${activeRepo.id}`);
      return res.data;
    },
    enabled: !!activeRepo,
    staleTime: 300_000,
    gcTime: 600_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const { data: explorerData, isLoading: explorerQueryLoading, refetch: refetchExplorerTree } = useQuery({
    queryKey: ["explorerTree", activeRepo?.id],
    queryFn: async () => {
      if (!activeRepo) return [];
      const res = await axios.get(`/repositories/${activeRepo.id}/explorer`);
      return res.data;
    },
    enabled: activeTab === "explorer" && !!activeRepo,
    staleTime: 300_000,
    gcTime: 600_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const explorerLoading = explorerQueryLoading;

  useEffect(() => {
    if (prsData) {
      useRepositoryStore.setState({ prs: prsData });
    }
  }, [prsData]);

  useEffect(() => {
    if (analysesData) {
      useAnalysisStore.setState({ analyses: analysesData });
    }
  }, [analysesData]);

  useEffect(() => {
    if (explorerData) {
      setExplorerTree(explorerData);
    }
  }, [explorerData]);

  // Auto-select the most recent completed scan when the repo has one and
  // nothing is selected yet (e.g. first visit / after refresh).
  useEffect(() => {
    if (!activeAnalysis && analyses.length > 0) {
      const latestCompleted = analyses.find((a: any) => a.status === "completed");
      if (latestCompleted) {
        fetchAnalysisDetails(latestCompleted.id);
      }
    }
  }, [analyses, activeAnalysis]);

  // ── Scan summary: shown once when a scan transitions to completed ──
  // Tracks the previous progress so the summary appears exactly once,
  // only for scans the user actually triggered in this session.
  const [showScanSummary, setShowScanSummary] = useState(false);
  const [summaryAnalysisId, setSummaryAnalysisId] = useState<string | null>(null);
  const [deepSection, setDeepSection] = useState<string>("health");
  const [showAlreadyAnalyzed, setShowAlreadyAnalyzed] = useState(false);
  const [scanIdentity, setScanIdentity] = useState<any>(null);
  const prevProgressRef = useRef<number>(0);

  // Pagination for large finding lists (10 per page; filters/sorting live in
  // the backend-ordered arrays so page changes preserve them automatically).
  const SECURITY_PAGE_SIZE = 10;
  const {
    page: securityPage,
    setPage: setSecurityPage,
    pageItems: securityPageItems,
  } = usePagination(securityFindings || [], SECURITY_PAGE_SIZE);
  const {
    page: qualityPage,
    setPage: setQualityPage,
    pageItems: qualityPageItems,
  } = usePagination(codeSmells || [], SECURITY_PAGE_SIZE);

  useEffect(() => {
    const prev = prevProgressRef.current;
    prevProgressRef.current = progress;

    // Transition: was in-progress (<100), now completed → show summary
    if (
      prev > 0 && prev < 100 &&
      activeAnalysis?.status === "completed" &&
      (progress >= 100 || activeAnalysis.progress >= 100)
    ) {
      setSummaryAnalysisId(activeAnalysis.id);
      setShowScanSummary(true);
      toast.success("Scan completed successfully.");
    }
  }, [progress, activeAnalysis?.status, activeAnalysis?.progress, activeAnalysis?.id]);

  const [openFilePath, setOpenFilePath] = useState<string | null>(null);
  const [openFileContent, setOpenFileContent] = useState("");
  // [REMOVED] editorOriginalContent, editorUnsaved — read-only explorer
  const [monacoEditor, setMonacoEditor] = useState<any>(null);
  const [monacoInstance, setMonacoInstance] = useState<any>(null);
  const [decorations, setDecorations] = useState<string[]>([]);
  // [REMOVED] showCommitModal, commitMsg, saveLoading — commit modal removed
  // This project does not modify repositories

  // Explain states
  const [explainFinding, setExplainFinding] = useState<{ id: string; type: "security" | "code_smell" } | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [explainResult, setExplainResult] = useState<string | null>(null);

  // Fetch Tree
  const fetchExplorerTree = async () => {
    refetchExplorerTree();
  };

  // Fetch File Content
  const handleSelectFile = async (path: string): Promise<void> => {
    if (!activeRepo) return;
    
    // Clear residual Monaco decorations
    if (monacoEditor && decorations.length > 0) {
      monacoEditor.deltaDecorations(decorations, []);
      setDecorations([]);
    }
    
    setOpenFilePath(path);
    setOpenFileContent("");
    
    try {
      const res = await axios.get(`/repositories/${activeRepo.id}/files`, {
        params: { path }
      });
      setOpenFileContent(res.data.content);
    } catch (err: any) {
      toast.error(err.response?.data?.detail || "Failed to download file content from GitHub.");
    }
  };

  // Jump to a line (or line range) in the Monaco editor and highlight it.
  const handleJumpToLine = async (filePath: string, line: number, endLine?: number | null) => {
    setActiveTab("explorer");
    await handleSelectFile(filePath);
    // Wait for content load
    setTimeout(() => {
      if (monacoEditor) {
        const start = Math.max(1, line);
        const end = endLine && endLine >= start ? endLine : start;
        monacoEditor.revealLinesInCenter(start, end);
        monacoEditor.setPosition({ lineNumber: start, column: 1 });
        monacoEditor.focus();
        
        // Highlight the exact line range with decorations if monacoInstance is available
        if (monacoInstance) {
          const newDecs = monacoEditor.deltaDecorations(decorations, [
            {
              range: new monacoInstance.Range(start, 1, end, 1),
              options: {
                isWholeLine: true,
                className: 'bg-red-500/10 border-l-2 border-red-500',
                glyphMarginClassName: 'bg-red-500'
              }
            }
          ]);
          setDecorations(newDecs);
        }
      }
    }, 850);
  };

  // Fetch Explain Finding
  const handleExplainFinding = async (findingId: string, issueType: "security" | "code_smell") => {
    setExplainLoading(true);
    setExplainResult(null);
    setExplainFinding({ id: findingId, type: issueType });
    try {
      const res = await axios.post("/analysis/explain", {
        finding_id: findingId,
        issue_type: issueType
      });
      setExplainResult(res.data.explanation);
    } catch (err: any) {
      setExplainResult(`### Error\nFailed to generate AI explanation: ${err.response?.data?.detail || err.message}`);
    } finally {
      setExplainLoading(false);
    }
  };

  const handleEditorDidMount = (editor: any, monaco: any) => {
    setMonacoEditor(editor);
    setMonacoInstance(monaco);
  };

  useEffect(() => {
    if (activeTab === "explorer" && explorerTree.length === 0) {
      fetchExplorerTree();
    }
  }, [activeTab]);
  const { deleteRepository, disconnectRepository } = useRepositoryStore();
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [showDeleteRepoModal, setShowDeleteRepoModal] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  // Stopwatch state
  const [elapsedTime, setElapsedTime] = useState(0);

  useEffect(() => {
    let intervalId: any = null;
    if (showProgress) {
      setElapsedTime(0);
      intervalId = setInterval(() => {
        setElapsedTime(prev => prev + 1);
      }, 1000);
    } else {
      setElapsedTime(0);
    }
    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [showProgress]);

  const getEstimatedRemaining = () => {
    if (progress <= 0 || progress >= 100) return "Calculating...";
    const totalEst = (elapsedTime / progress) * 100;
    const remaining = Math.round(totalEst - elapsedTime);
    if (remaining <= 0) return "Almost done...";
    
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  };

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  };

  const handleDisconnectRepo = async () => {
    if (!activeRepo) return;
    setActionLoading(true);
    try {
      await disconnectRepository(activeRepo.id);
      onBack();
    } catch (err: any) {
      toast.error(err.message || "Failed to disconnect repository");
    } finally {
      setActionLoading(false);
      setShowDisconnectModal(false);
    }
  };

  const handleDeleteRepo = async () => {
    if (!activeRepo) return;
    setActionLoading(true);
    try {
      await deleteRepository(activeRepo.id);
      onBack();
    } catch (err: any) {
      toast.error(err.message || "Failed to delete repository");
    } finally {
      setActionLoading(false);
      setShowDeleteRepoModal(false);
    }
  };

  const [scanToDelete, setScanToDelete] = useState<string | null>(null);
  const [showDeleteAllModal, setShowDeleteAllModal] = useState(false);

  // Clean up polling/WebSocket on unmount or repo change
  useEffect(() => {
    return () => {
      resetProgress();
    };
  }, [resetProgress, activeRepo?.id]);

  const handleRunAnalysis = async () => {
    if (!activeRepo) return;
    // Scan identity check: if this exact commit was already analyzed, ask the
    // user instead of silently producing a possibly-different-looking rescan.
    try {
      const res = await axios.get(`/repositories/${activeRepo.id}/scan-identity`);
      if (res.data?.already_analyzed) {
        setScanIdentity(res.data);
        setShowAlreadyAnalyzed(true);
        return;
      }
    } catch {
      // Identity check is best-effort; proceed with the scan if unavailable.
    }
    await startScan();
  };

  const startScan = async () => {
    if (!activeRepo) return;
    try {
      resetProgress();
      await triggerAnalysis(activeRepo.id);
      toast.info("Repository scan started. You can watch the progress below.");
    } catch (err: any) {
      // Error state is surfaced via the analysisError banner below —
      // the scanning UI must never remain stuck.
      toast.error(err?.response?.data?.detail || err?.message || "Scan failed. Please try again.");
    }
  };

  const handleDownload = (type: string) => {
    if (!activeAnalysis) return;
    axios.get(`/reports`, {
      params: { analysis_id: activeAnalysis.id }
    }).then(res => {
      const reports = res.data;
      const target = reports.find((r: any) => r.type === type);
      if (target) {
        axios.get(`/reports/${target.id}`, {
          responseType: "blob"
        }).then(response => {
          const contentTypeHeader = response.headers["content-type"];
          const contentType = typeof contentTypeHeader === "string" ? contentTypeHeader : "application/octet-stream";
          const blob = new Blob([response.data], { type: contentType });
          const url = window.URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          let filename = `report_${activeAnalysis.id}.${type.toLowerCase()}`;
          const contentDispositionHeader = response.headers["content-disposition"];
          const contentDisposition = typeof contentDispositionHeader === "string" ? contentDispositionHeader : undefined;
          if (contentDisposition) {
            const match = contentDisposition.match(/filename="?([^"]+)"?/);
            if (match && match[1]) {
              filename = match[1];
            }
          }
          link.setAttribute("download", filename);
          document.body.appendChild(link);
          link.click();
          link.remove();
          window.URL.revokeObjectURL(url);
          toast.success("Report generated successfully.");
        }).catch(() => {
          toast.error(`Failed to download report content for ${type}.`);
        });
      } else {
        toast.error(`${type} report file generation in progress or failed.`);
      }
    }).catch(() => {
      toast.error("Failed to fetch reports index.");
    });
  };

  if (!activeRepo) return null;

  const scanCompleted = activeAnalysis?.status === "completed";

  return (
    <div className="flex-1 p-8 overflow-y-auto max-h-screen">
      {/* Header breadcrumb */}
      <button onClick={onBack} className="flex items-center gap-2 text-zinc-700 hover:text-zinc-950 text-xs font-semibold mb-4 transition-colors dark:text-zinc-300 dark:hover:text-white">
        <ArrowLeft className="w-4 h-4" />
        Back to Repository Selection
      </button>

      {/* Premium Hero Section */}
      <div className="glass-hero p-8 mb-8 relative overflow-hidden">
        <div className="absolute inset-0 bg-card-glow-blue pointer-events-none" />
        <div className="relative z-10">
          <div className="flex justify-between items-start flex-wrap gap-4">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <div className="w-10 h-10 rounded-2xl bg-accent-gradient flex items-center justify-center shadow-glow-blue">
                  <BookOpen className="w-5 h-5 text-white" />
                </div>
                <h1 className="text-3xl font-bold text-zinc-900 dark:text-white">{activeRepo.name}</h1>
              </div>
              <p className="text-sm text-zinc-700 mt-1 max-w-xl font-medium dark:text-zinc-300">{activeRepo.description}</p>
              
              {/* Stats row */}
              <div className="flex flex-wrap items-center gap-4 mt-4 text-xs">
                <span className="glass px-3 py-1.5 rounded-xl text-zinc-500 flex items-center gap-1.5 dark:text-zinc-300">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-green" />
                  {activeRepo.default_branch}
                </span>
                {activeRepo.stars > 0 && (
                  <span className="text-zinc-500 dark:text-zinc-300">⭐ {activeRepo.stars}</span>
                )}
                {scanCompleted && (
                  <>
                    <span className="text-zinc-500 dark:text-zinc-300">Risk: <strong className={activeAnalysis.risk_score > 60 ? 'text-accent-red' : 'text-accent-green'}>{activeAnalysis.risk_score}</strong></span>
                    <span className="text-zinc-500 dark:text-zinc-300">Security: <strong className="text-accent-blue">{securityFindings.length} issues</strong></span>
                  </>
                )}
              </div>
            </div>

            <div className="flex items-center gap-3">
              {/* NEXT → RepoLens project features (Insights) for THIS
                  repository: analysis, security, quality, tests, dependencies,
                  duplicates, complexity, tech debt, architecture, PR review,
                  commits, reports and AI chat — all repository-scoped tabs. */}
              <button
                onClick={() => setActiveTab("insights")}
                className="btn-secondary flex items-center gap-2"
                title="Open project features — Insights, Deep Insights, Reports and more"
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </button>
              <button
                onClick={() => setShowDisconnectModal(true)}
                disabled={showProgress || actionLoading}
                className="btn-secondary"
              >
                Disconnect
              </button>
              <button
                onClick={() => setShowDeleteRepoModal(true)}
                disabled={showProgress || actionLoading}
                className="btn-danger"
              >
                Delete Repo
              </button>
              <button
                onClick={() => {
                  if (!hasLlmKey) {
                    return;
                  }
                  handleRunAnalysis();
                }}
                title={!hasLlmKey ? "Please configure an LLM API key in Settings first before scanning." : "Run a full AI scan on this repository"}
                disabled={showProgress}
                className={`btn-primary flex items-center gap-2 ${!hasLlmKey ? "cursor-not-allowed opacity-70" : ""}`}
              >
                {!hasLlmKey && !showProgress ? (
                  <>
                    <AlertTriangle className="w-4 h-4" />
                    Configure API Key First
                  </>
                ) : showProgress ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Scanning...
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5 fill-current" />
                    Scan Repository
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Scan trigger / analysis error banner */}
      {!showProgress && analysisError && (
        <div className="mb-6 bg-red-50 border border-red-300 text-red-700 p-4 rounded-2xl text-sm font-semibold flex items-start gap-3 dark:bg-red-950/30 dark:border-red-800 dark:text-red-300">
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          <div>
            <p className="font-bold">Scan could not be completed</p>
            <p className="font-medium mt-0.5">{analysisError}</p>
            <p className="text-xs font-medium text-red-600 mt-1 dark:text-red-400">
              Check your LLM provider API key and model in Settings, and your GitHub PAT, then try again.
            </p>
          </div>
        </div>
      )}

      {/* Failed scan banner — never leave the UI stuck on "Scanning" */}
      {scanFailed && !showProgress && (
        <div className="mb-6 bg-red-50 border border-red-300 text-red-700 p-4 rounded-2xl text-sm font-semibold flex items-start gap-3 dark:bg-red-950/30 dark:border-red-800 dark:text-red-300">
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          <div>
            <p className="font-bold">The last scan failed</p>
            <p className="font-medium mt-0.5">
              {activeAnalysis.insights ? activeAnalysis.insights.slice(0, 300) : "An error occurred while scanning. Check your API keys in Settings and run the scan again."}
            </p>
          </div>
        </div>
      )}

      {/* Live progress stream */}
      {showProgress && (
        <div className="glass-card p-6 mb-6 space-y-4" role="status" aria-live="polite" aria-label="Repository scan progress">
          <div className="flex justify-between items-center text-sm font-bold text-zinc-900 dark:text-white">
            <span className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-accent-orange animate-ping" aria-hidden="true" />
              Analyzing Repository...
            </span>
            <span className="text-accent-orange">{progress}%</span>
          </div>
          
          <div className="progress-bar">
            <div className="progress-bar-fill relative" style={{ width: `${Math.min(progress, 100)}%` }}>
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent shimmer" />
            </div>
          </div>
          
          {/* Actual backend status message — real scan state, never fabricated */}
          {progressDetailed?.message && (
            <p className="text-xs text-zinc-600 font-medium dark:text-zinc-300">{progressDetailed.message}</p>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 py-3 border-y border-border/40 text-xs">
            <div>
              <span className="metric-label block text-[9px] tracking-wider">Status</span>
              <span className="text-zinc-600 font-semibold uppercase dark:text-zinc-300">{progressDetailed?.status || "Processing"}</span>
            </div>
            <div>
              <span className="metric-label block text-[9px] tracking-wider">Files Scanned</span>
              <span className="text-zinc-600 font-semibold dark:text-zinc-300">
                {progressDetailed?.files_analyzed || 0}
                {progressDetailed?.total_files && progressDetailed.total_files > 0
                  ? ` / ${progressDetailed.total_files}`
                  : ""}
              </span>
            </div>
            <div>
              <span className="metric-label block text-[9px] tracking-wider">Elapsed</span>
              <span className="text-zinc-600 font-semibold flex items-center gap-1 dark:text-zinc-300"><Clock className="w-3.5 h-3.5 text-zinc-500 dark:text-zinc-400" />{formatTime(elapsedTime)}</span>
            </div>
            <div>
              <span className="metric-label block text-[9px] tracking-wider">Est. Remaining</span>
              <span className="text-zinc-600 font-semibold flex items-center gap-1 dark:text-zinc-300"><RefreshCw className="w-3.5 h-3.5 text-zinc-500 dark:text-zinc-400 animate-spin" style={{ animationDuration: '4s' }} />{getEstimatedRemaining()}</span>
            </div>
          </div>
          
          {progressDetailed?.current_file && (
            <div>
              <span className="metric-label block text-[9px] tracking-wider mb-1">Current File</span>
              <span className="text-accent-blue font-mono font-semibold truncate block max-w-full" title={progressDetailed.current_file}>
                {progressDetailed.current_file}
              </span>
            </div>
          )}

          <div className="pt-3 border-t border-border/40">
            <span className="metric-label block text-[9px] tracking-wider mb-3">Scan Stages</span>
            <div className="grid grid-cols-1 md:grid-cols-7 gap-3">
              {[
                "Cloning Repository",
                "Indexing/Analyzing Files",
                "Running Security Checks",
                "Generating AI Findings",
                "Generating Tests",
                "Creating Insights",
                "Saving Results"
              ].map((stageName, idx) => {
                const currentStatus = progressDetailed?.status || "";
                const currentIdx = [
                  "Cloning Repository",
                  "Indexing/Analyzing Files",
                  "Running Security Checks",
                  "Generating AI Findings",
                  "Generating Tests",
                  "Creating Insights",
                  "Saving Results"
                ].findIndex(s => s.toLowerCase() === currentStatus.toLowerCase());

                const isCompleted = idx < currentIdx;
                const isActive = idx === currentIdx;

                let iconNode = <div className="w-4 h-4 rounded-full border border-border bg-background dark:bg-zinc-800" />;
                let textClass = "text-zinc-500 dark:text-zinc-400";
                let containerBorder = "border-border/30 bg-white/[0.02] dark:bg-zinc-900/40";

                if (isCompleted) {
                  iconNode = <Check className="w-3.5 h-3.5 text-accent-green" />;
                  textClass = "text-zinc-600 font-medium dark:text-zinc-300";
                  containerBorder = "border-accent-green/20 bg-accent-green/[0.03]";
                } else if (isActive) {
                  iconNode = <Loader2 className="w-3.5 h-3.5 text-accent-blue animate-spin" />;
                  textClass = "text-accent-blue font-bold";
                  containerBorder = "border-accent-blue/30 bg-accent-blue/[0.05]";
                }

                return (
                  <div key={idx} className={`flex md:flex-col items-center gap-2 md:gap-1.5 p-2 rounded-2xl border ${containerBorder} transition-all duration-150`}>
                    <div className="flex items-center justify-center w-5 h-5">{iconNode}</div>
                    <span className={`text-[10px] md:text-center leading-tight ${textClass}`}>{stageName}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Tabs Menu */}
      <div className="border-b border-border flex gap-6 mb-6 overflow-x-auto">
        {[
          { id: "overview", name: "Overview" },
          { id: "explorer", name: "Code Explorer" },
          { id: "prs", name: `Pull Requests (${prs.length})` },
          { id: "security", name: "Security" },
          { id: "quality", name: "Code Quality" },
          { id: "tests", name: "Tests" },
          { id: "insights", name: "Insights" },
          { id: "deep", name: "Deep Insights" }
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as RepoTabId)}
            className={`pb-3.5 text-xs font-semibold tracking-wider border-b-2 transition-all whitespace-nowrap ${
              activeTab === tab.id
                ? "border-accent-blue text-accent-blue"
                : "border-transparent text-zinc-500 hover:text-zinc-800 hover:border-border-strong dark:text-zinc-400 dark:hover:text-zinc-100 dark:hover:border-zinc-600"
            }`}
          >
            {tab.name}
          </button>
        ))}
      </div>

      {/* Tab Contents */}
      <div className="space-y-6">
        {/* Tab 1: Overview — evidence-based executive summary first */}
        {activeTab === "overview" && (
          <div className="space-y-6">
            {/* Repository Overview: real counts + grounded AI summary + scan freshness */}
            <RepositoryOverviewPanel repoId={activeRepo.id} />

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left info */}
            <div className="lg:col-span-2 space-y-6">
              <div className="glass-card p-6">
                <h3 className="font-bold text-zinc-900 text-sm mb-5 dark:text-white">Repository Analytics</h3>
                <div className="grid grid-cols-3 gap-4 text-center stagger-children">
                  <div className="glass p-5 rounded-2xl hover:-translate-y-0.5 transition-all duration-300">
                    <p className="metric-label text-[10px]">Health Rating</p>
                    {scanCompleted && activeAnalysis?.health_score !== undefined ? (
                      <h4 className="text-2xl font-bold font-sans mt-1.5 text-accent-green">
                        {activeAnalysis.health_score}/100
                      </h4>
                    ) : scanCompleted && activeAnalysis?.risk_score !== undefined ? (
                      <h4 className="text-2xl font-bold font-sans mt-1.5 text-accent-green">
                        {Math.max(0, 100 - activeAnalysis.risk_score)}/100
                      </h4>
                    ) : activeAnalysis?.status === "pending" || activeAnalysis?.status === "running" ? (
                      <h4 className="text-2xl font-bold font-sans mt-1.5 text-zinc-500 dark:text-zinc-400">...</h4>
                    ) : (
                      <div className="mt-2">
                        <p className="text-xs text-zinc-600 italic dark:text-zinc-300">Health score unavailable</p>
                        <p className="text-[10px] text-zinc-500 mt-0.5 dark:text-zinc-400">Run a repository scan</p>
                      </div>
                    )}
                  </div>
                  <div className="glass p-5 rounded-2xl hover:-translate-y-0.5 transition-all duration-300">
                    <p className="metric-label text-[10px]">Security Risks</p>
                    <h4 className="text-2xl font-bold font-sans mt-1.5 text-accent-red">
                      {scanCompleted ? securityFindings.length : "-"}
                    </h4>
                  </div>
                  <div className="glass p-5 rounded-2xl hover:-translate-y-0.5 transition-all duration-300">
                    <p className="metric-label text-[10px]">Code Issues</p>
                    <h4 className="text-2xl font-bold font-sans mt-1.5 text-accent-orange">
                      {scanCompleted ? codeSmells.length : "-"}
                    </h4>
                  </div>
                </div>
              </div>

              {scanCompleted && (
                <div className="glass-card p-6">
                  <h3 className="font-bold text-zinc-900 text-sm mb-5 dark:text-white">AI Statistics</h3>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-4 stagger-children">
                    <div className="glass p-4 rounded-2xl text-left">
                      <p className="metric-label text-[10px]">Model</p>
                      <h4 className="text-xs font-bold mt-1.5 text-zinc-900 truncate dark:text-zinc-100" title={activeAnalysis.model_name || "llama-3.3-70b-versatile"}>
                        {activeAnalysis.model_name || "llama-3.3-70b-versatile"}
                      </h4>
                    </div>
                    <div className="glass p-4 rounded-2xl text-center">
                      <p className="metric-label text-[10px]">Files</p>
                      <h4 className="text-lg font-bold font-sans mt-1.5 text-zinc-900 dark:text-zinc-100">{activeAnalysis.files_analyzed_count || "-"}</h4>
                    </div>
                    <div className="glass p-4 rounded-2xl text-center">
                      <p className="metric-label text-[10px]">Tokens</p>
                      <h4 className="text-lg font-bold font-sans mt-1.5 text-zinc-900 dark:text-zinc-100">
                        {activeAnalysis.total_tokens !== undefined && activeAnalysis.total_tokens > 0 
                          ? activeAnalysis.total_tokens : (activeAnalysis.estimated_token_usage || "-")}
                      </h4>
                    </div>
                    <div className="glass p-4 rounded-2xl text-center">
                      <p className="metric-label text-[10px]">Duration</p>
                      <h4 className="text-lg font-bold font-sans mt-1.5 text-zinc-900 dark:text-zinc-100">
                        {activeAnalysis.scan_duration_seconds !== undefined && activeAnalysis.scan_duration_seconds > 0
                          ? `${activeAnalysis.scan_duration_seconds}s` : (activeAnalysis.latency_seconds > 0 ? `${activeAnalysis.latency_seconds}s` : "-")}
                      </h4>
                    </div>
                    <div className="glass p-4 rounded-2xl text-center">
                      <p className="metric-label text-[10px]">Cache</p>
                      <h4 className={`text-lg font-bold font-sans mt-1.5 ${activeAnalysis.cached_results_used > 0 ? "text-accent-green" : "text-zinc-500 dark:text-zinc-400"}`}>
                        {activeAnalysis.cached_results_used > 0 ? "Enabled" : "Disabled"}
                      </h4>
                    </div>
                  </div>
                </div>
              )}

              {/* Analysis history list */}
              <div className="glass-card p-6">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="font-bold text-zinc-900 dark:text-white">Historical Scans</h3>
                  {analyses.length > 0 && (
                    <button
                      onClick={() => setShowDeleteAllModal(true)}
                      className="text-[10px] font-bold uppercase text-red-600 hover:text-red-700 border border-red-300 px-2.5 py-1.5 rounded bg-red-50 hover:bg-red-100 transition-colors dark:text-red-400 dark:border-red-500/30 dark:bg-red-500/10 dark:hover:bg-red-500/20"
                    >
                      Delete All History
                    </button>
                  )}
                </div>
                {analyses.length > 0 ? (
                  <div className="space-y-3">
                    {analyses.map((an) => (
                      <div
                        key={an.id}
                        onClick={() => fetchAnalysisDetails(an.id)}
                        className={`p-4 bg-background border rounded-lg flex justify-between items-center cursor-pointer hover:border-zinc-500 dark:bg-zinc-900/60 ${
                          activeAnalysis?.id === an.id ? "border-accent-blue" : "border-border"
                        }`}
                      >
                        <div className="text-xs">
                          <p className="font-bold text-zinc-900 dark:text-zinc-100">
                            Scan on branch {activeRepo.default_branch}
                          </p>
                          <span className="text-[10px] text-zinc-500 block mt-1 dark:text-zinc-400">
                            {formatDateTime(an.timestamp)}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-xs font-semibold">
                          <span className={an.status === "completed" ? "text-accent-green" : an.status === "failed" ? "text-accent-red" : "text-zinc-500 dark:text-zinc-400"}>
                            {an.status}
                          </span>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-extrabold ${
                            an.risk_score > 60 ? "bg-red-500/10 text-red-600 dark:text-red-400" : "bg-green-500/10 text-green-700 dark:text-green-400"
                          }`}>
                            Risk: {an.risk_score}
                          </span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setScanToDelete(an.id);
                            }}
                            className="text-red-600 hover:text-red-700 hover:bg-red-50 border border-red-300 px-2.5 py-1 rounded text-[10px] font-bold uppercase tracking-wider transition-colors dark:text-red-400 dark:border-red-500/30 dark:hover:bg-red-500/10"
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-zinc-700 font-semibold text-xs py-4 dark:text-zinc-300">No scan reports recorded yet. Click "Scan Repository" to run your first scan.</p>
                )}
              </div>
            </div>

            {/* Right exports / actions */}
            <div className="space-y-4">
              {/* Export Reports */}
              <div className="glass-card p-6">
                <div>
                  <h3 className="font-bold text-zinc-900 mb-2 dark:text-white">Export Scan Reports</h3>
                  <p className="text-xs text-zinc-500 mb-6 dark:text-zinc-400">Download the latest completed AI code review findings.</p>
                </div>

                {scanCompleted ? (
                  <>
                  {/* Unified full-report entry point — uses the existing report system */}
                  <button
                    onClick={() => handleDownload("PDF")}
                    className="btn-primary w-full flex items-center justify-center gap-2 mb-3"
                  >
                    <Download className="w-4 h-4" />
                    Download Full Report
                  </button>
                  <div className="grid grid-cols-2 gap-3">
                    <button onClick={() => handleDownload("PDF")} className="flex items-center justify-center gap-2 border border-border hover:bg-zinc-100 py-2.5 rounded-lg text-xs text-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-800">
                      <Download className="w-3.5 h-3.5" /> PDF
                    </button>
                    <button onClick={() => handleDownload("Markdown")} className="flex items-center justify-center gap-2 border border-border hover:bg-zinc-100 py-2.5 rounded-lg text-xs text-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-800">
                      <Download className="w-3.5 h-3.5" /> Markdown
                    </button>
                    <button onClick={() => handleDownload("JSON")} className="flex items-center justify-center gap-2 border border-border hover:bg-zinc-100 py-2.5 rounded-lg text-xs text-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-800">
                      <Download className="w-3.5 h-3.5" /> JSON
                    </button>
                    <button onClick={() => handleDownload("CSV")} className="flex items-center justify-center gap-2 border border-border hover:bg-zinc-100 py-2.5 rounded-lg text-xs text-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-800">
                      <Download className="w-3.5 h-3.5" /> CSV
                    </button>
                  </div>
                  <p className="text-[10px] text-zinc-500 mt-3 dark:text-zinc-400">
                    The full PDF report includes findings, health analysis, dependencies,
                    duplicates, technical debt, architecture and complexity sections where data is available.
                  </p>
                  </>
                ) : (
                  <div className="text-center text-zinc-700 font-semibold text-xs p-4 bg-background/50 border border-dashed border-border rounded-lg dark:text-zinc-300 dark:bg-zinc-900/40">
                    No completed analysis selected. Run a repository scan first.
                  </div>
                )}
              </div>
            </div>
            </div>
          </div>
        )}

        {/* Tab: Code Explorer */}
        {activeTab === "explorer" && (
          <div className="glass-card p-4 flex gap-6 h-[720px] font-sans">
            {/* File Tree Explorer (25% width) */}
            <div className="w-1/4 border-r border-border pr-4 flex flex-col h-full overflow-y-auto">
              <div className="flex justify-between items-center mb-3">
                <span className="metric-label text-[10px]">File Explorer</span>
                <button
                  onClick={fetchExplorerTree}
                  className="text-zinc-500 hover:text-zinc-900 transition-colors dark:text-zinc-400 dark:hover:text-white"
                  title="Refresh Directory tree"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${explorerLoading ? "animate-spin" : ""}`} />
                </button>
              </div>
              
              {explorerLoading ? (
                <div className="flex flex-col items-center justify-center py-24 gap-2">
                  <Loader2 className="w-5 h-5 text-accent-blue animate-spin" />
                  <span className="text-[10px] text-zinc-500 dark:text-zinc-400">Retrieving directory tree...</span>
                </div>
              ) : explorerTree.length > 0 ? (
                <div className="space-y-1 select-none overflow-x-hidden">
                  {explorerTree.map((node, idx) => (
                    <FileTreeItem
                      key={idx}
                      node={node}
                      onSelectFile={handleSelectFile}
                      selectedPath={openFilePath}
                    />
                  ))}
                </div>
              ) : (
                <div className="text-center py-20 text-xs text-zinc-700 font-semibold dark:text-zinc-300">
                  No files indexed or repository empty.
                </div>
              )}
            </div>
            
            {/* Monaco Editor (75% width) — dark surface in both themes so the
                vs-dark syntax theme stays readable */}
            <div className="flex-1 flex flex-col h-full bg-zinc-950 rounded-xl border border-border overflow-hidden relative">
              {openFilePath ? (
                <div className="flex-1 flex flex-col h-full">
                  <div className="px-4 py-3 border-b border-border bg-zinc-900 flex justify-between items-center text-xs">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span className="font-mono text-zinc-100 font-bold truncate">{openFilePath.split("/").pop()}</span>
                      <span className="text-[10px] font-mono text-zinc-400 truncate">{openFilePath}</span>
                    </div>
                    
                    <span className="px-3.5 py-2 bg-zinc-800 text-zinc-300 rounded-lg text-xs font-semibold border border-zinc-700">
                      <Save className="w-3.5 h-3.5 inline mr-1" /> Read-Only
                    </span>
                  </div>
                  
                  <div className="flex-1 overflow-hidden bg-black">
                    <Editor
                      height="100%"
                      theme="vs-dark"
                      language={
                        openFilePath.endsWith(".py") ? "python" :
                        openFilePath.endsWith(".js") || openFilePath.endsWith(".jsx") ? "javascript" :
                        openFilePath.endsWith(".ts") || openFilePath.endsWith(".tsx") ? "typescript" :
                        openFilePath.endsWith(".json") ? "json" :
                        openFilePath.endsWith(".md") ? "markdown" :
                        openFilePath.endsWith(".html") ? "html" :
                        openFilePath.endsWith(".css") ? "css" : "plaintext"
                      }
                      value={openFileContent}
                      onMount={handleEditorDidMount}
                      options={{
                        readOnly: true,
                        minimap: { enabled: false },
                        fontSize: 13,
                        lineNumbers: "on",
                        automaticLayout: true
                      }}
                    />
                  </div>
                </div>
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center text-center p-6 text-zinc-400">
                  <Code className="w-12 h-12 text-zinc-500 mb-3" />
                  <p className="text-xs font-bold text-zinc-200">Inline Code Editor</p>
                  <p className="text-[11px] text-zinc-400 font-medium mt-1.5 max-w-xs leading-relaxed">
                    Select a source file from the directory tree to inspect it directly in your browser.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab 2: Pull Requests — real GitHub PRs + stored AI review results */}
        {activeTab === "prs" && (
          <div className="space-y-6">
            <div className="glass-card p-6">
              <h3 className="font-bold text-zinc-900 mb-4 dark:text-white">Open Pull Requests</h3>
              {prs.length > 0 ? (
                <div className="divide-y divide-border">
                  {prs.map((pr) => (
                    <div
                      key={pr.id}
                      onClick={() => onSelectPr(pr)}
                      className="py-4 first:pt-0 last:pb-0 flex justify-between items-center cursor-pointer hover:bg-zinc-100 px-3 rounded-lg transition-colors dark:hover:bg-zinc-800"
                    >
                      <div>
                        <div className="flex items-center gap-2">
                          <GitPullRequest className="w-4 h-4 text-accent-green" />
                          <h4 className="font-bold text-sm text-zinc-900 hover:text-accent-blue transition-colors dark:text-zinc-100">
                            #{pr.number}: {pr.title}
                          </h4>
                        </div>
                        <p className="text-xs text-zinc-600 mt-1 dark:text-zinc-400">Opened by @{pr.author} | {pr.head_sha.slice(0, 7)}</p>
                      </div>
                      <div className="flex items-center gap-4 text-xs font-semibold">
                        <span className="text-accent-green">+{pr.additions}</span>
                        <span className="text-accent-red">-{pr.deletions}</span>
                        <ArrowLeft className="w-4 h-4 rotate-180 text-zinc-500 dark:text-zinc-400" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center text-zinc-700 font-semibold text-sm py-8 bg-background/50 border border-dashed border-border rounded-lg dark:text-zinc-300 dark:bg-zinc-900/40">
                  No active pull requests found in this repository.
                </div>
              )}
            </div>

            {/* Real PR review feature (insights backend) */}
            <PRReviewPanel repoId={activeRepo.id} />
          </div>
        )}

        {/* Tab 3: Security Findings */}
        {activeTab === "security" && (
          <div className="glass-card p-6">
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-bold text-zinc-900 dark:text-white">Security Findings ({securityFindings.length})</h3>
            </div>
            {securityFindings.length > 0 ? (
              <>
                <div className="space-y-4">
                  {securityPageItems.map((finding) => (
                    <FindingCard
                      key={finding.id}
                      severity={finding.severity}
                      issue={finding.issue}
                      file={finding.file}
                      line={finding.line}
                      startLine={finding.start_line}
                      endLine={finding.end_line}
                      evidence={finding.before_code || finding.code_snippet || null}
                      suggestedFix={finding.after_code || null}
                      whyItMatters={finding.why_it_matters}
                      suggestion={finding.suggestion}
                      source={finding.source}
                      onJumpToLine={() => handleJumpToLine(finding.file, finding.line, finding.end_line)}
                      onExplain={() => handleExplainFinding(finding.id, "security")}
                    />
                  ))}
                </div>
                <Pagination
                  page={securityPage}
                  pageSize={SECURITY_PAGE_SIZE}
                  totalItems={securityFindings.length}
                  onPageChange={setSecurityPage}
                  itemLabel="security findings"
                />
              </>
            ) : scanCompleted ? (
              <div className="text-center py-8 bg-background/50 border border-dashed border-border rounded-lg dark:bg-zinc-900/40">
                <ShieldCheck className="w-10 h-10 text-accent-green mx-auto mb-3" />
                <p className="text-sm font-bold text-zinc-800 dark:text-zinc-100">No security vulnerabilities detected.</p>
                <p className="text-xs text-zinc-600 mt-1 dark:text-zinc-400">The last completed scan found no security findings.</p>
              </div>
            ) : showProgress ? (
              <div className="text-center py-10">
                <Loader2 className="w-6 h-6 text-accent-blue animate-spin mx-auto mb-3" />
                <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">Scan in progress — security findings will appear here.</p>
              </div>
            ) : (
              <ScanRequiredEmptyState icon={<ShieldCheck className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />} />
            )}
          </div>
        )}

        {/* Tab 4: Code Quality */}
        {activeTab === "quality" && (
          <div className="glass-card p-6">
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-bold text-zinc-900 dark:text-white">Code Smells &amp; Maintainability ({codeSmells.length})</h3>
            </div>
            {codeSmells.length > 0 ? (
              <>
                <div className="space-y-4">
                  {qualityPageItems.map((smell) => (
                    <FindingCard
                      key={smell.id}
                      severity={smell.severity}
                      issue={smell.issue}
                      file={smell.file}
                      line={smell.line}
                      startLine={smell.start_line}
                      endLine={smell.end_line}
                      evidence={smell.before_code || smell.code_snippet || null}
                      suggestedFix={smell.after_code || null}
                      whyItMatters={smell.why_it_matters}
                      suggestion={smell.suggestion}
                      source={smell.source}
                      onJumpToLine={() => handleJumpToLine(smell.file, smell.line, smell.end_line)}                      onExplain={() => handleExplainFinding(smell.id, "code_smell")}
                    />
                  ))}
                </div>
                <Pagination
                  page={qualityPage}
                  pageSize={SECURITY_PAGE_SIZE}
                  totalItems={codeSmells.length}
                  onPageChange={setQualityPage}
                  itemLabel="code quality findings"
                />
              </>
            ) : scanCompleted ? (
              <div className="text-center py-8 bg-background/50 border border-dashed border-border rounded-lg dark:bg-zinc-900/40">
                <ShieldCheck className="w-10 h-10 text-accent-green mx-auto mb-3" />
                <p className="text-sm font-bold text-zinc-800 dark:text-zinc-100">No code quality issues detected.</p>
                <p className="text-xs text-zinc-600 mt-1 dark:text-zinc-400">The last completed scan found no code smells.</p>
              </div>
            ) : showProgress ? (
              <div className="text-center py-10">
                <Loader2 className="w-6 h-6 text-accent-blue animate-spin mx-auto mb-3" />
                <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">Scan in progress — code quality findings will appear here.</p>
              </div>
            ) : (
              <ScanRequiredEmptyState icon={<BarChart3 className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />} />
            )}
          </div>
        )}

        {/* Tab 5: Tests */}
        {activeTab === "tests" && (
          <div className="glass-card p-6">
            <h3 className="font-bold text-zinc-900 mb-4 dark:text-white">Generated QA Test Templates</h3>
            {testSuggestions && testSuggestions !== "No test suggestions generated." ? (
              <Markdown content={testSuggestions} className="text-xs" />
            ) : scanCompleted ? (
              <div className="text-center py-8 bg-background/50 border border-dashed border-border rounded-lg dark:bg-zinc-900/40">
                <p className="text-sm font-bold text-zinc-800 dark:text-zinc-100">No test suggestions generated.</p>
                <p className="text-xs text-zinc-600 mt-1 dark:text-zinc-400">The last scan did not produce test templates.</p>
              </div>
            ) : showProgress ? (
              <div className="text-center py-10">
                <Loader2 className="w-6 h-6 text-accent-blue animate-spin mx-auto mb-3" />
                <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">Scan in progress — generated tests will appear here.</p>
              </div>
            ) : (
              <ScanRequiredEmptyState />
            )}
          </div>
        )}

        {/* Tab 6: INSIGHTS — the simple level: what is happening */}
        {activeTab === "insights" && activeRepo && (
          <InsightsOverviewPanel
            repoId={activeRepo.id}
            onOpenDeep={(section) => {
              setDeepSection(section || "health");
              setActiveTab("deep");
            }}
          />
        )}

        {/* Tab 7: DEEP INSIGHTS — the technical level: detailed evidence */}
        {activeTab === "deep" && activeRepo && (
          <div className="space-y-5">
            <p className="text-[11px] text-zinc-600 font-medium dark:text-zinc-400">
              Technical analysis of your latest scan. For a plain-language summary, open the Insights tab.
            </p>
            {/* Qualitative Engineering Report (AI narrative of the scan) */}
            <div className="glass-card p-6">
              <h3 className="font-bold text-zinc-900 mb-4 dark:text-white">Qualitative Engineering Report</h3>
              {activeAnalysis?.insights && scanCompleted ? (
                <Markdown content={activeAnalysis.insights} />
              ) : showProgress ? (
                <div className="text-center py-10">
                  <Loader2 className="w-6 h-6 text-accent-blue animate-spin mx-auto mb-3" />
                  <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">Scan in progress — the qualitative report will appear here.</p>
                </div>
              ) : (
                <ScanRequiredEmptyState />
              )}
            </div>

            <DeepInsightsTab repoId={activeRepo.id} initialSection={deepSection} />
          </div>
        )}
      </div>

      {/* Already-scanned dialog: same repository + commit */}
      {showAlreadyAnalyzed && scanIdentity && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-[70] p-4 animate-fade-in" role="dialog" aria-modal="true" aria-labelledby="already-scanned-title">
          <div className="glass-card w-full max-w-md rounded-2xl shadow-2xl overflow-hidden">
            <div className="px-6 py-4 border-b border-border flex items-center gap-2.5 bg-zinc-50 dark:bg-zinc-900">
              <CheckCircle2 className="w-5 h-5 text-accent-blue" aria-hidden="true" />
              <h3 id="already-scanned-title" className="text-md font-bold text-zinc-900 dark:text-white">Already scanned</h3>
            </div>
            <div className="p-6 space-y-4 text-xs">
              <div className="glass p-4 rounded-xl space-y-2">
                <p className="flex justify-between">
                  <span className="text-zinc-500 dark:text-zinc-400">Commit</span>
                  <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100">{String(scanIdentity.last_scan?.commit_sha || "").slice(0, 7) || "Not recorded"}</span>
                </p>
                <p className="flex justify-between">
                  <span className="text-zinc-500 dark:text-zinc-400">Scanned</span>
                  <span className="font-semibold text-zinc-900 dark:text-zinc-100">
                    {scanIdentity.last_scan?.timestamp ? formatDateTime(scanIdentity.last_scan.timestamp) : "Date not recorded"}
                  </span>
                </p>
                <p className="flex justify-between">
                  <span className="text-zinc-500 dark:text-zinc-400">Branch</span>
                  <span className="font-semibold text-zinc-900 dark:text-zinc-100">{scanIdentity.branch || "Not available"}</span>
                </p>
              </div>
              <p className="text-[11px] text-zinc-500 leading-relaxed dark:text-zinc-400">
                The existing results were produced from this exact repository state. Note: AI-generated findings may vary
                slightly between scans because LLM responses are not guaranteed to be identical — deterministic analysis
                (dependencies, duplicates, complexity, architecture, technical debt) remains stable.
              </p>
            </div>
            <div className="px-6 py-4 border-t border-border bg-zinc-50 flex flex-col sm:flex-row gap-2 dark:bg-zinc-900">
              <button
                onClick={() => setShowAlreadyAnalyzed(false)}
                className="flex-1 px-4 py-2.5 border border-border text-xs rounded-lg hover:bg-zinc-100 text-zinc-700 font-bold transition-colors dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                View Previous Scan
              </button>
              <button
                onClick={async () => {
                  setShowAlreadyAnalyzed(false);
                  await startScan();
                }}
                className="flex-1 px-4 py-2.5 bg-accent-blue hover:bg-blue-600 text-white text-xs rounded-lg font-bold transition-colors"
              >
                Scan Again
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Scan Completed Summary — real counts from the latest completed scan */}
      {showScanSummary && activeRepo && (
        <ScanSummaryModal
          analysisId={summaryAnalysisId}
          repoId={activeRepo.id}
          onClose={() => setShowScanSummary(false)}
          onViewDetails={() => setActiveTab("insights")}
          onDownloadReport={() => {
            setActiveTab("overview");
            if (activeAnalysis) handleDownload("PDF");
          }}
        />
      )}

      {/* Explain Finding Modal */}
      {explainFinding && (
        <div className="fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-[60] p-4 animate-fade-in" role="dialog" aria-modal="true" aria-label="AI explanation of finding">
          <div className="glass-card w-full max-w-2xl rounded-2xl shadow-2xl flex flex-col max-h-[80vh] overflow-hidden">
            <div className="px-6 py-4 border-b border-border flex justify-between items-center bg-zinc-50 dark:bg-zinc-900">
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-accent-blue bg-accent-blue/10 px-2 py-0.5 rounded border border-accent-blue/20">
                  AI Deep Insights
                </span>
                <h3 className="text-md font-bold text-zinc-900 mt-1.5 dark:text-white">
                  Vulnerability Root-Cause Analysis
                </h3>
              </div>
              <button
                onClick={() => setExplainFinding(null)}
                className="text-zinc-500 hover:text-zinc-900 p-1 rounded-lg hover:bg-zinc-100 transition-colors dark:text-zinc-400 dark:hover:text-white dark:hover:bg-zinc-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-6 text-xs text-zinc-700 leading-relaxed space-y-4 font-sans dark:text-zinc-300">
              {explainLoading ? (
                <div className="flex flex-col items-center justify-center py-20 gap-3">
                  <div className="w-10 h-10 border-4 border-accent-blue/20 border-t-accent-blue rounded-full animate-spin" />
                  <span className="text-xs text-zinc-700 dark:text-zinc-300">Generating markdown explanation from your LLM provider...</span>
                </div>
              ) : explainResult ? (
                <Markdown content={explainResult} />
              ) : (
                <p>No explanation generated.</p>
              )}
            </div>
            
            <div className="px-6 py-3 border-t border-border bg-zinc-50 flex justify-end dark:bg-zinc-900">
              <button
                onClick={() => setExplainFinding(null)}
                className="px-4 py-2 border border-border text-xs rounded-lg hover:bg-zinc-100 text-zinc-700 font-semibold transition-colors dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                Close Explanation
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Scan Confirmation Modal */}
      {scanToDelete && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in" role="dialog" aria-modal="true" aria-labelledby="delete-scan-title">
          <div className="glass-card w-full max-w-sm rounded-2xl p-6 shadow-2xl space-y-4">
            <h3 id="delete-scan-title" className="text-md font-bold text-zinc-900 font-sans dark:text-white">Delete Scan?</h3>
            <p className="text-xs text-zinc-600 leading-relaxed font-sans dark:text-zinc-300">This action cannot be undone.</p>
            <div className="flex gap-3 pt-2 font-sans">
              <button
                onClick={() => setScanToDelete(null)}
                className="flex-1 border border-border hover:bg-zinc-100 text-zinc-600 hover:text-zinc-900 font-semibold text-xs py-2.5 rounded-lg transition-colors dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  try {
                    await deleteAnalysis(scanToDelete);
                  } catch (err: any) {
                    toast.error(err.message || "Failed to delete scan");
                  } finally {
                    setScanToDelete(null);
                  }
                }}
                className="flex-1 bg-red-500 hover:bg-red-600 text-white font-semibold text-xs py-2.5 rounded-lg transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete All History Confirmation Modal */}
      {showDeleteAllModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in" role="dialog" aria-modal="true" aria-labelledby="delete-all-title">
          <div className="glass-card w-full max-w-sm rounded-2xl p-6 shadow-2xl space-y-4">
            <h3 id="delete-all-title" className="text-md font-bold text-zinc-900 font-sans dark:text-white">Delete ALL scans?</h3>
            <p className="text-xs text-zinc-600 leading-relaxed font-sans dark:text-zinc-300">This action cannot be undone.</p>
            <div className="flex gap-3 pt-2 font-sans">
              <button
                onClick={() => setShowDeleteAllModal(false)}
                className="flex-1 border border-border hover:bg-zinc-100 text-zinc-600 hover:text-zinc-900 font-semibold text-xs py-2.5 rounded-lg transition-colors dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  try {
                    await deleteAllHistory();
                  } catch (err: any) {
                    toast.error(err.message || "Failed to delete all scans");
                  } finally {
                    setShowDeleteAllModal(false);
                  }
                }}
                className="flex-1 bg-red-500 hover:bg-red-600 text-white font-semibold text-xs py-2.5 rounded-lg transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Disconnect Confirmation Modal */}
      {showDisconnectModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in font-sans" role="dialog" aria-modal="true" aria-labelledby="disconnect-title">
          <div className="glass-card w-full max-w-sm rounded-2xl p-6 shadow-2xl space-y-4">
            <h3 id="disconnect-title" className="text-md font-bold text-zinc-900 dark:text-white">Disconnect Repository?</h3>
            <p className="text-xs text-zinc-600 leading-relaxed dark:text-zinc-300">
              Disconnecting will hide this repository from your active workspace but keep its history intact. You can reconnect it at any time.
            </p>
            <div className="flex gap-3 pt-2">
              <button
                onClick={() => setShowDisconnectModal(false)}
                disabled={actionLoading}
                className="flex-1 border border-border hover:bg-zinc-100 text-zinc-600 hover:text-zinc-900 font-semibold text-xs py-2.5 rounded-lg transition-colors dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={handleDisconnectRepo}
                disabled={actionLoading}
                className="flex-1 bg-accent-blue hover:bg-blue-600 text-white font-semibold text-xs py-2.5 rounded-lg transition-colors flex items-center justify-center gap-1.5"
              >
                {actionLoading && <Loader2 className="w-3 h-3 animate-spin" />}
                Disconnect
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Repository Confirmation Modal */}
      {showDeleteRepoModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in font-sans" role="dialog" aria-modal="true" aria-labelledby="delete-repo-title">
          <div className="glass-card w-full max-w-sm rounded-2xl p-6 shadow-2xl space-y-4">
            <h3 id="delete-repo-title" className="text-md font-bold text-accent-red">Hard Delete Repository?</h3>
            <p className="text-xs text-zinc-600 leading-relaxed dark:text-zinc-300">
              This will permanently delete the repository registration, all scan history, reports, code findings, and patches from the system. <strong>This action cannot be undone.</strong>
            </p>
            <div className="flex gap-3 pt-2">
              <button
                onClick={() => setShowDeleteRepoModal(false)}
                disabled={actionLoading}
                className="flex-1 border border-border hover:bg-zinc-100 text-zinc-600 hover:text-zinc-900 font-semibold text-xs py-2.5 rounded-lg transition-colors dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteRepo}
                disabled={actionLoading}
                className="flex-1 bg-accent-red hover:bg-red-600 text-white font-semibold text-xs py-2.5 rounded-lg transition-colors flex items-center justify-center gap-1.5"
              >
                {actionLoading && <Loader2 className="w-3 h-3 animate-spin" />}
                Delete Permanently
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
