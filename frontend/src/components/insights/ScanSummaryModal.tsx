import React, { useEffect } from "react";
import axios from "../../lib/api";
import { useQuery } from "@tanstack/react-query";
import {
  Loader2, CheckCircle2, ShieldAlert, AlertTriangle, Boxes, Copy,
  FileCode2, Layers, FileSearch, Download, X,
} from "lucide-react";
import { formatDateTime } from "../../lib/datetime";

interface OverviewData {
  repository: { id: string; name: string };
  scan: null | {
    analysis_id: string;
    files_analyzed: number;
    health_score: number | null;
    risk_score: number | null;
    timestamp: string | null;
  };
  counts?: {
    security_issues: number;
    code_smells: number;
    dependencies: number;
    duplicate_blocks: number;
    technical_debt: number;
    high_complexity: number;
  };
  message: string | null;
}

export const ScanSummaryModal: React.FC<{
  analysisId: string | null;
  repoId: string | null;
  onClose: () => void;
  onViewDetails: () => void;
  onDownloadReport: () => void;
}> = ({ analysisId, repoId, onClose, onViewDetails, onDownloadReport }) => {
  // Only render when there is a completed scan to summarize
  const enabled = !!(analysisId && repoId);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["scanSummary", repoId, analysisId],
    queryFn: async () => {
      const res = await axios.get(`/repositories/${repoId}/overview`);
      return res.data as OverviewData;
    },
    enabled,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  if (!enabled) return null;

  const counts = data?.counts;

  const summaryRows = [
    { label: "Security Issues", value: counts?.security_issues, icon: ShieldAlert, tone: "text-accent-red" },
    { label: "Code Smells", value: counts?.code_smells, icon: AlertTriangle, tone: "text-accent-orange" },
    { label: "Dependencies", value: counts?.dependencies, icon: Boxes, tone: "text-accent-blue" },
    { label: "Duplicate Blocks", value: counts?.duplicate_blocks, icon: Copy, tone: "text-zinc-600" },
    { label: "Technical Debt", value: counts?.technical_debt, icon: FileCode2, tone: "text-yellow-600" },
    { label: "High Complexity Functions", value: counts?.high_complexity, icon: Layers, tone: "text-purple-500" },
  ];

  return (
    <div
      className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-[70] p-4 animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-label="Scan completed summary"
    >
      <div className="glass-card w-full max-w-md rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border flex justify-between items-center bg-zinc-50 dark:bg-zinc-900">
          <div className="flex items-center gap-2.5">
            <CheckCircle2 className="w-5 h-5 text-accent-green" />
            <h3 className="text-md font-bold text-zinc-900 dark:text-white">Scan Completed</h3>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-900 p-1 rounded-lg hover:bg-zinc-100 transition-colors dark:text-zinc-400 dark:hover:text-white dark:hover:bg-zinc-800"
            aria-label="Close scan summary"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-8 gap-3">
              <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
              <p className="text-xs text-zinc-600 dark:text-zinc-400">Loading scan summary…</p>
            </div>
          ) : isError || !data?.scan ? (
            <div className="text-center py-6">
              <FileSearch className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
              <p className="text-xs text-zinc-600 dark:text-zinc-400">
                Unable to load the scan summary. The scan results are still available in the analysis tabs.
              </p>
            </div>
          ) : (
            <>
              {/* Headline numbers — real values from the completed scan */}
              <div className="grid grid-cols-2 gap-3">
                <div className="glass p-4 rounded-xl text-center">
                  <p className="metric-label text-[9px]">Repository Health</p>
                  <p className={`text-2xl font-black mt-1 ${data.scan.health_score == null ? "text-zinc-400" : data.scan.health_score >= 80 ? "text-accent-green" : data.scan.health_score >= 60 ? "text-yellow-600 dark:text-yellow-400" : "text-accent-red"}`}>
                    {data.scan.health_score != null ? `${data.scan.health_score}/100` : "N/A"}
                  </p>
                </div>
                <div className="glass p-4 rounded-xl text-center">
                  <p className="metric-label text-[9px]">Files Analyzed</p>
                  <p className="text-2xl font-black mt-1 text-zinc-900 dark:text-zinc-100">
                    {data.scan.files_analyzed}
                  </p>
                </div>
              </div>

              {/* Finding counts */}
              <div className="glass p-4 rounded-xl divide-y divide-border/40">
                {summaryRows.map((row) => {
                  const Icon = row.icon;
                  return (
                    <div key={row.label} className="flex justify-between items-center py-2 first:pt-0 last:pb-0">
                      <span className="flex items-center gap-2 text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                        <Icon className={`w-3.5 h-3.5 ${row.tone}`} />
                        {row.label}
                      </span>
                      <span className="text-sm font-black text-zinc-900 dark:text-zinc-100">
                        {row.value ?? "N/A"}
                      </span>
                    </div>
                  );
                })}
              </div>

              {data.scan.timestamp && (
                <p className="text-[10px] text-zinc-500 text-center dark:text-zinc-400">
                  Scanned {formatDateTime(data.scan.timestamp)}
                </p>
              )}
            </>
          )}
        </div>

        {/* Actions */}
        <div className="px-6 py-4 border-t border-border bg-zinc-50 flex flex-col sm:flex-row gap-2 dark:bg-zinc-900">
          <button
            onClick={() => {
              onViewDetails();
              onClose();
            }}
            className="flex-1 px-4 py-2.5 border border-border text-xs rounded-lg hover:bg-zinc-100 text-zinc-700 font-bold transition-colors flex items-center justify-center gap-1.5 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            <FileSearch className="w-3.5 h-3.5" />
            View Detailed Analysis
          </button>
          <button
            onClick={() => {
              onDownloadReport();
              onClose();
            }}
            className="flex-1 px-4 py-2.5 bg-accent-blue hover:bg-blue-600 text-white text-xs rounded-lg font-bold transition-colors flex items-center justify-center gap-1.5"
          >
            <Download className="w-3.5 h-3.5" />
            Download Full Report
          </button>
        </div>
      </div>
    </div>
  );
};
