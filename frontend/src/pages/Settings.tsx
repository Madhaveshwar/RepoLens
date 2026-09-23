import React, { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import axios from "../lib/api";
import { useAuthStore } from "../store/authStore";
import {
  Key, Github, CheckCircle2, AlertTriangle, Loader2,
  Eye, EyeOff, Brain, Shield, Rocket, X, Trash2, Sparkles, Cpu, Zap, Globe,
  Sun, Moon
} from "lucide-react";
import { useThemeStore } from "../store/themeStore";

// ── Types ──

interface ProviderStatus {
  configured: boolean;
  status: string;        // "Configured" | "Invalid" | "Missing"
  api_status: string;    // "Connected" | "Invalid Key" | "Missing Key" | ...
  last_tested?: string;
}

interface ProvidersDiagnostics {
  providers: Record<string, ProviderStatus>;
  encryption_status?: string;
  database_status?: string;
  jwt_status?: string;
}

type ToastType = "success" | "error";

interface Toast {
  id: number;
  type: ToastType;
  message: string;
}

let toastIdCounter = 0;

// ── Constants ──

const PROVIDERS = [
  {
    key: "github",
    label: "GitHub Token",
    icon: <Github className="w-4 h-4" />,
    placeholder: "ghp_xxxxxxxxxxxxxxxxxxxx",
    docsUrl: "https://github.com/settings/tokens",
    fieldName: "github_pat",
    optional: true,
    category: "integration"
  },
  {
    key: "groq",
    label: "Groq API Key",
    icon: <Zap className="w-4 h-4" />,
    placeholder: "gsk_xxxxxxxxxxxxxxxxxxxx",
    docsUrl: "https://console.groq.com/keys",
    fieldName: "groq_api_key",
    optional: false,
    category: "llm"
  },
  {
    key: "openai",
    label: "OpenAI API Key",
    icon: <Brain className="w-4 h-4" />,
    placeholder: "sk-xxxxxxxxxxxxxxxxxxxx",
    docsUrl: "https://platform.openai.com/api-keys",
    fieldName: "openai_api_key",
    optional: false,
    category: "llm"
  },
  {
    key: "claude",
    label: "Claude API Key",
    icon: <Sparkles className="w-4 h-4" />,
    placeholder: "sk-ant-xxxxxxxxxxxxxxxxxxxx",
    docsUrl: "https://console.anthropic.com/settings/keys",
    fieldName: "claude_api_key",
    optional: false,
    category: "llm"
  },
  {
    key: "gemini",
    label: "Gemini API Key",
    icon: <Cpu className="w-4 h-4" />,
    placeholder: "AIzaxxxxxxxxxxxxxxxxxxxxxxxx",
    docsUrl: "https://aistudio.google.com/app/apikey",
    fieldName: "gemini_api_key",
    optional: false,
    category: "llm"
  },
  {
    key: "openrouter",
    label: "OpenRouter API Key",
    icon: <Globe className="w-4 h-4" />,
    placeholder: "sk-or-xxxxxxxxxxxxxxxxxxxx",
    docsUrl: "https://openrouter.ai/keys",
    fieldName: "openrouter_api_key",
    optional: false,
    category: "llm"
  }
];

const EMPTY_FORM_KEYS: Record<string, string> = Object.fromEntries(
  PROVIDERS.map(p => [p.key, ""])
);

// ── Toast ──

const ToastContainer: React.FC<{ toasts: Toast[]; onDismiss: (id: number) => void }> = ({ toasts, onDismiss }) => (
  <div className="fixed bottom-6 right-6 z-[100] flex flex-col gap-2 max-w-sm">
    <AnimatePresence>
      {toasts.map((t) => (
        <motion.div
          key={t.id}
          initial={{ opacity: 0, y: 20, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -10, scale: 0.95 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
          className={`flex items-start gap-3 px-5 py-4 rounded-2xl shadow-lg border backdrop-blur-sm ${
            t.type === "success"
              ? "bg-emerald-50 border-emerald-200 text-emerald-800"
              : "bg-red-50 border-red-200 text-red-800"
          }`}
        >
          {t.type === "success"
            ? <CheckCircle2 className="w-5 h-5 shrink-0 mt-0.5" />
            : <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          }
          <p className="text-sm font-medium flex-1">{t.message}</p>
          <button onClick={() => onDismiss(t.id)} className="shrink-0 bg-transparent border-0 cursor-pointer p-0.5 hover:opacity-70 transition-opacity">
            <X className="w-4 h-4" />
          </button>
        </motion.div>
      ))}
    </AnimatePresence>
  </div>
);

// ── Settings ──

export const Settings: React.FC = () => {
  const { user, initialize } = useAuthStore();
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((type: ToastType, message: string) => {
    const id = ++toastIdCounter;
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 5000);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // ── Diagnostics ──
  const [diagnostics, setDiagnostics] = useState<ProvidersDiagnostics | null>(null);
  const [loadingDiag, setLoadingDiag] = useState(false);

  const fetchDiagnostics = useCallback(async () => {
    if (!user) return;
    setLoadingDiag(true);
    try {
      const res = await axios.get("/users/me/diagnostics");
      setDiagnostics(res.data as ProvidersDiagnostics);
    } catch {
      // silently fail
    } finally {
      setLoadingDiag(false);
    }
  }, [user]);

  useEffect(() => {
    fetchDiagnostics();
  }, [fetchDiagnostics]);

  // ── Form state ──
  const [formKeys, setFormKeys] = useState<Record<string, string>>({ ...EMPTY_FORM_KEYS });
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [deletingProvider, setDeletingProvider] = useState<string | null>(null);

  const getProviderStatus = (providerKey: string): { status: string; api_status: string; last_tested?: string } => {
    const d = diagnostics?.providers?.[providerKey];
    if (!d) {
      // Check user profile as fallback
      const fieldKey = providerKey === "github" ? "has_github_pat" : `has_${providerKey}_api_key`;
      const configured = user ? (user as any)[fieldKey] : false;
      return { status: configured ? "Configured" : "Missing", api_status: configured ? "Configured" : "Missing Key" };
    }
    return { status: d.status, api_status: d.api_status, last_tested: d.last_tested };
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload: Record<string, any> = {};
      for (const provider of PROVIDERS) {
        const value = formKeys[provider.key];
        if (value.trim()) {
          payload[provider.fieldName] = value.trim();
        }
      }

      if (Object.keys(payload).length === 0) {
        addToast("error", "Enter at least one credential to save.");
        setSaving(false);
        return;
      }

      await axios.post("/users/keys", payload);
      addToast("success", "Credentials saved successfully");
      setFormKeys({ ...EMPTY_FORM_KEYS });
      await initialize();
      await fetchDiagnostics();
    } catch (err: any) {
      const detail = err.response?.data?.detail || "Failed to save credentials.";
      // Extract first line for a concise toast
      const firstLine = detail.split("\n")[0].trim();
      addToast("error", firstLine);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteCredential = async (providerKey: string) => {
    setDeletingProvider(providerKey);
    try {
      await axios.delete(`/users/keys/${providerKey}`);
      addToast("success", `${providerKey.charAt(0).toUpperCase() + providerKey.slice(1)} credential deleted`);
      await initialize();
      await fetchDiagnostics();
    } catch (err: any) {
      const detail = err.response?.data?.detail || "Failed to delete credential.";
      addToast("error", detail);
    } finally {
      setDeletingProvider(null);
    }
  };

  const toggleShowKey = (provider: string) => {
    setShowKeys((prev) => ({ ...prev, [provider]: !prev[provider] }));
  };

  const hasLlmKey = user ? (
    user.has_groq_api_key || user.has_openai_api_key ||
    user.has_claude_api_key || user.has_gemini_api_key || user.has_openrouter_api_key
  ) : false;

  const { theme, setTheme } = useThemeStore();

  return (
    <div className="flex-1 p-8 overflow-y-auto max-h-screen">
      <div className="max-w-2xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-zinc-900">Settings</h1>
          <p className="text-base text-zinc-700 font-medium mt-1">Configure your API credentials and default LLM provider</p>
        </div>

        {/* Onboarding */}
        {!hasLlmKey && user && (
          <motion.div
            className="mb-8 bg-gradient-to-br from-violet-50 to-blue-50 border border-violet-200/60 rounded-3xl p-8 shadow-sm relative overflow-hidden"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-bl from-violet-200/20 to-transparent rounded-full -mr-20 -mt-20 pointer-events-none" />
            <div className="relative z-10">
              <div className="flex items-center gap-3 mb-2">
                <div className="w-12 h-12 rounded-2xl bg-accent-gradient flex items-center justify-center shadow-glow-blue">
                  <Rocket className="w-6 h-6 text-zinc-900" />
                </div>
                <div>
                  <h2 className="text-2xl font-bold text-zinc-900">Welcome to RepoLens AI</h2>
                  <p className="text-base text-zinc-700 mt-0.5">Configure an AI provider to get started</p>
                </div>
              </div>
              <div className="mt-4 bg-white/50 backdrop-blur-sm border border-violet-200/30 rounded-2xl p-4 flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />                  <p className="text-xs text-zinc-800 font-medium leading-relaxed">
                  Add at least one LLM API key below (<strong>Groq</strong>, <strong>OpenAI</strong>, <strong>Claude</strong>, <strong>Gemini</strong>, or <strong>OpenRouter</strong>) to run code reviews and scan repositories.
                  Your key is encrypted with AES-256 before storage.
                </p>
              </div>
            </div>
          </motion.div>
        )}

        {/* Credential Status Summary */}
        <div className="glass-card p-6 mb-8">
          <div className="flex items-center gap-3 mb-5 border-b border-border/40 pb-4">
            <div className="w-10 h-10 rounded-2xl bg-emerald-50 flex items-center justify-center">
              <Shield className="w-5 h-5 text-emerald-600" />
            </div>
            <div>
              <h3 className="font-bold font-sans text-zinc-950">Credential Status</h3>
              <p className="text-xs text-zinc-700 font-medium">Real-time validation against provider APIs</p>
            </div>
          </div>

          {loadingDiag ? (
            <div className="flex justify-center py-6">
              <Loader2 className="w-5 h-5 animate-spin text-accent-blue" />
            </div>
          ) : (
            <div className="space-y-3">
              {PROVIDERS.map((provider) => {
                const s = getProviderStatus(provider.key);
                const isConnected = s.status === "Configured" && s.api_status === "Connected";
                const isInvalid = s.status === "Invalid";
                const isConfigured = s.status !== "Missing";

                return (
                  <div key={provider.key} className="flex items-center justify-between py-2.5 border-b border-border/20 last:border-0">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-xl bg-zinc-50 flex items-center justify-center">
                        {provider.icon}
                      </div>
                      <div>
                        <span className="text-sm font-semibold text-zinc-900">{provider.label}</span>
                        {provider.category === "llm" && (
                          <span className="ml-2 text-[10px] text-zinc-400 font-medium">LLM</span>
                        )}
                        {provider.key === "github" && (
                          <span className="ml-2 text-[10px] text-zinc-400 font-medium">Integration</span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {isConnected ? (
                        <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-700">
                          <span className="w-2 h-2 rounded-full bg-emerald-500" />
                          Connected
                        </span>
                      ) : isInvalid ? (
                        <span className="flex items-center gap-1.5 text-xs font-semibold text-red-700">
                          <span className="w-2 h-2 rounded-full bg-red-500" />
                          Invalid
                        </span>
                      ) : s.status === "Missing" ? (
                        <span className="text-xs text-zinc-600 font-semibold">Not configured</span>
                      ) : (
                        <span className="text-xs text-zinc-600 font-semibold">Not configured</span>
                      )}
                      {isConfigured && (
                        <button
                          onClick={() => handleDeleteCredential(provider.key)}
                          disabled={deletingProvider === provider.key}
                          className="ml-1 p-1.5 rounded-lg text-zinc-400 hover:text-red-500 hover:bg-red-50 transition-all bg-transparent border-0 cursor-pointer disabled:opacity-50"
                          title={`Delete ${provider.label}`}
                        >
                          {deletingProvider === provider.key ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Trash2 className="w-3.5 h-3.5" />
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Appearance — Light/Dark theme */}
        <div className="glass-card p-6 mb-8">
          <div className="flex items-center gap-3 mb-5 border-b border-border/40 pb-4">
            <div className="w-10 h-10 rounded-2xl bg-blue-50 flex items-center justify-center">
              {theme === "dark" ? <Moon className="w-5 h-5 text-accent-blue" /> : <Sun className="w-5 h-5 text-accent-blue" />}
            </div>
            <div>
              <h3 className="font-bold text-zinc-950">Appearance</h3>
              <p className="text-xs text-zinc-700 font-medium">Choose how RepoLens AI looks on this device</p>
            </div>
          </div>
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <p className="text-sm font-semibold text-zinc-900">Theme</p>
              <p className="text-[11px] text-zinc-600 mt-0.5">
                Follows your system preference until you pick one. Your choice is remembered.
              </p>
            </div>
            <div className="flex gap-1 bg-zinc-100 rounded-2xl p-1 dark:bg-zinc-800">
              <button
                type="button"
                onClick={() => setTheme("light")}
                className={`flex items-center gap-1.5 text-xs font-bold px-4 py-2 rounded-xl transition-all ${
                  theme === "light" ? "bg-white text-accent-blue shadow-sm dark:bg-zinc-950 dark:text-white" : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-white"
                }`}
              >
                <Sun className="w-3.5 h-3.5" /> Light
              </button>
              <button
                type="button"
                onClick={() => setTheme("dark")}
                className={`flex items-center gap-1.5 text-xs font-bold px-4 py-2 rounded-xl transition-all ${
                  theme === "dark" ? "bg-zinc-900 text-white shadow-sm dark:bg-white dark:text-zinc-900" : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-white"
                }`}
              >
                <Moon className="w-3.5 h-3.5" /> Dark
              </button>
            </div>
          </div>
        </div>

        {/* Save Credentials Form */}
        <div className="glass-card p-8">
          <div className="flex items-center gap-3 mb-6 border-b border-border/40 pb-5">
            <div className="w-10 h-10 rounded-2xl bg-accent-gradient/20 flex items-center justify-center">
              <Key className="w-5 h-5 text-accent-blue" />
            </div>
            <div>
              <h3 className="font-bold text-zinc-950">Save Credentials</h3>
              <p className="text-xs text-zinc-700 font-medium">Keys are encrypted with AES-256 before storage</p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            {PROVIDERS.map((provider) => {
              const s = getProviderStatus(provider.key);
              const hasKey = s.status !== "Missing";

              return (
                <div key={provider.key}>
                  <label className="block text-xs font-bold text-zinc-800 mb-2 flex items-center gap-1.5">
                    {provider.icon}
                    {provider.label}
                    {provider.category === "llm" && <span className="text-accent-red text-[10px]">*</span>}
                  </label>
                  <div className="relative">
                    <input
                      type={showKeys[provider.key] ? "text" : "password"}
                      placeholder={hasKey ? "Leave blank to keep current key" : provider.placeholder}
                      value={formKeys[provider.key]}
                      onChange={(e) => setFormKeys((prev) => ({ ...prev, [provider.key]: e.target.value }))}
                      className="input-glass text-sm pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => toggleShowKey(provider.key)}
                      className="absolute inset-y-0 right-0 pr-3 flex items-center text-zinc-400 hover:text-zinc-700 bg-transparent border-0 cursor-pointer"
                    >
                      {showKeys[provider.key] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  {provider.docsUrl && (
                    <a href={provider.docsUrl} target="_blank" rel="noopener noreferrer" className="text-[10px] text-accent-blue hover:underline mt-1 inline-block">
                      Get your key →
                    </a>
                  )}
                </div>
              );
            })}

            <div className="pt-2">
              <button
                type="submit"
                disabled={saving}
                className="btn-primary w-full flex items-center justify-center gap-2 py-3.5"
              >
                {saving ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Validating & Saving...</>
                ) : "Save Credentials"}
              </button>
            </div>
          </form>
        </div>
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
};
