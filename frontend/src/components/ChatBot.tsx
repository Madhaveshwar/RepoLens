import React, { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Markdown } from "./Markdown";
import {
  MessageSquare, X, Send, Bot,
  User, GraduationCap,
  Minimize2, Maximize2
} from "lucide-react";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  isError?: boolean;
}

interface ChatProps {
  currentPage?: string;
  findingContext?: Record<string, any>;
}

const SUGGESTED_QUESTIONS: Record<string, string[]> = {
  dashboard: [
    "Explain my health score",
    "How do I improve my security score?",
    "What's the most critical issue?",
    "What do the severity colors mean?"
  ],
  repository: [
    "Summarize this scan",
    "How do I fix these findings?",
    "What's the risk score mean?",
    "Explain this vulnerability"
  ],
  repositories: [
    "Summarize this scan",
    "How do I fix these findings?",
    "What's the risk score mean?",
    "Explain this vulnerability"
  ],
  settings: [
    "Which LLM provider should I use?",
    "How are my keys encrypted?",
    "How do I get a Groq API key?",
    "Why use a GitHub PAT?"
  ],
  "pr-review": [
    "Summarize this PR",
    "What are the riskiest changes?",
    "Should I approve this PR?",
    "Explain this finding"
  ],
};

const DEFAULT_QUESTIONS = [
  "What can you help me with?",
  "How do scans work?",
  "Give me best practices",
  "Explain beginner mode"
];


export const ChatBot: React.FC<ChatProps> = ({ currentPage, findingContext }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content: "Hi! I'm your AI Review Assistant. I can explain scan results, summarize security findings, suggest fixes, and answer questions about your repositories. What would you like to know?",
      timestamp: Date.now()
    }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [beginnerMode, setBeginnerMode] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>(DEFAULT_QUESTIONS);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when opening
  useEffect(() => {
    if (isOpen && !isMinimized) {
      setTimeout(() => inputRef.current?.focus(), 300);
    }
  }, [isOpen, isMinimized]);

  // Update suggestions based on page
  useEffect(() => {
    if (currentPage && SUGGESTED_QUESTIONS[currentPage]) {
      setSuggestions(SUGGESTED_QUESTIONS[currentPage]);
    } else {
      setSuggestions(DEFAULT_QUESTIONS);
    }
  }, [currentPage]);

  // Abort controller for canceling streaming requests
  const abortControllerRef = useRef<AbortController | null>(null);
  const loadingRef = useRef(false);

  const cancelStream = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    loadingRef.current = false;
    setLoading(false);
  }, []);

  const appendMessage = useCallback((msg: ChatMessage) => {
    setMessages(prev => [...prev, msg]);
  }, []);

  const updateLastMessage = useCallback((content: string, isError = false) => {
    setMessages(prev => {
      const updated = [...prev];
      const last = updated[updated.length - 1];
      if (last && last.role === "assistant") {
        updated[updated.length - 1] = { ...last, content, isError };
      }
      return updated;
    });
  }, []);

  const sendMessage = useCallback(async (content: string) => {
    const trimmed = content.trim();
    if (!trimmed) return;
    if (loadingRef.current) return; // synchronous double-send guard

    const userMsg: ChatMessage = { role: "user", content: trimmed, timestamp: Date.now() };
    appendMessage(userMsg);
    setInput("");
    loadingRef.current = true;
    setLoading(true);

    // Placeholder assistant message the response/error streams into
    appendMessage({ role: "assistant", content: "", timestamp: Date.now() });

    const history = messages
      .filter(m => m.content && !m.isError)
      .slice(-10)
      .map(m => ({ role: m.role, content: m.content }));

    const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");
    const token = localStorage.getItem("acr_token");

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const fillPlaceholder = (text: string, isError = false) => {
      updateLastMessage(text, isError);
    };

    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/chat/ask/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: trimmed,
          current_page: currentPage || null,
          finding_context: findingContext || null,
          beginner_mode: beginnerMode,
          conversation_history: history,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        // Non-streaming failure (e.g. 400 no key, 502 provider error) —
        // surface the backend's friendly detail message.
        let friendlyDetail = "The AI Assistant failed to respond. Please try again.";
        try {
          const errJson = await response.json();
          if (errJson?.detail) friendlyDetail = errJson.detail;
        } catch {
          // keep default message
        }
        throw new Error(friendlyDetail);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("Streaming is not supported in this browser.");

      const decoder = new TextDecoder();
      let buffer = "";
      let accumulated = "";
      let streamError: string | null = null;

      const handleSseLine = (line: string) => {
        if (!line.startsWith("data: ")) return;
        const payload = line.slice(6).trim();
        if (!payload) return;
        let data: any;
        try {
          data = JSON.parse(payload);
        } catch {
          return; // ignore fragments; the buffer keeps split lines together
        }
        if (data.token) {
          accumulated += data.token;
          fillPlaceholder(accumulated);
        }
        if (data.suggested_questions) {
          setSuggestions(data.suggested_questions);
        }
        if (data.error && !streamError) {
          streamError = data.error;
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Split on complete SSE events only; keep the incomplete tail buffered
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const event of parts) {
          for (const line of event.split("\n")) {
            handleSseLine(line);
          }
        }
        if (streamError) break;
      }
      // Flush any complete trailing event left in the buffer
      if (!streamError && buffer) {
        for (const line of buffer.split("\n")) {
          handleSseLine(line);
        }
      }

      if (streamError) {
        throw new Error(streamError);
      }

      if (!accumulated.trim()) {
        throw new Error("The AI Assistant returned an empty response. Please try again.");
      }
    } catch (err: any) {
      if (err.name === "AbortError") {
        // User cancelled — keep partial content, or mark as cancelled
        setMessages(prev => {
          const updated = [...prev];
          const lastMsg = updated[updated.length - 1];
          if (lastMsg && lastMsg.role === "assistant" && !lastMsg.content) {
            updated[updated.length - 1] = {
              role: "assistant",
              content: "Response cancelled.",
              timestamp: Date.now(),
              isError: false
            };
          }
          return updated;
        });
      } else {
        const errorText = err.message || "Failed to get response. Please try again.";
        fillPlaceholder(
          `**AI Assistant Error**\n\n${errorText}\n\nIf this keeps happening, check your LLM provider API key and model in **Settings**.`,
          true
        );
      }
    } finally {
      abortControllerRef.current = null;
      loadingRef.current = false;
      setLoading(false);
    }
  }, [messages, currentPage, findingContext, beginnerMode, appendMessage, updateLastMessage]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const handleSuggestionClick = (q: string) => {
    sendMessage(q);
  };

  const clearChat = () => {
    setMessages([
      {
        role: "assistant",
        content: "Chat cleared. How can I help you with code review?",
        timestamp: Date.now()
      }
    ]);
  };

  return (
    <>
      {/* Floating Chat Button */}
      <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end gap-3">
        <AnimatePresence>
          {isOpen && !isMinimized && (
            <motion.div
              className="w-[380px] md:w-[420px] h-[580px] bg-white border border-zinc-200/80 shadow-2xl rounded-3xl flex flex-col overflow-hidden"
              initial={{ opacity: 0, y: 20, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 20, scale: 0.95 }}
              transition={{ duration: 0.25, ease: [0.25, 0.4, 0.25, 1] }}
            >
              {/* Header */}
              <div className="bg-gradient-to-r from-violet-600 to-blue-600 p-4 flex items-center justify-between shrink-0">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-xl bg-white/20 flex items-center justify-center backdrop-blur-sm">
                    <Bot className="w-4 h-4 text-white" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-white">AI Assistant</h3>
                    <p className="text-[10px] text-white/70">RepoLens AI Helper</p>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setBeginnerMode(!beginnerMode)}
                    className={`p-1.5 rounded-lg transition-colors ${
                      beginnerMode ? "bg-white/25 text-white" : "text-white/60 hover:text-white hover:bg-white/10"
                    }`}
                    title={beginnerMode ? "Beginner mode ON" : "Toggle beginner mode"}
                  >
                    <GraduationCap className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setIsMinimized(true)}
                    className="p-1.5 rounded-lg text-white/60 hover:text-white hover:bg-white/10 transition-colors"
                  >
                    <Minimize2 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setIsOpen(false)}
                    className="p-1.5 rounded-lg text-white/60 hover:text-white hover:bg-white/10 transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Beginner Mode Badge */}
              <AnimatePresence>
                {beginnerMode && (
                  <motion.div
                    className="bg-amber-50 border-b border-amber-200/60 px-4 py-2 flex items-center gap-2"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                  >
                    <GraduationCap className="w-3.5 h-3.5 text-amber-600 shrink-0" />
                    <span className="text-[10px] text-amber-700 font-medium">Beginner Mode — simplified explanations with plain language</span>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-zinc-50/50">
                {messages.map((msg, idx) => (
                  <motion.div
                    key={idx}
                    className={`flex gap-2.5 ${msg.role === "user" ? "flex-row-reverse" : ""}`}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.2 }}
                  >
                    <div className={`w-7 h-7 rounded-xl flex items-center justify-center shrink-0 ${
                      msg.role === "user"
                        ? "bg-accent-blue/10 text-accent-blue"
                        : "bg-violet-100 text-violet-600"
                    }`}>
                      {msg.role === "user" ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
                    </div>
                    <div className={`max-w-[85%] ${
                      msg.role === "user"
                        ? "bg-accent-blue text-white px-3.5 py-2.5 rounded-2xl rounded-tr-md"
                        : msg.isError
                          ? "bg-red-50 border border-red-200/80 shadow-sm px-3.5 py-2.5 rounded-2xl rounded-tl-md"
                          : "bg-white border border-zinc-200/60 shadow-sm px-3.5 py-2.5 rounded-2xl rounded-tl-md"
                    }`}>
                      {msg.role === "user" ? (
                        <p className="text-xs leading-relaxed text-white">{msg.content}</p>
                      ) : msg.content ? (
                        <Markdown content={msg.content} />
                      ) : (
                        // Loading dots inside the placeholder bubble while waiting for the LLM
                        <div className="flex items-center gap-1.5 py-0.5">
                          <motion.span
                            className="w-2 h-2 rounded-full bg-violet-400"
                            animate={{ opacity: [0.3, 1, 0.3] }}
                            transition={{ duration: 1.2, repeat: Infinity, delay: 0 }}
                          />
                          <motion.span
                            className="w-2 h-2 rounded-full bg-violet-400"
                            animate={{ opacity: [0.3, 1, 0.3] }}
                            transition={{ duration: 1.2, repeat: Infinity, delay: 0.2 }}
                          />
                          <motion.span
                            className="w-2 h-2 rounded-full bg-violet-400"
                            animate={{ opacity: [0.3, 1, 0.3] }}
                            transition={{ duration: 1.2, repeat: Infinity, delay: 0.4 }}
                          />
                        </div>
                      )}
                    </div>
                  </motion.div>
                ))}

                <div ref={messagesEndRef} />
              </div>

              {/* Suggested Questions — only before the first real question; avoids duplicate-looking prompts */}
              {suggestions.length > 0 && !messages.some(m => m.role === "user") && (
                <div className="px-4 py-2 border-t border-zinc-200/40 bg-white">
                  <p className="text-[10px] text-zinc-500 font-semibold mb-2 uppercase tracking-wider">Try asking:</p>
                  <div className="flex flex-wrap gap-1.5">
                    {suggestions.map((q, idx) => (
                      <motion.button
                        key={idx}
                        onClick={() => handleSuggestionClick(q)}
                        className="text-[10px] bg-zinc-100 hover:bg-zinc-200 text-zinc-700 hover:text-zinc-900 px-2.5 py-1.5 rounded-xl border border-zinc-200/60 transition-all font-medium"
                        whileHover={{ scale: 1.03 }}
                        whileTap={{ scale: 0.97 }}
                        initial={{ opacity: 0, y: 5 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: idx * 0.05 }}
                      >
                        {q}
                      </motion.button>
                    ))}
                  </div>
                </div>
              )}

              {/* Input */}
              <div className="p-3 border-t border-zinc-200/60 bg-white">
                <div className="flex items-center gap-2">
                  <input
                    ref={inputRef}
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Ask about code review..."
                    disabled={loading}
                    className="flex-1 bg-zinc-100 border border-zinc-200/60 rounded-2xl text-xs px-4 py-2.5 text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 disabled:opacity-50"
                  />
                  {loading ? (
                    <button
                      onClick={cancelStream}
                      className="w-9 h-9 rounded-2xl bg-accent-red flex items-center justify-center shadow-sm"
                      title="Cancel generation"
                    >
                      <X className="w-4 h-4 text-white" />
                    </button>
                  ) : (
                    <motion.button
                      onClick={() => sendMessage(input)}
                      disabled={!input.trim()}
                      className="w-9 h-9 rounded-2xl bg-accent-gradient flex items-center justify-center shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                    >
                      <Send className="w-4 h-4 text-white" />
                    </motion.button>
                  )}
                </div>
                <div className="flex justify-between items-center mt-1.5 px-1">
                  <button
                    onClick={clearChat}
                    className="text-[9px] text-zinc-500 hover:text-zinc-600 transition-colors"
                  >
                    Clear chat
                  </button>
                  <span className="text-[9px] text-zinc-500">
                    {beginnerMode ? "Beginner mode" : "Standard mode"}
                  </span>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Minimized Chat Panel */}
        <AnimatePresence>
          {isOpen && isMinimized && (
            <motion.div
              className="bg-white border border-zinc-200/80 shadow-lg rounded-2xl px-4 py-3 flex items-center gap-3 cursor-pointer"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 10 }}
              onClick={() => setIsMinimized(false)}
              whileHover={{ scale: 1.02 }}
            >
              <div className="w-2 h-2 rounded-full bg-accent-green animate-pulse" />
              <span className="text-xs font-medium text-zinc-700">AI Assistant</span>
              <Maximize2 className="w-3.5 h-3.5 text-zinc-400" />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Toggle Button */}
        <motion.button
          onClick={() => setIsOpen(!isOpen)}
          className="w-14 h-14 rounded-2xl bg-accent-gradient shadow-glow-blue flex items-center justify-center relative"
          whileHover={{ scale: 1.08 }}
          whileTap={{ scale: 0.92 }}
          animate={isOpen ? { rotate: 45 } : { rotate: 0 }}
          transition={{ duration: 0.25, ease: "easeInOut" }}
        >
          {isOpen ? (
            <X className="w-6 h-6 text-white" />
          ) : (
            <>
              <MessageSquare className="w-6 h-6 text-white" />
              <motion.span
                className="absolute -top-1 -right-1 w-4 h-4 bg-accent-green rounded-full border-2 border-white"
                animate={{ scale: [1, 1.2, 1] }}
                transition={{ duration: 2, repeat: Infinity }}
              />
            </>
          )}
        </motion.button>
      </div>
    </>
  );
};
