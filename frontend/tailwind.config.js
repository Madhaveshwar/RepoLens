/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        background: "#09090b",
        surface: "#18181b",
        border: "#27272a",
        muted: "#71717a",
        accent: {
          blue: "#3b82f6",
          green: "#22c55e",
          red: "#ef4444",
          orange: "#f97316"
        }
      }
    },
  },
  plugins: [],
}
