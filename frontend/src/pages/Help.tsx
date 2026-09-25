import React from "react";
import {
  Shield, FolderGit2, ScanSearch, ShieldAlert, Wrench, Network,
  Sparkles, Gauge, Layers, FileDown, HelpCircle, ArrowDown, Bot,
  AlertTriangle, FileCode2, MapPin, Lightbulb, Wrench as WrenchAction,
} from "lucide-react";

/**
 * Help / How RepoLens Works — a single, simple page that explains the whole
 * product to a first-time user, plus the About / project information section.
 * Content is descriptive only; no live data or fabricated examples beyond the
 * clearly-labelled illustration of a finding.
 */

const FLOW_STEPS = [
  {
    icon: FolderGit2,
    title: "1. Connect GitHub Repository",
    text: "RepoLens connects to a GitHub repository you choose using your own GitHub token.",
  },
  {
    icon: ScanSearch,
    title: "2. Scan Repository",
    text: "RepoLens reads the selected repository and analyzes its source files.",
  },
  {
    icon: ShieldAlert,
    title: "3. Analyze Security & Code Quality",
    text: "Finds possible security problems and code smells, and shows the affected file and line.",
  },
  {
    icon: Network,
    title: "4. Analyze Dependencies & Architecture",
    text: "Checks external libraries for known security issues and maps how your project is organized.",
  },
  {
    icon: Sparkles,
    title: "5. Generate AI Explanations",
    text: "The AI assistant explains what was found in plain language and suggests fixes.",
  },
  {
    icon: Gauge,
    title: "6. View Insights",
    text: "A simple summary shows your repository's current health and what needs attention.",
  },
  {
    icon: Layers,
    title: "7. Explore Deep Insights",
    text: "Detailed technical analysis for developers: complexity, duplicates, technical debt, and more.",
  },
  {
    icon: FileDown,
    title: "8. Download Report",
    text: "Download the complete analysis as PDF, Markdown, JSON or CSV.",
  },
];

const FEATURE_EXPLAINERS = [
  {
    icon: ScanSearch,
    title: "Repository Scan",
    text: "RepoLens reads the selected repository and analyzes its source files. Every scan is tied to a specific branch and commit so you always know what was analyzed.",
  },
  {
    icon: ShieldAlert,
    title: "Security",
    text: "Finds possible security problems and shows the affected file and line, with a code snippet as evidence.",
  },
  {
    icon: Wrench,
    title: "Code Quality",
    text: "Finds code smells and maintainability problems, like duplicated logic or overly complex functions.",
  },
  {
    icon: Gauge,
    title: "Insights",
    text: "Shows a simple summary of the repository's current health, what needs attention, and what to fix first.",
  },
  {
    icon: Layers,
    title: "Deep Insights",
    text: "Shows detailed technical analysis for developers: dependencies, duplicate code, complexity, architecture, and technical debt.",
  },
  {
    icon: Bot,
    title: "AI Assistant",
    text: "Answers questions using general knowledge or the selected repository's actual scan data. It never invents repository facts.",
  },
  {
    icon: FileDown,
    title: "Reports",
    text: "Download the analysis as PDF, Markdown, JSON or CSV.",
  },
];

const FINDING_FIELDS = [
  { icon: AlertTriangle, label: "Issue", text: "What the problem is — for example, a hardcoded credential or an unused variable." },
  { icon: MapPin, label: "File & Line", text: "Exactly where the problem is, so you can go straight to it." },
  { icon: FileCode2, label: "Evidence", text: "The actual code that triggered the finding. Secrets are always redacted before display." },
  { icon: Lightbulb, label: "Why this matters", text: "A plain-language explanation of the risk or cost of leaving the problem unfixed." },
  { icon: WrenchAction, label: "Suggested action", text: "A concrete recommendation for fixing the problem." },
];

type IconComponent = React.ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>;

const Section: React.FC<{
  icon: IconComponent;
  title: string;
  children: React.ReactNode;
}> = ({ icon: Icon, title, children }) => (
  <section className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-3xl p-6 sm:p-8 shadow-glass-sm">
    <div className="flex items-center gap-3 mb-5">
      <div className="w-10 h-10 rounded-2xl bg-accent-blue/10 flex items-center justify-center shrink-0">
        <Icon className="w-5 h-5 text-accent-blue" aria-hidden="true" />
      </div>
      <h2 className="text-xl font-bold text-zinc-900 dark:text-zinc-50">{title}</h2>
    </div>
    {children}
  </section>
);

export const Help: React.FC = () => {
  return (
    <div className="flex-1 p-8 overflow-y-auto max-h-screen">
      <div className="max-w-4xl mx-auto space-y-8">
        {/* Header */}
        <div>
          <div className="flex items-center gap-3 mb-2">
            <HelpCircle className="w-7 h-7 text-accent-blue" aria-hidden="true" />
            <h1 className="text-3xl font-bold text-zinc-900 dark:text-zinc-50">
              How RepoLens AI Works
            </h1>
          </div>
          <p className="text-zinc-600 dark:text-zinc-400 font-medium">
            RepoLens AI analyzes your GitHub repository and explains what it finds —
            in plain language, with real evidence. Here is the complete workflow.
          </p>
        </div>

        {/* Visual flow */}
        <Section icon={Shield} title="The workflow at a glance">
          <ol className="space-y-0" aria-label="RepoLens workflow steps">
            {FLOW_STEPS.map((step, i) => (
              <li key={step.title}>
                <div className="flex items-start gap-4 py-3">
                  <div className="w-10 h-10 rounded-2xl bg-accent-gradient/15 flex items-center justify-center shrink-0">
                    <step.icon className="w-5 h-5 text-accent-blue" aria-hidden="true" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-bold text-zinc-900 dark:text-zinc-100">{step.title}</p>
                    <p className="text-sm text-zinc-600 dark:text-zinc-400 mt-0.5">{step.text}</p>
                  </div>
                </div>
                {i < FLOW_STEPS.length - 1 && (
                  <div className="flex" aria-hidden="true">
                    <div className="w-10 flex justify-center">
                      <ArrowDown className="w-4 h-4 text-zinc-300 dark:text-zinc-600" />
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ol>
        </Section>

        {/* Feature explainers */}
        <Section icon={Sparkles} title="What each feature does">
          <div className="grid sm:grid-cols-2 gap-4">
            {FEATURE_EXPLAINERS.map((f) => (
              <div
                key={f.title}
                className="border border-zinc-200 dark:border-zinc-800 rounded-2xl p-4"
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <f.icon className="w-4 h-4 text-accent-blue" aria-hidden="true" />
                  <p className="font-bold text-sm text-zinc-900 dark:text-zinc-100">{f.title}</p>
                </div>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">{f.text}</p>
              </div>
            ))}
          </div>
        </Section>

        {/* How to read a finding */}
        <Section icon={AlertTriangle} title="How to read a finding">
          <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-5">
            Every finding in RepoLens follows the same structure, so you always know
            what was found, where, and what to do about it. Illustrative example:
          </p>
          <div className="border border-zinc-200 dark:border-zinc-800 rounded-2xl divide-y divide-zinc-200 dark:divide-zinc-800">
            <div className="px-4 py-3">
              <p className="text-[10px] font-bold uppercase tracking-wider text-red-600 dark:text-red-400 mb-1">Security Issue</p>
              <p className="font-bold text-zinc-900 dark:text-zinc-100">Unused state variable</p>
            </div>
            <div className="px-4 py-3 grid sm:grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-0.5">File</p>
                <p className="font-semibold text-zinc-900 dark:text-zinc-100 font-mono text-xs break-all">frontend/src/pages/ReportsPage.jsx</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-0.5">Line</p>
                <p className="font-semibold text-zinc-900 dark:text-zinc-100 font-mono text-xs">11</p>
              </div>
            </div>
            <div className="px-4 py-3">
              <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-0.5">Why this matters</p>
              <p className="text-sm text-zinc-700 dark:text-zinc-300">Unused code makes maintenance harder.</p>
            </div>
            <div className="px-4 py-3">
              <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-0.5">Suggested action</p>
              <p className="text-sm text-zinc-700 dark:text-zinc-300">Remove the unused variable if it is not required.</p>
            </div>
          </div>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3 mt-5">
            {FINDING_FIELDS.map((f) => (
              <div key={f.label} className="flex items-start gap-2.5">
                <f.icon className="w-4 h-4 text-accent-blue mt-0.5 shrink-0" aria-hidden="true" />
                <div>
                  <p className="text-xs font-bold text-zinc-900 dark:text-zinc-100">{f.label}</p>
                  <p className="text-xs text-zinc-600 dark:text-zinc-400">{f.text}</p>
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Tips */}
        <Section icon={Lightbulb} title="Tips for getting started">
          <ul className="space-y-2.5 text-sm text-zinc-700 dark:text-zinc-300 list-disc list-inside">
            <li>Connect a repository from the Dashboard, then run a scan — Insights fill in automatically once the scan completes.</li>
            <li>Start with <strong>Insights</strong> for a quick summary; open <strong>Deep Insights</strong> only when you need technical detail.</li>
            <li>Every scan records the branch and commit it analyzed, so re-running a scan on the same commit will tell you if it was already analyzed.</li>
            <li>Use the AI assistant (bottom-right) to ask questions — it answers from your real scan data when a repository is selected.</li>
          </ul>
        </Section>

        {/* About */}
        <Section icon={Shield} title="About RepoLens AI">
          <p className="text-sm text-zinc-700 dark:text-zinc-300 mb-6">
            RepoLens AI is an AI-powered GitHub repository analysis platform that
            helps developers understand the security, quality, architecture and
            maintainability of their codebase.
          </p>

          <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-3">
            Capabilities
          </h3>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2 mb-8">
            {[
              "Repository Security Analysis",
              "Code Quality Analysis",
              "Dependency Analysis",
              "Duplicate Code Detection",
              "Complexity Analysis",
              "Architecture Analysis",
              "Technical Debt Analysis",
              "Repository Health",
              "Pull Request Review",
              "Commit/Change Analysis",
              "AI Repository Assistant",
              "Reports and Exports",
            ].map((cap) => (
              <p key={cap} className="text-sm text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-blue shrink-0" aria-hidden="true" />
                {cap}
              </p>
            ))}
          </div>

          <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-3">
            Technology
          </h3>
          <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-3 mb-8">
            {[
              ["Frontend", "React + TypeScript"],
              ["Backend", "FastAPI + Python"],
              ["Repository source", "GitHub API"],
              ["Database", "PostgreSQL (SQLite in local development)"],
              ["AI", "Supported LLM providers configured by RepoLens AI"],
            ].map(([term, desc]) => (
              <div key={term}>
                <dt className="text-xs font-bold text-zinc-900 dark:text-zinc-100">{term}</dt>
                <dd className="text-sm text-zinc-600 dark:text-zinc-400">{desc}</dd>
              </div>
            ))}
          </dl>

          <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-3">
            Project
          </h3>
          <div className="text-sm text-zinc-700 dark:text-zinc-300 space-y-1">
            <p className="font-semibold text-zinc-900 dark:text-zinc-100">
              Developed as a B.Tech Mini Project
            </p>
            <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3 mt-4">
              <div>
                <p className="text-xs font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1">Team</p>
                <p>Eshwar Madhav</p>
                <p>Penta Arogya Sumanth Reddy</p>
                <p>Kodithyala Santhosh</p>
              </div>
              <div>
                <p className="text-xs font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1">Guide</p>
                <p>Dr. V. Biksham</p>
                <p className="text-xs font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mt-3 mb-1">Department</p>
                <p>Data Science</p>
                <p className="text-xs font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mt-3 mb-1">University</p>
                <p>Anurag University</p>
              </div>
            </div>
          </div>
        </Section>
      </div>
    </div>
  );
};
