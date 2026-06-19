import React, { useState, useEffect } from "react";
import axios from "../lib/api";
import { useAuthStore } from "../store/authStore";
import { useQuery } from "@tanstack/react-query";
import { Key, Github, HelpCircle, CheckCircle2, AlertTriangle, Loader2, RefreshCw, Eye, EyeOff, Brain } from "lucide-react";

interface ProvidersDiagnostics {
  providers: Record<string, { configured: boolean; status: string; api_status?: string }>;
  encryption_status: string;
  database_status: string;
  redis_status: string;
  jwt_status: string;
}

const PROVIDER_INFO: Record<string, { label: string; icon: React.ReactNode; placeholder: string; docsUrl: string }> = {
  github: {
    label: "GitHub Personal Access Token (PAT)",
    icon: <Github className="w-4 h-4" />,
    placeholder: "ghp_xxxxxxxxxxxxxxxxxxxx",
    docsUrl: "https://github.com/settings/tokens"
  },
  groq: {
    label: "Groq API Key",
    icon: <Brain className="w-4 h-4" />,
    placeholder: "gsk_xxxxxxxxxxxxxxxxxxxx",
    docsUrl: "https://console.groq.com/keys"
  },
  openai: {
    label: "OpenAI API Key",
    icon: <Key className="w-4 h-4" />,
    placeholder: "sk-xxxxxxxxxxxxxxxxxxxx",
    docsUrl: "https://platform.openai.com/api-keys"
  },
  claude: {
    label: "Anthropic Claude API Key",
    icon: <Key className="w-4 h-4" />,
    placeholder: "sk-ant-xxxxxxxxxxxxxxxxxxxx",
    docsUrl: "https://console.anthropic.com/settings/keys"
  },
  gemini: {
    label: "Google Gemini API Key",
    icon: <Key className="w-4 h-4" />,
    placeholder: "AIzaxxxxxxxxxxxxxxxxxxxx",
    docsUrl: "https://aistudio.google.com/apikey"
  },
  openrouter: {
    label: "OpenRouter API Key",
    icon: <Key className="w-4 h-4" />,
    placeholder: "sk-or-v1-xxxxxxxxxxxxxxxxxxxx",
    docsUrl: "https://openrouter.ai/keys"
  }
};

const MODELS_BY_PROVIDER: Record<string, string[]> = {
  groq: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"],
  openai: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
  claude: ["claude-sonnet-4-20250514", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"],
  gemini: ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
  openrouter: ["openai/gpt-4o", "anthropic/claude-sonnet-4", "google/gemini-2.0-flash", "meta-llama/llama-3.3-70b"]
};

// Helper component for displaying system status
const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const isHealthy = status === "Connected" || status === "Active" || status === "Active (AES-256)" || status === "Configured";
  const isError = status?.toLowerCase().includes("error") || status?.toLowerCase().includes("inactive");
  return (
    <span className={`text-xs font-semibold ${isHealthy ? "text-accent-green" : isError ? "text-red-400" : "text-zinc-500"}`}>
      {status}
    </span>
  );
};

export const Settings: React.FC = () => {
  const { user, initialize } = useAuthStore();
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Form state for each provider
  const [formKeys, setFormKeys] = useState<Record<string, string>>({
    github: "", groq: "", openai: "", claude: "", gemini: "", openrouter: ""
  });
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [defaultProvider, setDefaultProvider] = useState(user?.llm_default_provider || "groq");
  const [defaultModel, setDefaultModel] = useState(user?.llm_default_model || "");
  const [temperature, setTemperature] = useState(user?.llm_temperature ?? 0.3);
  const [maxTokens, setMaxTokens] = useState(user?.llm_max_tokens ?? 4096);
  const [updating, setUpdating] = useState(false);
  const [testConnectionLoading, setTestConnectionLoading] = useState<string | null>(null);
  const [connectionTestResults, setConnectionTestResults] = useState<Record<string, string>>({});

  // Diagnostics
  const [diagnostics, setDiagnostics] = useState<ProvidersDiagnostics | null>(null);

  const { data: diagnosticsData, isLoading: loadingDiag, refetch: refetchDiag } = useQuery({
    queryKey: ["diagnostics", user?.id],
    queryFn: async () => {
      const response = await axios.get("/users/me/diagnostics");
      return response.data as ProvidersDiagnostics;
    },
    enabled: !!user,
    staleTime: 30000,
    gcTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    if (diagnosticsData) setDiagnostics(diagnosticsData);
  }, [diagnosticsData]);

  useEffect(() => {
    if (user?.llm_default_provider) setDefaultProvider(user.llm_default_provider);
    if (user?.llm_default_model) setDefaultModel(user.llm_default_model);
    if (user?.llm_temperature != null) setTemperature(user.llm_temperature);
    if (user?.llm_max_tokens != null) setMaxTokens(user.llm_max_tokens);
  }, [user]);

  const toggleKeyVisibility = (provider: string) => {
    setShowKeys((prev) => ({ ...prev, [provider]: !prev[provider] }));
  };

  const handleKeyChange = (provider: string, value: string) => {
    setFormKeys((prev) => ({ ...prev, [provider]: value }));
  };

  const handleTestConnection = async (provider: string) => {
    setTestConnectionLoading(provider);
    setConnectionTestResults((prev) => ({ ...prev, [provider]: "Testing..." }));
    try {
      if (provider === "github") {
        const res = await axios.get("/users/me/diagnostics");
        const apiStatus = res.data?.providers?.github?.api_status || "Unknown";
        setConnectionTestResults((prev) => ({ ...prev, [provider]: apiStatus === "Online" ? "Connected" : apiStatus }));
      } else {
        // For LLM providers, we just check if the key is configured
        const res = await axios.get("/users/me/diagnostics");
        const configured = res.data?.providers?.[provider]?.configured;
        setConnectionTestResults((prev) => ({ ...prev, [provider]: configured ? "Configured" : "Not Configured" }));
      }
    } catch (err: any) {
      setConnectionTestResults((prev) => ({ ...prev, [provider]: `Error: ${err.message}` }));
    } finally {
      setTestConnectionLoading(null);
    }
  };

  const hasAnyKeysToUpdate = () => {
    return Object.values(formKeys).some((v) => v.trim().length > 0) || 
           defaultProvider !== (user?.llm_default_provider || "groq") || 
           defaultModel !== (user?.llm_default_model || "") ||
           temperature !== (user?.llm_temperature ?? 0.3) ||
           maxTokens !== (user?.llm_max_tokens ?? 4096);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setUpdating(true);
    setMessage(null);

    try {
      const payload: Record<string, any> = {};
      for (const [provider, value] of Object.entries(formKeys)) {
        if (value.trim()) {
          payload[provider === "github" ? "github_pat" : `${provider}_api_key`] = value.trim();
        }
      }
      payload.llm_default_provider = defaultProvider;
      payload.llm_default_model = defaultModel || null;
      payload.llm_temperature = temperature;
      payload.llm_max_tokens = maxTokens;

      await axios.post("/users/keys", payload);
      setMessage({ type: "success", text: "Credentials saved and encrypted successfully!" });
      // Clear form
      setFormKeys({ github: "", groq: "", openai: "", claude: "", gemini: "", openrouter: "" });
      await initialize();
      refetchDiag();
    } catch (err: any) {
      setMessage({ type: "error", text: err.response?.data?.detail || "Failed to update credentials." });
    } finally {
      setUpdating(false);
    }
  };

  const toggleProvider = (provider: string) => {
    if (defaultProvider === provider) return;
    setDefaultProvider(provider);
    // Auto-select first model for this provider
    const models = MODELS_BY_PROVIDER[provider] || [];
    setDefaultModel(models[0] || "");
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto max-h-screen font-sans">
      <div className="max-w-4xl">
        <h1 className="text-3xl font-extrabold tracking-tight mb-2">Settings</h1>
        <p className="text-muted mb-6">Manage your LLM provider API keys, default model preferences, and integration diagnostics.</p>

        {message && (
          <div className={`mb-6 p-4 rounded-lg text-sm flex items-start gap-3 border ${
            message.type === "success"
              ? "bg-green-500/10 border-green-500/20 text-green-400"
              : "bg-red-500/10 border-red-500/20 text-red-400"
          }`}>
            {message.type === "success" ? (
              <CheckCircle2 className="w-5 h-5 shrink-0 mt-0.5" />
            ) : (
              <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
            )}
            <div>
              <p className="font-semibold">{message.type === "success" ? "Success" : "Error"}</p>
              <p className="mt-1 text-xs">{message.text}</p>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
          {/* Left Column: API Keys Form */}
          <div className="xl:col-span-2 space-y-8">
            {/* API Credentials */}
            <div className="bg-surface border border-border rounded-xl p-6 shadow-xl">
              <div className="flex items-center gap-3 mb-6 border-b border-border pb-4">
                <Key className="w-5 h-5 text-accent-blue" />
                <div>
                  <h3 className="font-bold text-white">Multi-Provider LLM Credentials</h3>
                  <p className="text-xs text-muted">All API keys are encrypted via AES-256 before storage. You can configure multiple providers and select your default.</p>
                </div>
              </div>

              <form onSubmit={handleSubmit} className="space-y-5">
                {Object.entries(PROVIDER_INFO).map(([provider, info]) => {
                  const fieldKey = provider === "github" ? "has_github_pat" : "has_" + provider + "_api_key";
                  const configured = user ? (user as any)[fieldKey] : false;

                  return (
                    <div key={provider}>
                      <div className="flex justify-between items-center mb-2">
                        <label className="block text-xs font-semibold text-zinc-300 uppercase tracking-wider flex items-center gap-1.5">
                          {info.icon}
                          {info.label}
                        </label>
                        <div className="flex items-center gap-2">
                          <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${
                            configured ? "bg-green-500/10 text-green-400 border border-green-500/20" : "bg-zinc-800 text-zinc-500"
                          }`}>
                            {configured ? "Configured" : "Not Configured"}
                          </span>
                          <span title={`Get your key at ${info.docsUrl}`}>
                            <a href={info.docsUrl} target="_blank" rel="noopener noreferrer" className="text-accent-blue hover:text-blue-400">
                              <HelpCircle className="w-3.5 h-3.5" />
                            </a>
                          </span>
                        </div>
                      </div>
                      <div className="flex gap-2">
                      <div className="relative flex-1">
                        <input
                          type={showKeys[provider] ? "text" : "password"}
                          placeholder={configured ? "•••••••••••••••••• (Leave blank to keep current)" : info.placeholder}
                          value={formKeys[provider]}
                          onChange={(e) => handleKeyChange(provider, e.target.value)}
                          className="w-full px-3 py-2.5 pr-10 bg-background border border-border rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue text-sm"
                        />
                        <button
                          type="button"
                          onClick={() => toggleKeyVisibility(provider)}
                          className="absolute inset-y-0 right-0 pr-3 flex items-center text-zinc-500 hover:text-white bg-transparent border-0 cursor-pointer"
                        >
                          {showKeys[provider] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                        </button>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleTestConnection(provider)}
                        disabled={testConnectionLoading === provider}
                        className="px-3 py-2 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 border border-border text-zinc-300 hover:text-white text-[10px] font-semibold rounded-lg transition-colors flex items-center gap-1.5 shrink-0"
                      >
                        {testConnectionLoading === provider ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <RefreshCw className="w-3 h-3" />
                        )}
                        Test
                      </button>
                      </div>
                      {connectionTestResults[provider] && (
                        <p className={`mt-1 text-[10px] font-medium ${
                          connectionTestResults[provider] === "Connected" || connectionTestResults[provider] === "Configured"
                            ? "text-accent-green" : "text-red-400"
                        }`}>
                          {connectionTestResults[provider]}
                        </p>
                      )}
                    </div>
                  );
                })}

                {/* Default Provider & Model */}
                <div className="border-t border-border pt-5 mt-5">
                  <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-4">Default LLM Configuration</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Provider Selector */}
                    <div>
                      <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Default Provider</label>
                      <div className="flex flex-wrap gap-2">
                        {Object.keys(MODELS_BY_PROVIDER).map((provider) => (
                          <button
                            key={provider}
                            type="button"
                            onClick={() => toggleProvider(provider)}
                            className={`px-3 py-1.5 text-xs font-bold rounded-lg border transition-all cursor-pointer ${
                              defaultProvider === provider
                                ? "bg-accent-blue/15 border-accent-blue text-accent-blue"
                                : "bg-zinc-900 border-zinc-700 text-zinc-400 hover:text-white hover:border-zinc-500"
                            }`}
                          >
                            {provider.charAt(0).toUpperCase() + provider.slice(1)}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Model Selector */}
                    <div>
                      <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Default Model</label>
                      <select
                        value={defaultModel}
                        onChange={(e) => setDefaultModel(e.target.value)}
                        className="w-full bg-zinc-900 border border-border rounded-lg text-white text-xs px-3 py-2.5 focus:outline-none focus:border-accent-blue"
                      >
                        <option value="">-- Select Model --</option>
                        {(MODELS_BY_PROVIDER[defaultProvider] || []).map((model) => (
                          <option key={model} value={model}>{model}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* Temperature & Max Tokens */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                    <div>
                      <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
                        Temperature <span className="text-zinc-600 font-normal normal-case">(0.0 - 2.0)</span>
                      </label>
                      <div className="flex items-center gap-3">
                        <input
                          type="range"
                          min="0"
                          max="200"
                          value={Math.round(temperature * 100)}
                          onChange={(e) => setTemperature(parseFloat((parseInt(e.target.value) / 100).toFixed(2)))}
                          step="5"
                          className="flex-1 h-2 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-accent-blue"
                        />
                        <input
                          type="number"
                          min={0}
                          max={2}
                          step={0.05}
                          value={temperature}
                          onChange={(e) => setTemperature(parseFloat(e.target.value) || 0)}
                          className="w-16 bg-zinc-900 border border-border rounded-lg text-white text-xs px-2 py-1.5 text-center focus:outline-none focus:border-accent-blue"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
                        Max Tokens <span className="text-zinc-600 font-normal normal-case">(per response)</span>
                      </label>
                      <input
                        type="number"
                        min={256}
                        max={128000}
                        step={256}
                        value={maxTokens}
                        onChange={(e) => setMaxTokens(parseInt(e.target.value) || 4096)}
                        className="w-full bg-zinc-900 border border-border rounded-lg text-white text-xs px-3 py-2 focus:outline-none focus:border-accent-blue"
                      />
                    </div>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={updating || !hasAnyKeysToUpdate()}
                  className="w-full py-2.5 bg-accent-blue hover:bg-blue-600 disabled:opacity-50 text-white font-semibold text-sm rounded-lg flex items-center justify-center gap-2 transition-all duration-150 mt-2"
                >
                  {updating ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Encrypting and saving...
                    </>
                  ) : (
                    "Save Credentials"
                  )}
                </button>
              </form>
            </div>
          </div>

          {/* Right Column: Diagnostics */}
          <div className="space-y-6">
            {/* Diagnostics Card */}
            <div className="bg-surface border border-border rounded-xl p-6">
              <div className="flex justify-between items-center mb-2">
                <h3 className="font-bold text-white text-sm">Integration Diagnostics</h3>
                <button
                  onClick={() => refetchDiag()}
                  disabled={loadingDiag}
                  className="text-xs text-accent-blue hover:text-blue-400 flex items-center gap-1.5 disabled:opacity-50 bg-transparent border-0 cursor-pointer"
                  type="button"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${loadingDiag ? "animate-spin" : ""}`} />
                  Refresh
                </button>
              </div>
              <p className="text-xs text-muted mb-4">Shows which providers have valid API keys configured in your account.</p>                  {loadingDiag ? (
                <div className="flex justify-center py-8">
                  <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
                </div>
              ) : (
                <div className="space-y-3">
                  {diagnostics?.providers && Object.entries(diagnostics.providers).map(([provider, status]) => (
                    <div key={provider} className="flex justify-between items-center text-xs border-b border-border/40 pb-2.5 last:border-0 last:pb-0">
                      <span className="text-zinc-400 font-medium capitalize">{provider}</span>
                      <span className={status.configured ? "text-accent-green font-semibold" : "text-zinc-500"}>
                        {status.configured ? "Configured" : "Not Configured"}
                      </span>
                    </div>
                  ))}

                  {/* System Status Section */}
                  <div className="pt-3 mt-3 border-t border-border/60">
                    <h4 className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider mb-2">System Status</h4>
                    <div className="space-y-2">
                      <div className="flex justify-between items-center text-xs">
                        <span className="text-zinc-400">Database</span>
                        <StatusBadge status={diagnostics?.database_status || "Unknown"} />
                      </div>
                      <div className="flex justify-between items-center text-xs">
                        <span className="text-zinc-400">Redis (Broker/Cache)</span>
                        <StatusBadge status={diagnostics?.redis_status || "Unknown"} />
                      </div>
                      <div className="flex justify-between items-center text-xs">
                        <span className="text-zinc-400">JWT Signing</span>
                        <StatusBadge status={diagnostics?.jwt_status || "Unknown"} />
                      </div>
                      <div className="flex justify-between items-center text-xs">
                        <span className="text-zinc-400">Encryption (AES-256)</span>
                        <StatusBadge status={diagnostics?.encryption_status || "Unknown"} />
                      </div>
                    </div>
                  </div>

                  {!diagnostics && (
                    <div className="text-center py-4 text-xs text-zinc-500">
                      Click Refresh to check status.
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Quick Help */}
            <div className="bg-surface border border-border rounded-xl p-6">
              <h3 className="font-bold text-white text-sm mb-3">Provider Information</h3>
              <div className="space-y-2 text-xs text-zinc-400">
                <p>Configure at least one LLM provider API key to run code reviews.</p>
                <p>Your default provider is used for all AI scans and explanations.</p>
                <p>All keys are encrypted (AES-256) before being stored in the database.</p>
                <div className="pt-2 border-t border-border/40 mt-3">
                  <p className="text-zinc-500 font-semibold mb-1">Get API Keys:</p>
                  <ul className="space-y-1">
                    {Object.entries(PROVIDER_INFO).map(([provider, info]) => (
                      <li key={provider}>
                        <a href={info.docsUrl} target="_blank" rel="noopener noreferrer" className="text-accent-blue hover:text-blue-400">
                          {info.label}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
