import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // VITE_API_URL in .env.local (or the environment) overrides the proxy
  // target so local dev can run against a local backend. Default unchanged:
  // requests proxy to the deployed backend.
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_API_URL || "https://repolens-ft5r.onrender.com"

  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true,
          secure: true,
          ws: true, // scan-progress WebSocket must proxy to the same backend
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyRequest) => {
              proxyRequest.removeHeader("origin");
              proxyRequest.removeHeader("referer");
            });
          },
        },
      },
    },
  }
})
