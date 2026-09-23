import { create } from "zustand";

/**
 * Theme store — Light/Dark mode for the whole app.
 *
 * - Preference is persisted in localStorage ("repolens-theme").
 * - No saved preference → follows the OS (prefers-color-scheme), but a manual
 *   choice always wins and is remembered across refreshes/navigation.
 * - Applies/removes the `dark` class on <html> (Tailwind `darkMode: "class"`),
 *   which drives both the dark: utilities and the CSS overrides in index.css.
 */

const STORAGE_KEY = "repolens-theme";

export type Theme = "light" | "dark";

function getInitialTheme(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // localStorage unavailable — fall through to system preference
  }
  if (typeof window !== "undefined" && window.matchMedia) {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return "light";
}

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  // Keeps the page background correct before React mounts / on navigation
  root.style.colorScheme = theme;
}

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: getInitialTheme(),
  setTheme: (theme) => {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // ignore persistence errors (private mode etc.)
    }
    applyTheme(theme);
    set({ theme });
  },
  toggleTheme: () => {
    get().setTheme(get().theme === "dark" ? "light" : "dark");
  },
}));

// Apply the theme immediately at module load so there is no flash of the
// wrong theme between page load and the first React render.
applyTheme(useThemeStore.getState().theme);
