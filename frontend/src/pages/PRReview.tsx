import React, { useEffect, useState } from "react";
import axios from "../lib/api";
import { useRepositoryStore } from "../store/repositoryStore";
import { useAnalysisStore } from "../store/analysisStore";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, GitPullRequest, Loader2, CheckCircle2, MessageSquare, FileText, Send,
  Lightbulb
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
  const { triggerAnalysis, progress, progressStatus, resetProgress } = useAnalysisStore();

  const [files, setFiles] = useState<PRFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<PRFile | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);

  // Operations state
  const [postingReview, setPostingReview] = useState(false);
  const [postMessage, setPostMessage] = useState<string | null>(null);

  // Explain/Recommendation state
  const [explainingId, setExplainingId] = useState<string | null>(null);

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
    } catch (err) {
      console.error(err);
    }
  };

  const handlePostReview = async () => {
    if (!activePr) return;
    setPostingReview(true);
    setPostMessage(null);
    try {
      const res = await axios.post(`/pull-requests/${activePr.id}/post-review`);
      setPostMessage(`Review posted back! ${res.data.posted_inline} inline comments posted.`);
    } catch (err: any) {
      setPostMessage(`Error posting review: ${err.response?.data?.detail || err.message}`);
    } finally {
      setPostingReview(false);
    }
  };

  const handleExplain = async (findingId: string, issueType: string) => {
    setExplainingId(findingId);
    try {
      const res = await axios.post("/analysis/explain", {
        finding_id: findingId,
        issue_type: issueType === "Security" ? "security" : "code_smell"
      });
      alert(res.data.explanation);
    } catch (err: any) {
      alert("Failed to generate explanation: " + (err.response?.data?.detail || err.message));
    } finally {
      setExplainingId(null);
    }
  };

  if (!activePr || !activeRepo) return null;

  const showProgress = progress > 0 && progress < 100;

  const renderPatchDiff = (patchText: string) => {
    if (!patchText) {
      return (
        <div className="h-full flex items-center justify-center text-xs text-muted">
          No modifications in this file diff.
        </div>
      );
    }

    const lines = patchText.split("\n");

    return (
      <div className="font-mono text-xs overflow-x-auto p-4 space-y-0.5 bg-black h-full">
        {lines.map((line, idx) => {
          let lineBg = "bg-transparent";
          let lineText = "text-zinc-400";

          if (line.startsWith("+")) {
            lineBg = "bg-green-950/30 text-green-300";
          } else if (line.startsWith("-")) {
            lineBg = "bg-red-950/30 text-red-300";
          } else if (line.startsWith("@@")) {
            lineBg = "bg-zinc-900/60 text-accent-blue font-semibold";
          }

          return (
            <div key={idx} className={`flex ${lineBg} py-0.5 px-2 rounded`}>
              <span className="w-10 text-right select-none pr-3 text-zinc-600 border-r border-border/20 mr-3">
                {line.startsWith("+") || (!line.startsWith("-") && !line.startsWith("@@")) ? idx + 1 : ""}
              </span>
              <span className={`whitespace-pre ${lineText}`}>{line}</span>
            </div>
          );
        })}
      </div>
    );
  };

  const mapSeverityClass = (sev: string) => {
    switch (sev) {
      case "Critical":
      case "High":
        return "border-l-red-500 bg-red-500/10 text-red-400";
      case "Medium":
        return "border-l-orange-500 bg-orange-500/10 text-orange-400";
      default:
        return "border-l-blue-500 bg-blue-500/10 text-blue-400";
    }
  };

  return (
    <div className="flex-1 flex flex-col h-screen overflow-hidden bg-background">
      {/* Top Header */}
      <div className="bg-surface border-b border-border px-6 py-4 flex justify-between items-center z-10">
        <div className="flex items-center gap-4">
          <button onClick={onBack} className="text-zinc-400 hover:text-white p-1 rounded hover:bg-zinc-800">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="flex items-center gap-2">
            <GitPullRequest className="w-5 h-5 text-accent-green" />
            <span className="font-bold text-white truncate max-w-xs">{activeRepo.name}</span>
            <span className="text-muted">/</span>
            <span className="font-semibold text-zinc-300 truncate max-w-xs">PR #{activePr.number}</span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {analysisId && (
            <button
              onClick={handlePostReview}
              disabled={postingReview}
              className="flex items-center gap-2 border border-border hover:bg-zinc-800 disabled:opacity-50 text-white font-semibold text-xs px-3.5 py-2.5 rounded-lg transition-colors"
            >
              {postingReview ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Posting Comments...
                </>
              ) : (
                <>
                  <Send className="w-3 h-3" />
                  Post Review to GitHub
                </>
              )}
            </button>
          )}
          <button
            onClick={handleRunAnalysis}
            disabled={showProgress}
            className="flex items-center gap-2 bg-accent-blue hover:bg-blue-600 disabled:opacity-50 text-white font-semibold text-xs px-3.5 py-2.5 rounded-lg transition-colors"
          >
            {showProgress ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Auditing PR...
              </>
            ) : (
              "Run PR Scan"
            )}
          </button>
        </div>
      </div>

      {/* Progress alert */}
      {showProgress && (
        <div className="bg-surface border-b border-border px-6 py-3">
          <div className="flex justify-between text-[11px] font-semibold mb-1">
            <span className="text-accent-orange animate-pulse">{progressStatus}</span>
            <span className="text-white">{progress}%</span>
          </div>
          <div className="w-full bg-zinc-800 h-1.5 rounded-full overflow-hidden">
            <div className="bg-accent-orange h-full rounded-full transition-all duration-300" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      {postMessage && (
        <div className="bg-blue-500/10 border-b border-blue-500/20 text-accent-blue px-6 py-2 text-xs text-center font-medium">
          {postMessage}
        </div>
      )}

      {loadingFiles ? (
        <div className="flex-1 flex flex-col items-center justify-center">
          <Loader2 className="w-8 h-8 animate-spin text-accent-blue mb-2" />
          <p className="text-sm text-muted">Retrieving changed files...</p>
        </div>
      ) : (
        <div className="flex-1 flex overflow-hidden">
          {/* Column 1: Left Files Tree */}
          <div className="w-64 bg-surface border-r border-border overflow-y-auto flex flex-col">
            <div className="p-4 border-b border-border text-xs font-bold text-zinc-400 uppercase tracking-wider">
              Changed Files
            </div>
            <div className="flex-1 p-2 space-y-1">
              {files.map((file) => {
                const isSelected = selectedFile?.filename === file.filename;
                return (
                  <button
                    key={file.filename}
                    onClick={() => {
                      setSelectedFile(file);
                      setPostMessage(null);
                    }}
                    className={`w-full text-left p-3 rounded-lg flex flex-col gap-1 transition-colors duration-150 ${
                      isSelected ? "bg-accent-blue/10 border border-accent-blue/20" : "hover:bg-zinc-800/40"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-zinc-400 shrink-0" />
                      <span className={`text-xs font-semibold truncate ${isSelected ? "text-accent-blue" : "text-zinc-300"}`}>
                        {file.filename.split("/").pop()}
                      </span>
                    </div>
                    <div className="text-[10px] text-muted flex items-center justify-between pl-6 mt-0.5">
                      <span className="truncate max-w-[120px]">{file.filename}</span>
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

          {/* Column 2: Center Diff Viewer */}
          <div className="flex-1 overflow-hidden flex flex-col bg-black">
            <div className="bg-surface/50 border-b border-border/40 px-4 py-3 text-xs text-zinc-400 flex items-center gap-2">
              <FileText className="w-3.5 h-3.5" />
              <span>{selectedFile?.filename}</span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {selectedFile ? renderPatchDiff(selectedFile.patch) : null}
            </div>
          </div>

          {/* Column 3: Right Findings */}
          <div className="w-80 bg-surface border-l border-border overflow-y-auto flex flex-col">
            <div className="p-4 border-b border-border text-xs font-bold text-zinc-400 uppercase tracking-wider flex items-center gap-2">
              <MessageSquare className="w-4 h-4 text-accent-blue" />
              <span>AI Findings ({selectedFile?.findings?.length || 0})</span>
            </div>

            <div className="flex-1 p-4 space-y-4">
              {selectedFile && selectedFile.findings.length > 0 ? (
                selectedFile.findings.map((f: any, idx: number) => (
                  <div
                    key={idx}
                    className={`p-4 border-l-4 rounded-r-lg border border-border border-l-solid text-xs space-y-3 ${mapSeverityClass(f.severity)}`}
                  >
                    <div className="flex justify-between items-start">
                      <p className="font-semibold text-white">{f.issue}</p>
                      <span className="text-[8px] font-extrabold px-1.5 py-0.5 bg-zinc-800 rounded text-zinc-400">
                        {f.severity}
                      </span>
                    </div>
                    <div className="text-[10px] text-zinc-400 mt-1 flex justify-between">
                      <span>Line {f.line}</span>
                      <span className="italic">{f.category}</span>
                    </div>
                    <p className="text-zinc-300 leading-relaxed">{f.suggestion}</p>

                    {/* Explain Issue Button */}
                    <div className="pt-2.5 border-t border-border/40 flex justify-end">
                      <button
                        onClick={() => handleExplain(f.id, f.category)}
                        disabled={explainingId === f.id}
                        className="px-2.5 py-1 bg-accent-blue/10 hover:bg-accent-blue/20 text-accent-blue rounded text-[10px] font-bold transition-colors flex items-center gap-1 disabled:opacity-50"
                      >
                        <Lightbulb className="w-3 h-3" />
                        Explain Issue
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-center text-muted p-6 mt-12">
                  <CheckCircle2 className="w-10 h-10 text-zinc-700 mb-3" />
                  <p className="text-sm font-semibold">No issues identified</p>
                  <p className="text-xs text-zinc-500 mt-1">This file's modifications comply with code safety standards.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
