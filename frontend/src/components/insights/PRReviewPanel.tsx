import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "../../lib/api";
import { Markdown } from "../Markdown";
import {
  Loader2, GitPullRequest, Bot, Cpu, ShieldCheck, ShieldAlert, Sparkles, RefreshCw, FileCode2,
} from "lucide-react";

interface PRListItem {
  number: number;
  title: string;
  author: string;
  state: string;
  additions: number;
  deletions: number;
  head_sha: string;
  base_sha: string;
  review: {
    id: string;
    risk_score: number;
    status: string;
    findings_count: number;
    reviewed_at: string | null;
  } | null;
}

interface PRReviewFinding {
  file: string;
  line: number | null;
  severity: string;
  issue: string;
  explanation: string | null;
  suggestion: string | null;
  source: string;
  category: string;
}

interface PRReviewData {
  id: string;
  pr_number: number;
  title: string | null;
  description: string | null;
  author: string | null;
  base_branch: string | null;
  head_branch: string | null;
  head_sha: string | null;
  risk_score: number;
  summary: string | null;
  findings: PRReviewFinding[];
  files_changed: number;
  additions: number;
  deletions: number;
  status: string;
  reviewed_at?: string | null;
  scanned_source_files?: number;
  severity_counts?: Record<string, number>;
}

const SEVERITY_STYLES: Record<string, string> = {
  Critical: "bg-red-500/15 text-red-500 border border-red-500/30",
  High: "bg-orange-500/15 text-orange-500 border border-orange-500/30",
  Medium: "bg-yellow-500/15 text-yellow-600 border border-yellow-500/30",
  Low: "bg-blue-500/15 text-blue-500 border border-blue-500/30",
  Info: "bg-zinc-500/15 text-zinc-500 border border-zinc-500/30",
};

function riskColor(score: number): string {
  if (score >= 60) return "text-red-500";
  if (score >= 30) return "text-orange-500";
  return "text-green-600";
}

export const PRReviewPanel: React.FC<{ repoId: string }> = ({ repoId }) => {
  const qc = useQueryClient();
  const [selectedPR, setSelectedPR] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<"all" | "deterministic" | "ai">("all");

  const prsQuery = useQuery({
    queryKey: ["prList", repoId],
    queryFn: async () => {
      const res = await axios.get(`/repositories/${repoId}/pull-requests`);
      return res.data as { repository_id: string; pull_requests: PRListItem[] };
    },
    enabled: !!repoId,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const reviewQuery = useQuery({
    queryKey: ["prReview", repoId, selectedPR],
    queryFn: async () => {
      const res = await axios.get(`/repositories/${repoId}/pull-requests/${selectedPR}/review`);
      return res.data as PRReviewData;
    },
    enabled: !!repoId && !!selectedPR,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const analyzeMutation = useMutation({
    mutationFn: async (prNumber: number) => {
      const res = await axios.post(`/repositories/${repoId}/pull-requests/${prNumber}/review`);
      return res.data as PRReviewData;
    },
    onSuccess: (data) => {
      setSelectedPR(data.pr_number);
      qc.invalidateQueries({ queryKey: ["prList", repoId] });
    },
  });

  const prs = prsQuery.data?.pull_requests || [];

  const review = reviewQuery.data;
  const findings = review?.findings || [];
  const filteredFindings =
    sourceFilter === "all" ? findings : findings.filter((f) => f.source === sourceFilter);

  if (prsQuery.isLoading) {
    return (
      <div className="glass-card p-10 flex flex-col items-center gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
        <p className="text-xs text-zinc-600">Loading pull requests…</p>
      </div>
    );
  }

  if (prsQuery.isError) {
    return (
      <div className="glass-card p-8 text-center">
        <GitPullRequest className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-800">Could not load pull requests</p>
        <p className="text-xs text-zinc-600 mt-1">
          {(prsQuery.error as any)?.response?.data?.detail || "Please try again."}
        </p>
      </div>
    );
  }

  return (
    <div className="glass-card p-6 space-y-5">
      <div>
        <h3 className="font-bold text-zinc-900 text-sm flex items-center gap-2">
          <GitPullRequest className="w-4 h-4 text-accent-blue" /> Pull Request Review
        </h3>
        <p className="text-[10px] text-zinc-500 mt-0.5">
          Analyzes the actual changed files of a PR. Read-only — nothing is posted to GitHub.
        </p>
      </div>

      {prs.length === 0 ? (
        <div className="text-center py-8">
          <GitPullRequest className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
          <p className="text-sm font-bold text-zinc-800">No open pull requests</p>
          <p className="text-xs text-zinc-600 mt-1">
            This repository currently has no open pull requests on GitHub.
          </p>
        </div>
      ) : (
        <>
          {/* PR list */}
          <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
            {prs.map((pr) => {
              const isSel = selectedPR === pr.number;
              return (
                <button
                  key={pr.number}
                  onClick={() => setSelectedPR(isSel ? null : pr.number)}
                  className={`w-full text-left glass p-3 rounded-xl transition-all hover:shadow-md ${isSel ? "ring-2 ring-accent-blue/40" : ""}`}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[10px] font-mono font-bold text-accent-blue">#{pr.number}</span>
                    <span className="text-xs font-bold text-zinc-900 truncate">{pr.title}</span>
                    {pr.review && (
                      <span className={`ml-auto text-[10px] font-black ${riskColor(pr.review.risk_score)}`}>
                        risk {pr.review.risk_score}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 flex-wrap mt-1 text-[10px] text-zinc-500">
                    <span>@{pr.author}</span>
                    <span className="text-green-600">+{pr.additions}</span>
                    <span className="text-red-500">−{pr.deletions}</span>
                    {pr.review ? (
                      <span className="text-zinc-500">
                        · reviewed {pr.review.reviewed_at ? new Date(pr.review.reviewed_at).toLocaleDateString() : ""} · {pr.review.findings_count} findings
                      </span>
                    ) : (
                      <span className="text-zinc-400">· not reviewed yet</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Analyze button */}
          {selectedPR && (
            <button
              onClick={() => analyzeMutation.mutate(selectedPR)}
              disabled={analyzeMutation.isPending}
              className="inline-flex items-center gap-2 bg-accent-blue text-white text-xs font-bold px-4 py-2.5 rounded-xl hover:opacity-90 disabled:opacity-50"
            >
              {analyzeMutation.isPending ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Analyzing PR — fetching real diff and running scanners…
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5" /> Analyze PR #{selectedPR}
                </>
              )}
            </button>
          )}

          {analyzeMutation.isError && (
            <div className="glass p-3 rounded-xl border border-red-500/30">
              <p className="text-xs text-red-500 font-bold flex items-center gap-1.5">
                <ShieldAlert className="w-4 h-4" /> Analysis failed
              </p>
              <p className="text-[10px] text-zinc-600 mt-1">
                {(analyzeMutation.error as any)?.response?.data?.detail || "Please try again."}
              </p>
            </div>
          )}

          {selectedPR && !review && !analyzeMutation.isPending && !reviewQuery.isFetching && (
            <p className="text-[10px] text-zinc-500">
              No stored review for PR #{selectedPR} yet — click "Analyze PR" to run the review.
            </p>
          )}

          {/* Review result */}
          {review && (
            <div className="space-y-4 pt-2 border-t border-border/40">
              <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2">
                <div>
                  <p className="text-sm font-bold text-zinc-900">
                    #{review.pr_number} — {review.title}
                  </p>
                  <p className="text-[10px] text-zinc-500 font-mono">
                    {review.head_branch || "head"} → {review.base_branch || "base"} · @{review.author} · {review.files_changed} files · +{review.additions}/−{review.deletions}
                  </p>
                </div>
                <div className={`text-2xl font-black ${riskColor(review.risk_score)}`}>
                  {review.risk_score}
                  <span className="text-[10px] text-zinc-400 font-bold ml-1">RISK/100</span>
                </div>
              </div>

              {review.description && (
                <div className="glass p-3 rounded-xl max-h-32 overflow-y-auto">
                  <p className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider mb-1">PR description</p>
                  <p className="text-[10px] text-zinc-600 whitespace-pre-wrap">{review.description.slice(0, 1000)}</p>
                </div>
              )}

              {/* Summary */}
              <div className="glass p-4 rounded-xl">
                <p className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider mb-2 flex items-center gap-1.5">
                  <Bot className="w-3.5 h-3.5 text-accent-blue" /> Review summary
                </p>
                <div className="text-zinc-700 text-xs">
                  <Markdown content={review.summary || "No summary available."} />
                </div>
              </div>

              {/* Findings */}
              <div>
                <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
                  <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">
                    Findings ({filteredFindings.length}/{findings.length})
                  </p>
                  <div className="flex gap-1 glass rounded-xl p-1">
                    {([
                      { v: "all", label: "All" },
                      { v: "deterministic", label: "Deterministic" },
                      { v: "ai", label: "AI" },
                    ] as const).map((o) => (
                      <button
                        key={o.v}
                        onClick={() => setSourceFilter(o.v)}
                        className={`text-[10px] font-bold px-2.5 py-1 rounded-lg transition-colors ${
                          sourceFilter === o.v ? "bg-accent-blue text-white" : "text-zinc-600 hover:text-zinc-900"
                        }`}
                      >
                        {o.label}
                      </button>
                    ))}
                  </div>
                </div>

                {filteredFindings.length === 0 ? (
                  <div className="glass p-4 rounded-xl text-center">
                    <ShieldCheck className="w-6 h-6 text-green-500 mx-auto mb-1" />
                    <p className="text-xs font-bold text-zinc-800">No findings for this filter</p>
                    <p className="text-[10px] text-zinc-600 mt-0.5">
                      {sourceFilter === "ai"
                        ? "AI suggestions are added only when the model returns grounded recommendations for the real diff."
                        : "The deterministic scanners found no issues in the changed code."}
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {filteredFindings.map((f, idx) => {
                      const key = `${f.file}-${f.line}-${idx}`;
                      const isOpen = expanded === key;
                      const isAI = f.source === "ai";
                      return (
                        <button
                          key={key}
                          onClick={() => setExpanded(isOpen ? null : key)}
                          className={`w-full text-left glass p-3.5 rounded-xl transition-all hover:shadow-md ${isOpen ? "ring-2 ring-accent-blue/40" : ""}`}
                        >
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full ${SEVERITY_STYLES[f.severity] || "glass text-zinc-500"}`}>
                              {f.severity}
                            </span>
                            <span className={`inline-flex items-center gap-1 text-[9px] font-bold uppercase px-2 py-0.5 rounded-full ${isAI ? "bg-purple-500/15 text-purple-600" : "bg-cyan-500/15 text-cyan-600"}`}>
                              {isAI ? <Bot className="w-3 h-3" /> : <Cpu className="w-3 h-3" />}
                              {isAI ? "AI review" : "Deterministic"}
                            </span>
                            <span className="text-[10px] text-zinc-500 uppercase">{f.category}</span>
                            <span className="text-xs font-semibold text-zinc-900">{f.issue}</span>
                          </div>
                          <div className="flex items-center gap-1.5 mt-1.5 text-[10px] font-mono text-zinc-500">
                            <FileCode2 className="w-3 h-3 flex-shrink-0" />
                            <span className="truncate">{f.file}{f.line ? `:L${f.line}` : ""}</span>
                          </div>
                          {isOpen && (
                            <div className="mt-2 pt-2 border-t border-border/40 space-y-1">
                              {f.explanation && (
                                <p className="text-[10px] text-zinc-600">
                                  <span className="font-bold">Why:</span> {f.explanation}
                                </p>
                              )}
                              {f.suggestion && (
                                <p className="text-[10px] text-zinc-600">
                                  <span className="font-bold">Fix:</span> {f.suggestion}
                                </p>
                              )}
                              {!f.explanation && !f.suggestion && (
                                <p className="text-[10px] text-zinc-400 italic">No further detail available for this finding.</p>
                              )}
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {review.reviewed_at && (
                <p className="text-[9px] text-zinc-400">
                  Reviewed {new Date(review.reviewed_at).toLocaleString()} · analysis stored read-only; nothing was posted to GitHub.
                </p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};
