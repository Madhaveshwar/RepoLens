import { create } from "zustand";
import axios, { websocketUrl } from "../lib/api";

export interface Analysis {
  id: string;
  repository_id: string;
  pull_request_id?: string;
  status: string;
  progress: number;
  risk_score: number;
  latency_seconds: number;
  estimated_token_usage: number;
  files_analyzed_count: number;
  characters_analyzed_count: number;
  groq_requests_made: number;
  cached_results_used: number;
  insights?: string;
  timestamp: string;
  model_name?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  scan_duration_seconds?: number;
}

export interface SecurityFinding {
  id: string;
  file: string;
  line: number;
  severity: string;
  issue: string;
  why_it_matters?: string;
  risk_level?: string;
  suggestion: string;
  before_code?: string;
  after_code?: string;
}

export interface CodeSmell {
  id: string;
  file: string;
  line: number;
  severity: string;
  issue: string;
  why_it_matters?: string;
  risk_level?: string;
  suggestion: string;
  before_code?: string;
  after_code?: string;
}

export interface ProgressDetailed {
  status: string;
  message: string;
  files_analyzed: number;
  total_files: number;
  current_file: string;
}

const MAX_POLL_RETRIES = 30;   // 5s * 30 = 2.5 minutes max
const POLL_INTERVAL_MS = 5000; // 5 seconds between polls

interface AnalysisState {
  analyses: Analysis[];
  activeAnalysis: Analysis | null;
  securityFindings: SecurityFinding[];
  codeSmells: CodeSmell[];
  testSuggestions: string;
  healthScore: any;
  loading: boolean;
  progress: number;
  progressStatus: string;
  progressDetailed: ProgressDetailed | null;
  error: string | null;

  triggerAnalysis: (repoId: string, prNumber?: number) => Promise<Analysis>;
  fetchAnalysisDetails: (analysisId: string) => Promise<void>;
  fetchRepoAnalyses: (repoId: string) => Promise<void>;
  startProgressStream: (analysisId: string) => void;
  resetProgress: () => void;
  deleteAnalysis: (analysisId: string) => Promise<void>;
  deleteAllHistory: () => Promise<void>;
  deleteRepositoryHistory: (repoId: string) => Promise<void>;
  restoreAnalysis: (analysisId: string) => Promise<void>;
  compareScans: (scanAId: string, scanBId: string) => Promise<any>;
}

export const useAnalysisStore = create<AnalysisState>((set, get) => {
  let ws: WebSocket | null = null;
  let pollingIntervalId: any = null;
  let pollingStopped = false;
  let pollRetryCount = 0;

  function stopPolling() {
    pollingStopped = true;
    if (pollingIntervalId) {
      clearInterval(pollingIntervalId);
      pollingIntervalId = null;
    }
    if (ws) {
      ws.close();
      ws = null;
    }
  }

  return {
    analyses: [],
    activeAnalysis: null,
    securityFindings: [],
    codeSmells: [],
    testSuggestions: "",
    healthScore: null,
    loading: false,
    progress: 0,
    progressStatus: "",
    progressDetailed: null,
    error: null,

    triggerAnalysis: async (repoId, prNumber) => {
      set({ loading: true, progress: 0, progressStatus: "Triggering analysis job...", progressDetailed: null });
      try {
        const res = await axios.post("/analysis/trigger", {
          repository_id: repoId,
          pr_number: prNumber
        });
        const analysis = res.data;
        set({ activeAnalysis: analysis, error: null });
        get().startProgressStream(analysis.id);
        return analysis;
      } catch (err: any) {
        const msg = err.response?.data?.detail || "Failed to trigger analysis";
        set({ error: msg, progressStatus: "Failed" });
        throw new Error(msg);
      } finally {
        set({ loading: false });
      }
    },

    fetchAnalysisDetails: async (analysisId) => {
      set({ loading: true });
      try {
        const [analysisRes, secRes, smellRes, testRes] = await Promise.all([
          axios.get(`/analysis/${analysisId}`),
          axios.get(`/security/analysis/${analysisId}`),
          axios.get(`/code-quality/analysis/${analysisId}`),
          axios.get(`/tests/analysis/${analysisId}`)
        ]);

        const analysisData = analysisRes.data;
        set({
          activeAnalysis: analysisData,
          securityFindings: secRes.data,
          codeSmells: smellRes.data,
          testSuggestions: testRes.data[0]?.content || "No test suggestions generated.",
          error: null
        });

        // Note: intentionally NOT invalidating React Query cache here.
        // The store state is already correct after set() above.
        // Invalidating would trigger duplicate refetches that race with
        // the existing polling and cause 429 request storms.
      } catch (err: any) {
        set({ error: err.response?.data?.detail || "Failed to load analysis details" });
      } finally {
        set({ loading: false });
      }
    },

    fetchRepoAnalyses: async (repoId) => {
      try {
        const res = await axios.get(`/analysis/repo/${repoId}`);
        set({ analyses: res.data });
      } catch (err: any) {
        console.error("Failed to load repo analyses:", err);
      }
    },

    startProgressStream: (analysisId) => {
      // Clean up any previous stream
      stopPolling();
      pollingStopped = false;
      pollRetryCount = 0;

      // ── Single interval polling ──────────────────────────────
      // Only ONE polling mechanism. Stops on completion, failure, error, or max retries.
      pollingIntervalId = setInterval(async () => {
        if (pollingStopped) return;
        if (pollRetryCount >= MAX_POLL_RETRIES) {
          stopPolling();
          set({ error: `Polling stopped after ${MAX_POLL_RETRIES} retries.`, progressStatus: "timeout" });
          return;
        }

        try {
          const res = await axios.get(`/analysis/${analysisId}`);
          const data = res.data;
          pollRetryCount = 0; // Reset on success

          set((state) => ({
            progress: data.progress,
            progressStatus: data.status,
            progressDetailed: {
              status: data.status,
              message: `Polling: ${data.progress}%`,
              files_analyzed: data.files_analyzed_count || 0,
              total_files: data.files_analyzed_count || 0,
              current_file: ""
            },
            activeAnalysis: {
              ...state.activeAnalysis,
              progress: data.progress,
              status: data.status,
              files_analyzed_count: data.files_analyzed_count,
            } as any,
            analyses: state.analyses.map((an) =>
              an.id === analysisId ? { ...an, progress: data.progress, status: data.status } : an
            )
          }));

          // Terminal states → stop polling and fetch details ONCE
          if (data.status === "completed" || data.progress === 100) {
            stopPolling();
            get().fetchAnalysisDetails(analysisId);
          } else if (data.status === "failed" || data.status === "cancelled") {
            stopPolling();
            set({ error: `Analysis ${data.status}.`, progressStatus: data.status });
          }
        } catch (err: any) {
          // ANY error stops polling to prevent 429 death spiral
          pollRetryCount++;
          const status = err?.response?.status;

          // If analysis returns 404, the analysis was deleted → stop completely
          if (status === 404) {
            stopPolling();
            set({ error: "Analysis not found (may have been deleted).", progressStatus: "not_found" });
            return;
          }

          // On rate limit (429) or any other error, stop polling.
          // The WebSocket or manual refresh can pick up if needed.
          if (status === 429) {
            stopPolling();
            set({ error: "Rate limit exceeded. Polling stopped.", progressStatus: "rate_limited" });
            return;
          }

          // Other errors: stop immediately rather than retrying into 429 territory
          stopPolling();
          set({ error: err.response?.data?.detail || "Polling error. Stopped.", progressStatus: "error" });
        }
      }, POLL_INTERVAL_MS);

      // ── WebSocket for live progress (best-effort) ────────────
      // Does NOT call fetchAnalysisDetails — only updates progress.
      // The interval handles completion detection and details fetch.
      ws = new WebSocket(websocketUrl(`/analysis/ws/${analysisId}`));

      ws.onmessage = (event) => {
        if (pollingStopped) return;
        const data = JSON.parse(event.data);

        // Ignore heartbeats
        if (data.type === "heartbeat") return;

        const updatedStatus = data.progress >= 100
          ? ((data.message || "").toLowerCase().includes("failed") ? "failed" : "completed")
          : data.status;

        set((state) => ({
          progress: data.progress,
          progressStatus: data.message || data.status,
          activeAnalysis: {
            ...state.activeAnalysis,
            progress: data.progress,
            status: updatedStatus,
          } as any,
          progressDetailed: {
            status: data.status,
            message: data.message || "",
            files_analyzed: data.files_analyzed || 0,
            total_files: data.total_files || 0,
            current_file: data.current_file || ""
          },
          analyses: state.analyses.map((an) =>
            an.id === analysisId ? { ...an, progress: data.progress, status: updatedStatus } : an
          )
        }));

        // Terminal → close WS; interval will handle fetchAnalysisDetails
        if (data.progress === 100 || updatedStatus === "completed") {
          ws?.close();
        } else if (updatedStatus === "failed") {
          ws?.close();
        }
      };

      ws.onerror = () => {
        console.error("WebSocket connection error — falling back to polling.");
      };

      ws.onclose = () => {
        ws = null;
      };
    },

    resetProgress: () => {
      stopPolling();
      pollRetryCount = 0;
      set({ progress: 0, progressStatus: "", progressDetailed: null, error: null });
    },

    deleteAnalysis: async (analysisId) => {
      set({ loading: true });
      try {
        await axios.delete(`/analyses/${analysisId}`);
        set((state) => {
          const filtered = state.analyses.filter(an => an.id !== analysisId);
          const nextActive = state.activeAnalysis?.id === analysisId ? (filtered[0] || null) : state.activeAnalysis;
          return {
            analyses: filtered,
            activeAnalysis: nextActive,
            error: null
          };
        });
      } catch (err: any) {
        const msg = err.response?.data?.detail || "Failed to delete scan";
        set({ error: msg });
        throw new Error(msg);
      } finally {
        set({ loading: false });
      }
    },

    deleteAllHistory: async () => {
      set({ loading: true });
      try {
        await axios.delete("/analyses");
        set({
          analyses: [],
          activeAnalysis: null,
          securityFindings: [],
          codeSmells: [],
          testSuggestions: "",
          error: null
        });
      } catch (err: any) {
        const msg = err.response?.data?.detail || "Failed to delete all scans";
        set({ error: msg });
        throw new Error(msg);
      } finally {
        set({ loading: false });
      }
    },

    deleteRepositoryHistory: async (repoId) => {
      set({ loading: true });
      try {
        await axios.delete(`/analyses/repo/${repoId}`);
        set({
          analyses: [],
          activeAnalysis: null,
          securityFindings: [],
          codeSmells: [],
          testSuggestions: "",
          error: null
        });
      } catch (err: any) {
        const msg = err.response?.data?.detail || "Failed to delete repository history";
        set({ error: msg });
        throw new Error(msg);
      } finally {
        set({ loading: false });
      }
    },

    restoreAnalysis: async (analysisId) => {
      set({ loading: true });
      try {
        await axios.post(`/analysis/${analysisId}/restore`);
        set({ error: null });
      } catch (err: any) {
        const msg = err.response?.data?.detail || "Failed to restore scan history";
        set({ error: msg });
        throw new Error(msg);
      } finally {
        set({ loading: false });
      }
    },

    compareScans: async (scanAId, scanBId) => {
      set({ loading: true });
      try {
        const res = await axios.get("/analyses/compare", {
          params: { scan_a: scanAId, scan_b: scanBId }
        });
        set({ error: null });
        return res.data;
      } catch (err: any) {
        const msg = err.response?.data?.detail || "Failed to compare scans";
        set({ error: msg });
        throw new Error(msg);
      } finally {
        set({ loading: false });
      }
    }
  };
});
