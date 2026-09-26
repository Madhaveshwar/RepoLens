import React, { useEffect, useState } from "react";
import axios from "../lib/api";
import { useRepositoryStore } from "../store/repositoryStore";
import type { Repository } from "../store/repositoryStore";
import { useAuthStore } from "../store/authStore";
import {
  Plus, Search, Loader2, BookOpen, AlertTriangle, ArrowRight,
  GitBranch, FolderGit2, Clock,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { formatDateTime } from "../lib/datetime";

/**
 * Repository Selection page — the first page a returning user sees after login
 * (provided credentials are already configured).
 *
 * The user must *explicitly* select a repository to open its dashboard.
 * No repository is selected automatically.
 */

interface RepositorySelectionProps {
  onSelectRepo: (repo: Repository) => void;
  onNavigateToSettings: () => void;
}

export const RepositorySelection: React.FC<RepositorySelectionProps> = ({
  onSelectRepo,
  onNavigateToSettings,
}) => {
  const { repositories, connectRepository } = useRepositoryStore();
  const { user } = useAuthStore();

  const hasLlmKey = user
    ? user.has_groq_api_key || user.has_openai_api_key ||
      user.has_claude_api_key || user.has_gemini_api_key || user.has_openrouter_api_key
    : false;
  const hasGithubPat = user?.has_github_pat || false;

  const [searchQuery, setSearchQuery] = useState("");
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  // Fetch repositories from backend — only once the session is actually
  // initialized (token restored AND user loaded). Firing earlier made the
  // request without an Authorization header on refresh, logging a 401.
  const { data: reposData, isLoading: loadingRepos } = useQuery({
    enabled: !!user,
    queryKey: ["repositories"],
    queryFn: async () => {
      const res = await axios.get("/repositories");
      return res.data;
    },
    staleTime: 30_000,
    gcTime: 120_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  // Sync React Query data into Zustand store
  useEffect(() => {
    if (reposData) {
      useRepositoryStore.setState({ repositories: reposData });
    }
  }, [reposData]);

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    setConnecting(true);
    setConnectError(null);
    try {
      const newRepo = await connectRepository(repoUrl);
      setShowConnectModal(false);
      setRepoUrl("");
      // After successful connection, open the new repository immediately
      onSelectRepo(newRepo);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to connect repository";
      setConnectError(msg);
    } finally {
      setConnecting(false);
    }
  };

  const filteredRepos = repositories.filter((repo) =>
    repo.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex-1 p-8 overflow-y-auto max-h-screen">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-2xl bg-accent-gradient flex items-center justify-center shadow-glow-blue">
              <FolderGit2 className="w-5 h-5 text-white" aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-zinc-900 dark:text-white">
                Select Repository
              </h1>
              <p className="text-sm text-zinc-600 font-medium dark:text-zinc-400">
                Choose a repository to continue to its analysis dashboard.
              </p>
            </div>
          </div>
        </div>

        {/* Setup warning — if LLM key or GitHub PAT is missing */}
        {user && (!hasLlmKey || !hasGithubPat) && (
          <div className="mb-6 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-700/50 rounded-2xl p-5 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-bold text-amber-800 dark:text-amber-200">
                Credentials not fully configured
              </p>
              <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
                {!hasLlmKey && "An AI/LLM API key is required to run code analysis. "}
                {!hasGithubPat && "A GitHub Personal Access Token is required to connect repositories. "}
              </p>
              <button
                onClick={onNavigateToSettings}
                className="mt-3 text-xs font-bold text-amber-700 dark:text-amber-300 hover:underline flex items-center gap-1"
              >
                Go to Settings <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}

        {/* Actions bar */}
        <div className="flex justify-between items-center mb-6 gap-4 flex-wrap">
          <div className="relative w-full max-w-xs">
            <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-zinc-500">
              <Search className="w-4 h-4" />
            </span>
            <input
              aria-label="Search repositories"
              type="text"
              placeholder="Search connected repositories…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="input-glass pl-9 text-xs w-full"
            />
          </div>
          <button
            onClick={() => {
              if (!hasLlmKey) return;
              setShowConnectModal(true);
            }}
            title={
              !hasLlmKey
                ? "Please configure an LLM API key in Settings first."
                : "Connect a new GitHub repository"
            }
            className={`btn-primary flex items-center gap-2 shrink-0 ${
              !hasLlmKey ? "cursor-not-allowed opacity-70" : ""
            }`}
          >
            {!hasLlmKey ? (
              <AlertTriangle className="w-4 h-4" />
            ) : (
              <Plus className="w-4 h-4" />
            )}
            {!hasLlmKey ? "Configure API Key First" : "Connect New Repository"}
          </button>
        </div>

        {/* Repository list */}
        {loadingRepos ? (
          <div className="flex flex-col items-center justify-center h-64 gap-4">
            <div className="w-12 h-12 rounded-2xl bg-accent-gradient/30 flex items-center justify-center">
              <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
            </div>
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              Loading your repositories…
            </p>
          </div>
        ) : filteredRepos.length > 0 ? (
          <div className="space-y-4">
            <p className="text-xs text-zinc-500 dark:text-zinc-400 font-semibold uppercase tracking-wider">
              Connected Repositories · {filteredRepos.length}
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {filteredRepos.map((repo) => (
                <div
                  key={repo.id}
                  className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl p-5 shadow-glass-sm hover:shadow-glass hover:border-accent-blue/30 transition-all duration-300 group"
                >
                  <div className="flex items-center gap-2.5 mb-3">
                    <div className="w-9 h-9 rounded-xl bg-accent-blue/10 flex items-center justify-center shrink-0">
                      <BookOpen className="w-4.5 h-4.5 text-accent-blue" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <h3 className="font-bold text-sm text-zinc-900 dark:text-zinc-100 truncate">
                        {repo.name}
                      </h3>
                      {repo.default_branch && (
                        <p className="flex items-center gap-1 text-[10px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                          <GitBranch className="w-3 h-3" /> {repo.default_branch}
                        </p>
                      )}
                    </div>
                  </div>

                  {repo.description && (
                    <p className="text-xs text-zinc-600 dark:text-zinc-400 line-clamp-2 mb-3">
                      {repo.description}
                    </p>
                  )}

                  <div className="flex items-center justify-between gap-3 border-t border-zinc-200/60 dark:border-zinc-800 pt-3 mt-auto">
                    <div className="flex items-center gap-3 text-[10px] text-zinc-500 dark:text-zinc-400">
                      <span>⭐ {repo.stars}</span>
                      <span>⑂ {repo.forks}</span>
                      {repo.created_at && (
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" /> {formatDateTime(repo.created_at)}
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => onSelectRepo(repo)}
                      className="btn-primary text-xs px-4 py-2 flex items-center gap-1.5 group-hover:shadow-glow-blue transition-all"
                    >
                      Open Repository <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-3xl p-16 text-center shadow-glass-sm">
            <div className="w-16 h-16 rounded-3xl bg-accent-blue/5 flex items-center justify-center mx-auto mb-5">
              <FolderGit2 className="w-8 h-8 text-zinc-400" />
            </div>
            <p className="text-lg font-bold text-zinc-800 dark:text-zinc-100 mb-2">
              {searchQuery ? "No matching repositories" : "No repositories connected"}
            </p>
            <p className="text-sm text-zinc-600 dark:text-zinc-400 max-w-sm mx-auto mb-6">
              {searchQuery
                ? `No repositories match "${searchQuery}".`
                : "Connect your first GitHub repository to start analyzing its code quality and security."}
            </p>
            {!searchQuery && (
              <button
                onClick={() => {
                  if (hasLlmKey) setShowConnectModal(true);
                }}
                disabled={!hasLlmKey}
                className={`btn-primary inline-flex items-center gap-2 ${
                  !hasLlmKey ? "cursor-not-allowed opacity-70" : ""
                }`}
              >
                <Plus className="w-4 h-4" /> Connect New Repository
              </button>
            )}
          </div>
        )}
      </div>

      {/* Connect Repo Modal */}
      {showConnectModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="glass-card w-full max-w-md p-8 animate-scale-in">
            <h3 className="text-lg font-bold text-zinc-900 dark:text-white mb-2">
              Connect Repository
            </h3>
            <p className="text-xs text-zinc-600 dark:text-zinc-400 mb-5">
              Enter a GitHub repository URL or slug
            </p>

            {connectError && (
              <div className="mb-4 bg-accent-red/10 border border-accent-red/20 text-accent-red p-3 rounded-2xl text-xs">
                {connectError}
              </div>
            )}

            <form onSubmit={handleConnect} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-300 mb-2">
                  Repository URL
                </label>
                <input
                  type="text"
                  required
                  placeholder="https://github.com/owner/repo"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  aria-label="GitHub repository URL"
                  className="input-glass text-sm"
                />
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowConnectModal(false)}
                  className="btn-secondary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={connecting}
                  className="btn-primary flex items-center gap-2"
                >
                  {connecting ? (
                    <>
                      <Loader2 className="w-3 h-3 animate-spin" /> Connecting…
                    </>
                  ) : (
                    "Connect"
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
