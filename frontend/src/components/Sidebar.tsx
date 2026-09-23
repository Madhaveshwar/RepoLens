import React, { useState } from "react";
import { useAuthStore } from "../store/authStore";
import { useThemeStore } from "../store/themeStore";
import {
  LayoutDashboard, FolderKanban, Settings, LogOut,
  Shield, ChevronLeft, Sun, Moon
} from "lucide-react";

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab }) => {
  const { user, logout } = useAuthStore();
  const { theme, toggleTheme } = useThemeStore();
  const [collapsed, setCollapsed] = useState(false);

  const menuItems = [
    { id: "dashboard", name: "Dashboard", icon: LayoutDashboard },
    { id: "repositories", name: "Repositories", icon: FolderKanban },
    { id: "settings", name: "Settings", icon: Settings },
  ];

  return (
    <div className={`relative ${collapsed ? 'w-20' : 'w-64'} flex-shrink-0 transition-all duration-500 ease-[cubic-bezier(0.25,0.8,0.25,1)]`}>
      {/* Floating glass sidebar */}
      <div className="fixed top-4 bottom-4 left-4 w-[inherit] flex flex-col bg-white border border-zinc-200/60 shadow-glass rounded-3xl overflow-hidden z-40">
        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="absolute -right-3 top-10 w-6 h-6 bg-white border border-zinc-200 rounded-full flex items-center justify-center text-zinc-400 hover:text-zinc-600 hover:border-zinc-300 z-10 transition-all shadow-sm"
        >
          <ChevronLeft className={`w-3.5 h-3.5 transition-transform duration-300 ${collapsed ? 'rotate-180' : ''}`} />
        </button>

        {/* Brand */}
        <div className="p-5 border-b border-zinc-200/40 flex items-center gap-3">
          <div className="w-10 h-10 rounded-2xl bg-accent-gradient flex items-center justify-center shadow-glow-blue flex-shrink-0">
            <Shield className="w-5 h-5 text-white" />
          </div>
          {!collapsed && (
            <div className="min-w-0 animate-fade-in">
              <h1 className="text-sm font-bold text-zinc-900 truncate">RepoLens AI</h1>
              <span className="text-[10px] text-zinc-700 font-semibold">Code Analysis</span>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-2xl transition-all duration-300 group ${
                  isActive
                    ? "bg-accent-blue/10 border border-accent-blue/25 shadow-sm text-accent-blue font-bold"
                    : "text-zinc-700 hover:text-zinc-950 hover:bg-zinc-100 border border-transparent hover:scale-[1.02]"
                }`}
                title={collapsed ? item.name : undefined}
              >
                <Icon className={`w-4.5 h-4.5 flex-shrink-0 transition-transform duration-300 ${
                  isActive ? 'scale-110' : 'group-hover:scale-110'
                }`} />
                {!collapsed && (
                  <span className="text-xs font-bold truncate">{item.name}</span>
                )}
                {isActive && !collapsed && (
                  <div className="w-1.5 h-1.5 rounded-full bg-accent-blue ml-auto animate-pulse" />
                )}
              </button>
            );
          })}
        </nav>

        {/* Appearance: Light/Dark toggle */}
        <div className="px-3 pb-1">
          <button
            onClick={toggleTheme}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-2xl transition-all duration-300 text-zinc-700 hover:text-zinc-950 hover:bg-zinc-100 border border-transparent hover:scale-[1.02] ${collapsed ? 'justify-center' : ''}`}
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? <Sun className="w-4.5 h-4.5 flex-shrink-0" /> : <Moon className="w-4.5 h-4.5 flex-shrink-0" />}
            {!collapsed && (
              <span className="text-xs font-bold truncate">
                {theme === "dark" ? "Light Mode" : "Dark Mode"}
              </span>
            )}
          </button>
        </div>

        {/* User profile & logout */}
        <div className="p-3 border-t border-zinc-200/40 mt-auto">
          <div className={`flex items-center gap-3 px-3 py-3 rounded-2xl bg-zinc-50 ${collapsed ? 'justify-center' : ''}`}>
            <div className="w-9 h-9 rounded-xl bg-accent-gradient/20 flex items-center justify-center font-bold text-xs text-accent-blue border border-accent-blue/10 flex-shrink-0">
              {user?.email?.[0]?.toUpperCase() || "U"}
            </div>
            {!collapsed && (
              <div className="min-w-0 flex-1 animate-fade-in">
                <p className="text-xs font-bold text-zinc-900 truncate">{user?.email?.split("@")[0] || "User"}</p>
                <span className="text-[10px] text-zinc-700 font-semibold block truncate">Developer</span>
              </div>
            )}
          </div>

          <button
            onClick={logout}
            className={`w-full flex items-center gap-3 px-4 py-3 mt-1 text-sm font-bold text-red-600 hover:text-red-700 hover:bg-red-50 rounded-2xl transition-all duration-300 ${collapsed ? 'justify-center' : ''}`}
            title="Log Out"
          >
            <LogOut className="w-4 h-4 flex-shrink-0" />
            {!collapsed && <span className="text-xs font-bold">Log Out</span>}
          </button>
        </div>
      </div>
    </div>
  );
};
