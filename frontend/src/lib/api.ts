import axios from "axios";

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined;

export const API_BASE_URL = (configuredBaseUrl || "http://localhost:8000").replace(/\/+$/, "");
export const API_V1_BASE_URL = `${API_BASE_URL}/api/v1`;

export function websocketUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const wsBase = API_BASE_URL.replace(/^http/i, "ws");
  return `${wsBase}/api/v1${normalizedPath}`;
}

axios.defaults.baseURL = API_V1_BASE_URL;

export default axios;


