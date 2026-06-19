import React from "react";
import { useAuthStore } from "../store/authStore";
import { LayoutDashboard, FolderKanban, Code, Settings, LogOut, ShieldAlert } from "lucide-react";

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab }) => {
  const { user, logout } = useAuthStore();

  const menuItems = [
    { id: "dashboard", name: "Dashboard", icon: LayoutDashboard },
    { id: "repositories", name: "Repositories", icon: FolderKanban },
    { id: "local-review", name: "Local Snippet Review", icon: Code },
    { id: "settings", name: "Settings", icon: Settings },
  ];

  return (
    <div className="w-64 bg-surface border-r border-border flex flex-col min-h-screen">
      {/* Branding */}
      <div className="p-6 border-b border-border flex items-center gap-3">
        <div className="bg-accent-blue/10 p-2 rounded-lg text-accent-blue">
          <ShieldAlert className="w-6 h-6" />
        </div>
        <div>
          <h1 className="text-md font-bold tracking-tight text-white">AI Code Reviewer</h1>
          <span className="text-xs text-muted">SaaS Platform v1.0</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1">
        {menuItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 text-sm font-medium rounded-lg transition-colors duration-150 ${
                isActive
                  ? "bg-accent-blue/10 text-accent-blue"
                  : "text-zinc-400 hover:bg-zinc-800 hover:text-white"
              }`}
            >
              <Icon className="w-4 h-4" />
              {item.name}
            </button>
          );
        })}
      </nav>

      {/* Profile & Logout */}
      <div className="p-4 border-t border-border mt-auto">
        <div className="flex items-center gap-3 mb-4 px-2">
          <div className="w-8 h-8 rounded-full bg-zinc-700 flex items-center justify-center font-semibold text-white">
            {user?.email[0].toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-white truncate">{user?.email}</p>
            <span className="text-[10px] text-muted block truncate">Developer Account</span>
          </div>
        </div>
        <button
          onClick={logout}
          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm font-medium text-red-400 hover:bg-red-500/10 rounded-lg transition-colors duration-150"
        >
          <LogOut className="w-4 h-4" />
          Log Out
        </button>
      </div>
    </div>
  );
};

