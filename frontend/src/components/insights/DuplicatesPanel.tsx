import React, { useState } from "react";
import { Pagination } from "../Pagination";
import { useQuery } from "@tanstack/react-query";
import axios from "../../lib/api";
import { Loader2, Copy, FileCode2, ArrowRight, ChevronDown, ChevronUp } from "lucide-react";

interface DuplicateFinding {
  id: string;
  file_a: string;
  start_line_a: number;
  end_line_a: number;
  file_b: string;
  start_line_b: number;
  end_line_b: number;
  similarity: number;
  duplicated_lines: number;
  token_hash: string;
  snippet: string | null;
}

interface DuplicatesData {
  analysis_id: string | null;
  findings: DuplicateFinding[];
  groups: number;
  parameters: {
    min_similarity_pct: number;
    min_block_lines: number;
    scan_default_min_similarity?: number;
  };
  message: string | null;
}

export const DuplicatesPanel: React.FC<{ repoId: string }> = ({ repoId }) => {
  const [minSimilarity, setMinSimilarity] = useState(50);
  const [expanded, setExpanded] = useState<string | null>(null);

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["duplicates", repoId, minSimilarity],
    queryFn: async () => {
      const res = await axios.get(`/repositories/${repoId}/duplicates`, {
        params: { min_similarity: minSimilarity },
      });
      return res.data as DuplicatesData;
    },
    enabled: !!repoId,
    staleTime: 120_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const findings = data?.findings || [];
  const totalDuplicatedLines = findings.reduce((acc, f) => acc + f.duplicated_lines, 0);

  // Pagination — resets when the threshold filter changes the list.
  const DUP_PAGE_SIZE = 10;
  const [dupPage, setDupPage] = useState(1);
  React.useEffect(() => { setDupPage(1); }, [minSimilarity]);
  const dupTotalPages = Math.max(1, Math.ceil(findings.length / DUP_PAGE_SIZE));
  const dupSafePage = Math.min(dupPage, dupTotalPages);
  const pageItems = findings.slice((dupSafePage - 1) * DUP_PAGE_SIZE, dupSafePage * DUP_PAGE_SIZE);

  if (isLoading) {
    return (
      <div className="glass-card p-10 flex flex-col items-center gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
        <p className="text-xs text-zinc-600">Detecting duplicate code…</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="glass-card p-8 text-center">
        <Copy className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-800">Could not load duplicate analysis</p>
        <p className="text-xs text-zinc-600 mt-1">
          {(error as any)?.response?.data?.detail || "Please try again."}
        </p>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="glass-card p-6 space-y-5">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <div>
          <h3 className="font-bold text-zinc-900 text-sm flex items-center gap-2">
            <Copy className="w-4 h-4 text-accent-blue" /> Duplicate Code Detection
          </h3>
          <p className="text-[10px] text-zinc-500 mt-0.5">
            Blocks of ≥{data.parameters.min_block_lines} lines compared across source files (generated code, deps and build output excluded)
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider">Min similarity</label>
          <select
            value={minSimilarity}
            onChange={(e) => setMinSimilarity(Number(e.target.value))}
            className="text-xs glass rounded-xl px-3 py-2 text-zinc-700 bg-transparent focus:outline-none"
          >
            {[50, 60, 70, 80, 90, 100].map((t) => (
              <option key={t} value={t}>{t}%</option>
            ))}
          </select>
        </div>
      </div>

      {data.analysis_id && findings.length > 0 && (
        <div className="flex gap-2">
          <div className="glass rounded-xl px-3 py-2">
            <p className="text-lg font-black text-zinc-900 leading-none">{findings.length}</p>
            <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">Duplicate pairs</p>
          </div>
          <div className="glass rounded-xl px-3 py-2">
            <p className="text-lg font-black text-zinc-900 leading-none">{data.groups}</p>
            <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">Distinct blocks</p>
          </div>
          <div className="glass rounded-xl px-3 py-2">
            <p className="text-lg font-black text-zinc-900 leading-none">{totalDuplicatedLines}</p>
            <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">Duplicated lines</p>
          </div>
        </div>
      )}

      {data.analysis_id && findings.length === 0 ? (
        <div className="text-center py-8">
          <Copy className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
          <p className="text-sm font-bold text-zinc-800">No duplicate code found</p>
          <p className="text-xs text-zinc-600 mt-1">
            {data.message || "No sufficiently similar code blocks were detected at the current threshold."}
          </p>
        </div>
      ) : (
        <>
          <div className="space-y-2">
          {pageItems.map((f) => {
            const isOpen = expanded === f.id;
            return (
              <button
                key={f.id}
                onClick={() => setExpanded(isOpen ? null : f.id)}
                className={`w-full text-left glass p-4 rounded-xl transition-all hover:shadow-md ${isOpen ? "ring-2 ring-accent-blue/40" : ""}`}
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] font-mono bg-accent-blue/10 text-accent-blue px-2 py-0.5 rounded-full font-bold">
                    {f.similarity}% similar
                  </span>
                  <span className="text-[10px] text-zinc-500">~{f.duplicated_lines} lines</span>
                  <span className="text-[10px] text-zinc-400 font-mono">#{f.token_hash.slice(0, 10)}</span>
                  <span className="ml-auto text-zinc-400">
                    {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </span>
                </div>
                <div className="mt-2 space-y-1">
                  <div className="flex items-center gap-2 text-xs">
                    <FileCode2 className="w-3.5 h-3.5 text-zinc-400 flex-shrink-0" />
                    <span className="font-mono text-zinc-800 truncate" title={f.file_a}>{f.file_a}</span>
                    <span className="text-[10px] text-zinc-500 flex-shrink-0">
                      L{f.start_line_a}–{f.end_line_a}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <ArrowRight className="w-3 h-3 text-zinc-400 flex-shrink-0" />
                    <span className="font-mono text-zinc-800 truncate" title={f.file_b}>{f.file_b}</span>
                    <span className="text-[10px] text-zinc-500 flex-shrink-0">
                      L{f.start_line_b}–{f.end_line_b}
                    </span>
                  </div>
                </div>
                {isOpen && f.snippet && (
                  <div className="mt-3 pt-3 border-t border-border/40">
                    <p className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider mb-1">
                      Duplicated snippet (first block)
                    </p>
                    <pre className="text-[10px] font-mono bg-zinc-950 text-zinc-200 rounded-xl p-3 overflow-x-auto leading-relaxed whitespace-pre">
                      {f.snippet}
                    </pre>
                    <p className="text-[10px] text-zinc-500 mt-2">
                      Consider extracting the shared logic into a single shared helper so both locations stay in sync.
                    </p>
                  </div>
                )}
              </button>
            );
          })}
          </div>
          <Pagination
            page={dupPage}
            pageSize={DUP_PAGE_SIZE}
            totalItems={findings.length}
            onPageChange={setDupPage}
            itemLabel="duplicate pairs"
          />
        </>
      )}
      {isFetching && <p className="text-[10px] text-zinc-400 text-center">Refreshing…</p>}
    </div>
  );
};
