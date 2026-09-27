import axios from "axios";

const configuredBaseUrl = import.meta.env.VITE_API_URL as string | undefined;
const productionBaseUrl = configuredBaseUrl || "https://repolens-8y8r.onrender.com";

export const API_BASE_URL = (import.meta.env.DEV ? "" : productionBaseUrl).replace(/\/+$/, "");
export const API_V1_BASE_URL = `${API_BASE_URL}/api/v1`;

export function websocketUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const websocketBase = API_BASE_URL
    ? API_BASE_URL.replace(/^http/i, "ws")
    : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;
  return `${websocketBase}/api/v1${normalizedPath}`;
}

axios.defaults.baseURL = API_V1_BASE_URL;

export default axios;


