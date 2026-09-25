import React from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "../../lib/api";
import { Loader2, Network, Boxes, GitBranch, Layers3, Link2, ArrowRight, AlertOctagon } from "lucide-react";
import { formatDateTime } from "../../lib/datetime";

interface Framework {
  name: string;
  category: string;
  evidence: string[];
}

interface ArchitectureData {
  analysis_id: string;
  generated_at: string | null;
  result: {
    summary: {
      note: string;
      structure: { total_files: number; tree_truncated?: boolean; directories?: string[] };
      languages: Record<string, number>;
    };
    frameworks: Framework[];
    layers: Array<{ layer: string; evidence_directories: string[] }>;
    components: Array<{ name: string; file_count: number }>;
    entry_points: string[];
    internal_dependencies: Array<{ from: string; to: string; imports: number }>;
    external_dependencies: Array<{ package: string; import_count: number }>;
    concerns: Array<{ concern: string; evidence: string[]; suggestion: string }>;
  };
}

export const ArchitecturePanel: React.FC<{ repoId: string }> = ({ repoId }) => {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["architecture", repoId],
    queryFn: async () => {
      const res = await axios.get(`/repositories/${repoId}/architecture`);
      return res.data as ArchitectureData;
    },
    enabled: !!repoId,
    staleTime: 120_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="glass-card p-10 flex flex-col items-center gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
        <p className="text-xs text-zinc-600">Mapping repository architecture…</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="glass-card p-8 text-center">
        <Network className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-800">No architecture analysis available</p>
        <p className="text-xs text-zinc-600 mt-1">
          {(error as any)?.response?.data?.detail || "Run a repository scan to generate one."}
        </p>
      </div>
    );
  }

  if (!data) return null;
  const r = data.result;

  return (
    <div className="glass-card p-6 space-y-6">
      <div>
        <h3 className="font-bold text-zinc-900 text-sm flex items-center gap-2">
          <Network className="w-4 h-4 text-accent-blue" /> Architecture Analysis
        </h3>
        <p className="text-[10px] text-zinc-500 mt-1">{r.summary.note}</p>
      </div>

      {/* Detected technologies with evidence */}
      <div>
        <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider mb-2 flex items-center gap-1.5">
          <Boxes className="w-3.5 h-3.5" /> Detected Technologies ({r.frameworks.length})
        </p>
        {r.frameworks.length === 0 ? (
          <p className="text-xs text-zinc-600 italic bg-background/50 border border-dashed border-border rounded-xl p-3">
            No frameworks or infrastructure detected from repository evidence.
          </p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {r.frameworks.map((f, i) => (
              <div key={`${f.name}-${i}`} className="glass p-3 rounded-xl">
                <div className="flex justify-between items-center">
                  <span className="text-xs font-bold text-zinc-900">{f.name}</span>
                  <span className="text-[9px] text-zinc-500 uppercase font-bold">{f.category}</span>
                </div>
                {f.evidence.map((e, j) => (
                  <p key={j} className="text-[9px] text-zinc-600 mt-0.5 font-mono truncate" title={e}>↳ {e}</p>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Layers */}
        <div>
          <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider mb-2 flex items-center gap-1.5">
            <Layers3 className="w-3.5 h-3.5" /> Detected Layers
          </p>
          {r.layers.length === 0 ? (
            <p className="text-xs text-zinc-600 italic bg-background/50 border border-dashed border-border rounded-xl p-3">
              No distinct architectural layers detected in the directory structure.
            </p>
          ) : (
            <div className="space-y-2">
              {r.layers.map((l) => (
                <div key={l.layer} className="glass p-3 rounded-xl">
                  <span className="text-xs font-bold text-zinc-900">{l.layer}</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {l.evidence_directories.map((d) => (
                      <span key={d} className="text-[9px] font-mono bg-accent-blue/10 text-accent-blue px-1.5 py-0.5 rounded">
                        {d}/
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Components + entry points */}
        <div>
          <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider mb-2 flex items-center gap-1.5">
            <GitBranch className="w-3.5 h-3.5" /> Main Modules
          </p>
          <div className="space-y-1.5">
            {r.components.map((c) => (
              <div key={c.name} className="flex justify-between items-center glass p-2.5 rounded-xl text-xs">
                <span className="font-mono font-semibold text-zinc-800">{c.name}</span>
                <span className="text-[10px] text-zinc-500">{c.file_count} files</span>
              </div>
            ))}
          </div>
          {r.entry_points.length > 0 && (
            <>
              <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider mt-4 mb-2">
                Entry Points
              </p>
              <div className="flex flex-wrap gap-1.5">
                {r.entry_points.map((e) => (
                  <span key={e} className="text-[9px] font-mono bg-green-500/10 text-green-600 border border-green-500/20 px-2 py-0.5 rounded-full">
                    {e}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Dependency graph */}
      {(r.internal_dependencies.length > 0 || r.external_dependencies.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div>
            <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider mb-2 flex items-center gap-1.5">
              <Link2 className="w-3.5 h-3.5" /> Internal Module Dependencies
            </p>
            {r.internal_dependencies.length === 0 ? (
              <p className="text-xs text-zinc-600 italic">No cross-module imports detected.</p>
            ) : (
              <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                {r.internal_dependencies.map((e, i) => (
                  <div key={i} className="flex items-center gap-2 text-[10px] font-mono glass p-2 rounded-lg">
                    <span className="font-bold text-zinc-800">{e.from}</span>
                    <ArrowRight className="w-3 h-3 text-accent-blue" />
                    <span className="font-bold text-zinc-800">{e.to}</span>
                    <span className="ml-auto text-zinc-500">{e.imports} imports</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider mb-2">
              Top External Dependencies (by import count)
            </p>
            {r.external_dependencies.length === 0 ? (
              <p className="text-xs text-zinc-600 italic">None detected.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5 max-h-48 overflow-y-auto">
                {r.external_dependencies.map((d) => (
                  <span key={d.package} className="text-[10px] font-mono glass px-2 py-1 rounded-lg text-zinc-700">
                    {d.package} <span className="text-zinc-400">×{d.import_count}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Concerns */}
      {r.concerns.length > 0 && (
        <div>
          <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider mb-2 flex items-center gap-1.5">
            <AlertOctagon className="w-3.5 h-3.5 text-accent-orange" /> Potential Architectural Concerns
          </p>
          <div className="space-y-2">
            {r.concerns.map((c, i) => (
              <div key={i} className="glass p-3 rounded-xl border-l-2 border-accent-orange">
                <p className="text-xs text-zinc-800 font-semibold">{c.concern}</p>
                {c.evidence.map((e, j) => (
                  <p key={j} className="text-[9px] text-zinc-500 font-mono mt-0.5">↳ {e}</p>
                ))}
                {c.suggestion && (
                  <p className="text-[10px] text-zinc-600 mt-1">
                    <span className="font-bold">Suggestion:</span> {c.suggestion}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Footer stats */}
      <div className="flex flex-wrap gap-3 text-[10px] text-zinc-500 border-t border-border/40 pt-3">
        <span>{r.summary.structure.total_files} files analyzed</span>
        {Object.entries(r.summary.languages).slice(0, 5).map(([lang, count]) => (
          <span key={lang}>{lang}: {count}</span>
        ))}
        {data.generated_at && (
          <span className="ml-auto">Generated {formatDateTime(data.generated_at)}</span>
        )}
      </div>
      {r.summary.structure.tree_truncated && (
        <p className="text-[10px] text-orange-500 font-semibold">
          Note: the repository file tree is very large and was truncated by GitHub — the analysis covers the retrieved subset.
        </p>
      )}
    </div>
  );
};
