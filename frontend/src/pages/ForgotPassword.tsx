import React, { useState } from "react";
import axios from "../lib/api";
import { Shield, Mail, Loader2, ArrowRight } from "lucide-react";

interface ForgotPasswordProps {
  onNavigateToLogin: () => void;
  /** Called in dev mode (no SMTP) with the raw token so the user can continue immediately. */
  onContinueToReset: (token: string) => void;
}

function extractTokenFromResetUrl(url: string): string | null {
  try {
    const hashIndex = url.indexOf("#");
    const afterHash = hashIndex >= 0 ? url.slice(hashIndex + 1) : url;
    const queryIndex = afterHash.indexOf("?");
    if (queryIndex < 0) return null;
    return new URLSearchParams(afterHash.slice(queryIndex + 1)).get("token");
  } catch {
    return null;
  }
}

export const ForgotPassword: React.FC<ForgotPasswordProps> = ({
  onNavigateToLogin,
  onContinueToReset,
}) => {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [devResetUrl, setDevResetUrl] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setDevResetUrl(null);
    setLoading(true);

    try {
      const response = await axios.post("/auth/forgot-password", { email: email.trim().toLowerCase() });
      setMessage(response.data.message || "Request received.");
      if (response.data.dev_reset_url) {
        setDevResetUrl(response.data.dev_reset_url);
      }
    } catch (err: any) {
      if (!err.response) {
        setError("Cannot reach the RepoLens AI server. Make sure the backend is running on port 8000, then try again.");
      } else {
        setError(err.response?.data?.detail || "Something went wrong. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  const devToken = devResetUrl ? extractTokenFromResetUrl(devResetUrl) : null;

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-md bg-white border border-zinc-200 rounded-3xl p-8 shadow-glass-lg">
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-accent-gradient flex items-center justify-center shadow-glow-blue mb-5">
            <Shield className="w-7 h-7 text-white" />
          </div>
          <h2 className="text-2xl font-bold text-zinc-900">Forgot your password?</h2>
          <p className="text-base text-zinc-800 font-medium mt-1 text-center">
            Enter your registered email address and we'll send you a reset link.
          </p>
        </div>

        {error && (
          <div className="mb-4 bg-red-50 border border-red-300 text-red-700 font-semibold p-3 rounded-2xl text-sm text-center">
            {error}
          </div>
        )}

        {message && (
          <div className="mb-4 bg-green-50 border border-green-200 text-green-700 p-3 rounded-2xl text-sm text-center">
            {message}
          </div>
        )}

        {/* Development-only flow: email sending is not configured, so the reset
            link is surfaced here instead of being emailed. Never shown in production. */}
        {devResetUrl && (
          <div className="mb-4 bg-amber-50 border border-amber-300 p-4 rounded-2xl text-sm">
            <p className="font-semibold text-amber-800 mb-2">
              Development mode — email sending is not configured
            </p>
            <p className="text-amber-800 mb-2">Use this reset link (valid for 30 minutes):</p>
            <a
              href={devResetUrl}
              className="text-accent-blue hover:underline break-all"
            >
              {devResetUrl}
            </a>
            {devToken && (
              <button
                type="button"
                onClick={() => onContinueToReset(devToken)}
                className="btn-primary w-full mt-3 flex items-center justify-center gap-2"
              >
                Continue to Reset Password <ArrowRight className="w-4 h-4" />
              </button>
            )}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-xs font-bold text-zinc-800 uppercase tracking-wider mb-2">
              Email Address
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-zinc-500">
                <Mail className="w-4 h-4" />
              </span>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full pl-10 pr-4 py-3 bg-white border border-zinc-200 rounded-2xl text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue/20 text-sm"
                placeholder="you@example.com"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" /> Sending...
              </>
            ) : (
              "Send Reset Link"
            )}
          </button>
        </form>

        <p className="text-sm text-center text-zinc-800 font-medium mt-8">
          Remembered it?{" "}
          <button onClick={onNavigateToLogin} className="text-accent-blue hover:underline font-bold">
            Back to login
          </button>
        </p>
      </div>
    </div>
  );
};
