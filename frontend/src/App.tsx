import React, { useEffect, useState } from "react";
import { useAuthStore } from "./store/authStore";
import { useRepositoryStore } from "./store/repositoryStore";
import { useAnalysisStore } from "./store/analysisStore";
import { Sidebar } from "./components/Sidebar";
import { ChatBot } from "./components/ChatBot";
import { Landing } from "./pages/Landing";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
import { ForgotPassword } from "./pages/ForgotPassword";
import { ResetPassword } from "./pages/ResetPassword";
import { Dashboard } from "./pages/Dashboard";
import { RepositoryDetail } from "./pages/RepositoryDetail";
import { PRReview } from "./pages/PRReview";
import { Settings } from "./pages/Settings";
import { Loader2, Shield } from "lucide-react";

export const App: React.FC = () => {
  const { token, user, initialize, loading, justLoggedIn, clearJustLoggedIn } = useAuthStore();
  const { activeRepo, activePr, setActiveRepo, setActivePr } = useRepositoryStore();

  // Navigation tabs
  const [activeTab, setActiveTab] = useState("dashboard");

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

  // Post-login behavior: open the Settings page first after a successful
  // interactive login (NOT after a session restore on refresh). Once setup is
  // complete the flag is cleared so the user isn't trapped on Settings.
  useEffect(() => {
    if (!user) return;
    if (justLoggedIn) {
      setActiveTab("settings");
      if (isSetupComplete) {
        clearJustLoggedIn();
      }
    } else if (activeTab === "settings" && isSetupComplete && !justLoggedIn) {
      // Setup completed while on Settings — leave the user where they are;
      // they can navigate to the Dashboard themselves.
    }
  }, [user?.id, isSetupComplete, justLoggedIn]);

  // Restore the last viewed repository on refresh so deep-linking/refresh
  // doesn't dump the user back on the Dashboard.
  useEffect(() => {
    if (!user || activeRepo) return;
    try {
      const saved = localStorage.getItem("repolens-active-repo");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed && parsed.id && parsed.name) {
          setActiveRepo(parsed);
        } else {
          localStorage.removeItem("repolens-active-repo");
        }
      }
    } catch {
      localStorage.removeItem("repolens-active-repo");
    }
  }, [user?.id]);

  // Persist the active repository for refresh restore
  useEffect(() => {
    try {
      if (activeRepo) {
        localStorage.setItem("repolens-active-repo", JSON.stringify(activeRepo));
      } else {
        localStorage.removeItem("repolens-active-repo");
      }
    } catch {
      // ignore persistence errors
    }
  }, [activeRepo]);

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
    return <ResetPassword token={resetToken} onNavigateToLogin={navigateBackToLogin} />;
  }

  // Not authenticated — show landing page first
  if (!token) {
    if (showLanding) {
      return (
        <Landing
          onNavigateToLogin={() => { setShowLanding(false); setAuthPage("login"); }}
          onNavigateToRegister={() => { setShowLanding(false); setAuthPage("register"); }}
        />
      );
    }
    if (authPage === "forgot") {
      return (
        <ForgotPassword
          onNavigateToLogin={() => setAuthPage("login")}
          onContinueToReset={(tok) => { setResetToken(tok); setAuthPage("reset"); }}
        />
      );
    }
    return authPage === "login" ? (
      <Login
        onNavigateToRegister={() => setAuthPage("register")}
        onNavigateToForgotPassword={() => setAuthPage("forgot")}
      />
    ) : (
      <Register onNavigateToLogin={() => setAuthPage("login")} />
    );
  }

  // PR review takes priority screen overlay
  if (activePr) {
    return (
      <PRReview
        onBack={() => setActivePr(null)}
      />
    );
  }

  const renderContent = () => {
    if (activeTab === "repositories" && activeRepo) {
      return (
        <RepositoryDetail
          onBack={() => setActiveRepo(null)}
          onSelectPr={(pr) => setActivePr(pr)}
        />
      );
    }

    switch (activeTab) {
      case "dashboard":
        return <Dashboard onSelectRepoId={async (id) => {
          const { repositories, setActiveRepo } = useRepositoryStore.getState();
          const target = repositories.find(r => r.id === id);
          if (target) {
            setActiveRepo(target);
            setActiveTab("repositories");
          }
        }} />;
      case "repositories":
        return <Dashboard onSelectRepoId={async (id) => {
          const { repositories, setActiveRepo } = useRepositoryStore.getState();
          const target = repositories.find(r => r.id === id);
          if (target) {
            setActiveRepo(target);
          }
        }} />;
      case "settings":
        return <Settings />;
      default:
        return <Dashboard onSelectRepoId={() => {}} />;
    }
  };

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar activeTab={activeTab} setActiveTab={(tab) => {
        if (tab !== "repositories") {
          setActiveRepo(null);
        }
        setActiveTab(tab);
      }} />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {renderContent()}
      </div>

      {/* AI Review Assistant — ChatBot accessible from all authenticated pages */}
      <ChatBot
        currentPage={activeTab}
        findingContext={(() => {
          const { activeAnalysis, securityFindings, codeSmells } = useAnalysisStore.getState();
          const { activeRepo } = useRepositoryStore.getState();
          
          if (activeTab === "repositories" && activeRepo && activeAnalysis) {
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
          
          if (activeTab === "dashboard") {
            return {
              type: "dashboard",
              active_repository: activeRepo?.name || null,
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
