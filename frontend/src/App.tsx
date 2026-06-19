import React, { useEffect, useState } from "react";
import { useAuthStore } from "./store/authStore";
import { useRepositoryStore } from "./store/repositoryStore";
import { Sidebar } from "./components/Sidebar";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
import { Dashboard } from "./pages/Dashboard";
import { RepositoryDetail } from "./pages/RepositoryDetail";
import { PRReview } from "./pages/PRReview";
import { LocalReview } from "./pages/LocalReview";
import { Settings } from "./pages/Settings";
import { Loader2 } from "lucide-react";

export const App: React.FC = () => {
  const { token, initialize, loading } = useAuthStore();
  const { activeRepo, activePr, setActiveRepo, setActivePr } = useRepositoryStore();
  
  // Navigation tabs
  const [activeTab, setActiveTab] = useState("dashboard");
  
  // Login vs Register page toggle
  const [authPage, setAuthPage] = useState<"login" | "register">("login");

  useEffect(() => {
    if (token) {
      initialize();
    }
  }, [token]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background text-white">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-10 h-10 animate-spin text-accent-blue" />
          <p className="text-sm text-muted">Initializing profile session...</p>
        </div>
      </div>
    );
  }

  // Not authenticated
  if (!token) {
    return authPage === "login" ? (
      <Login onNavigateToRegister={() => setAuthPage("register")} />
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
        // Fallback to dashboard selection
        return <Dashboard onSelectRepoId={async (id) => {
          const { repositories, setActiveRepo } = useRepositoryStore.getState();
          const target = repositories.find(r => r.id === id);
          if (target) {
            setActiveRepo(target);
          }
        }} />;
      case "local-review":
        return <LocalReview />;
      case "settings":
        return <Settings />;
      default:
        return <Dashboard onSelectRepoId={() => {}} />;
    }
  };

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar activeTab={activeTab} setActiveTab={(tab) => {
        // Reset active repo details if navigating away from repositories
        if (tab !== "repositories") {
          setActiveRepo(null);
        }
        setActiveTab(tab);
      }} />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden bg-background text-white">
        {renderContent()}
      </div>
    </div>
  );
};

export default App;

