import React from "react";
import { create } from "zustand";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, AlertTriangle, X, Info } from "lucide-react";

/**
 * App-wide toast notifications.
 *
 * Usage (from anywhere, including stores):
 *   import { toast } from "./Toast";
 *   toast.success("Repository deleted successfully.");
 *   toast.error("Could not delete repository. Please try again.");
 *
 * The <ToastContainer /> is mounted once in App.tsx. Success messages use
 * aria-live="polite"; errors use role="alert" so screen readers announce them.
 */

export type ToastType = "success" | "error" | "info";

interface ToastItem {
  id: number;
  type: ToastType;
  message: string;
}

interface ToastStore {
  toasts: ToastItem[];
  push: (type: ToastType, message: string, durationMs?: number) => void;
  dismiss: (id: number) => void;
}

let toastIdCounter = 0;
const DEFAULT_DURATION = 5000;

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  push: (type, message, durationMs = DEFAULT_DURATION) => {
    const id = ++toastIdCounter;
    set((state) => ({ toasts: [...state.toasts, { id, type, message }] }));
    if (durationMs > 0) {
      window.setTimeout(() => {
        set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
      }, durationMs);
    }
  },
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));

export const toast = {
  success: (message: string, durationMs?: number) =>
    useToastStore.getState().push("success", message, durationMs),
  error: (message: string, durationMs?: number) =>
    useToastStore.getState().push("error", message, durationMs),
  info: (message: string, durationMs?: number) =>
    useToastStore.getState().push("info", message, durationMs),
};

const ICONS: Record<ToastType, React.ReactNode> = {
  success: <CheckCircle2 className="w-5 h-5 shrink-0 mt-0.5" aria-hidden="true" />,
  error: <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" aria-hidden="true" />,
  info: <Info className="w-5 h-5 shrink-0 mt-0.5" aria-hidden="true" />,
};

const STYLES: Record<ToastType, string> = {
  success: "bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-950/80 dark:border-emerald-800 dark:text-emerald-200",
  error: "bg-red-50 border-red-200 text-red-800 dark:bg-red-950/80 dark:border-red-800 dark:text-red-200",
  info: "bg-sky-50 border-sky-200 text-sky-800 dark:bg-sky-950/80 dark:border-sky-800 dark:text-sky-200",
};

export const ToastContainer: React.FC = () => {
  const { toasts, dismiss } = useToastStore();

  return (
    <div
      className="fixed bottom-6 right-6 z-[100] flex flex-col gap-2 max-w-sm pointer-events-none"
      aria-live="polite"
      aria-atomic="false"
    >
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.95 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            role={t.type === "error" ? "alert" : "status"}
            className={`pointer-events-auto flex items-start gap-3 px-5 py-4 rounded-2xl shadow-lg border backdrop-blur-sm ${STYLES[t.type]}`}
          >
            {ICONS[t.type]}
            <p className="text-sm font-medium flex-1">{t.message}</p>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className="shrink-0 bg-transparent border-0 cursor-pointer p-0.5 hover:opacity-70 transition-opacity focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current rounded"
            >
              <X className="w-4 h-4" aria-hidden="true" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
};
