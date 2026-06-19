import React, { useState } from "react";
import axios from "../lib/api";
import Editor from "@monaco-editor/react";
import { Play, Code, Loader2, Sparkles, ShieldCheck, AlertCircle } from "lucide-react";

export const LocalReview: React.FC = () => {
  const [code, setCode] = useState(
    `# Paste your code snippet here for a real-time review\ndef calculate_sum(a, b):\n    # TODO: add input validation\n    result = a + b\n    print("Calculating...")\n    return result`
  );
  const [language, setLanguage] = useState("Auto");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const langOptions = [
    { label: "Auto-Detect", value: "Auto" },
    { label: "Python", value: "Python" },
    { label: "JavaScript", value: "JavaScript" },
    { label: "TypeScript", value: "TypeScript" },
    { label: "Java", value: "Java" },
    { label: "C#", value: "C#" },
    { label: "Go", value: "Go" },
    { label: "Rust", value: "Rust" },
    { label: "C/C++", value: "C/C++" }
  ];

  const handleReview = async () => {
    setLoading(true);
    setError(null);
    setResults(null);

    try {
      const res = await axios.post("/analysis/snippet", {
        code,
        language
      });
      setResults(res.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Snippet review failed. Confirm Groq Key is set.");
    } finally {
      setLoading(false);
    }
  };

  const mapSeverityClass = (sev: string) => {
    switch (sev) {
      case "Critical":
      case "High":
        return "border-l-red-500 bg-red-500/10 text-red-400";
      case "Medium":
        return "border-l-orange-500 bg-orange-500/10 text-orange-400";
      case "Low":
        return "border-l-blue-500 bg-blue-500/10 text-blue-400";
      default:
        return "border-l-zinc-500 bg-zinc-800/20 text-zinc-400";
    }
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto max-h-screen">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight">Local Code Snippet Review</h1>
          <p className="text-muted mt-1">Audit temporary code snippets instantly without connecting repository</p>
        </div>
        <div className="flex items-center gap-3">
          {results && results.is_valid_code && (
            <span className="px-3 py-1.5 bg-blue-500/10 text-blue-400 border border-blue-500/20 text-xs font-bold rounded-lg flex items-center gap-1.5">
              <Code className="w-3.5 h-3.5" />
              Detected: {results.detected_language}
            </span>
          )}
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="bg-surface border border-border rounded-lg text-white text-xs px-3 py-2.5 focus:outline-none"
          >
            {langOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <button
            onClick={handleReview}
            disabled={loading || !code.trim()}
            className="flex items-center gap-2 bg-accent-blue hover:bg-blue-600 disabled:opacity-50 text-white font-semibold text-xs px-4 py-2.5 rounded-lg transition-all"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Auditing...
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                Run AI Review
              </>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-6 bg-red-500/10 border border-red-500/20 text-red-400 p-4 rounded-lg text-sm">
          {error}
        </div>
      )}

      {/* Validation Banner if code is invalid */}
      {results && !results.is_valid_code && (
        <div className="mb-6 bg-amber-500/10 border border-amber-500/20 text-amber-400 p-4 rounded-lg flex items-center gap-3 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <div>
            <span className="font-semibold block mb-0.5">Snippet Validation Warning</span>
            <span className="text-xs text-zinc-300">{results.validation_message}</span>
          </div>
        </div>
      )}

      {/* Editor & Results Panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Editor */}
        <div className="bg-surface border border-border rounded-xl p-4 flex flex-col h-[650px]">
          <div className="flex items-center gap-2 text-zinc-400 text-xs font-semibold mb-3 border-b border-border pb-2">
            <Code className="w-4 h-4 text-accent-blue" />
            <span>Monaco Source Code Snippet Editor</span>
          </div>
          <div className="flex-1 rounded-lg overflow-hidden border border-border bg-black">
            <Editor
              height="100%"
              theme="vs-dark"
              language={
                language === "Auto"
                  ? (results?.detected_language?.toLowerCase() || "python")
                  : language.toLowerCase()
              }
              value={code}
              onChange={(val) => setCode(val || "")}
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                lineNumbers: "on",
                automaticLayout: true
              }}
            />
          </div>
        </div>

        {/* Results Panel */}
        <div className="bg-surface border border-border rounded-xl p-6 h-[650px] overflow-y-auto flex flex-col">
          {results && results.is_valid_code ? (
            <div className="flex-1 space-y-6">
              {/* Quality & Risk Metrics */}
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-background border border-border p-4 rounded-lg text-center">
                  <p className="text-[10px] text-zinc-500 uppercase tracking-widest font-bold">Risk Score</p>
                  <h4 className={`text-3xl font-extrabold mt-1 ${
                    results.risk_score > 60 ? "text-accent-red" : results.risk_score > 30 ? "text-accent-orange" : "text-accent-green"
                  }`}>{results.risk_score}/100</h4>
                </div>
                <div className="bg-background border border-border p-4 rounded-lg text-center">
                  <p className="text-[10px] text-zinc-500 uppercase tracking-widest font-bold">Code Quality Score</p>
                  <h4 className={`text-3xl font-extrabold mt-1 ${
                    results.quality_score >= 80 ? "text-accent-green" : results.quality_score >= 55 ? "text-accent-orange" : "text-accent-red"
                  }`}>{results.quality_score}/100</h4>
                </div>
              </div>

              {/* Findings */}
              <div>
                <h3 className="font-bold text-white mb-3">AI Findings ({results.findings?.length})</h3>
                {results.findings?.length > 0 ? (
                  <div className="space-y-3">
                    {results.findings.map((finding: any, idx: number) => (
                      <div
                        key={idx}
                        className={`p-4 border-l-4 rounded-r-lg border border-border border-l-solid ${mapSeverityClass(finding.severity)}`}
                      >
                        <div className="flex justify-between items-start">
                          <p className="font-semibold text-xs text-white">{finding.issue}</p>
                          <span className="text-[9px] uppercase tracking-wider font-extrabold px-1.5 py-0.5 bg-zinc-800 text-zinc-400 rounded">
                            {finding.severity}
                          </span>
                        </div>
                        <p className="text-[11px] text-zinc-400 mt-2">Line {finding.line} | <span className="italic">{finding.category}</span></p>
                        <p className="text-xs mt-2 text-zinc-300">{finding.suggestion}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center p-8 border border-dashed border-border rounded-lg bg-background/50">
                    <ShieldCheck className="w-8 h-8 text-accent-green mb-2" />
                    <p className="text-xs text-muted">No security flaws, bugs, or smells identified!</p>
                  </div>
                )}
              </div>

              {/* Optimized Version Card or Success Card */}
              {results.optimization_required ? (
                <div className="border-t border-border pt-4">
                  <div className="flex justify-between items-center mb-3">
                    <h3 className="font-bold text-white flex items-center gap-1.5">
                      <Sparkles className="w-4 h-4 text-accent-green" />
                      Optimized Version
                    </h3>
                    <span className="text-[10px] bg-accent-green/10 text-accent-green border border-accent-green/20 px-2 py-0.5 rounded font-bold uppercase tracking-wider">
                      Recommended Refactoring
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 mb-3">
                    Here is an improved version addressing the security, performance, or maintainability issues.
                  </p>
                  <div className="rounded-lg overflow-hidden border border-border bg-black h-[280px]">
                    <Editor
                      height="100%"
                      theme="vs-dark"
                      language={results.detected_language?.toLowerCase() || "python"}
                      value={results.optimized_code}
                      options={{
                        readOnly: true,
                        minimap: { enabled: false },
                        fontSize: 12,
                        lineNumbers: "on",
                        automaticLayout: true
                      }}
                    />
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center p-8 border border-dashed border-accent-green/30 bg-accent-green/5 rounded-lg text-center mt-4">
                  <ShieldCheck className="w-12 h-12 text-accent-green mb-3 animate-pulse" />
                  <h4 className="text-lg font-bold text-white mb-1">Code already follows best practices</h4>
                  <p className="text-xs text-zinc-400 max-w-md">
                    No optimization required. The submitted code has been analyzed and is already high quality with clean structures and sound design.
                  </p>
                </div>
              )}

              {/* Test Suggestions */}
              {results.test_suggestions && (
                <div className="border-t border-border pt-4">
                  <h3 className="font-bold text-white mb-3 flex items-center gap-1.5">
                    <Sparkles className="w-4 h-4 text-accent-orange" />
                    Suggested Unit & Edge Tests
                  </h3>
                  <pre className="p-4 bg-background border border-border rounded-lg text-zinc-300 text-xs overflow-x-auto whitespace-pre-wrap font-mono">
                    {results.test_suggestions}
                  </pre>
                </div>
              )}
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-muted text-center p-4">
              <Sparkles className="w-10 h-10 text-zinc-700 mb-3" />
              <p className="text-sm font-medium">Click "Run AI Review" to start auditing</p>
              <p className="text-xs text-zinc-600 mt-1">Review results will populate here</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

