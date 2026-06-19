import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // ── Cache lifetimes ──────────────────────────────────────────────────
      // Data is considered fresh for 5 minutes → no duplicate requests while
      // the user navigates between tabs or re-mounts the same component.
      staleTime: 300_000, // 5 minutes

      // Keep unused query data in memory for 10 minutes after component unmounts.
      gcTime: 600_000, // 10 minutes

      // ── Retry policy ──────────────────────────────────────────────────────
      // Only retry once for transient errors; never retry on 4xx client errors.
      retry: (failureCount, error: any) => {
        const status = error?.response?.status;
        // Do not retry on client-side errors (auth failures, not found, rate limit)
        if (status && status >= 400 && status < 500) return false;
        // Retry once on server errors or network failures
        return failureCount < 1;
      },
      retryDelay: (attemptIndex) => Math.min(2000 * 2 ** attemptIndex, 30_000),

      // ── Anti-spam: disable automatic background refetching ────────────────
      // These are the primary cause of the 429 flood when the app is idle or
      // when the user switches windows/tabs.
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,

      // Disable automatic interval polling for all queries by default.
      // Individual queries that need live data use WebSocket instead.
      refetchInterval: false,
    },
    mutations: {
      // Mutations do not retry by default (they have side effects).
      retry: 0,
    },
  },
});
