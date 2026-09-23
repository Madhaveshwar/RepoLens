import React, { useState, useRef, useEffect, Suspense, lazy } from "react";
import { motion, useInView, AnimatePresence } from "framer-motion";
import {
  Shield, ArrowRight, CheckCircle2, Star, Github, Code2,
  ShieldCheck, Zap, BarChart3, GitPullRequest, Sparkles, ChevronDown,
  Menu, X, Mail, Linkedin, Twitter,
  Bot, Lock, Wrench
} from "lucide-react";

// Lazy-load the 3D scene for perf
const ThreeDHero = lazy(() => import("../components/ThreeDHero"));

interface LandingProps {
  onNavigateToLogin: () => void;
  onNavigateToRegister: () => void;
}

// ── Reusable animation variants ──

const fadeUp = {
  hidden: { opacity: 0, y: 30 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: [0.25, 0.4, 0.25, 1] } }
};

const fadeUpFast = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.25, 0.4, 0.25, 1] } }
};

const staggerContainer = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.1, delayChildren: 0.1 }
  }
};

const staggerItem = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.25, 0.4, 0.25, 1] } }
};

const scaleIn = {
  hidden: { opacity: 0, scale: 0.9 },
  visible: { opacity: 1, scale: 1, transition: { duration: 0.5, ease: [0.25, 0.4, 0.25, 1] } }
};

const slideInLeft = {
  hidden: { opacity: 0, x: -40 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.6, ease: [0.25, 0.4, 0.25, 1] } }
};

const slideInRight = {
  hidden: { opacity: 0, x: 40 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.6, ease: [0.25, 0.4, 0.25, 1] } }
};

// ── Animated Counter Component ──

const AnimatedCounter: React.FC<{ value: string; label: string; suffix?: string }> = ({ value, label }) => {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });
  const [displayValue, setDisplayValue] = useState("0");

  useEffect(() => {
    if (!isInView) return;
    const num = parseInt(value.replace(/[^0-9]/g, ""));
    const suffix = value.includes("+") ? "+" : value.includes("%") ? "%" : "";
    if (!num) { setDisplayValue(value); return; }

    let start = 0;
    const duration = 1500;
    const steps = 30;
    const increment = num / steps;
    let current = 0;
    const timer = setInterval(() => {
      current += increment;
      start++;
      if (start >= steps) {
        setDisplayValue(`${num}${suffix}`);
        clearInterval(timer);
      } else {
        setDisplayValue(`${Math.floor(current)}${suffix}`);
      }
    }, duration / steps);
    return () => clearInterval(timer);
  }, [isInView, value]);

  return (
    <div ref={ref} className="text-center">
      <motion.p className="text-3xl font-bold font-sans text-zinc-950" initial={{ opacity: 0, y: 10 }}
        animate={isInView ? { opacity: 1, y: 0 } : {}} transition={{ duration: 0.4 }}>
        {displayValue}
      </motion.p>
      <p className="text-xs text-zinc-600 mt-1">{label}</p>
    </div>
  );
};

// ── Section Wrapper (scroll-triggered reveal) ──

const Section: React.FC<{
  children: React.ReactNode;
  className?: string;
  id?: string;
  delay?: number;
}> = ({ children, className = "", id, delay = 0 }) => {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-100px" });
  return (
    <motion.section
      id={id}
      ref={ref}
      className={className}
      initial="hidden"
      animate={isInView ? "visible" : "hidden"}
      variants={fadeUp}
      transition={{ delay }}
    >
      {children}
    </motion.section>
  );
};

// ── Data ──

const FEATURES = [
  { icon: <Shield className="w-6 h-6" />, title: "AI Security Scanner", description: "Detect vulnerabilities, injection flaws, and security misconfigurations across your entire codebase with Groq-powered LLM analysis.", color: "text-accent-red" },
  { icon: <Code2 className="w-6 h-6" />, title: "Code Quality Analysis", description: "Identify code smells, anti-patterns, and maintainability issues before they compound into technical debt.", color: "text-accent-orange" },
  { icon: <Wrench className="w-6 h-6" />, title: "AI Remediation", description: "Generate production-ready fixes with before/after code diffs. Create pull requests directly to GitHub.", color: "text-accent-purple" },
  { icon: <GitPullRequest className="w-6 h-6" />, title: "PR Review Automation", description: "Automatically analyze pull requests for regressions, new vulnerabilities, and code quality deviations.", color: "text-accent-green" },
  { icon: <BarChart3 className="w-6 h-6" />, title: "Analytics Dashboard", description: "Track security scores, health trends, token consumption, and model usage with interactive charts.", color: "text-accent-cyan" },
  { icon: <Bot className="w-6 h-6" />, title: "Multi-Provider AI", description: "Choose from Groq, OpenAI, Claude, Gemini, or OpenRouter. Your keys, your models, your control.", color: "text-accent-blue" }
];

const WORKFLOW_STEPS = [
  { step: "01", title: "Connect Repository", description: "Link any public or private GitHub repository. Our app clones and indexes your codebase for analysis.", icon: <Github className="w-8 h-8" /> },
  { step: "02", title: "AI-Powered Scan", description: "Advanced LLMs analyze every file for security vulnerabilities, code smells, and architectural issues.", icon: <Zap className="w-8 h-8" /> },
  { step: "03", title: "Review Findings", description: "Browse detailed findings with severity ratings, file locations, code snippets, and AI-generated explanations.", icon: <ShieldCheck className="w-8 h-8" /> },
  { step: "04", title: "Fix & Deploy", description: "Generate AI fixes, validate syntax, and create pull requests – all from your browser.", icon: <GitPullRequest className="w-8 h-8" /> }
];

const TESTIMONIALS = [
  { quote: "This tool caught a critical SQL injection vulnerability that our team had missed for two sprints. The auto-generated fix was production-ready.", author: "Sarah Chen", role: "Lead Engineer at TechCorp", avatar: "SC", rating: 5 },
  { quote: "The AI explanations are incredibly detailed. It doesn't just tell you what's wrong – it teaches you why it matters and how to fix it.", author: "Marcus Rivera", role: "Security Architect at CloudScale", avatar: "MR", rating: 5 },
  { quote: "We reduced our code review cycle from 3 days to 4 hours. The PR integration is seamless and the quality suggestions are spot-on.", author: "Priya Patel", role: "Engineering Manager at DataFlow", avatar: "PP", rating: 5 }
];

const FAQ_ITEMS = [
  { q: "How does the AI code review work?", a: "When you connect a repository or submit a code snippet, our platform sends your code through advanced LLMs (Groq, OpenAI, etc.) that analyze it for security vulnerabilities, code smells, performance bottlenecks, and architectural issues. Each finding includes an explanation, severity rating, and suggested remediation." },
  { q: "Do I need my own API keys?", a: "Yes, you configure your own API keys for your preferred LLM providers (Groq, OpenAI, Claude, Gemini, or OpenRouter). All keys are encrypted with AES-256 before storage. You can also set a default provider and model for all scans." },
  { q: "Is my code secure?", a: "Absolutely. Your code is only sent to the LLM provider you configure for analysis. All API keys are encrypted at rest. We never store your full repository – only scan results and findings. GitHub integration uses your own PAT token." },
  { q: "Can I review local code snippets?", a: "Yes! The Local Snippet Review feature lets you paste any code snippet for instant AI analysis. You can run full reviews, security scans, complexity analysis, performance audits, refactoring suggestions, and test generation without connecting a repository." },
  { q: "What file types are supported?", a: "The platform supports all major programming languages including Python, JavaScript, TypeScript, Java, C#, Go, Rust, C/C++, and more. The Monaco editor provides syntax highlighting for dozens of languages." },
  { q: "Can I create PRs directly from the platform?", a: "Yes! After generating an AI fix, you can create a pull request directly to your GitHub repository with a single click. The platform handles branching, committing, and PR creation using your configured GitHub PAT." }
];

const PRICING_PLANS = [
  { name: "Starter", price: "Free", period: "", description: "Get started with basic code review capabilities", features: ["Up to 3 repositories", "50 AI scans per month", "Basic security analysis", "Local snippet review", "Community support"], cta: "Get Started", popular: false },
  { name: "Pro", price: "$29", period: "/month", description: "For professional developers and small teams", features: ["Unlimited repositories", "500 AI scans per month", "Advanced security & code quality", "PR review automation", "Export reports (PDF, CSV, JSON)", "Multi-provider LLM support", "Priority support"], cta: "Start Free Trial", popular: true },
  { name: "Enterprise", price: "$99", period: "/month", description: "For organizations with advanced needs", features: ["Everything in Pro", "Unlimited AI scans", "Custom LLM configuration", "Team collaboration", "SSO & SAML", "Audit logs", "Dedicated support", "SLA guarantee"], cta: "Contact Sales", popular: false }
];

export const Landing: React.FC<LandingProps> = ({ onNavigateToLogin, onNavigateToRegister }) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [openFaq, setOpenFaq] = useState<number | null>(null);

  // [REMOVED] scrollYProgress — parallax effects removed with 3D hero integration

  const scrollTo = (id: string) => {
    setMobileMenuOpen(false);
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="min-h-screen bg-background text-zinc-900 overflow-x-hidden">
      {/* ── Navigation ── */}
      <motion.nav
        className="fixed top-0 left-0 right-0 z-50 bg-white/80 backdrop-blur-glass border-b border-zinc-200/40"
        initial={{ y: -20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
      >
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <motion.div className="flex items-center gap-3" whileHover={{ scale: 1.02 }}>
            <div className="w-9 h-9 rounded-2xl bg-accent-gradient flex items-center justify-center shadow-glow-blue">
              <Shield className="w-5 h-5 text-white" />
            </div>
            <span className="font-bold text-sm font-sans text-zinc-950">RepoLens AI</span>
          </motion.div>

          <div className="hidden md:flex items-center gap-8">
            {["features", "workflow", "pricing", "faq"].map((item) => (
              <motion.button
                key={item}
                onClick={() => scrollTo(item)}
                className="text-xs text-zinc-600 hover:text-zinc-900 font-medium transition-colors"
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
              >
                {item === "workflow" ? "How it Works" : item.charAt(0).toUpperCase() + item.slice(1)}
              </motion.button>
            ))}
            <div className="flex items-center gap-3 pl-4 border-l border-border/40">
              <button onClick={onNavigateToLogin} className="btn-secondary text-xs">Sign In</button>
              <motion.button
                onClick={onNavigateToRegister}
                className="btn-primary text-xs flex items-center gap-1.5"
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
              >
                Start Reviewing <Sparkles className="w-3 h-3" />
              </motion.button>
            </div>
          </div>

          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="md:hidden text-muted hover:text-white p-2"
            aria-label="Toggle mobile menu"
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>

        <AnimatePresence>
          {mobileMenuOpen && (
            <motion.div
              className="md:hidden glass border-t border-border/40 p-4 space-y-3"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: "easeInOut" }}
            >
              {["features", "workflow", "pricing", "faq"].map((item) => (
                <button key={item} onClick={() => scrollTo(item)}
                  className="block w-full text-left text-sm text-muted hover:text-white py-2">
                  {item === "workflow" ? "How it Works" : item.charAt(0).toUpperCase() + item.slice(1)}
                </button>
              ))}
              <div className="flex gap-3 pt-2 border-t border-border/40">
                <button onClick={onNavigateToLogin} className="btn-secondary flex-1 text-xs">Sign In</button>
                <button onClick={onNavigateToRegister} className="btn-primary flex-1 text-xs">Start Reviewing</button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.nav>

      {/* ── Hero Section (with 3D background) ── */}
      <section className="relative pt-32 pb-24 overflow-hidden min-h-[90vh] flex items-center">
        <div className="absolute inset-0 bg-hero-gradient pointer-events-none" />
        
        {/* Premium 3D Scene */}
        <Suspense fallback={
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-16 h-16 rounded-3xl bg-accent-gradient flex items-center justify-center animate-pulse">
              <Shield className="w-8 h-8 text-white" />
            </div>
          </div>
        }>
          <ThreeDHero />
        </Suspense>

        <motion.div
          className="relative max-w-5xl mx-auto px-6 text-center"
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: [0.25, 0.4, 0.25, 1] }}
        >
          <motion.div
            className="inline-flex items-center gap-2 glass px-4 py-2 rounded-full mb-8"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2, duration: 0.5 }}
          >
            <span className="w-2 h-2 rounded-full bg-accent-green animate-pulse" />
            <span className="text-xs text-zinc-600 font-medium">AI-Powered Code Analysis Platform</span>
          </motion.div>

          <motion.h1
            className="text-5xl md:text-[72px] font-bold text-zinc-950 leading-tight mb-6"
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3, duration: 0.6 }}
          >
            AI Code Review That
            <motion.span
              className="block text-transparent bg-clip-text bg-accent-gradient"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.5, duration: 0.6 }}
            >
              Thinks Like a Senior Engineer
            </motion.span>
          </motion.h1>

          <motion.p
            className="text-lg text-zinc-700 max-w-2xl mx-auto mb-10"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.5, duration: 0.5 }}
          >
            Analyze repositories, detect vulnerabilities, generate fixes, and create pull requests using advanced AI.
            Your code, your API keys, your control.
          </motion.p>

          <motion.div
            className="flex flex-wrap items-center justify-center gap-4"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.6, duration: 0.5 }}
          >
            <motion.button
              onClick={onNavigateToRegister}
              className="btn-primary text-sm px-8 py-4 flex items-center gap-2"
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.97 }}
            >
              Start Reviewing <ArrowRight className="w-4 h-4" />
            </motion.button>
            <motion.button
              onClick={() => scrollTo("workflow")}
              className="btn-secondary text-sm px-8 py-4 flex items-center gap-2"
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.97 }}
            >
              See How It Works <ChevronDown className="w-4 h-4" />
            </motion.button>
          </motion.div>

          {/* Animated Counters */}
          <motion.div
            className="grid grid-cols-2 md:grid-cols-4 gap-6 mt-20 max-w-3xl mx-auto"
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
          >
            {[
              { value: "10K+", label: "Scans Run" },
              { value: "50K+", label: "Findings Detected" },
              { value: "99.9%", label: "Uptime" },
              { value: "15+", label: "Languages" }
            ].map((stat, i) => (
              <motion.div key={i} variants={staggerItem}>
                <AnimatedCounter value={stat.value} label={stat.label} />
              </motion.div>
            ))}
          </motion.div>
        </motion.div>
      </section>

      {/* ── Features Section ── */}
      <Section id="features" className="py-24 relative">
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-accent-blue/[0.02] to-transparent pointer-events-none" />
        <div className="relative max-w-6xl mx-auto px-6">
          <motion.div className="text-center mb-16" variants={fadeUpFast}>
            <h2 className="text-4xl md:text-5xl font-bold text-zinc-950 mb-4">Everything You Need</h2>
            <p className="text-zinc-600 max-w-xl mx-auto">Comprehensive code analysis powered by the latest LLMs</p>
          </motion.div>

          <motion.div
            className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"
            variants={staggerContainer}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-100px" }}
          >
            {FEATURES.map((feature, i) => (
              <motion.div
                key={i}
                className="glass-card-hover p-8 group cursor-default"
                variants={staggerItem}
                whileHover={{ y: -6, transition: { duration: 0.2 } }}
              >
                <motion.div
                  className={`w-12 h-12 rounded-2xl bg-white/5 flex items-center justify-center mb-5 ${feature.color}`}
                  whileHover={{ scale: 1.15, rotate: 5 }}
                  transition={{ type: "spring", stiffness: 300, damping: 10 }}
                >
                  {feature.icon}
                </motion.div>
                <h3 className="text-xl font-bold text-zinc-950 mb-3">{feature.title}</h3>
                <p className="text-base text-zinc-700 leading-relaxed">{feature.description}</p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </Section>

      {/* ── How It Works ── */}
      <Section id="workflow" className="py-24 relative">
        <div className="max-w-5xl mx-auto px-6">
          <motion.div className="text-center mb-16" variants={fadeUpFast}>
            <h2 className="text-4xl md:text-5xl font-bold text-zinc-950 mb-4">How It Works</h2>
            <p className="text-zinc-600 max-w-xl mx-auto">From repository connection to production fix in minutes</p>
          </motion.div>

          <div className="relative">
            <motion.div
              className="absolute left-8 md:left-1/2 top-0 bottom-0 w-px bg-accent-gradient/30 md:-translate-x-px hidden md:block"
              initial={{ scaleY: 0 }}
              whileInView={{ scaleY: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 1.5, ease: "easeInOut" }}
              style={{ originY: 0 }}
            />

            <div className="space-y-16">
              {WORKFLOW_STEPS.map((step, i) => {
                const isLeft = i % 2 === 0;
                return (
                  <motion.div
                    key={i}
                    className={`relative flex flex-col md:flex-row items-center gap-8 ${isLeft ? 'md:flex-row' : 'md:flex-row-reverse'}`}
                    initial={{ opacity: 0, x: isLeft ? -40 : 40 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    viewport={{ once: true, margin: "-100px" }}
                    transition={{ duration: 0.6, delay: i * 0.15 }}
                  >
                    <motion.div
                      className="absolute -left-3 md:left-1/2 md:-translate-x-1/2 w-14 h-14 rounded-2xl bg-accent-gradient flex items-center justify-center shadow-glow-blue z-10"
                      whileHover={{ scale: 1.1, rotate: 5 }}
                      transition={{ type: "spring", stiffness: 300 }}
                    >
                      <span className="text-lg font-bold font-sans text-white">{step.step}</span>
                    </motion.div>

                    <div className={`md:w-1/2 ${isLeft ? 'md:pr-20' : 'md:pl-20'} pt-20 md:pt-0`}>
                      <motion.div
                        className="glass-card-hover p-8"
                        whileHover={{ y: -4 }}
                        transition={{ duration: 0.2 }}
                      >
                        <div className="w-14 h-14 rounded-2xl bg-white/5 flex items-center justify-center mb-4 text-accent-blue">
                          {step.icon}
                        </div>
                        <h3 className="text-xl font-bold text-zinc-950 mb-3">{step.title}</h3>
                        <p className="text-base text-zinc-700 leading-relaxed">{step.description}</p>
                      </motion.div>
                    </div>

                    <div className="hidden md:block md:w-1/2" />
                  </motion.div>
                );
              })}
            </div>
          </div>
        </div>
      </Section>

      {/* ── Security Section ── */}
      <Section className="py-24 relative">
        <div className="absolute inset-0 bg-accent-blue/[0.01] pointer-events-none" />
        <div className="relative max-w-5xl mx-auto px-6">
          <motion.div
            className="glass-hero p-12 md:p-16 relative overflow-hidden"
            variants={scaleIn}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-100px" }}
          >
            <div className="absolute inset-0 bg-card-glow-blue pointer-events-none" />
            <div className="relative z-10 grid md:grid-cols-2 gap-12 items-center">
              <motion.div variants={slideInLeft} initial="hidden" whileInView="visible" viewport={{ once: true }}>
                <div className="w-16 h-16 rounded-3xl bg-accent-green/10 flex items-center justify-center mb-6">
                  <Lock className="w-8 h-8 text-accent-green" />
                </div>
                <h2 className="text-3xl md:text-4xl font-bold text-zinc-950 mb-4">Enterprise-Grade Security</h2>
                <p className="text-zinc-600 leading-relaxed mb-6">
                  Your code never leaves your control. We use AES-256 encryption for all API keys,
                  and you choose which LLM provider processes your code. No data retention, no third-party sharing.
                </p>
                <motion.ul className="space-y-3" variants={staggerContainer} initial="hidden" whileInView="visible" viewport={{ once: true }}>
                  {["AES-256 encrypted credential storage", "Your own API keys for all providers", "No code stored on our servers", "GitHub PAT-based authentication"].map((item, i) => (
                    <motion.li key={i} className="flex items-center gap-3 text-sm text-zinc-700" variants={staggerItem}>
                      <motion.div whileHover={{ scale: 1.2, rotate: 5 }} transition={{ type: "spring" }}>
                        <CheckCircle2 className="w-4 h-4 text-accent-green shrink-0" />
                      </motion.div>
                      {item}
                    </motion.li>
                  ))}
                </motion.ul>
              </motion.div>

              <motion.div
                className="hidden md:flex flex-col gap-4"
                variants={slideInRight}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
              >
                {[
                  { label: "Encryption", value: "AES-256-GCM", color: "border-l-accent-green" },
                  { label: "Authentication", value: "JWT + Argon2", color: "border-l-accent-blue" },
                  { label: "Data Policy", value: "Zero Retention", color: "border-l-accent-purple" }
                ].map((item, i) => (
                  <motion.div
                    key={i}
                    className={`glass p-6 rounded-3xl border-l-4 ${item.color}`}
                    initial={{ opacity: 0, x: 30 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    viewport={{ once: true }}
                    transition={{ delay: i * 0.15, duration: 0.5 }}
                    whileHover={{ x: 4 }}
                  >
                    <p className="text-xs text-zinc-600 uppercase font-bold tracking-wider mb-1">{item.label}</p>
                    <p className="text-sm text-zinc-900">{item.value}</p>
                  </motion.div>
                ))}
              </motion.div>
            </div>
          </motion.div>
        </div>
      </Section>

      {/* ── Testimonials ── */}
      <Section className="py-24 relative">
        <div className="max-w-5xl mx-auto px-6">
          <motion.div className="text-center mb-16" variants={fadeUpFast}>
            <h2 className="text-4xl md:text-5xl font-bold text-zinc-950 mb-4">Trusted by Engineers</h2>
            <p className="text-zinc-600 max-w-xl mx-auto">What our users say about RepoLens AI</p>
          </motion.div>

          <motion.div
            className="grid grid-cols-1 md:grid-cols-3 gap-6"
            variants={staggerContainer}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-100px" }}
          >
            {TESTIMONIALS.map((t, i) => (
              <motion.div
                key={i}
                className="bg-white border border-zinc-200/60 shadow-glass rounded-3xl p-8 flex flex-col"
                variants={staggerItem}
                whileHover={{ y: -6, transition: { duration: 0.2 } }}
              >
                <motion.div
                  className="flex gap-1 mb-4"
                  initial={{ opacity: 0 }}
                  whileInView={{ opacity: 1 }}
                  viewport={{ once: true }}
                  transition={{ delay: 0.3 }}
                >
                  {Array.from({ length: t.rating }).map((_, j) => (
                    <motion.div
                      key={j}
                      initial={{ opacity: 0, scale: 0 }}
                      whileInView={{ opacity: 1, scale: 1 }}
                      viewport={{ once: true }}
                      transition={{ delay: 0.4 + j * 0.1, type: "spring" }}
                    >
                      <Star className="w-4 h-4 fill-accent-orange text-accent-orange" />
                    </motion.div>
                  ))}
                </motion.div>
                <p className="text-base text-zinc-700 leading-relaxed flex-1 mb-6 italic">"{t.quote}"</p>
                <motion.div
                  className="flex items-center gap-3 pt-4 border-t border-border/40"
                  initial={{ opacity: 0 }}
                  whileInView={{ opacity: 1 }}
                  viewport={{ once: true }}
                  transition={{ delay: 0.5 }}
                >
                  <div className="w-10 h-10 rounded-xl bg-accent-gradient/30 flex items-center justify-center text-xs font-bold text-white">
                    {t.avatar}
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-zinc-950">{t.author}</p>
                    <p className="text-xs text-zinc-600">{t.role}</p>
                  </div>
                </motion.div>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </Section>

      {/* ── Pricing ── */}
      <Section id="pricing" className="py-24 relative">
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-accent-purple/[0.02] to-transparent pointer-events-none" />
        <div className="relative max-w-5xl mx-auto px-6">
          <motion.div className="text-center mb-16" variants={fadeUpFast}>
            <h2 className="text-4xl md:text-5xl font-bold text-zinc-950 mb-4">Simple Pricing</h2>
            <p className="text-zinc-600 max-w-xl mx-auto">Start free, upgrade when you need more power</p>
          </motion.div>

          <motion.div
            className="grid grid-cols-1 md:grid-cols-3 gap-6"
            variants={staggerContainer}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-100px" }}
          >
            {PRICING_PLANS.map((plan, i) => (
              <motion.div
                key={i}
                className={`relative glass-card p-8 flex flex-col ${plan.popular ? 'border-accent-blue/30 shadow-glow-blue' : 'border-zinc-200'}`}
                variants={staggerItem}
                whileHover={{ y: -8, transition: { duration: 0.2 } }}
              >
                {plan.popular && (
                  <motion.div
                    className="absolute -top-3 left-1/2 -translate-x-1/2 bg-accent-gradient text-white text-[10px] font-bold px-4 py-1 rounded-full uppercase tracking-wider"
                    initial={{ opacity: 0, y: -10 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true }}
                    transition={{ delay: 0.3 }}
                  >
                    Most Popular
                  </motion.div>
                )}
                <h3 className="text-xl font-bold text-zinc-950 mb-2">{plan.name}</h3>
                <div className="flex items-baseline gap-1 mb-2">
                  <span className="text-4xl font-bold font-sans text-zinc-950">{plan.price}</span>
                  {plan.period && <span className="text-sm text-zinc-600">{plan.period}</span>}
                </div>
                <p className="text-xs text-zinc-600 mb-6">{plan.description}</p>
                <ul className="space-y-3 mb-8 flex-1">
                  {plan.features.map((feature, j) => (
                    <motion.li
                      key={j}
                      className="flex items-start gap-2.5 text-xs text-zinc-700"
                      initial={{ opacity: 0, x: -10 }}
                      whileInView={{ opacity: 1, x: 0 }}
                      viewport={{ once: true }}
                      transition={{ delay: 0.5 + j * 0.05 }}
                    >
                      <CheckCircle2 className="w-4 h-4 text-green-600 shrink-0 mt-0.5" />
                      {feature}
                    </motion.li>
                  ))}
                </ul>
                <motion.button
                  onClick={onNavigateToRegister}
                  className={`w-full py-3.5 rounded-2xl text-xs font-bold transition-all ${
                    plan.popular
                      ? 'bg-accent-gradient text-white shadow-glow-blue hover:opacity-90'
                      : 'bg-zinc-100 border-2 border-zinc-300 hover:border-zinc-400 hover:bg-zinc-200 text-zinc-800 hover:text-zinc-900 shadow-sm hover:shadow-md'
                  }`}
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: 0.97 }}
                >
                  {plan.cta}
                </motion.button>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </Section>

      {/* ── FAQ ── */}
      <Section id="faq" className="py-24 relative">
        <div className="max-w-3xl mx-auto px-6">
          <motion.div className="text-center mb-16" variants={fadeUpFast}>
            <h2 className="text-4xl md:text-5xl font-bold text-zinc-950 mb-4">Frequently Asked Questions</h2>
            <p className="text-zinc-600 max-w-xl mx-auto">Everything you need to know about RepoLens AI</p>
          </motion.div>

          <motion.div
            className="space-y-3"
            variants={staggerContainer}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-50px" }}
          >
            {FAQ_ITEMS.map((item, i) => (
              <motion.div key={i} className="glass-card overflow-hidden" variants={staggerItem}>
                <motion.button
                  onClick={() => setOpenFaq(openFaq === i ? null : i)}
                  className="w-full flex items-center justify-between p-6 text-left hover:bg-white/[0.02] transition-colors"
                  whileHover={{ backgroundColor: "rgba(255,255,255,0.03)" }}
                >
                  <span className="text-sm font-semibold text-zinc-950 pr-4">{item.q}</span>
                  <motion.div
                    animate={{ rotate: openFaq === i ? 180 : 0 }}
                    transition={{ duration: 0.3, ease: "easeInOut" }}
                  >
                    <ChevronDown className="w-4 h-4 text-muted shrink-0" />
                  </motion.div>
                </motion.button>
                <AnimatePresence initial={false}>
                  {openFaq === i && (
                    <motion.div
                      className="px-6 pb-6 overflow-hidden"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.3, ease: "easeInOut" }}
                    >
                      <p className="text-base text-zinc-700 leading-relaxed">{item.a}</p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </Section>

      {/* ── CTA Section ── */}
      <Section className="py-24 relative">
        <div className="max-w-3xl mx-auto px-6 text-center">
          <motion.div
            className="glass-hero p-12 md:p-16 relative overflow-hidden"
            variants={scaleIn}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-100px" }}
          >
            <div className="absolute inset-0 bg-card-glow-blue pointer-events-none" />
            <div className="relative z-10">
              <h2 className="text-3xl md:text-5xl font-bold text-zinc-950 mb-4">
                Ready to Transform Your Code Reviews?
              </h2>
              <p className="text-zinc-600 max-w-lg mx-auto mb-8">
                Join thousands of engineers using AI-powered code review to ship better software, faster.
              </p>
              <motion.div
                className="flex flex-wrap items-center justify-center gap-4"
                variants={staggerContainer}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
              >
                <motion.button
                  onClick={onNavigateToRegister}
                  className="btn-primary text-sm px-8 py-4 flex items-center gap-2"
                  variants={staggerItem}
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.97 }}
                >
                  Get Started Free <ArrowRight className="w-4 h-4" />
                </motion.button>
                <motion.button
                  onClick={onNavigateToLogin}
                  className="btn-secondary text-sm px-8 py-4"
                  variants={staggerItem}
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.97 }}
                >
                  Sign In
                </motion.button>
              </motion.div>
            </div>
          </motion.div>
        </div>
      </Section>

      {/* ── Footer ── */}
      <motion.footer
        className="border-t border-border/40 py-12"
        initial={{ opacity: 0 }}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.6 }}
      >
        <div className="max-w-6xl mx-auto px-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-12">
            <div className="col-span-2 md:col-span-1">
              <div className="flex items-center gap-2.5 mb-4">
                <div className="w-8 h-8 rounded-xl bg-accent-gradient flex items-center justify-center">
                  <Shield className="w-4 h-4 text-white" />
                </div>
                <span className="font-bold text-sm text-zinc-950">RepoLens AI</span>
              </div>
              <p className="text-xs text-zinc-600 leading-relaxed max-w-xs">
                Premium AI-powered code analysis platform for modern engineering teams.
              </p>
            </div>

            {[
              { title: "Product", links: ["Features", "Pricing", "Integrations", "Changelog"] },
              { title: "Company", links: ["About", "Blog", "Careers", "Contact"] },
              { title: "Resources", links: ["Documentation", "API Reference", "Status", "Support"] }
            ].map((section, i) => (
              <div key={i}>
                <h4 className="text-xs font-bold text-zinc-950 uppercase tracking-wider mb-4">{section.title}</h4>
                <ul className="space-y-2.5">
                  {section.links.map((link, j) => (
                    <motion.li key={j} whileHover={{ x: 3 }}>
                      <a href="#" className="text-xs text-zinc-600 hover:text-zinc-900 transition-colors">{link}</a>
                    </motion.li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <motion.div
            className="flex flex-col md:flex-row items-center justify-between pt-8 border-t border-border/40 gap-4"
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true }}
            transition={{ delay: 0.2 }}
          >
            <p className="text-xs text-zinc-600">
              &copy; {new Date().getFullYear()} RepoLens AI. All rights reserved.
            </p>
            <div className="flex items-center gap-4">
              {[Github, Twitter, Linkedin, Mail].map((Icon, i) => (
                <motion.a key={i} href="#" className="text-muted hover:text-white transition-colors" whileHover={{ scale: 1.2, rotate: 5 }}>
                  <Icon className="w-4 h-4" />
                </motion.a>
              ))}
            </div>
          </motion.div>
        </div>
      </motion.footer>
    </div>
  );
};
