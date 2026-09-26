import React, { useEffect, useRef, useState } from "react";
import { useAuthStore } from "./store/authStore";
import { useRepositoryStore, type Repository } from "./store/repositoryStore";
import { useAnalysisStore } from "./store/analysisStore";
import { Sidebar } from "./components/Sidebar";
import { ChatBot } from "./components/ChatBot";
import { Landing } from "./pages/Landing";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
import { ForgotPassword } from "./pages/ForgotPassword";
import { ResetPassword } from "./pages/ResetPassword";
import { RepositorySelection } from "./pages/RepositorySelection";
import { RepositoryDetail } from "./pages/RepositoryDetail";
import { PRReview } from "./pages/PRReview";
import { Settings } from "./pages/Settings";
import { Help } from "./pages/Help";
import { ToastContainer } from "./components/Toast";
import { useQuery } from "@tanstack/react-query";
import axios from "./lib/api";
import { Loader2, Shield } from "lucide-react";

// ─── Session-scoped active repository ──────────────────────────────
// "Active repository" is an EXPLICIT, session-scoped user choice:
//   • set only when the user clicks a repository (or connects a new one),
//   • cleared on logout/login and never persisted to localStorage,
//   • restored across a page refresh ONLY when the URL (#/repo/<id>)
//     explicitly identifies it.
// It is intentionally not persisted: a new session always starts with NO
// active repository.

/** Repository id from the URL deep link (#/repo/<id>[/<tab>]), if any. */
function readRepoIdFromHash(): string | null {
  const match = window.location.hash.match(/^#\/repo\/([^/?]+)/);
  return match ? match[1] : null;
}

/** Remove a stale repository deep link from the URL. */
function clearRepoHash() {
  if (window.location.hash.startsWith("#/repo/")) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
}

export const App: React.FC = () => {
  const { token, user, initialize, loading, justLoggedIn, clearJustLoggedIn } = useAuthStore();
  const { activeRepo, activePr, setActiveRepo, setActivePr, hydrateActiveRepo } = useRepositoryStore();

  // Navigation tabs
  const [activeTab, setActiveTab] = useState("repositories");

  // Whether to show the landing page or auth forms
  const [showLanding, setShowLanding] = useState(true);
  // Login vs Register page toggle (plus forgot/reset password pages)
  const [authPage, setAuthPage] = useState<"login" | "register" | "forgot" | "reset">("login");
  // Token for the password-reset page (from deep-link hash or the dev flow)
  const [resetToken, setResetToken] = useState<string | null>(null);

  useEffect(() => {
    if (token) {
      initialize();
    }
  }, [token]);

  // Support password-reset deep links of the form
  // http://<frontend>/#/reset-password?token=<token>
  useEffect(() => {
    const hash = window.location.hash;
    if (hash.startsWith("#/reset-password")) {
      const params = new URLSearchParams(hash.split("?")[1] || "");
      const tokenFromHash = params.get("token");
      if (tokenFromHash) {
        setResetToken(tokenFromHash);
        setShowLanding(false);
        setAuthPage("reset");
      }
    }
  }, []);

  // Has an LLM key or GitHub PAT been configured?
  const hasLlmKey = user
    ? (user.has_groq_api_key || user.has_openai_api_key ||
       user.has_claude_api_key || user.has_gemini_api_key || user.has_openrouter_api_key)
    : false;
  const hasGithubPat = user?.has_github_pat || false;
  const isSetupComplete = user ? (hasLlmKey && hasGithubPat) : false;

  // ─── Post-login behavior ───────────────────────────────────────────
  // After a fresh interactive login (justLoggedIn === true):
  //   • If credentials are missing → Settings page
  //   • If credentials are complete → Repository Selection page
  // In BOTH cases, the active repository is NONE until the user selects one.
  //
  // On a page REFRESH (justLoggedIn === false, token restored from
  // localStorage), we do NOT auto-restore a previous active repository.
  // The user is placed on "repositories" (Repository Selection) unless
  // setup is incomplete.
  useEffect(() => {
    if (!user) return;

    if (justLoggedIn) {
      // A new session starts with NO active repository — never restore a
      // previously selected one, and clear any stale repository URL.
      setActiveRepo(null);
      setActivePr(null);
      clearRepoHash();

      if (!isSetupComplete) {
        // Credentials are missing → send to Settings first
        setActiveTab("settings");
      } else {
        // Credentials OK → Repository Selection
        setActiveTab("repositories");
        clearJustLoggedIn();
      }
    }
    // Zustand setters are stable; user/isSetupComplete read intentionally.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, justLoggedIn]);

  // When setup completes on the Settings page during onboarding,
  // navigate to Repository Selection.
  useEffect(() => {
    if (!user || !justLoggedIn) return;
    if (isSetupComplete) {
      clearJustLoggedIn();
      setActiveTab("repositories");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSetupComplete, justLoggedIn]);

  // ─── Session restore & URL deep-link handling ────────────────────
  // The URL is the ONLY thing that can restore a repository across a page
  // refresh, because the URL explicitly identifies it (#/repo/<id>).
  // A new session (fresh login) must NEVER restore a previous repository.
  const [bootstrapped, setBootstrapped] = useState(false);
  useEffect(() => {
    if (bootstrapped) return;
    // With a token, wait for /users/me to resolve so we know whether the
    // session is valid before making navigation decisions.
    if (token && (loading || !user)) return;
    setBootstrapped(true);
    if (!token) return;
    if (justLoggedIn) return; // interactive login — handled by the effect above

    const deepLinkRepoId = readRepoIdFromHash();
    if (deepLinkRepoId) {
      // Refresh/reload while viewing a repository: the URL explicitly
      // identifies it, so restore it. A partial object is enough to render;
      // the ownership check below hydrates it with real data (or bounces
      // to Repository Selection if it does not belong to this user).
      setActiveRepo({ id: deepLinkRepoId } as Repository);
      setActiveTab("repo-detail");
    } else {
      // Plain refresh with no repository URL → Repository Selection.
      setActiveRepo(null);
      setActiveTab("repositories");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, user?.id, loading, justLoggedIn, bootstrapped]);

  // Keep the URL hash aligned with the explicit repository view:
  //   • repo-detail   → #/repo/<id> (survives refresh — the URL owns it)
  //   • anything else → clear a stale #/repo/<id> so an old deep link can
  //     never resurrect a repository the user has not selected this session.
  // Gated on `bootstrapped` so the deep-link URL is NOT wiped while the
  // session-restore effect is still waiting for /users/me to resolve.
  useEffect(() => {
    if (!bootstrapped || !token) return;
    if (activeTab === "repo-detail" && activeRepo?.id) {
      if (readRepoIdFromHash() !== activeRepo.id) {
        window.history.replaceState(null, "", `#/repo/${activeRepo.id}`);
      }
    } else {
      clearRepoHash();
    }
  }, [bootstrapped, token, activeTab, activeRepo?.id]);

  // ─── Active repository ownership & freshness ─────────────────────
  // Once this user's repositories are known:
  //   • hydrate a partial repository object (URL restore) with real data;
  //   • drop any active repository that is NOT in the user's list —
  //     deleted/disconnected repositories, or a deep link to another
  //     user's repository, must never expose repository-specific state.
  const { data: reposData } = useQuery({
    queryKey: ["repositories"],
    queryFn: async () => {
      const res = await axios.get("/repositories");
      return res.data;
    },
    enabled: !!user && !!activeRepo,
    staleTime: 30_000,
    gcTime: 120_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  useEffect(() => {
    if (!Array.isArray(reposData) || !activeRepo) return;
    const match = (reposData as Repository[]).find((r) => r.id === activeRepo.id);
    if (!match) {
      if (!loading) {
        setActiveRepo(null);
        setActivePr(null);
        setActiveTab("repositories");
      }
      return;
    }
    // Refresh the object so the detail view shows current metadata without
    // touching repository-specific scan state (same repository — no reset).
    if (
      !activeRepo.name ||
      activeRepo.description !== match.description ||
      activeRepo.stars !== match.stars ||
      activeRepo.forks !== match.forks ||
      activeRepo.open_prs_count !== match.open_prs_count ||
      activeRepo.open_issues_count !== match.open_issues_count ||
      activeRepo.default_branch !== match.default_branch
    ) {
      hydrateActiveRepo(match);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reposData, activeRepo?.id, loading]);

  // Safety net: if the active repository disappears (deleted/disconnected)
  // while the detail view is open, fall back to the repository selection.
  useEffect(() => {
    if (activeTab === "repo-detail" && !activeRepo && !loading) {
      setActiveTab("repositories");
    }
  }, [activeTab, activeRepo, loading]);

  // Credentials changed while authenticated (saved or removed) → drop the
  // active repository and return to Repository Selection. Never keep
  // repository-specific state across a credentials change.
  const prevSetupCompleteRef = useRef<boolean | null>(null);
  useEffect(() => {
    if (!user) {
      prevSetupCompleteRef.current = null;
      return;
    }
    const prev = prevSetupCompleteRef.current;
    prevSetupCompleteRef.current = Boolean(isSetupComplete);
    if (prev === null || prev === isSetupComplete) return;
    setActiveRepo(null);
    setActivePr(null);
    setActiveTab("repositories");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSetupComplete, user?.id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background">
        <div className="flex flex-col items-center gap-6">
          <div className="w-16 h-16 rounded-3xl bg-accent-gradient flex items-center justify-center shadow-glow-blue animate-float">
            <Shield className="w-8 h-8 text-white" />
          </div>
          <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
          <p className="text-base text-zinc-700 font-medium dark:text-zinc-200">Initializing your workspace...</p>
        </div>
      </div>
    );
  }

  // Password reset page — reachable whether or not the user is signed in
  const navigateBackToLogin = () => {
    setResetToken(null);
    setAuthPage("login");
    setShowLanding(false);
    if (window.location.hash) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
  };
  if (authPage === "reset") {
    return (
      <>
        <ResetPassword token={resetToken} onNavigateToLogin={navigateBackToLogin} />
        <ToastContainer />
      </>
    );
  }

  // Not authenticated — show landing page first
  if (!token) {
    if (showLanding) {
      return (
        <>
          <Landing
            onNavigateToLogin={() => { setShowLanding(false); setAuthPage("login"); }}
            onNavigateToRegister={() => { setShowLanding(false); setAuthPage("register"); }}
          />
          <ToastContainer />
        </>
      );
    }
    if (authPage === "forgot") {
      return (
        <>
          <ForgotPassword
            onNavigateToLogin={() => setAuthPage("login")}
            onContinueToReset={(tok) => { setResetToken(tok); setAuthPage("reset"); }}
          />
          <ToastContainer />
        </>
      );
    }
    const authForm = authPage === "login" ? (
      <Login
        onNavigateToRegister={() => setAuthPage("register")}
        onNavigateToForgotPassword={() => setAuthPage("forgot")}
      />
    ) : (
      <Register onNavigateToLogin={() => setAuthPage("login")} />
    );
    return (
      <>
        {authForm}
        <ToastContainer />
      </>
    );
  }

  // Explicit repository selection — the ONLY way a repository becomes active
  // (besides a URL deep link). A selection is a user action, never inferred.
  const handleSelectRepo = (repo: Repository) => {
    setActiveRepo(repo);
    setActiveTab("repo-detail");
  };

  // PR review takes priority screen overlay
  if (activePr) {
    return (
      <>
        <PRReview
          onBack={() => setActivePr(null)}
        />
        <ToastContainer />
      </>
    );
  }

  const renderContent = () => {
    // Repository Detail view — ONLY when the user explicitly selected (or
    // connected) a repository this session, or the URL deep link explicitly
    // names it. No repository can ever be "active" by default.
    if (activeTab === "repo-detail" && activeRepo) {
      return (
        <RepositoryDetail
          onBack={() => {
            // Back = explicit deselect. The URL is cleared too, so a refresh
            // lands on Repository Selection, not on the deselected repository.
            setActiveRepo(null);
            setActiveTab("repositories");
          }}
          onSelectPr={(pr) => setActivePr(pr)}
        />
      );
    }
    // Guard: repo-detail without an explicitly selected repository is not
    // reachable — Repository Selection is the only authenticated landing.
    if (activeTab === "repo-detail" && !activeRepo) {
      return (
        <RepositorySelection
          onSelectRepo={handleSelectRepo}
          onNavigateToSettings={() => setActiveTab("settings")}
        />
      );
    }

    switch (activeTab) {
      case "repositories":
        return (
          <RepositorySelection
            onSelectRepo={handleSelectRepo}
            onNavigateToSettings={() => setActiveTab("settings")}
          />
        );
      case "settings":
        return <Settings />;
      case "help":
        return <Help />;
      default:
        return (
          <RepositorySelection
            onSelectRepo={handleSelectRepo}
            onNavigateToSettings={() => setActiveTab("settings")}
          />
        );
    }
  };

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar activeTab={activeTab} setActiveTab={(tab) => {
        if (tab !== "repo-detail") {
          // Navigating away from a repository view deselects it explicitly.
          setActiveRepo(null);
        }
        setActiveTab(tab);
      }} />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {renderContent()}
        <ToastContainer />
      </div>

      {/* AI Review Assistant — ChatBot accessible from all authenticated pages */}
      <ChatBot
        currentPage={activeTab}
        findingContext={(() => {
          const { activeAnalysis, securityFindings, codeSmells } = useAnalysisStore.getState();
          const { activeRepo } = useRepositoryStore.getState();

          if (activeTab === "repo-detail" && activeRepo && activeAnalysis) {
            return {
              type: "repository_scan",
              repository: activeRepo.name,
              risk_score: activeAnalysis.risk_score,
              status: activeAnalysis.status,
              security_findings_count: securityFindings.length,
              code_smells_count: codeSmells.length,
              security_findings: securityFindings.slice(0, 5).map(f => ({
                issue: f.issue,
                severity: f.severity,
                file: f.file,
                line: f.line,
                suggestion: f.suggestion,
              })),
              code_smells: codeSmells.slice(0, 5).map(s => ({
                issue: s.issue,
                severity: s.severity,
                file: s.file,
                line: s.line,
              })),
            };
          }
          

          if (activeTab === "settings") {
            return {
              type: "settings",
              message: "The user is configuring API keys for LLM providers (Groq, OpenAI, Claude, Gemini, OpenRouter) and GitHub PAT. The user can test connections, set defaults, and manage encryption.",
            };
          }
          
          return undefined;
        })()}
      />
    </div>
  );
};

export default App;
