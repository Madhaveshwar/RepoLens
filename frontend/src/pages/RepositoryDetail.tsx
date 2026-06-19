import React, { useEffect, useState } from "react";
import axios from "../lib/api";
import { useRepositoryStore } from "../store/repositoryStore";
import type { PullRequest } from "../store/repositoryStore";
import { useAnalysisStore } from "../store/analysisStore";
import {
  ArrowLeft, GitPullRequest, BookOpen,
  Play, Loader2, Download, Clock, Check, RefreshCw,
  Folder, File, ChevronRight, ChevronDown, Save, X, Code, Lightbulb, ExternalLink,
  ShieldCheck, GitBranch
} from "lucide-react";
import Editor from "@monaco-editor/react";
import { useQuery } from "@tanstack/react-query";

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
          isSelected ? "bg-accent-blue/15 text-accent-blue font-semibold border-l-2 border-accent-blue" : "text-zinc-400 hover:text-white hover:bg-zinc-800/40"
        }`}
      >
        <File className="w-3.5 h-3.5 shrink-0 text-zinc-500" />
        <span className="truncate">{node.name}</span>
      </button>
    );
  }
  
  return (
    <div className="space-y-0.5">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-1.5 px-2 py-1 text-[11px] text-left text-zinc-300 hover:text-white hover:bg-zinc-800/30 rounded-md transition-colors"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 shrink-0 text-zinc-500" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 shrink-0 text-zinc-500" />
        )}
        <Folder className="w-3.5 h-3.5 shrink-0 text-amber-500/80 fill-amber-500/10" />
        <span className="truncate font-medium">{node.name}</span>
      </button>
      
      {expanded && node.children && (
        <div className="pl-3.5 border-l border-zinc-800/60 ml-2.5 space-y-0.5">
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

export const RepositoryDetail: React.FC<RepositoryDetailProps> = ({ onBack, onSelectPr }) => {
  const { activeRepo, prs } = useRepositoryStore();
  const {
    analyses, activeAnalysis, securityFindings, codeSmells, testSuggestions,
    progress, progressDetailed, triggerAnalysis, fetchRepoAnalyses,
    fetchAnalysisDetails, resetProgress, deleteAnalysis, deleteAllHistory
  } = useAnalysisStore();

  const showProgress = progress > 0 && progress < 100;

  const [activeTab, setActiveTab] = useState("overview");

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

  const { data: analysesData, refetch: refetchRepoAnalyses } = useQuery({
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

  const [openFilePath, setOpenFilePath] = useState<string | null>(null);
  const [openFileContent, setOpenFileContent] = useState("");
  const [editorOriginalContent, setEditorOriginalContent] = useState("");
  const [editorUnsaved, setEditorUnsaved] = useState(false);
  const [monacoEditor, setMonacoEditor] = useState<any>(null);
  const [monacoInstance, setMonacoInstance] = useState<any>(null);
  const [decorations, setDecorations] = useState<string[]>([]);
  const [showCommitModal, setShowCommitModal] = useState(false);
  const [commitMsg, setCommitMsg] = useState("Direct code update from browser");
  const [saveLoading, setSaveLoading] = useState(false);

  // Explain states
  const [explainFinding, setExplainFinding] = useState<{ id: string; type: "security" | "code_smell" } | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [explainResult, setExplainResult] = useState<string | null>(null);

  // Validate Fix states
  const [validateResult, setValidateResult] = useState<{ status: string; details: string; remaining_issues: any[] } | null>(null);
  const [validating, setValidating] = useState(false);
  const [showValidateModal, setShowValidateModal] = useState(false);

  // Deploy states
  const [deployInstructions, setDeployInstructions] = useState<{
    steps: string[];
    commit_suggestion: string;
    pr_title_suggestion: string;
    pr_description_suggestion: string;
  } | null>(null);
  const [deployLoading, setDeployLoading] = useState(false);
  const [showDeployModal, setShowDeployModal] = useState(false);

  // Push to GitHub states
  const [pushingToGitHub, setPushingToGitHub] = useState(false);

  // Fetch Tree
  const fetchExplorerTree = async () => {
    refetchExplorerTree();
  };

  // Fetch File Content
  const handleSelectFile = async (path: string): Promise<void> => {
    if (!activeRepo) return;
    if (editorUnsaved) {
      const confirmDiscard = window.confirm("You have unsaved changes in the current file. Discard changes?");
      if (!confirmDiscard) return;
    }
    
    // Clear residual Monaco decorations
    if (monacoEditor && decorations.length > 0) {
      monacoEditor.deltaDecorations(decorations, []);
      setDecorations([]);
    }
    
    setOpenFilePath(path);
    setOpenFileContent("");
    setEditorOriginalContent("");
    setEditorUnsaved(false);
    
    try {
      const res = await axios.get(`/repositories/${activeRepo.id}/files`, {
        params: { path }
      });
      setOpenFileContent(res.data.content);
      setEditorOriginalContent(res.data.content);
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to download file content from GitHub.");
    }
  };

  // Save File Content
  const handleSaveFile = async () => {
    if (!activeRepo || !openFilePath) return;
    setSaveLoading(true);
    try {
      await axios.post(`/repositories/${activeRepo.id}/files`, {
        path: openFilePath,
        content: openFileContent,
        commit_message: commitMsg
      });
      alert("File saved successfully! A background re-scan has been triggered.");
      setEditorOriginalContent(openFileContent);
      setEditorUnsaved(false);
      setShowCommitModal(false);
      // Refresh analyses
      if (activeRepo) fetchRepoAnalyses(activeRepo.id);
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to save file on GitHub.");
    } finally {
      setSaveLoading(false);
    }
  };

  // Jump to Line number in Monaco editor
  const handleJumpToLine = async (filePath: string, line: number) => {
    setActiveTab("explorer");
    await handleSelectFile(filePath);
    // Wait for content load
    setTimeout(() => {
      if (monacoEditor) {
        monacoEditor.revealLineInCenter(line);
        monacoEditor.setPosition({ lineNumber: line, column: 1 });
        monacoEditor.focus();
        
        // Highlight line with decorations if monacoInstance is available
        if (monacoInstance) {
          const newDecs = monacoEditor.deltaDecorations(decorations, [
            {
              range: new monacoInstance.Range(line, 1, line, 1),
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

  // Validate Fix
  const handleValidateFix = async () => {
    if (!activeAnalysis || !openFilePath) return;
    setValidating(true);
    setValidateResult(null);
    setShowValidateModal(true);
    try {
      const res = await axios.post("/analysis/validate-fix", {
        analysis_id: activeAnalysis.id,
        file_path: openFilePath,
        original_content: editorOriginalContent,
        edited_content: openFileContent
      });
      setValidateResult(res.data);
    } catch (err: any) {
      setValidateResult({
        status: "error",
        details: err.response?.data?.detail || "Validation failed",
        remaining_issues: []
      });
    } finally {
      setValidating(false);
    }
  };

  // Deploy Changes
  const handleDeployChanges = async () => {
    if (!activeAnalysis) return;
    setDeployLoading(true);
    setDeployInstructions(null);
    setShowDeployModal(true);
    try {
      const res = await axios.post("/analysis/deploy-instructions", {
        analysis_id: activeAnalysis.id,
        branch: activeRepo?.default_branch || "main"
      });
      setDeployInstructions(res.data);
    } catch (err: any) {
      setDeployInstructions({
        steps: ["Failed to generate deploy instructions."],
        commit_suggestion: "",
        pr_title_suggestion: "",
        pr_description_suggestion: ""
      });
    } finally {
      setDeployLoading(false);
    }
  };

  // Push to GitHub
  const handlePushToGitHub = async () => {
    if (!activeRepo || !openFilePath) return;
    setPushingToGitHub(true);
    try {
      const commitMsg = `Fix: ${openFilePath} - AI-guided code remediation`;
      await axios.post(`/repositories/${activeRepo.id}/git-push`, {
        repository_id: activeRepo.id,
        file_path: openFilePath,
        file_content: openFileContent,
        commit_message: commitMsg,
        branch: activeRepo.default_branch || "main"
      });
      alert("Changes pushed to GitHub successfully! A new commit has been created. A background re-scan will now trigger.");
      setEditorOriginalContent(openFileContent);
      setEditorUnsaved(false);
      // Trigger automatic re-scan after successful push
      if (activeRepo) {
        try {
          resetProgress();
          await triggerAnalysis(activeRepo.id);
          refetchRepoAnalyses();
        } catch (scanErr) {
          console.error("Background re-scan trigger failed:", scanErr);
        }
      }
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to push to GitHub. Check your PAT has push access.");
    } finally {
      setPushingToGitHub(false);
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
      alert(err.message || "Failed to disconnect repository");
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
      alert(err.message || "Failed to delete repository");
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

  // When user clicks a historical scan in the list, load its details.
  // The interval handler in analysisStore.ts handles auto-loading for the
  // most recently triggered scan, so we only need to handle user clicks here.
  // (fetchAnalysisDetails is already called from the onClick on each scan row.)

  const handleRunAnalysis = async () => {
    if (!activeRepo) return;
    try {
      resetProgress();
      await triggerAnalysis(activeRepo.id);
      // No refetchRepoAnalyses() here — the interval polling in
      // analysisStore.startProgressStream will update both progress
      // and call fetchAnalysisDetails on completion, which updates
      // the store and React Query indirectly.
    } catch (err) {
      console.error(err);
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
        }).catch(err => {
          console.error(err);
          alert(`Failed to download report content for ${type}.`);
        });
      } else {
        alert(`${type} report file generation in progress or failed.`);
      }
    }).catch(err => {
      console.error(err);
      alert("Failed to fetch reports index.");
    });
  };

  if (!activeRepo) return null;

  return (
    <div className="flex-1 p-8 overflow-y-auto max-h-screen">
      {/* Header breadcrumb */}
      <button onClick={onBack} className="flex items-center gap-2 text-zinc-400 hover:text-white text-xs mb-4">
        <ArrowLeft className="w-4 h-4" />
        Back to Dashboard
      </button>

      <div className="flex justify-between items-start mb-6">
        <div>
          <div className="flex items-center gap-3">
            <BookOpen className="w-6 h-6 text-accent-blue" />
            <h1 className="text-2xl font-extrabold text-white">{activeRepo.name}</h1>
          </div>
          <p className="text-sm text-muted mt-1">{activeRepo.description}</p>
          {activeRepo.permissions && (
            <div className="flex flex-wrap gap-2 mt-2 font-sans select-none">
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                activeRepo.permissions.pull
                  ? "bg-green-500/10 text-accent-green border-green-500/20"
                  : "bg-red-500/10 text-accent-red border-red-500/20"
              }`}>
                PULL: {activeRepo.permissions.pull ? "YES" : "NO"}
              </span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                activeRepo.permissions.push
                  ? "bg-green-500/10 text-accent-green border-green-500/20"
                  : "bg-red-500/10 text-accent-red border-red-500/20"
              }`}>
                PUSH: {activeRepo.permissions.push ? "YES" : "NO"}
              </span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                activeRepo.permissions.admin
                  ? "bg-purple-500/10 text-purple-400 border-purple-500/20"
                  : "bg-zinc-800 text-zinc-400 border-zinc-700"
              }`}>
                ADMIN: {activeRepo.permissions.admin ? "YES" : "NO"}
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3 font-sans">
          <button
            onClick={() => setShowDisconnectModal(true)}
            disabled={showProgress || actionLoading}
            className="border border-border hover:bg-zinc-800 disabled:opacity-40 text-zinc-300 font-semibold text-xs px-3.5 py-2.5 rounded-lg transition-colors"
          >
            Disconnect
          </button>
          <button
            onClick={() => setShowDeleteRepoModal(true)}
            disabled={showProgress || actionLoading}
            className="border border-red-500/20 hover:bg-red-500/10 disabled:opacity-40 text-red-400 font-semibold text-xs px-3.5 py-2.5 rounded-lg transition-colors"
          >
            Delete Repo
          </button>
          <button
            onClick={handleRunAnalysis}
            disabled={showProgress}
            className="flex items-center gap-2 bg-accent-blue hover:bg-blue-600 disabled:opacity-50 text-white font-semibold text-xs px-4 py-2.5 rounded-lg transition-colors shadow-lg shadow-accent-blue/15"
          >
            {showProgress ? (
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

      {/* Live progress stream */}
      {showProgress && (
        <div className="bg-surface border border-border rounded-xl p-6 mb-6 font-sans text-xs text-zinc-300 space-y-4">
          <div className="flex justify-between items-center text-sm font-bold text-white">
            <span className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-accent-orange animate-ping" />
              Scanning Repository
            </span>
            <span className="text-accent-orange">{progress}%</span>
          </div>
          
          <div className="text-zinc-700 text-sm font-bold tracking-wider select-none leading-none font-mono">
            {"â–ˆ".repeat(Math.round((progress / 100) * 20)) + "â–‘".repeat(20 - Math.round((progress / 100) * 20))}
          </div>
          
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 py-3 border-y border-border/40 text-[11px]">
            <div>
              <span className="text-zinc-500 block uppercase font-bold text-[9px] tracking-wider">Status</span>
              <span className="text-zinc-300 font-semibold uppercase">{progressDetailed?.status || "Processing"}</span>
            </div>
            <div>
              <span className="text-zinc-500 block uppercase font-bold text-[9px] tracking-wider">Files Scanned</span>
              <span className="text-zinc-300 font-semibold">{progressDetailed?.files_analyzed || 0} / {progressDetailed?.total_files || 0}</span>
            </div>
            <div>
              <span className="text-zinc-500 block uppercase font-bold text-[9px] tracking-wider">Elapsed Time</span>
              <span className="text-zinc-300 font-semibold flex items-center gap-1">
                <Clock className="w-3.5 h-3.5 text-zinc-400" />
                {formatTime(elapsedTime)}
              </span>
            </div>
            <div>
              <span className="text-zinc-500 block uppercase font-bold text-[9px] tracking-wider">Est. Remaining</span>
              <span className="text-zinc-300 font-semibold flex items-center gap-1">
                <RefreshCw className="w-3.5 h-3.5 text-zinc-400 animate-spin" style={{ animationDuration: '4s' }} />
                {getEstimatedRemaining()}
              </span>
            </div>
          </div>
          
          {progressDetailed?.current_file && (
            <div className="pt-1">
              <span className="text-zinc-500 block uppercase font-bold text-[9px] tracking-wider mb-1">Current File</span>
              <span className="text-accent-blue font-mono font-semibold truncate block max-w-full" title={progressDetailed.current_file}>
                {progressDetailed.current_file}
              </span>
            </div>
          )}

          {/* Sequential Step Timeline */}
          <div className="pt-3 border-t border-border/40">
            <span className="text-zinc-500 block uppercase font-bold text-[9px] tracking-wider mb-3">Scan Stages</span>
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

                let iconNode = <div className="w-4 h-4 rounded-full border border-zinc-700 bg-background" />;
                let textClass = "text-zinc-500";
                let containerBorder = "border-border/30 bg-zinc-900/10";

                if (isCompleted) {
                  iconNode = <Check className="w-3.5 h-3.5 text-accent-green" />;
                  textClass = "text-zinc-300 font-medium";
                  containerBorder = "border-green-500/20 bg-green-500/5";
                } else if (isActive) {
                  iconNode = <Loader2 className="w-3.5 h-3.5 text-accent-blue animate-spin" />;
                  textClass = "text-accent-blue font-bold";
                  containerBorder = "border-accent-blue/30 bg-accent-blue/5 shadow-md shadow-accent-blue/5";
                }

                return (
                  <div
                    key={idx}
                    className={`flex md:flex-col items-center gap-2 md:gap-1.5 p-2 rounded-lg border ${containerBorder} transition-all duration-150`}
                  >
                    <div className="flex items-center justify-center w-5 h-5">
                      {iconNode}
                    </div>
                    <span className={`text-[10px] md:text-center leading-tight ${textClass}`}>
                      {stageName}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Tabs Menu */}
      <div className="border-b border-border flex gap-4 mb-6">
        {[
          { id: "overview", name: "Overview" },
          { id: "explorer", name: "Code Explorer" },
          { id: "prs", name: `Pull Requests (${prs.length})` },
          { id: "security", name: "Security" },
          { id: "quality", name: "Code Quality" },
          { id: "tests", name: "Tests" },
          { id: "insights", name: "Insights" }
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`pb-3 text-xs font-semibold uppercase tracking-wider border-b-2 transition-colors ${
              activeTab === tab.id
                ? "border-accent-blue text-accent-blue"
                : "border-transparent text-zinc-400 hover:text-white"
            }`}
          >
            {tab.name}
          </button>
        ))}
      </div>

      {/* Tab Contents */}
      <div className="space-y-6">
        {/* Tab 1: Overview */}
        {activeTab === "overview" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left info */}
            <div className="lg:col-span-2 space-y-6">
              <div className="bg-surface border border-border rounded-xl p-6">
                <h3 className="font-bold text-white mb-4">Repository Analytics Dashboard</h3>
                <div className="grid grid-cols-3 gap-4 text-center">
                  <div className="bg-background border border-border p-4 rounded-lg">
                    <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider">Health Rating</p>
                    <h4 className="text-2xl font-extrabold mt-1 text-accent-green">
                      {activeAnalysis?.status === "completed" && activeAnalysis?.risk_score !== undefined
                        ? `${100 - activeAnalysis.risk_score}/100`
                        : activeAnalysis?.status === "pending" || activeAnalysis?.status === "running"
                          ? "..."
                          : "N/A"}
                    </h4>
                  </div>
                  <div className="bg-background border border-border p-4 rounded-lg">
                    <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider">Security Risks</p>
                    <h4 className="text-2xl font-extrabold mt-1 text-accent-red">
                      {activeAnalysis?.status === "completed" ? securityFindings.length : "-"}
                    </h4>
                  </div>
                  <div className="bg-background border border-border p-4 rounded-lg">
                    <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider">Smells & Issues</p>
                    <h4 className="text-2xl font-extrabold mt-1 text-accent-orange">
                      {activeAnalysis?.status === "completed" ? codeSmells.length : "-"}
                    </h4>
                  </div>
                </div>
              </div>

              {activeAnalysis?.status === "completed" && (
                <div className="bg-surface border border-border rounded-xl p-6">
                  <h3 className="font-bold text-white mb-4">AI Statistics</h3>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-center">
                    <div className="bg-background border border-border p-4 rounded-lg text-left">
                      <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider">Model</p>
                      <h4 className="text-[11px] font-bold mt-1 text-white truncate" title={activeAnalysis.model_name || "llama-3.3-70b-versatile"}>
                        {activeAnalysis.model_name || "llama-3.3-70b-versatile"}
                      </h4>
                    </div>
                    <div className="bg-background border border-border p-4 rounded-lg">
                      <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider">Files</p>
                      <h4 className="text-xl font-extrabold mt-1 text-white">
                        {activeAnalysis.files_analyzed_count || "-"}
                      </h4>
                    </div>
                    <div className="bg-background border border-border p-4 rounded-lg">
                      <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider">Tokens</p>
                      <h4 className="text-xl font-extrabold mt-1 text-white">
                        {activeAnalysis.total_tokens !== undefined && activeAnalysis.total_tokens > 0 
                          ? activeAnalysis.total_tokens 
                          : (activeAnalysis.estimated_token_usage || "-")}
                      </h4>
                    </div>
                    <div className="bg-background border border-border p-4 rounded-lg">
                      <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider">Duration</p>
                      <h4 className="text-xl font-extrabold mt-1 text-white">
                        {activeAnalysis.scan_duration_seconds !== undefined && activeAnalysis.scan_duration_seconds > 0
                          ? `${activeAnalysis.scan_duration_seconds}s`
                          : (activeAnalysis.latency_seconds > 0 ? `${activeAnalysis.latency_seconds}s` : "-")}
                      </h4>
                    </div>
                    <div className="bg-background border border-border p-4 rounded-lg">
                      <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider">Cache</p>
                      <h4 className={`text-xl font-extrabold mt-1 ${
                        activeAnalysis.cached_results_used > 0 ? "text-accent-green" : "text-zinc-400"
                      }`}>
                        {activeAnalysis.cached_results_used > 0 ? "Enabled" : "Disabled"}
                      </h4>
                    </div>
                  </div>
                </div>
              )}

              {/* Analysis history list */}
              <div className="bg-surface border border-border rounded-xl p-6">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="font-bold text-white">Historical Scans</h3>
                  {analyses.length > 0 && (
                    <button
                      onClick={() => setShowDeleteAllModal(true)}
                      className="text-[10px] font-bold uppercase text-red-400 hover:text-red-300 border border-red-500/20 px-2.5 py-1.5 rounded bg-red-500/5 hover:bg-red-500/10 transition-colors"
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
                        className={`p-4 bg-background border rounded-lg flex justify-between items-center cursor-pointer hover:border-zinc-500 ${
                          activeAnalysis?.id === an.id ? "border-accent-blue" : "border-border"
                        }`}
                      >
                        <div className="text-xs">
                          <p className="font-bold text-white">
                            Scan on branch {activeRepo.default_branch}
                          </p>
                          <span className="text-[10px] text-zinc-500 block mt-1">
                            {new Date(an.timestamp).toLocaleString()}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-xs font-semibold">
                          <span className={an.status === "completed" ? "text-accent-green" : "text-zinc-500"}>
                            {an.status}
                          </span>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-extrabold ${
                            an.risk_score > 60 ? "bg-red-500/10 text-red-400" : "bg-green-500/10 text-green-400"
                          }`}>
                            Risk: {an.risk_score}
                          </span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setScanToDelete(an.id);
                            }}
                            className="text-red-400 hover:text-red-300 hover:bg-red-500/10 border border-red-500/20 px-2.5 py-1 rounded text-[10px] font-bold uppercase tracking-wider transition-colors"
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-zinc-500 text-xs py-4">No scan reports recorded yet. Click Scan Repository.</p>
                )}
              </div>
            </div>

            {/* Right exports / actions */}
            <div className="space-y-4">
              {/* Export Reports */}
              <div className="bg-surface border border-border rounded-xl p-6">
                <div>
                  <h3 className="font-bold text-white mb-2">Export Scans Reports</h3>
                  <p className="text-xs text-muted mb-6">Download the latest completed AI code review findings.</p>
                </div>

                {activeAnalysis && activeAnalysis.status === "completed" ? (
                  <div className="grid grid-cols-2 gap-3">
                    <button onClick={() => handleDownload("PDF")} className="flex items-center justify-center gap-2 border border-border hover:bg-zinc-800 py-2.5 rounded-lg text-xs text-white">
                      <Download className="w-3.5 h-3.5" /> PDF
                    </button>
                    <button onClick={() => handleDownload("Markdown")} className="flex items-center justify-center gap-2 border border-border hover:bg-zinc-800 py-2.5 rounded-lg text-xs text-white">
                      <Download className="w-3.5 h-3.5" /> Markdown
                    </button>
                    <button onClick={() => handleDownload("JSON")} className="flex items-center justify-center gap-2 border border-border hover:bg-zinc-800 py-2.5 rounded-lg text-xs text-white">
                      <Download className="w-3.5 h-3.5" /> JSON
                    </button>
                    <button onClick={() => handleDownload("CSV")} className="flex items-center justify-center gap-2 border border-border hover:bg-zinc-800 py-2.5 rounded-lg text-xs text-white">
                      <Download className="w-3.5 h-3.5" /> CSV
                    </button>
                  </div>
                ) : (
                  <div className="text-center text-muted text-xs p-4 bg-background/50 border border-dashed border-border rounded-lg">
                    No completed analysis selected.
                  </div>
                )}
              </div>

              {/* Validate Fix & Deploy */}
              {activeAnalysis && activeAnalysis.status === "completed" && (
                <div className="bg-surface border border-border rounded-xl p-6">
                  <h3 className="font-bold text-white mb-2">Code Remediation</h3>
                  <p className="text-xs text-muted mb-4">Validate your manual edits or deploy changes to GitHub.</p>
                  <div className="space-y-3">
                    <button
                      onClick={handleValidateFix}
                      disabled={validating || !openFilePath || !editorUnsaved}
                      className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-accent-green/10 hover:bg-accent-green/20 border border-accent-green/30 disabled:opacity-40 text-accent-green font-semibold text-xs rounded-lg transition-all"
                    >
                      {validating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />}
                      Validate Fix
                    </button>
                    <button
                      onClick={handleDeployChanges}
                      disabled={deployLoading}
                      className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-accent-blue/10 hover:bg-accent-blue/20 border border-accent-blue/30 disabled:opacity-40 text-accent-blue font-semibold text-xs rounded-lg transition-all"
                    >
                      {deployLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <GitBranch className="w-3.5 h-3.5" />}
                      Deploy Changes
                    </button>
                    <button
                      onClick={() => handlePushToGitHub()}
                      disabled={pushingToGitHub || !openFilePath || !editorUnsaved}
                      className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-accent-green/15 hover:bg-accent-green/25 border border-accent-green/30 disabled:opacity-40 text-accent-green font-semibold text-xs rounded-lg transition-all"
                    >
                      {pushingToGitHub ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <GitBranch className="w-3.5 h-3.5" />}
                      Push To GitHub
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab: Code Explorer */}
        {activeTab === "explorer" && (
          <div className="bg-surface border border-border rounded-xl p-4 flex gap-6 h-[720px] font-sans">
            {/* File Tree Explorer (25% width) */}
            <div className="w-1/4 border-r border-border/60 pr-4 flex flex-col h-full overflow-y-auto">
              <div className="flex justify-between items-center mb-3">
                <span className="text-[10px] uppercase font-bold text-zinc-400 tracking-wider">File Explorer</span>
                <button
                  onClick={fetchExplorerTree}
                  className="text-zinc-500 hover:text-white transition-colors"
                  title="Refresh Directory tree"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${explorerLoading ? "animate-spin" : ""}`} />
                </button>
              </div>
              
              {explorerLoading ? (
                <div className="flex flex-col items-center justify-center py-24 gap-2">
                  <Loader2 className="w-5 h-5 text-accent-blue animate-spin" />
                  <span className="text-[10px] text-zinc-500">Retrieving directory tree...</span>
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
                <div className="text-center py-20 text-[11px] text-zinc-600">
                  No files indexed or repository empty.
                </div>
              )}
            </div>
            
            {/* Monaco Editor (75% width) */}
            <div className="flex-1 flex flex-col h-full bg-zinc-950/20 rounded-xl border border-border/50 overflow-hidden relative">
              {openFilePath ? (
                <div className="flex-1 flex flex-col h-full">
                  <div className="px-4 py-3 border-b border-border bg-zinc-900/40 flex justify-between items-center text-xs">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span className="font-mono text-white font-bold truncate">{openFilePath.split("/").pop()}</span>
                      <span className="text-[10px] font-mono text-zinc-500 truncate">{openFilePath}</span>
                      {editorUnsaved && (
                        <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse shrink-0" title="Unsaved changes" />
                      )}
                    </div>
                    
                    <button
                      onClick={() => setShowCommitModal(true)}
                      disabled={!editorUnsaved}
                      className="px-3.5 py-2 bg-accent-blue hover:bg-blue-600 disabled:opacity-40 disabled:hover:bg-accent-blue text-white rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 shrink-0"
                    >
                      <Save className="w-3.5 h-3.5" />
                      Save File
                    </button>
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
                      onChange={(val) => {
                        setOpenFileContent(val || "");
                        setEditorUnsaved((val || "") !== editorOriginalContent);
                      }}
                      onMount={handleEditorDidMount}
                      options={{
                        minimap: { enabled: false },
                        fontSize: 13,
                        lineNumbers: "on",
                        automaticLayout: true
                      }}
                    />
                  </div>
                </div>
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center text-center p-6 text-zinc-500">
                  <Code className="w-12 h-12 text-zinc-800 mb-3" />
                  <p className="text-xs font-semibold text-zinc-400">Inline Code Editor</p>
                  <p className="text-[11px] text-zinc-600 mt-1.5 max-w-xs leading-relaxed">
                    Select a source file from the directory tree to inspect, edit, or patch it directly in your browser.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab 2: Pull Requests */}
        {activeTab === "prs" && (
          <div className="bg-surface border border-border rounded-xl p-6">
            <h3 className="font-bold text-white mb-4">Open Pull Requests</h3>
            {prs.length > 0 ? (
              <div className="divide-y divide-border/60">
                {prs.map((pr) => (
                  <div
                    key={pr.id}
                    onClick={() => onSelectPr(pr)}
                    className="py-4 first:pt-0 last:pb-0 flex justify-between items-center cursor-pointer hover:bg-zinc-800/20 px-3 rounded-lg transition-colors"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <GitPullRequest className="w-4 h-4 text-accent-green" />
                        <h4 className="font-bold text-sm text-white hover:text-accent-blue transition-colors">
                          #{pr.number}: {pr.title}
                        </h4>
                      </div>
                      <p className="text-xs text-muted mt-1">Opened by @{pr.author} | {pr.head_sha.slice(0, 7)}</p>
                    </div>
                    <div className="flex items-center gap-4 text-xs font-semibold">
                      <span className="text-accent-green">+{pr.additions}</span>
                      <span className="text-accent-red">-{pr.deletions}</span>
                      <ArrowLeft className="w-4 h-4 rotate-180 text-zinc-400" />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center text-muted text-xs py-8 bg-background/50 border border-dashed border-border rounded-lg">
                No active pull requests found in this repository.
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Security Findings */}
        {activeTab === "security" && (
          <div className="bg-surface border border-border rounded-xl p-6">
            <h3 className="font-bold text-white mb-4">Security Findings ({securityFindings.length})</h3>
            {securityFindings.length > 0 ? (
              <div className="space-y-4">
                {securityFindings.map((finding) => (
                  <div
                    key={finding.id}
                    className="bg-background border border-border p-5 rounded-xl flex flex-col justify-between"
                  >
                    <div className="flex justify-between items-start mb-3">
                      <div className="flex items-start gap-3">
                        <div>
                          <span className="text-[10px] text-accent-red font-bold uppercase px-2 py-0.5 bg-red-500/10 rounded-full border border-red-500/20">
                            {finding.severity}
                          </span>
                          <h4 className="font-bold text-sm text-white mt-2">{finding.issue}</h4>
                          <p className="text-xs text-zinc-400 mt-1">File: `{finding.file}` | Line {finding.line}</p>
                        </div>
                      </div>
                    </div>
                    
                    <div className="text-xs text-zinc-300 mt-2 space-y-2">
                      <p><span className="font-bold text-zinc-400 block mb-0.5">Why it matters:</span> {finding.why_it_matters}</p>
                      <p><span className="font-bold text-zinc-400 block mb-0.5">Remediation Steps:</span> {finding.suggestion}</p>
                    </div>

                    {finding.after_code && (
                      <div className="mt-4">
                        <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest block mb-2">Suggested Remediation</span>
                        <pre className="p-4 bg-zinc-900 border border-border rounded-lg text-zinc-300 font-mono text-xs overflow-x-auto whitespace-pre-wrap">
                          {finding.after_code}
                        </pre>
                      </div>
                    )}

                    <div className="mt-4 pt-4 border-t border-border/40 flex justify-between items-center font-sans">
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleJumpToLine(finding.file, finding.line)}
                          className="px-3 py-1.5 border border-border hover:bg-zinc-800 text-zinc-300 hover:text-white rounded-lg text-xs font-semibold transition-colors flex items-center gap-1.5"
                        >
                          <ExternalLink className="w-3 h-3" /> Open in Editor
                        </button>
                        <button
                          onClick={() => handleExplainFinding(finding.id, "security")}
                          className="px-3 py-1.5 border border-border hover:bg-zinc-800 text-zinc-300 hover:text-white rounded-lg text-xs font-semibold transition-colors flex items-center gap-1.5"
                        >
                          <Lightbulb className="w-3 h-3" />
                          Explain Issue
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center text-muted text-xs py-8 bg-background/50 border border-dashed border-border rounded-lg">
                No security findings available. Perform scan first.
              </div>
            )}
          </div>
        )}

        {/* Tab 4: Code Quality */}
        {activeTab === "quality" && (
          <div className="bg-surface border border-border rounded-xl p-6">
            <h3 className="font-bold text-white mb-4">Code Smells & Maintainability ({codeSmells.length})</h3>
            {codeSmells.length > 0 ? (
              <div className="space-y-4">
                {codeSmells.map((smell) => (
                  <div
                    key={smell.id}
                    className="bg-background border border-border p-5 rounded-xl flex flex-col justify-between"
                  >
                    <div className="flex justify-between items-start mb-3">
                      <div className="flex items-start gap-3">
                        <div>
                          <span className="text-[10px] text-accent-orange font-bold uppercase px-2 py-0.5 bg-orange-500/10 rounded-full border border-orange-500/20">
                            {smell.severity}
                          </span>
                          <h4 className="font-bold text-sm text-white mt-2">{smell.issue}</h4>
                          <p className="text-xs text-zinc-400 mt-1">File: `{smell.file}` | Line {smell.line}</p>
                        </div>
                      </div>
                    </div>
                    
                    <div className="text-xs text-zinc-300 mt-2 space-y-2">
                      <p><span className="font-bold text-zinc-400 block mb-0.5">Explanation:</span> {smell.why_it_matters}</p>
                      <p><span className="font-bold text-zinc-400 block mb-0.5">Refactoring suggestion:</span> {smell.suggestion}</p>
                    </div>

                    {smell.before_code && (
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
                        <div>
                          <span className="text-[10px] font-bold text-accent-red uppercase tracking-widest block mb-2">Before (Smell):</span>
                          <pre className="p-3 bg-red-950/20 border border-red-900/30 rounded-lg text-zinc-300 font-mono text-xs overflow-x-auto whitespace-pre-wrap">
                            {smell.before_code}
                          </pre>
                        </div>
                        <div>
                          <span className="text-[10px] font-bold text-accent-green uppercase tracking-widest block mb-2">Suggested Code:</span>
                          <pre className="p-3 bg-green-950/20 border border-green-900/30 rounded-lg text-zinc-300 font-mono text-xs overflow-x-auto whitespace-pre-wrap">
                            {smell.after_code}
                          </pre>
                        </div>
                      </div>
                    )}

                    <div className="mt-4 pt-4 border-t border-border/40 flex justify-between items-center font-sans">
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleJumpToLine(smell.file, smell.line)}
                          className="px-3 py-1.5 border border-border hover:bg-zinc-800 text-zinc-300 hover:text-white rounded-lg text-xs font-semibold transition-colors flex items-center gap-1.5"
                        >
                          <ExternalLink className="w-3 h-3" /> Open in Editor
                        </button>
                        <button
                          onClick={() => handleExplainFinding(smell.id, "code_smell")}
                          className="px-3 py-1.5 border border-border hover:bg-zinc-800 text-zinc-300 hover:text-white rounded-lg text-xs font-semibold transition-colors flex items-center gap-1.5"
                        >
                          <Lightbulb className="w-3 h-3" /> Explain Issue
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center text-muted text-xs py-8 bg-background/50 border border-dashed border-border rounded-lg">
                No code quality smells logged. Perform scan first.
              </div>
            )}
          </div>
        )}

        {/* Tab 5: Tests */}
        {activeTab === "tests" && (
          <div className="bg-surface border border-border rounded-xl p-6">
            <h3 className="font-bold text-white mb-4">Generated QA Test Templates</h3>
            {testSuggestions ? (
              <pre className="p-5 bg-background border border-border rounded-xl text-zinc-300 text-xs overflow-x-auto whitespace-pre-wrap font-mono">
                {testSuggestions}
              </pre>
            ) : (
              <div className="text-center text-muted text-xs py-8 bg-background/50 border border-dashed border-border rounded-lg">
                No test suggestions generated. Perform scan first.
              </div>
            )}
          </div>
        )}

        {/* Tab 6: Insights */}
        {activeTab === "insights" && (
          <div className="bg-surface border border-border rounded-xl p-6">
            <h3 className="font-bold text-white mb-4">Qualitative Engineering Report</h3>
            {activeAnalysis?.insights ? (
              <div className="prose prose-invert max-w-none text-sm text-zinc-300 whitespace-pre-wrap leading-relaxed">
                {activeAnalysis.insights}
              </div>
            ) : (
              <div className="text-center text-muted text-xs py-8 bg-background/50 border border-dashed border-border rounded-lg">
                No engineering insights loaded. Perform scan first.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Explain Finding Modal */}
      {explainFinding && (
        <div className="fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-[60] p-4 animate-in fade-in duration-150">
          <div className="bg-surface border border-border w-full max-w-2xl rounded-2xl shadow-2xl flex flex-col max-h-[80vh] overflow-hidden">
            <div className="px-6 py-4 border-b border-border flex justify-between items-center bg-zinc-900/50">
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-accent-blue bg-accent-blue/10 px-2 py-0.5 rounded border border-accent-blue/20">
                  AI Deep Insights
                </span>
                <h3 className="text-md font-bold text-white mt-1.5">
                  Vulnerability Root-Cause Analysis
                </h3>
              </div>
              <button
                onClick={() => setExplainFinding(null)}
                className="text-zinc-400 hover:text-white p-1 rounded-lg hover:bg-zinc-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-6 text-xs text-zinc-300 leading-relaxed space-y-4 font-sans">
              {explainLoading ? (
                <div className="flex flex-col items-center justify-center py-20 gap-3">
                  <div className="w-10 h-10 border-4 border-accent-blue/20 border-t-accent-blue rounded-full animate-spin" />
                  <span className="text-xs text-zinc-500">Generating markdown explanation from Groq...</span>
                </div>
              ) : explainResult ? (
                <div className="prose prose-invert prose-xs max-w-none space-y-4">
                  {explainResult.split("\n").map((line, idx) => {
                    if (line.startsWith("# ")) {
                      return <h2 key={idx} className="text-sm font-bold text-white border-b border-border/40 pb-1 mt-4">{line.replace("#", "").trim()}</h2>;
                    } else if (line.startsWith("## ")) {
                      return <h3 key={idx} className="text-xs font-bold text-white mt-3">{line.replace("##", "").trim()}</h3>;
                    } else if (line.startsWith("### ")) {
                      return <h4 key={idx} className="text-[11px] font-bold text-zinc-200 mt-2">{line.replace("###", "").trim()}</h4>;
                    } else if (line.startsWith("* ") || line.startsWith("- ")) {
                      return <li key={idx} className="ml-4 list-disc">{line.replace(/^[\s*-]+/, "").trim()}</li>;
                    } else if (line.trim().startsWith("```")) {
                      return null;
                    } else if (line.trim()) {
                      return <p key={idx} className="text-zinc-300">{line}</p>;
                    }
                    return <div key={idx} className="h-2" />;
                  })}
                </div>
              ) : (
                <p>No explanation generated.</p>
              )}
            </div>
            
            <div className="px-6 py-3 border-t border-border bg-zinc-900/30 flex justify-end">
              <button
                onClick={() => setExplainFinding(null)}
                className="px-4 py-2 border border-border text-xs rounded-lg hover:bg-zinc-800 text-white font-semibold transition-colors"
              >
                Close Explanation
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Direct Commit Save Modal */}
      {showCommitModal && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-in fade-in duration-150">
          <div className="bg-surface border border-border w-full max-w-md rounded-xl shadow-2xl flex flex-col overflow-hidden font-sans">
            <div className="px-5 py-4 border-b border-border bg-zinc-900/50 flex justify-between items-center">
              <span className="text-xs font-bold text-white uppercase tracking-wider">Commit File Updates</span>
              <button
                onClick={() => setShowCommitModal(false)}
                className="text-zinc-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <p className="text-xs text-zinc-400">
                You are about to commit your changes directly to the <strong>{activeRepo?.default_branch}</strong> branch of the GitHub repository. This will automatically queue a background re-scan.
              </p>
              
              <div className="space-y-1.5">
                <label className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Commit Message</label>
                <input
                  type="text"
                  value={commitMsg}
                  onChange={(e) => setCommitMsg(e.target.value)}
                  placeholder="Direct code update from browser"
                  className="w-full bg-background border border-border rounded-lg text-white text-xs px-3 py-2.5 focus:outline-none focus:border-accent-blue"
                />
              </div>
            </div>
            
            <div className="px-5 py-3 border-t border-border bg-zinc-900/30 flex justify-end gap-3">
              <button
                onClick={() => setShowCommitModal(false)}
                disabled={saveLoading}
                className="px-4 py-2 border border-border text-xs rounded-lg hover:bg-zinc-800 text-zinc-400 hover:text-white font-semibold transition-colors disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveFile}
                disabled={saveLoading || !commitMsg.trim()}
                className="px-4 py-2 bg-accent-blue hover:bg-blue-600 disabled:opacity-40 text-white text-xs rounded-lg font-semibold transition-colors flex items-center gap-1.5"
              >
                {saveLoading ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Committing...
                  </>
                ) : (
                  <>
                    <Save className="w-3.5 h-3.5" />
                    Confirm Commit
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Scan Confirmation Modal */}
      {scanToDelete && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-in fade-in duration-200">
          <div className="bg-surface border border-border w-full max-w-sm rounded-2xl p-6 shadow-2xl space-y-4">
            <h3 className="text-md font-bold text-white font-sans">Delete Scan?</h3>
            <p className="text-xs text-muted leading-relaxed font-sans">This action cannot be undone.</p>
            <div className="flex gap-3 pt-2 font-sans">
              <button
                onClick={() => setScanToDelete(null)}
                className="flex-1 border border-border hover:bg-zinc-800 text-zinc-400 hover:text-white font-semibold text-xs py-2.5 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  try {
                    await deleteAnalysis(scanToDelete);
                  } catch (err: any) {
                    alert(err.message || "Failed to delete scan");
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
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-in fade-in duration-200">
          <div className="bg-surface border border-border w-full max-w-sm rounded-2xl p-6 shadow-2xl space-y-4">
            <h3 className="text-md font-bold text-white font-sans">Delete ALL scans?</h3>
            <p className="text-xs text-muted leading-relaxed font-sans">This action cannot be undone.</p>
            <div className="flex gap-3 pt-2 font-sans">
              <button
                onClick={() => setShowDeleteAllModal(false)}
                className="flex-1 border border-border hover:bg-zinc-800 text-zinc-400 hover:text-white font-semibold text-xs py-2.5 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  try {
                    await deleteAllHistory();
                  } catch (err: any) {
                    alert(err.message || "Failed to delete all scans");
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
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-in fade-in duration-200 font-sans">
          <div className="bg-surface border border-border w-full max-w-sm rounded-2xl p-6 shadow-2xl space-y-4">
            <h3 className="text-md font-bold text-white">Disconnect Repository?</h3>
            <p className="text-xs text-muted leading-relaxed">
              Disconnecting will hide this repository from your active workspace but keep its history intact. You can reconnect it at any time.
            </p>
            <div className="flex gap-3 pt-2">
              <button
                onClick={() => setShowDisconnectModal(false)}
                disabled={actionLoading}
                className="flex-1 border border-border hover:bg-zinc-800 text-zinc-400 hover:text-white font-semibold text-xs py-2.5 rounded-lg transition-colors"
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
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-in fade-in duration-200 font-sans">
          <div className="bg-surface border border-border w-full max-w-sm rounded-2xl p-6 shadow-2xl space-y-4">
            <h3 className="text-md font-bold text-accent-red">Hard Delete Repository?</h3>
            <p className="text-xs text-muted leading-relaxed">
              This will permanently delete the repository registration, all scan history, reports, code findings, and patches from the system. <strong>This action cannot be undone.</strong>
            </p>
            <div className="flex gap-3 pt-2">
              <button
                onClick={() => setShowDeleteRepoModal(false)}
                disabled={actionLoading}
                className="flex-1 border border-border hover:bg-zinc-800 text-zinc-400 hover:text-white font-semibold text-xs py-2.5 rounded-lg transition-colors"
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

      {/* Validate Fix Modal */}
      {showValidateModal && (
        <div className="fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-[60] p-4 animate-in fade-in duration-150">
          <div className="bg-surface border border-border w-full max-w-lg rounded-2xl shadow-2xl flex flex-col max-h-[70vh] overflow-hidden">
            <div className="px-6 py-4 border-b border-border flex justify-between items-center bg-zinc-900/50">
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-accent-green bg-accent-green/10 px-2 py-0.5 rounded border border-accent-green/20">
                  Validate Fix
                </span>
                <h3 className="text-md font-bold text-white mt-1.5">Re-Scan Validation Results</h3>
              </div>
              <button
                onClick={() => { setShowValidateModal(false); setValidateResult(null); }}
                className="text-zinc-400 hover:text-white p-1 rounded-lg hover:bg-zinc-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-6 text-xs text-zinc-300 space-y-4">
              {validating ? (
                <div className="flex flex-col items-center justify-center py-16 gap-3">
                  <div className="w-10 h-10 border-4 border-accent-green/20 border-t-accent-green rounded-full animate-spin" />
                  <span className="text-xs text-zinc-500">Re-scanning edited file...</span>
                </div>
              ) : validateResult ? (
                <div className="space-y-6">
                  <div className={`p-4 rounded-xl border text-center ${
                    validateResult.status === "fixed" ? "bg-green-500/10 border-green-500/20" :
                    validateResult.status === "partially_fixed" ? "bg-amber-500/10 border-amber-500/20" :
                    validateResult.status === "not_fixed" ? "bg-red-500/10 border-red-500/20" :
                    "bg-zinc-800/30 border-zinc-700"
                  }`}>
                    <span className={`text-2xl font-extrabold ${
                      validateResult.status === "fixed" ? "text-accent-green" :
                      validateResult.status === "partially_fixed" ? "text-amber-400" :
                      "text-accent-red"
                    }`}>
                      {validateResult.status === "fixed" ? "Fixed" :
                       validateResult.status === "partially_fixed" ? "Partially Fixed" :
                       validateResult.status === "not_fixed" ? "Not Fixed" :
                       validateResult.status}
                    </span>
                    <p className="text-xs mt-2 text-zinc-400">{validateResult.details}</p>
                  </div>

                  {validateResult.remaining_issues && validateResult.remaining_issues.length > 0 && (
                    <div>
                      <h4 className="font-bold text-white mb-3 text-sm">Remaining Issues ({validateResult.remaining_issues.length})</h4>
                      <div className="space-y-3">
                        {validateResult.remaining_issues.map((issue: any, idx: number) => (
                          <div key={idx} className="bg-zinc-900/60 border border-zinc-800 p-3 rounded-lg">
                            <div className="flex items-center gap-2 mb-1">
                              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                issue.severity === "Critical" || issue.severity === "High"
                                  ? "bg-red-500/10 text-red-400" : "bg-amber-500/10 text-amber-400"
                              }`}>{issue.severity}</span>
                              <span className="font-semibold text-white text-xs">{issue.issue}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-center text-zinc-500 py-8">No validation data available.</p>
              )}
            </div>
            
            <div className="px-6 py-3 border-t border-border bg-zinc-900/30 flex justify-end">
              <button
                onClick={() => { setShowValidateModal(false); setValidateResult(null); }}
                className="px-4 py-2 border border-border text-xs rounded-lg hover:bg-zinc-800 text-white font-semibold transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Deploy Changes Modal */}
      {showDeployModal && (
        <div className="fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-[60] p-4 animate-in fade-in duration-150">
          <div className="bg-surface border border-border w-full max-w-2xl rounded-2xl shadow-2xl flex flex-col max-h-[85vh] overflow-hidden">
            <div className="px-6 py-4 border-b border-border flex justify-between items-center bg-zinc-900/50">
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-accent-blue bg-accent-blue/10 px-2 py-0.5 rounded border border-accent-blue/20">
                  Deploy Changes
                </span>
                <h3 className="text-md font-bold text-white mt-1.5">AI-Generated Deployment Instructions</h3>
              </div>
              <button
                onClick={() => { setShowDeployModal(false); setDeployInstructions(null); }}
                className="text-zinc-400 hover:text-white p-1 rounded-lg hover:bg-zinc-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-6 text-xs text-zinc-300 space-y-6">
              {deployLoading ? (
                <div className="flex flex-col items-center justify-center py-16 gap-3">
                  <div className="w-10 h-10 border-4 border-accent-blue/20 border-t-accent-blue rounded-full animate-spin" />
                  <span className="text-xs text-zinc-500">Generating deployment instructions...</span>
                </div>
              ) : deployInstructions ? (
                <div className="space-y-6">
                  <div>
                    <h4 className="font-bold text-white mb-3 flex items-center gap-2">
                      <GitBranch className="w-4 h-4 text-accent-blue" />
                      Steps to Deploy
                    </h4>
                    <div className="space-y-2">
                      {deployInstructions.steps.map((step: string, idx: number) => (
                        <div key={idx} className="flex items-start gap-3 p-3 bg-zinc-900/60 border border-zinc-800 rounded-lg">
                          <span className="w-5 h-5 rounded-full bg-accent-blue/20 text-accent-blue flex items-center justify-center text-[10px] font-bold shrink-0">
                            {idx + 1}
                          </span>
                          <code className="font-mono text-xs text-zinc-200 break-all">{step}</code>
                        </div>
                      ))}
                    </div>
                  </div>

                  {deployInstructions.commit_suggestion && (
                    <div className="bg-zinc-900/40 border border-zinc-800 rounded-xl p-4">
                      <h4 className="font-bold text-white mb-2 text-sm">Commit Message Suggestion</h4>
                      <code className="block p-3 bg-black/50 border border-zinc-800 rounded-lg font-mono text-xs text-accent-green break-all">
                        {deployInstructions.commit_suggestion}
                      </code>
                    </div>
                  )}

                  {deployInstructions.pr_title_suggestion && (
                    <div className="bg-zinc-900/40 border border-zinc-800 rounded-xl p-4">
                      <h4 className="font-bold text-white mb-2 text-sm">PR Title Suggestion</h4>
                      <p className="text-xs text-zinc-300">{deployInstructions.pr_title_suggestion}</p>
                    </div>
                  )}

                  {deployInstructions.pr_description_suggestion && (
                    <div className="bg-zinc-900/40 border border-zinc-800 rounded-xl p-4">
                      <h4 className="font-bold text-white mb-2 text-sm">PR Description Suggestion</h4>
                      <pre className="whitespace-pre-wrap text-xs text-zinc-300 font-sans leading-relaxed">
                        {deployInstructions.pr_description_suggestion}
                      </pre>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-center text-zinc-500 py-8">No instructions available.</p>
              )}
            </div>
            
            <div className="px-6 py-3 border-t border-border bg-zinc-900/30 flex justify-between items-center">
              <p className="text-[10px] text-zinc-500">Never modify files automatically. Review before deploying.</p>
              <button
                onClick={() => { setShowDeployModal(false); setDeployInstructions(null); }}
                className="px-4 py-2 border border-border text-xs rounded-lg hover:bg-zinc-800 text-white font-semibold transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
