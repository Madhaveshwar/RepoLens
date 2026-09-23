import React, { useEffect, useState } from "react";
import axios from "../lib/api";
import { useRepositoryStore } from "../store/repositoryStore";
import { useAnalysisStore } from "../store/analysisStore";
import { useAuthStore } from "../store/authStore";
import { useQuery } from "@tanstack/react-query";
import { Markdown } from "../components/Markdown";
import {
  ArrowLeft, GitPullRequest, Loader2, CheckCircle2, MessageSquare, FileText, Send,
  Lightbulb, Settings, X
} from "lucide-react";

interface PRReviewProps {
  onBack: () => void;
}

interface PRFile {
  filename: string;
  additions: number;
  deletions: number;
  changes: number;
  status: string;
  patch: string;
  raw_url: string;
  findings: any[];
}

export const PRReview: React.FC<PRReviewProps> = ({ onBack }) => {
  const { activeRepo, activePr } = useRepositoryStore();
  const { triggerAnalysis, progress, resetProgress } = useAnalysisStore();
  const { user } = useAuthStore();
  const hasAiProvider = user ? (
    user.has_groq_api_key || user.has_openai_api_key ||
    user.has_claude_api_key || user.has_gemini_api_key || user.has_openrouter_api_key
  ) : false;
  const hasGithubToken = user?.has_github_pat || false;

  const [files, setFiles] = useState<PRFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<PRFile | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [postingReview, setPostingReview] = useState(false);
  const [postMessage, setPostMessage] = useState<string | null>(null);
  const [explainingId, setExplainingId] = useState<string | null>(null);
  const [explainText, setExplainText] = useState<string | null>(null);
  const [explainError, setExplainError] = useState<string | null>(null);


  const { data: prFilesData, isLoading: loadingFiles, refetch: refetchPrFiles } = useQuery({
    queryKey: ["prFiles", activePr?.id],
    queryFn: async () => {
      if (!activePr) return null;
      const res = await axios.get(`/pull-requests/${activePr.id}/files`);
      return res.data;
    },
    enabled: !!activePr,
    staleTime: 30000,
    gcTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    if (prFilesData) {
      setFiles(prFilesData.files);
      setAnalysisId(prFilesData.analysis_id);
      if (prFilesData.files.length > 0 && !selectedFile) {
        setSelectedFile(prFilesData.files[0]);
      }
    }
  }, [prFilesData]);

  const handleRunAnalysis = async () => {
    if (!activeRepo || !activePr) return;
    try {
      resetProgress();
      await triggerAnalysis(activeRepo.id, activePr.number);
      refetchPrFiles();
    } catch {
      // Analysis trigger failed
    }
  };

  const handlePostReview = async () => {
    if (!activePr) return;
    setPostingReview(true);
    setPostMessage(null);
    try {
      const res = await axios.post(`/pull-requests/${activePr.id}/post-review`);
      setPostMessage(`Review posted! ${res.data.posted_inline} inline comments.`);
    } catch (err: any) {
      setPostMessage(`Error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setPostingReview(false);
    }
  };

  const handleExplain = async (findingId: string, issueType: string) => {
    setExplainingId(findingId);
    setExplainError(null);
    setExplainText(null);
    try {
      const res = await axios.post("/analysis/explain", { finding_id: findingId, issue_type: issueType === "Security" ? "security" : "code_smell" });
      setExplainText(res.data.explanation);
    } catch (err: any) {
      setExplainError(err.response?.data?.detail || err.message || "Failed to generate explanation.");
    } finally {
      setExplainingId(null);
    }
  };

  if (!activePr || !activeRepo) return null;

  // Guard: AI Provider not connected
  if (!hasAiProvider) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center h-screen bg-background p-8">
        <div className="glass-card max-w-md w-full p-8 text-center">
          <Settings className="w-12 h-12 mx-auto mb-4 text-amber-500" />
          <h2 className="text-lg font-bold text-zinc-900 mb-2">AI Provider Not Connected</h2>
          <p className="text-sm text-zinc-600 mb-6">
            Please connect Groq or OpenAI in Settings to run PR reviews.
          </p>
          <button onClick={onBack} className="btn-secondary mr-2">Go Back</button>
          <a href="/settings" onClick={(e) => { e.preventDefault(); window.location.hash = ""; }} className="btn-primary inline-flex items-center gap-2">
            <Settings className="w-4 h-4" /> Open Settings
          </a>
        </div>
      </div>
    );
  }

  // Guard: GitHub token not connected (needed for PR review)
  if (!hasGithubToken) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center h-screen bg-background p-8">
        <div className="glass-card max-w-md w-full p-8 text-center">
          <Settings className="w-12 h-12 mx-auto mb-4 text-amber-500" />
          <h2 className="text-lg font-bold text-zinc-900 mb-2">GitHub Token Required</h2>
          <p className="text-sm text-zinc-600 mb-6">
            Please connect a GitHub Token in Settings to review pull requests.
          </p>
          <button onClick={onBack} className="btn-secondary mr-2">Go Back</button>
          <a href="/settings" onClick={(e) => { e.preventDefault(); window.location.hash = ""; }} className="btn-primary inline-flex items-center gap-2">
            <Settings className="w-4 h-4" /> Open Settings
          </a>
        </div>
      </div>
    );
  }

  const showProgress = progress > 0 && progress < 100;

  const renderPatchDiff = (patchText: string) => {
    if (!patchText) {
      return <div className="h-full flex items-center justify-center text-xs text-zinc-600 dark:text-zinc-400">No diff available</div>;
    }
    const lines = patchText.split("\n");
    return (
      <div className="font-mono text-xs overflow-x-auto p-4 space-y-0.5 bg-zinc-50 dark:bg-zinc-900 h-full">
        {lines.map((line, idx) => {
          let lineBg = "bg-transparent";
          let lineText = "text-zinc-700 dark:text-zinc-300";
          if (line.startsWith("+")) { lineBg = "bg-accent-green/10 text-accent-green"; }
          else if (line.startsWith("-")) { lineBg = "bg-accent-red/10 text-accent-red"; }
          else if (line.startsWith("@@")) { lineBg = "bg-accent-blue/10 text-accent-blue font-semibold"; }
          return (
            <div key={idx} className={`flex ${lineBg} py-0.5 px-2 rounded`}>
              <span className="w-10 text-right select-none pr-3 text-zinc-500 dark:text-zinc-500 border-r border-border/40 mr-3">{idx + 1}</span>
              <span className={`whitespace-pre ${lineText}`}>{line}</span>
            </div>
          );
        })}
      </div>
    );
  };

  const mapSeverityClass = (sev: string) => {
    switch (sev) {
      case "Critical": case "High": return "border-l-accent-red bg-accent-red/10";
      case "Medium": return "border-l-accent-orange bg-accent-orange/10";
      default: return "border-l-accent-blue bg-accent-blue/10";
    }
  };

  return (
    <div className="flex-1 flex flex-col h-screen overflow-hidden bg-background">
      {/* Header */}
      <div className="bg-glass-gradient backdrop-blur-glass border-b border-border/60 px-6 py-4 flex justify-between items-center z-10">
        <div className="flex items-center gap-4">
          <button onClick={onBack} className="text-zinc-600 hover:text-zinc-900 p-1.5 rounded-xl hover:bg-white/5">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-accent-green/10 flex items-center justify-center">
              <GitPullRequest className="w-4 h-4 text-accent-green" />
            </div>
            <div>
              <span className="text-xs font-semibold text-zinc-600">{activeRepo.name}</span>
              <h2 className="font-bold text-zinc-900">PR #{activePr.number}: {activePr.title}</h2>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {analysisId && (
            <button onClick={handlePostReview} disabled={postingReview}
              className="btn-secondary flex items-center gap-2"
            >
              {postingReview ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Posting...</> : <><Send className="w-3 h-3" /> Post Review</>}
            </button>
          )}
          <button onClick={handleRunAnalysis} disabled={showProgress}
            className="btn-primary flex items-center gap-2"
          >
            {showProgress ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Scanning...</> : "Run PR Scan"}
          </button>
        </div>
      </div>

      {showProgress && (
        <div className="bg-white/[0.02] border-b border-border/40 px-6 py-3">
          <div className="flex justify-between text-xs font-semibold mb-2">
            <span className="text-accent-orange animate-pulse">Analyzing pull request...</span>
            <span className="text-zinc-900">{progress}%</span>
          </div>
          <div className="progress-bar">
            <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      {postMessage && (
        <div className="bg-accent-blue/10 border-b border-accent-blue/20 text-accent-blue px-6 py-2 text-xs text-center font-medium">{postMessage}</div>
      )}

      {loadingFiles ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3">
          <Loader2 className="w-8 h-8 animate-spin text-accent-blue" />
          <p className="text-base text-zinc-700">Loading changed files...</p>
        </div>
      ) : (
        <div className="flex-1 flex overflow-hidden">
          {/* File Tree */}
          <div className="w-64 bg-white/[0.02] border-r border-border/40 overflow-y-auto flex flex-col">
            <div className="p-4 border-b border-border/40 text-xs font-bold text-zinc-700 uppercase tracking-wider flex items-center gap-2">
              <FileText className="w-4 h-4 text-accent-blue" />
              Changed Files
            </div>
            <div className="flex-1 p-2 space-y-1">
              {files.map((file) => {
                const isSelected = selectedFile?.filename === file.filename;
                return (
                  <button key={file.filename} onClick={() => { setSelectedFile(file); setPostMessage(null); }}
                    className={`w-full text-left p-3 rounded-2xl transition-all duration-150 ${
                      isSelected ? "bg-accent-blue/10 border border-accent-blue/20" : "hover:bg-white/5 border border-transparent"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <FileText className="w-3.5 h-3.5 text-zinc-500 shrink-0" />
                      <span className={`text-xs font-semibold truncate ${isSelected ? "text-accent-blue" : "text-zinc-700"}`}>
                        {file.filename.split("/").pop()}
                      </span>
                    </div>
                    <div className="flex justify-between items-center text-[10px] text-zinc-600 mt-0.5 pl-5">
                      <span className="truncate">{file.filename}</span>
                      <span className="flex items-center gap-1 font-semibold shrink-0">
                        <span className="text-accent-green">+{file.additions}</span>
                        <span className="text-accent-red">-{file.deletions}</span>
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Diff Viewer */}
          <div className="flex-1 overflow-hidden flex flex-col bg-zinc-50">
            <div className="bg-white/[0.02] border-b border-border/30 px-4 py-3 text-xs text-zinc-700 flex items-center gap-2">
              <FileText className="w-3.5 h-3.5" />
              <span className="font-medium text-zinc-700">{selectedFile?.filename}</span>
              {selectedFile && (
                <span className="ml-auto flex items-center gap-2 text-[10px]">
                  <span className="text-accent-green">+{selectedFile.additions}</span>
                  <span className="text-accent-red">-{selectedFile.deletions}</span>
                </span>
              )}
            </div>
            <div className="flex-1 overflow-y-auto">
              {selectedFile ? renderPatchDiff(selectedFile.patch) : null}
            </div>
          </div>

          {/* Findings Panel */}
          <div className="w-80 bg-white/[0.02] border-l border-border/40 overflow-y-auto flex flex-col">
            <div className="p-4 border-b border-border/40 text-xs font-bold text-zinc-700 uppercase tracking-wider flex items-center gap-2">
              <MessageSquare className="w-4 h-4 text-accent-blue" />
              AI Findings ({selectedFile?.findings?.length || 0})
            </div>
            <div className="flex-1 p-4 space-y-3">
              {selectedFile && selectedFile.findings.length > 0 ? (
                selectedFile.findings.map((f: any, idx: number) => (
                  <div key={idx} className={`p-4 border-l-4 rounded-2xl border border-border/60 bg-background/40 ${mapSeverityClass(f.severity)} text-xs space-y-3`}>
                    <div className="flex justify-between items-start">
                      <p className="font-semibold text-zinc-900">{f.issue}</p>
                      <span className="badge bg-white/10 text-zinc-700 border-white/10">{f.severity}</span>
                    </div>
                    <div className="text-[10px] text-zinc-600 flex justify-between">
                      <span>Line {f.line}</span>
                      <span className="italic">{f.category}</span>
                    </div>
                    <p className="text-zinc-700 leading-relaxed">{f.suggestion}</p>
                    <div className="pt-2 border-t border-border/30 flex flex-wrap gap-2">
                      <button onClick={() => handleExplain(f.id, f.category)} disabled={explainingId === f.id}
                        className="px-2.5 py-1.5 bg-accent-blue/10 hover:bg-accent-blue/20 border border-accent-blue/20 text-accent-blue rounded-2xl text-[10px] font-bold transition-colors flex items-center gap-1"
                      ><Lightbulb className="w-3 h-3" /> Explain</button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-center text-zinc-600 p-6">
                  <div className="w-12 h-12 rounded-2xl bg-white/5 flex items-center justify-center mb-3">
                    <CheckCircle2 className="w-6 h-6 text-zinc-500" />
                  </div>
                  <p className="text-sm font-semibold text-zinc-700">No issues found</p>
                  <p className="text-xs text-zinc-600 mt-1">This file looks clean</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Explain Finding Modal (renders AI markdown properly) */}
      {(explainText || explainError) && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[70] p-4">
          <div className="bg-white border border-zinc-200 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col overflow-hidden">
            <div className="px-6 py-4 border-b border-zinc-200 flex justify-between items-center bg-zinc-50">
              <h3 className="text-sm font-bold text-zinc-900">AI Explanation</h3>
              <button
                onClick={() => { setExplainText(null); setExplainError(null); }}
                className="text-zinc-500 hover:text-zinc-900 p-1 rounded-lg hover:bg-zinc-100 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-6">
              {explainError ? (
                <div className="bg-red-50 border border-red-200 text-red-700 font-semibold p-3 rounded-xl text-xs">{explainError}</div>
              ) : (
                <Markdown content={explainText || ""} />
              )}
            </div>
          </div>
        </div>
      )}

    </div>
  );
};
