import React, { useState } from "react";
import axios from "../lib/api";
import { Shield, Mail, Lock, Loader2, Eye, EyeOff } from "lucide-react";
import { toast } from "../components/Toast";

interface RegisterProps {
  onNavigateToLogin: () => void;
}

export const Register: React.FC<RegisterProps> = ({ onNavigateToLogin }) => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters long.");
      return;
    }
    if (!/[a-zA-Z]/.test(password) || !/[0-9]/.test(password)) {
      setError("Password must contain at least one letter and one number.");
      return;
    }

    setLoading(true);

    try {
      // Normalize email (trim + lowercase) so the account is stored the same
      // way the user will type it at login — e.g. mobile autocapitalize.
      await axios.post("/auth/register", {
        email: email.trim().toLowerCase(),
        password
      });
      setSuccess(true);
      toast.success("Account created successfully. You can now sign in.");
      setTimeout(() => {
        onNavigateToLogin();
      }, 2000);
    } catch (err: any) {
      if (!err.response) {
        setError("Cannot reach the RepoLens AI server. Make sure the backend is running on port 8000, then try again.");
      } else {
        const msg = err.response?.data?.detail || "Registration failed. Try again.";
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
          <h2 className="text-2xl font-bold text-zinc-900">Create an account</h2>
          <p className="text-base text-zinc-800 font-medium mt-1">Get started with automated code auditing</p>
        </div>

        {error && (
          <div className="mb-4 bg-red-50 border border-red-300 text-red-700 font-semibold p-3 rounded-2xl text-sm text-center">{error}</div>
        )}

        {success && (
          <div className="mb-4 bg-green-50 border border-green-200 text-green-600 p-3 rounded-2xl text-sm text-center">
            Account created successfully! Redirecting to login...
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-xs font-bold text-zinc-800 uppercase tracking-wider mb-2">Email Address</label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-zinc-500"><Mail className="w-4 h-4" /></span>
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                className="w-full pl-10 pr-4 py-3 bg-white border border-zinc-200 rounded-2xl text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue/20 text-sm"
                placeholder="you@example.com" />
            </div>
          </div>

          <div>
            <label className="block text-xs font-bold text-zinc-800 uppercase tracking-wider mb-2">Password</label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-muted">
                <Lock className="w-4 h-4" />
              </span>
              <input type={showPassword ? "text" : "password"} required value={password} onChange={(e) => setPassword(e.target.value)}
                className="w-full pl-10 pr-12 py-3 bg-white border border-zinc-200 rounded-2xl text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue/20 text-sm"
                placeholder="••••••••" />
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

          <div>
            <label className="block text-xs font-bold text-zinc-800 uppercase tracking-wider mb-2">Confirm Password</label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-muted">
                <Lock className="w-4 h-4" />
              </span>
              <input type={showConfirm ? "text" : "password"} required value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full pl-10 pr-12 py-3 bg-white border border-zinc-200 rounded-2xl text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue/20 text-sm"
                placeholder="••••••••"
              />
              <button
                type="button"
                onClick={() => setShowConfirm(v => !v)}
                aria-label={showConfirm ? "Hide password" : "Show password"}
                title={showConfirm ? "Hide password" : "Show password"}
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-zinc-500 hover:text-zinc-700 transition-colors"
              >
                {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            <label className="flex items-center gap-2 mt-2 text-xs font-semibold text-zinc-700 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showConfirm}
                onChange={(e) => setShowConfirm(e.target.checked)}
                className="w-3.5 h-3.5 accent-violet-600"
              />
              Show password
            </label>
          </div>

          <button type="submit" disabled={loading || success}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {loading ? <><Loader2 className="w-4 h-4 animate-spin" /> Creating account...</> : "Sign Up"}
          </button>

          {loading && (
            <p className="text-[11px] text-zinc-500 text-center dark:text-zinc-400">
              Securely hashing your password — this can take a few seconds.
            </p>
          )}
        </form>

        <p className="text-sm text-center text-zinc-800 font-medium mt-8">
          Already have an account?{" "}
          <button onClick={onNavigateToLogin} className="text-accent-blue hover:underline font-bold">Log in instead</button>
        </p>
      </div>
    </div>
  );
};

