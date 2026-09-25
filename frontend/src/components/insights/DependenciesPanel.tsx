import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "../../lib/api";
import { Loader2, PackageSearch, ExternalLink } from "lucide-react";
import { formatDateTime } from "../../lib/datetime";
import { Pagination } from "../Pagination";

interface DependencyFinding {
  id: string;
  ecosystem: string;
  manifest_file: string;
  package_name: string;
  version_spec: string | null;
  resolved_version: string | null;
  status: string;
  severity: string | null;
  advisory_id: string | null;
  vulnerable_range: string | null;
  recommended_version: string | null;
  advisory_url: string | null;
  evidence: string | null;
}

interface DependenciesData {
  analysis_id: string | null;
  generated_at?: string | null;
  findings: DependencyFinding[];
  manifests?: string[];
  ecosystems: string[];
  summary?: {
    total: number;
    known_vulnerable: number;
    outdated: number;
    unknown: number;
    filtered_count?: number;
  } | null;
  message: string | null;
}

const SEVERITY_STYLES: Record<string, string> = {
  Critical: "bg-red-500/15 text-red-500 border border-red-500/30",
  High: "bg-orange-500/15 text-orange-500 border border-orange-500/30",
  Medium: "bg-yellow-500/15 text-yellow-600 border border-yellow-500/30",
  Low: "bg-blue-500/15 text-blue-500 border border-blue-500/30",
};

const STATUS_META: Record<string, { label: string; cls: string }> = {
  known_vulnerable: { label: "Known vulnerable", cls: "bg-red-500/15 text-red-500 border border-red-500/30" },
  outdated: { label: "Outdated", cls: "bg-yellow-500/15 text-yellow-600 border border-yellow-500/30" },
  unknown: { label: "Unverified", cls: "bg-zinc-500/15 text-zinc-500 border border-zinc-500/30" },
  ok: { label: "OK", cls: "bg-green-500/15 text-green-600 border border-green-500/30" },
};

export const DependenciesPanel: React.FC<{ repoId: string }> = ({ repoId }) => {
  const [severity, setSeverity] = useState("all");
  const [ecosystem, setEcosystem] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["dependencies", repoId],
    queryFn: async () => {
      const res = await axios.get(`/repositories/${repoId}/dependencies`);
      return res.data as DependenciesData;
    },
    enabled: !!repoId,
    staleTime: 120_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const findings = data?.findings || [];

  const filtered = useMemo(
    () =>
      findings.filter((f) => {
        if (severity !== "all" && (f.severity || "none") !== severity) return false;
        if (ecosystem !== "all" && f.ecosystem !== ecosystem) return false;
        if (statusFilter !== "all" && f.status !== statusFilter) return false;
        return true;
      }),
    [findings, severity, ecosystem, statusFilter]
  );

  // Pagination — resets to page 1 when filters change.
  const DEP_PAGE_SIZE = 15;
  const [depPage, setDepPage] = useState(1);
  React.useEffect(() => { setDepPage(1); }, [severity, ecosystem, statusFilter]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / DEP_PAGE_SIZE));
  const safePage = Math.min(depPage, totalPages);
  const pageItems = filtered.slice((safePage - 1) * DEP_PAGE_SIZE, safePage * DEP_PAGE_SIZE);

  if (isLoading) {
    return (
      <div className="glass-card p-10 flex flex-col items-center gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
        <p className="text-xs text-zinc-600">Loading dependency findings…</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="glass-card p-8 text-center">
        <PackageSearch className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-800">Could not load dependencies</p>
        <p className="text-xs text-zinc-600 mt-1">
          {(error as any)?.response?.data?.detail || "Please try again."}
        </p>
      </div>
    );
  }

  if (!data) return null;

  const noScan = !data.analysis_id;
  const summary = data.summary;

  return (
    <div className="glass-card p-6 space-y-5">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <div>
          <h3 className="font-bold text-zinc-900 text-sm flex items-center gap-2">
            <PackageSearch className="w-4 h-4 text-accent-blue" /> Dependency Vulnerability Scanner
          </h3>
          {data.generated_at && (
            <p className="text-[10px] text-zinc-500 mt-0.5">
              From scan {formatDateTime(data.generated_at)}
            </p>
          )}
        </div>
        {summary && summary.total > 0 && (
          <div className="flex gap-2">
            <div className="glass rounded-xl px-3 py-2 text-center">
              <p className="text-lg font-black text-red-500 leading-none">{summary.known_vulnerable}</p>
              <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">Vulnerable</p>
            </div>
            <div className="glass rounded-xl px-3 py-2 text-center">
              <p className="text-lg font-black text-yellow-500 leading-none">{summary.outdated}</p>
              <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">Outdated</p>
            </div>
            <div className="glass rounded-xl px-3 py-2 text-center">
              <p className="text-lg font-black text-zinc-400 leading-none">{summary.unknown}</p>
              <p className="text-[9px] uppercase font-bold text-zinc-500 mt-1">Unverified</p>
            </div>
          </div>
        )}
      </div>

      {noScan ? (
        <div className="text-center py-8">
          <PackageSearch className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
          <p className="text-sm font-bold text-zinc-800">No scan data</p>
          <p className="text-xs text-zinc-600 mt-1">{data.message}</p>
        </div>
      ) : findings.length === 0 ? (
        <div className="text-center py-8">
          <PackageSearch className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
          <p className="text-sm font-bold text-zinc-800">No dependency manifests detected</p>
          <p className="text-xs text-zinc-600 mt-1">
            No supported dependency files (package.json, requirements.txt, go.mod, Cargo.toml, etc.) were found in this repository.
          </p>
        </div>
      ) : (
        <>
          {/* Filters */}
          <div className="flex flex-wrap gap-2 items-center">
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              className="text-xs glass rounded-xl px-3 py-2 text-zinc-700 bg-transparent focus:outline-none"
            >
              <option value="all">All severities</option>
              {["Critical", "High", "Medium", "Low"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              value={ecosystem}
              onChange={(e) => setEcosystem(e.target.value)}
              className="text-xs glass rounded-xl px-3 py-2 text-zinc-700 bg-transparent focus:outline-none"
            >
              <option value="all">All ecosystems</option>
              {data.ecosystems.map((e) => (
                <option key={e} value={e}>{e}</option>
              ))}
            </select>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="text-xs glass rounded-xl px-3 py-2 text-zinc-700 bg-transparent focus:outline-none"
            >
              <option value="all">All statuses</option>
              <option value="known_vulnerable">Known vulnerable</option>
              <option value="outdated">Outdated</option>
              <option value="unknown">Unverified</option>
              <option value="ok">OK</option>
            </select>
            <span className="text-[10px] text-zinc-500 ml-auto">
              {filtered.length} of {findings.length} packages
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border/40">
                  {["Package", "Ecosystem", "Version", "Status", "Severity", "Advisory", "Vulnerable range", "Recommended", "Evidence"].map((h) => (
                    <th key={h} className="text-[9px] uppercase font-bold text-zinc-500 tracking-wider py-2 px-2 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageItems.map((f) => {
                  const meta = STATUS_META[f.status] || STATUS_META.unknown;
                  return (
                    <tr key={f.id} className="border-b border-border/20 text-xs align-top hover:bg-zinc-50/50">
                      <td className="py-2.5 px-2">
                        <p className="font-bold text-zinc-900">{f.package_name}</p>
                        <p className="text-[9px] text-zinc-500 font-mono">{f.manifest_file}</p>
                      </td>
                      <td className="py-2.5 px-2 text-zinc-600">{f.ecosystem}</td>
                      <td className="py-2.5 px-2 font-mono text-[11px] text-zinc-700">
                        {f.resolved_version || f.version_spec || "—"}
                      </td>
                      <td className="py-2.5 px-2">
                        <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full whitespace-nowrap ${meta.cls}`}>
                          {meta.label}
                        </span>
                      </td>
                      <td className="py-2.5 px-2">
                        {f.severity ? (
                          <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full ${SEVERITY_STYLES[f.severity] || "glass text-zinc-500"}`}>
                            {f.severity}
                          </span>
                        ) : (
                          <span className="text-zinc-400">—</span>
                        )}
                      </td>
                      <td className="py-2.5 px-2">
                        {f.advisory_url ? (
                          <a
                            href={f.advisory_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-[11px] font-mono text-accent-blue hover:underline"
                          >
                            {f.advisory_id || "advisory"} <ExternalLink className="w-3 h-3" />
                          </a>
                        ) : (
                          <span className="text-zinc-400">—</span>
                        )}
                      </td>
                      <td className="py-2.5 px-2 font-mono text-[10px] text-zinc-600">{f.vulnerable_range || "—"}</td>
                      <td className="py-2.5 px-2 font-mono text-[10px] text-green-600">{f.recommended_version || "—"}</td>
                      <td className="py-2.5 px-2 max-w-48">
                        {f.evidence ? (
                          <p className="text-[10px] text-zinc-600">{f.evidence}</p>
                        ) : (
                          <span className="text-zinc-400">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <Pagination
            page={depPage}
            pageSize={DEP_PAGE_SIZE}
            totalItems={filtered.length}
            onPageChange={setDepPage}
            itemLabel="dependencies"
          />

          {data.manifests && data.manifests.length > 0 && (
            <div>
              <p className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider mb-1.5">Manifests scanned</p>
              <div className="flex flex-wrap gap-1.5">
                {data.manifests.map((m) => (
                  <span key={m} className="text-[9px] font-mono glass px-2 py-1 rounded-lg text-zinc-600">{m}</span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};
