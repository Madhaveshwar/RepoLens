import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "../../lib/api";
import { Markdown } from "../Markdown";
import {
  Loader2, GitCommitHorizontal, Bot, Search, FileCode2, ArrowRight,
  RefreshCw, ShieldCheck, ShieldAlert, ChevronDown, ChevronUp,
} from "lucide-react";

interface CommitListItem {
  sha: string;
  short_sha: string;
  author: string;
  date: string | null;
  message: string;
  analyzed: boolean;
}

interface CommitFinding {
  file: string;
  line: number | null;
  severity: string;
  issue: string;
  explanation?: string | null;
  suggestion?: string | null;
  source?: string;
}

interface CommitAnalysisData {
  sha: string;
  parent_sha: string | null;
  author: string;
  message: string;
  committed_at: string | null;
  files_changed: number;
  additions: number;
  deletions: number;
  security_impact: string;
  quality_impact: string;
  files: Array<{
    filename: string;
    status: string;
    additions: number;
    deletions: number;
  }>;
  security_findings: CommitFinding[];
  code_smells: CommitFinding[];
  complexity_findings: Array<{
    file: string;
    name: string;
    kind: string;
    before?: number;
    after?: number;
    delta?: number;
    severity?: string;
  }>;
  ai_summary: string | null;
}

const SEVERITY_STYLES: Record<string, string> = {
  Critical: "bg-red-500/15 text-red-500 border border-red-500/30",
  High: "bg-orange-500/15 text-orange-500 border border-orange-500/30",
  Medium: "bg-yellow-500/15 text-yellow-600 border border-yellow-500/30",
  Low: "bg-blue-500/15 text-blue-500 border border-blue-500/30",
  Info: "bg-zinc-500/15 text-zinc-500 border border-zinc-500/30",
};

export const CommitAnalysisPanel: React.FC<{ repoId: string }> = ({ repoId }) => {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [selectedSHA, setSelectedSHA] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [tab, setTab] = useState<"overview" | "findings" | "complexity">("overview");

  const commitsQuery = useQuery({
    queryKey: ["commits", repoId],
    queryFn: async () => {
      const res = await axios.get(`/repositories/${repoId}/commits`, {
        params: { limit: 30 },
      });
      return res.data as {
        repository_id: string;
        branch: string;
        commits: CommitListItem[];
        message: string | null;
      };
    },
    enabled: !!repoId,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const analysisQuery = useQuery({
    queryKey: ["commitAnalysis", repoId, selectedSHA],
    queryFn: async () => {
      const res = await axios.get(`/repositories/${repoId}/commits/${selectedSHA}/analysis`);
      return res.data as CommitAnalysisData;
    },
    enabled: !!repoId && !!selectedSHA,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const analyzeMutation = useMutation({
    mutationFn: async (sha: string) => {
      const res = await axios.post(
        `/repositories/${repoId}/commits/${sha}/analyze`,
        null,
        { params: { with_ai_summary: true } }
      );
      return res.data as CommitAnalysisData;
    },
    onSuccess: (_data, sha) => {
      setSelectedSHA(sha);
      qc.invalidateQueries({ queryKey: ["commits", repoId] });
      qc.invalidateQueries({ queryKey: ["commitAnalysis", repoId, sha] });
    },
  });

  const commits = commitsQuery.data?.commits || [];
  const filteredCommits = commits.filter((c) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      c.message.toLowerCase().includes(q) ||
      c.author.toLowerCase().includes(q) ||
      c.sha.toLowerCase().includes(q)
    );
  });

  const analysis = analysisQuery.data;

  if (commitsQuery.isLoading) {
    return (
      <div className="glass-card p-10 flex flex-col items-center gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
        <p className="text-xs text-zinc-600">Loading commits…</p>
      </div>
    );
  }

  if (commitsQuery.isError) {
    return (
      <div className="glass-card p-8 text-center">
        <GitCommitHorizontal className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-800">Could not load commits</p>
        <p className="text-xs text-zinc-600 mt-1">
          {(commitsQuery.error as any)?.response?.data?.detail || "Please try again."}
        </p>
      </div>
    );
  }

  const allFindings = analysis
    ? [
        ...analysis.security_findings.map((f) => ({ ...f, kind: "Security" as const })),
        ...analysis.code_smells.map((f) => ({ ...f, kind: "Code Smell" as const })),
      ]
    : [];

  return (
    <div className="glass-card p-6 space-y-5">
      <div>
        <h3 className="font-bold text-zinc-900 text-sm flex items-center gap-2">
          <GitCommitHorizontal className="w-4 h-4 text-accent-blue" /> Commit / Change Analysis
        </h3>
        <p className="text-[10px] text-zinc-500 mt-0.5">
          Analyzes a commit against its parent on branch {commitsQuery.data?.branch || "default"}.
        </p>
      </div>

      {commits.length === 0 ? (
        <div className="text-center py-8">
          <GitCommitHorizontal className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
          <p className="text-sm font-bold text-zinc-800">No commits found</p>
          <p className="text-xs text-zinc-600 mt-1">
            {commitsQuery.data?.message || "No commits were returned for this branch."}
          </p>
        </div>
      ) : (
        <>
          {/* Search */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-zinc-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by message, author or SHA…"
              className="w-full text-xs glass rounded-xl py-2.5 pl-9 pr-3 text-zinc-800 placeholder-zinc-400 focus:outline-none focus:ring-2 focus:ring-accent-blue/40"
            />
          </div>

          {/* Commit list */}
          <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
            {filteredCommits.map((c) => {
              const isSel = selectedSHA === c.sha;
              return (
                <button
                  key={c.sha}
                  onClick={() => setSelectedSHA(isSel ? null : c.sha)}
                  className={`w-full text-left glass p-3 rounded-xl transition-all hover:shadow-md ${isSel ? "ring-2 ring-accent-blue/40" : ""}`}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[10px] font-mono font-bold text-accent-blue">{c.short_sha}</span>
                    <span className="text-xs font-bold text-zinc-900 truncate">{c.message.split("\n")[0]}</span>
                    {c.analyzed && (
                      <span className="ml-auto text-[9px] font-bold uppercase text-green-600 bg-green-500/10 px-2 py-0.5 rounded-full">
                        analyzed
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] text-zinc-500 mt-0.5">
                    @{c.author}
                    {c.date ? ` · ${new Date(c.date).toLocaleString()}` : ""}
                  </p>
                </button>
              );
            })}
            {filteredCommits.length === 0 && (
              <p className="text-xs text-zinc-500 text-center py-4">No commits match "{search}".</p>
            )}
          </div>

          {/* Analyze button */}
          {selectedSHA && (
            <button
              onClick={() => analyzeMutation.mutate(selectedSHA)}
              disabled={analyzeMutation.isPending}
              className="inline-flex items-center gap-2 bg-accent-blue text-white text-xs font-bold px-4 py-2.5 rounded-xl hover:opacity-90 disabled:opacity-50"
            >
              {analyzeMutation.isPending ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Analyzing commit — fetching real diff…
                </>
              ) : (
                <>
                  <GitCommitHorizontal className="w-3.5 h-3.5" /> Analyze commit {selectedSHA.slice(0, 7)}
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

          {/* Analysis result */}
          {analysis && (
            <div className="space-y-4 pt-2 border-t border-border/40">
              {/* Tabs */}
              <div className="flex gap-1 glass rounded-xl p-1 w-fit">
                {([
                  { v: "overview", label: "Overview" },
                  { v: "findings", label: `Findings (${allFindings.length})` },
                  { v: "complexity", label: "Complexity" },
                ] as const).map((t) => (
                  <button
                    key={t.v}
                    onClick={() => setTab(t.v)}
                    className={`text-[10px] font-bold px-3 py-1.5 rounded-lg transition-colors ${
                      tab === t.v ? "bg-accent-blue text-white" : "text-zinc-600 hover:text-zinc-900"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              {tab === "overview" && (
                <div className="space-y-3">
                  <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2">
                    <div>
                      <p className="text-sm font-bold text-zinc-900">{analysis.message.split("\n")[0]}</p>
                      <p className="text-[10px] text-zinc-500 font-mono">
                        {analysis.sha.slice(0, 10)}
                        {analysis.parent_sha ? ` (parent ${analysis.parent_sha.slice(0, 7)})` : " · no parent (root commit)"}
                        {" · "}@{analysis.author}
                        {analysis.committed_at ? ` · ${new Date(analysis.committed_at).toLocaleString()}` : ""}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <div className="glass rounded-xl px-3 py-2 text-center">
                        <p className="text-lg font-black text-green-600 leading-none">+{analysis.additions}</p>
                        <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">Added</p>
                      </div>
                      <div className="glass rounded-xl px-3 py-2 text-center">
                        <p className="text-lg font-black text-red-500 leading-none">−{analysis.deletions}</p>
                        <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">Removed</p>
                      </div>
                    </div>
                  </div>

                  {/* Impact */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <div className="glass p-3 rounded-xl">
                      <p className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider mb-1">Security impact</p>
                      <p className="text-xs text-zinc-800">{analysis.security_impact}</p>
                    </div>
                    <div className="glass p-3 rounded-xl">
                      <p className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider mb-1">Quality impact</p>
                      <p className="text-xs text-zinc-800">{analysis.quality_impact}</p>
                    </div>
                  </div>

                  {/* Files changed */}
                  <div>
                    <p className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider mb-1.5">
                      Files changed ({analysis.files_changed})
                    </p>
                    <div className="space-y-1 max-h-40 overflow-y-auto pr-1">
                      {analysis.files.map((f) => (
                        <div key={f.filename} className="flex items-center gap-2 glass px-3 py-1.5 rounded-lg text-[10px] font-mono">
                          <FileCode2 className="w-3 h-3 text-zinc-400 flex-shrink-0" />
                          <span className="text-zinc-800 truncate">{f.filename}</span>
                          <span className="ml-auto flex-shrink-0 text-zinc-400">{f.status}</span>
                          <span className="text-green-600 flex-shrink-0">+{f.additions}</span>
                          <span className="text-red-500 flex-shrink-0">−{f.deletions}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* AI summary */}
                  <div className="glass p-4 rounded-xl">
                    <p className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider mb-2 flex items-center gap-1.5">
                      <Bot className="w-3.5 h-3.5 text-accent-blue" /> AI summary
                    </p>
                    <div className="text-zinc-700 text-xs">
                      <Markdown content={analysis.ai_summary || "No AI summary available."} />
                    </div>
                  </div>
                </div>
              )}

              {tab === "findings" && (
                <div className="space-y-2">
                  {allFindings.length === 0 ? (
                    <div className="glass p-4 rounded-xl text-center">
                      <ShieldCheck className="w-6 h-6 text-green-500 mx-auto mb-1" />
                      <p className="text-xs font-bold text-zinc-800">No security findings or code smells</p>
                      <p className="text-[10px] text-zinc-600 mt-0.5">
                        The deterministic scanners found no issues in the added lines of this commit.
                      </p>
                    </div>
                  ) : (
                    allFindings.map((f, idx) => {
                      const key = `${f.file}-${f.line}-${idx}`;
                      const isOpen = expanded === key;
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
                            <span className="text-[10px] font-bold text-zinc-700 uppercase">{f.kind}</span>
                            <span className="text-xs font-semibold text-zinc-900">{f.issue}</span>
                            <span className="ml-auto text-zinc-400">
                              {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5 mt-1.5 text-[10px] font-mono text-zinc-500">
                            <FileCode2 className="w-3 h-3 flex-shrink-0" />
                            <span className="truncate">{f.file}{f.line ? `:L${f.line}` : ""}</span>
                          </div>
                          {isOpen && (
                            <div className="mt-2 pt-2 border-t border-border/40 space-y-1">
                              {f.explanation && (
                                <p className="text-[10px] text-zinc-600"><span className="font-bold">Why:</span> {f.explanation}</p>
                              )}
                              {f.suggestion && (
                                <p className="text-[10px] text-zinc-600"><span className="font-bold">Fix:</span> {f.suggestion}</p>
                              )}
                            </div>
                          )}
                        </button>
                      );
                    })
                  )}
                </div>
              )}

              {tab === "complexity" && (
                <div className="space-y-2">
                  {analysis.complexity_findings.length === 0 ? (
                    <p className="text-xs text-zinc-500 italic py-4 text-center">
                      No measurable complexity changes in this commit's Python/JavaScript functions.
                    </p>
                  ) : (
                    analysis.complexity_findings.map((c, i) => (
                      <div key={i} className="glass p-3 rounded-xl flex items-center gap-2 flex-wrap">
                        <FileCode2 className="w-3.5 h-3.5 text-zinc-400 flex-shrink-0" />
                        <span className="text-xs font-mono text-zinc-800 truncate">{c.file}</span>
                        <span className="text-xs font-bold text-zinc-900">{c.name}</span>
                        <span className="ml-auto flex items-center gap-1.5 text-[10px] font-mono">
                          <span className="text-zinc-400">{c.before ?? "?"}</span>
                          <ArrowRight className="w-3 h-3 text-zinc-400" />
                          <span className={`font-black ${(c.delta ?? 0) > 0 ? "text-red-500" : (c.delta ?? 0) < 0 ? "text-green-600" : "text-zinc-500"}`}>
                            {c.after ?? "?"}
                          </span>
                          {c.severity && (
                            <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full ${SEVERITY_STYLES[c.severity] || "glass text-zinc-500"}`}>
                              {c.severity}
                            </span>
                          )}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};
