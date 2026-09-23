import React, { useState } from "react";
import axios from "../lib/api";
import { Shield, Lock, Loader2, AlertTriangle } from "lucide-react";

interface ResetPasswordProps {
  token: string | null;
  onNavigateToLogin: () => void;
}

export const ResetPassword: React.FC<ResetPasswordProps> = ({ token, onNavigateToLogin }) => {
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const missingToken = !token;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters long.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post("/auth/reset-password", {
        token,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
      setSuccess(response.data.message || "Password reset successfully!");
      setTimeout(() => {
        onNavigateToLogin();
      }, 2500);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to reset password. Please try again.");
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
          <h2 className="text-2xl font-bold text-zinc-900">Set a new password</h2>
          <p className="text-base text-zinc-800 font-medium mt-1">Choose a strong password for your account</p>
        </div>

        {missingToken && (
          <div className="mb-4 bg-amber-50 border border-amber-300 text-amber-800 p-4 rounded-2xl text-sm text-center">
            <div className="flex items-center justify-center gap-2 mb-1 font-semibold">
              <AlertTriangle className="w-4 h-4" /> Reset link missing or invalid
            </div>
            This page needs a valid reset token. Please request a new reset link.
          </div>
        )}

        {error && (
          <div className="mb-4 bg-red-50 border border-red-300 text-red-700 font-semibold p-3 rounded-2xl text-sm text-center">
            {error}
          </div>
        )}

        {success && (
          <div className="mb-4 bg-green-50 border border-green-200 text-green-700 p-3 rounded-2xl text-sm text-center">
            {success} Redirecting to login...
          </div>
        )}

        {!missingToken && !success && (
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs font-bold text-zinc-800 uppercase tracking-wider mb-2">
                New Password
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-muted">
                  <Lock className="w-4 h-4" />
                </span>
                <input
                  type="password"
                  required
                  minLength={8}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full pl-10 pr-4 py-3 bg-white border border-zinc-200 rounded-2xl text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue/20 text-sm"
                  placeholder="••••••••"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold text-zinc-800 uppercase tracking-wider mb-2">
                Confirm New Password
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-muted">
                  <Lock className="w-4 h-4" />
                </span>
                <input
                  type="password"
                  required
                  minLength={8}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full pl-10 pr-4 py-3 bg-white border border-zinc-200 rounded-2xl text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue/20 text-sm"
                  placeholder="••••••••"
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
                  <Loader2 className="w-4 h-4 animate-spin" /> Resetting...
                </>
              ) : (
                "Reset Password"
              )}
            </button>
          </form>
        )}

        <p className="text-sm text-center text-zinc-800 font-medium mt-8">
          <button onClick={onNavigateToLogin} className="text-accent-blue hover:underline font-bold">
            Back to login
          </button>
        </p>
      </div>
    </div>
  );
};
