import { create } from "zustand";
import axios from "../lib/api";

interface UserProfile {
  id: string;
  email: string;
  created_at: string;
  has_github_pat: boolean;
  has_groq_api_key: boolean;
  has_openai_api_key?: boolean;
  has_claude_api_key?: boolean;
  has_gemini_api_key?: boolean;
  has_openrouter_api_key?: boolean;
  llm_default_provider?: string | null;
  llm_default_model?: string | null;
  llm_temperature?: number | null;
  llm_max_tokens?: number | null;
}

interface AuthState {
  token: string | null;
  user: UserProfile | null;
  loading: boolean;
  error: string | null;
  setToken: (token: string | null) => void;
  setUser: (user: UserProfile | null) => void;
  initialize: () => Promise<void>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem("acr_token"),
  user: null,
  loading: false,
  error: null,

  setToken: (token) => {
    if (token) {
      localStorage.setItem("acr_token", token);
      axios.defaults.headers.common["Authorization"] = `Bearer ${token}`;
    } else {
      localStorage.removeItem("acr_token");
      delete axios.defaults.headers.common["Authorization"];
    }
    set({ token });
  },

  setUser: (user) => set({ user }),

  initialize: async () => {
    const token = get().token;
    if (!token) return;
    
    set({ loading: true });
    axios.defaults.headers.common["Authorization"] = `Bearer ${token}`;
    try {
      const response = await axios.get("/users/me");
      set({ user: response.data, error: null });
    } catch (err: any) {
      console.error("Auth init failure:", err);
      // Token expired
      get().logout();
    } finally {
      set({ loading: false });
    }
  },

  logout: () => {
    get().setToken(null);
    set({ user: null });
  }
}));

