import React, { useState } from "react";
import { useAuthStore } from "../store/authStore";
import axios from "../lib/api";
import { Shield, Mail, Lock, Loader2, Eye, EyeOff } from "lucide-react";
import { toast } from "../components/Toast";

interface LoginProps {
  onNavigateToRegister: () => void;
  onNavigateToForgotPassword: () => void;
}

export const Login: React.FC<LoginProps> = ({ onNavigateToRegister, onNavigateToForgotPassword }) => {
  const { setToken, initialize, markJustLoggedIn } = useAuthStore();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    
    // Normalize email (trim + lowercase) so mixed-case/whitespace input
    // matches how accounts are stored — e.g. mobile autocapitalize.
    const normalizedEmail = email.trim().toLowerCase();

    // Prepare form data
    const formData = new FormData();
    formData.append("username", normalizedEmail);
    formData.append("password", password);

    try {
      const response = await axios.post("/auth/login", formData);
      setToken(response.data.access_token);
      // Flag the interactive login so App opens Settings first
      // (refresh/session-restore is unaffected).
      markJustLoggedIn();
      await initialize();
      toast.success("Login successful. Welcome back!");
    } catch (err: any) {
      if (!err.response) {
        // Network/CORS failure — the backend is unreachable, not a bad password.
        setError("Cannot reach the RepoLens AI server. Make sure the backend is running on port 8000, then try again.");
      } else {
        const msg = err.response?.data?.detail || "Invalid email or password";
        setError(msg);
        toast.error(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-md bg-white border border-zinc-200 rounded-3xl p-8 shadow-glass-lg">
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-accent-gradient flex items-center justify-center shadow-glow-blue mb-5">
            <Shield className="w-7 h-7 text-white" />
          </div>
          <h2 className="text-2xl font-bold text-zinc-900">Welcome back</h2>
          <p className="text-base text-zinc-800 font-medium mt-1">Sign in to review your code</p>
        </div>

        {error && (
          <div className="mb-4 bg-red-50 border border-red-300 text-red-700 font-semibold p-3 rounded-2xl text-sm text-center">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-xs font-bold text-zinc-800 uppercase tracking-wider mb-2">Email Address</label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-zinc-500">
                <Mail className="w-4 h-4" />
              </span>
              <input
                type="email" required value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full pl-10 pr-4 py-3 bg-white border border-zinc-200 rounded-2xl text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue/20 text-sm"
                placeholder="you@example.com"
              />
            </div>
          </div>

          <div>
            <div className="flex justify-between items-center mb-2">
              <label className="block text-xs font-bold text-zinc-800 uppercase tracking-wider">Password</label>
              <a href="#" onClick={(e) => { e.preventDefault(); onNavigateToForgotPassword(); }} className="text-xs text-accent-blue hover:underline font-semibold">Forgot password?</a>
            </div>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-muted">
                <Lock className="w-4 h-4" />
              </span>
              <input
                type={showPassword ? "text" : "password"} required value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full pl-10 pr-12 py-3 bg-white border border-zinc-200 rounded-2xl text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue/20 text-sm"
                placeholder="••••••••"
              />
              <button
                type="button"
                onClick={() => setShowPassword(v => !v)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                title={showPassword ? "Hide password" : "Show password"}
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-zinc-500 hover:text-zinc-700 transition-colors"
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            <label className="flex items-center gap-2 mt-2 text-xs font-semibold text-zinc-700 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showPassword}
                onChange={(e) => setShowPassword(e.target.checked)}
                className="w-3.5 h-3.5 accent-violet-600"
              />
              Show password
            </label>
          </div>

          <button type="submit" disabled={loading}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {loading ? <><Loader2 className="w-4 h-4 animate-spin" /> Signing in...</> : "Sign In"}
          </button>

          {loading && (
            <p className="text-[11px] text-zinc-500 text-center dark:text-zinc-400">
              Checking your credentials — the server may need a moment if it is waking up.
            </p>
          )}
        </form>

        <p className="text-sm text-center text-zinc-800 font-medium mt-8">
          Don't have an account?{" "}
          <button onClick={onNavigateToRegister} className="text-accent-blue hover:underline font-bold">
            Create an account
          </button>
        </p>
      </div>
    </div>
  );
};

