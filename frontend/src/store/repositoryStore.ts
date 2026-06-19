import { create } from "zustand";
import axios from "../lib/api";

export interface Repository {
  id: string;
  name: string;
  description?: string;
  stars: number;
  forks: number;
  open_prs_count: number;
  open_issues_count: number;
  default_branch: string;
  languages?: Record<string, number>;
  permissions?: Record<string, boolean>;
  created_at: string;
}

export interface PullRequest {
  id: string;
  number: number;
  title: string;
  author: string;
  state: string;
  additions: number;
  deletions: number;
  head_sha: string;
  base_sha: string;
  created_at: string;
}

interface RepositoryState {
  repositories: Repository[];
  activeRepo: Repository | null;
  prs: PullRequest[];
  activePr: PullRequest | null;
  loading: boolean;
  error: string | null;
  
  fetchRepositories: () => Promise<void>;
  connectRepository: (url: string) => Promise<Repository>;
  setActiveRepo: (repo: Repository | null) => void;
  fetchPrs: (repoId: string) => Promise<void>;
  setActivePr: (pr: PullRequest | null) => void;
  deleteRepository: (id: string) => Promise<void>;
  disconnectRepository: (id: string) => Promise<void>;
}

export const useRepositoryStore = create<RepositoryState>((set) => ({
  repositories: [],
  activeRepo: null,
  prs: [],
  activePr: null,
  loading: false,
  error: null,

  fetchRepositories: async () => {
    set({ loading: true });
    try {
      const res = await axios.get("/repositories");
      set({ repositories: res.data, error: null });
    } catch (err: any) {
      set({ error: err.response?.data?.detail || "Failed to fetch repositories" });
    } finally {
      set({ loading: false });
    }
  },

  connectRepository: async (url) => {
    set({ loading: true });
    try {
      const res = await axios.post("/repositories", { url });
      set((state) => ({
        repositories: [...state.repositories.filter((r) => r.id !== res.data.id), res.data],
        error: null
      }));
      return res.data;
    } catch (err: any) {
      const msg = err.response?.data?.detail || "Failed to connect repository";
      set({ error: msg });
      throw new Error(msg);
    } finally {
      set({ loading: false });
    }
  },

  setActiveRepo: (activeRepo) => set({ activeRepo, prs: [], activePr: null }),

  fetchPrs: async (repoId) => {
    set({ loading: true });
    try {
      const res = await axios.get(`/repositories/${repoId}/prs`);
      set({ prs: res.data, error: null });
    } catch (err: any) {
      set({ error: err.response?.data?.detail || "Failed to sync pull requests" });
    } finally {
      set({ loading: false });
    }
  },

  setActivePr: (activePr) => set({ activePr }),

  deleteRepository: async (id) => {
    set({ loading: true });
    try {
      await axios.delete(`/repositories/${id}`);
      set((state) => ({
        repositories: state.repositories.filter((r) => r.id !== id),
        activeRepo: state.activeRepo?.id === id ? null : state.activeRepo,
        error: null
      }));
    } catch (err: any) {
      const msg = err.response?.data?.detail || "Failed to delete repository";
      set({ error: msg });
      throw new Error(msg);
    } finally {
      set({ loading: false });
    }
  },

  disconnectRepository: async (id) => {
    set({ loading: true });
    try {
      await axios.post(`/repositories/${id}/disconnect`);
      set((state) => ({
        repositories: state.repositories.filter((r) => r.id !== id),
        activeRepo: state.activeRepo?.id === id ? null : state.activeRepo,
        error: null
      }));
    } catch (err: any) {
      const msg = err.response?.data?.detail || "Failed to disconnect repository";
      set({ error: msg });
      throw new Error(msg);
    } finally {
      set({ loading: false });
    }
  }
}));

