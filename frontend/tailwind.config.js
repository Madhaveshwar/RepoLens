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
        // Theme-aware tokens — resolved from CSS variables that flip with
        // html.dark (see index.css). Accents stay constant across themes.
        background: ({ opacityValue }) =>
          opacityValue !== undefined
            ? `rgb(var(--rl-bg) / ${opacityValue})`
            : `rgb(var(--rl-bg, 250 250 250))`,
        "background-elevated": "var(--rl-bg-elevated)",
        "background-raised": "var(--rl-bg-raised)",
        surface: "var(--rl-surface)",
        "surface-hover": "var(--rl-surface-hover)",
        "surface-elevated": "var(--rl-surface-elevated)",
        border: ({ opacityValue }) =>
          opacityValue !== undefined
            ? `rgb(var(--rl-border) / ${opacityValue})`
            : `rgb(var(--rl-border, 229 231 235))`,
        "border-light": "var(--rl-border-strong)",
        "border-strong": "var(--rl-border-strong)",
        muted: ({ opacityValue }) =>
          opacityValue !== undefined
            ? `rgb(var(--rl-muted) / ${opacityValue})`
            : `rgb(var(--rl-muted, 107 114 128))`,
        "muted-light": ({ opacityValue }) =>
          opacityValue !== undefined
            ? `rgb(var(--rl-muted-light) / ${opacityValue})`
            : `rgb(var(--rl-muted-light, 82 88 99))`,
        // Accent palette (keep same brand colors)
        accent: {
          blue: "#4F7CFF",
          purple: "#7C5CFF",
          cyan: "#06B6D4",
          green: "#22C55E",
          red: "#EF4444",
          orange: "#F59E0B",
          pink: "#EC4899",
        },
        severity: {
          critical: "#EF4444",
          high: "#F97316",
          medium: "#EAB308",
          low: "#3B82F6",
          info: "#6B7280",
        }
      },
      fontFamily: {
        sans: ['Inter', 'Plus Jakarta Sans', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      borderRadius: {
        'xl': '12px',
        '2xl': '16px',
        '3xl': '20px',
        '4xl': '24px',
      },
      backgroundImage: {
        'glass-gradient': 'linear-gradient(135deg, var(--rl-glass-a) 0%, var(--rl-glass-b) 100%)',
        'glass-hover': 'linear-gradient(135deg, var(--rl-glass-a) 0%, var(--rl-glass-b) 100%)',
        'accent-gradient': 'linear-gradient(135deg, #4F7CFF 0%, #7C5CFF 50%, #06B6D4 100%)',
        'accent-gradient-subtle': 'linear-gradient(135deg, rgba(79,124,255,0.08) 0%, rgba(124,92,255,0.08) 100%)',
        'card-glow-blue': 'linear-gradient(135deg, rgba(79,124,255,0.04) 0%, transparent 100%)',
        'card-glow-green': 'linear-gradient(135deg, rgba(34,197,94,0.04) 0%, transparent 100%)',
        'card-glow-purple': 'linear-gradient(135deg, rgba(124,92,255,0.04) 0%, transparent 100%)',
        'hero-gradient': 'linear-gradient(135deg, rgba(79,124,255,0.03) 0%, rgba(124,92,255,0.02) 50%, rgba(6,182,212,0.02) 100%)',
        'shimmer': 'linear-gradient(90deg, transparent 0%, rgba(0,0,0,0.03) 50%, transparent 100%)',
      },
      boxShadow: {
        'glass': 'var(--rl-shadow-glass)',
        'glass-sm': '0 1px 2px rgba(0,0,0,0.04)',
        'glass-lg': 'var(--rl-shadow-glass-lg)',
        'glow-blue': '0 0 16px rgba(79,124,255,0.15)',
        'card': 'var(--rl-shadow-glass)',
        'card-hover': 'var(--rl-shadow-glass-lg)',
        'elevated': '0 8px 24px rgba(0,0,0,0.08)',
      },
      backdropBlur: {
        'xs': '2px',
        'glass': '12px',
      },
      animation: {
        'fade-in': 'fadeIn 0.4s ease-out',
        'fade-in-fast': 'fadeIn 0.2s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'slide-down': 'slideDown 0.3s ease-out',
        'scale-in': 'scaleIn 0.3s ease-out',
        'pulse-slow': 'pulse 3s infinite',
        'shimmer': 'shimmer 2s infinite linear',
        'glow-pulse': 'glowPulse 2s infinite alternate',
        'float': 'float 6s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideDown: {
          '0%': { opacity: '0', transform: 'translateY(-8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        scaleIn: {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        shimmer: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(200%)' },
        },
        glowPulse: {
          '0%': { boxShadow: '0 0 8px rgba(79,124,255,0.15)' },
          '100%': { boxShadow: '0 0 20px rgba(79,124,255,0.25)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-8px)' },
        },
      },
    },
  },
  plugins: [],
}
