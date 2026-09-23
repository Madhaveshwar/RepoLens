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
        // Premium light palette
        background: "#FAFAFA",
        "background-elevated": "#F3F4F6",
        "background-raised": "#EEF0F3",
        surface: "#FFFFFF",
        "surface-hover": "#F8F9FB",
        "surface-elevated": "#F0F2F5",
        border: "#E5E7EB",
        "border-light": "#D1D5DB",
        muted: "#9CA3AF",
        "muted-light": "#6B7280",
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
        'glass-gradient': 'linear-gradient(135deg, rgba(255,255,255,0.9) 0%, rgba(255,255,255,0.7) 100%)',
        'glass-hover': 'linear-gradient(135deg, rgba(255,255,255,1) 0%, rgba(255,255,255,0.85) 100%)',
        'accent-gradient': 'linear-gradient(135deg, #4F7CFF 0%, #7C5CFF 50%, #06B6D4 100%)',
        'accent-gradient-subtle': 'linear-gradient(135deg, rgba(79,124,255,0.08) 0%, rgba(124,92,255,0.08) 100%)',
        'card-glow-blue': 'linear-gradient(135deg, rgba(79,124,255,0.04) 0%, transparent 100%)',
        'card-glow-green': 'linear-gradient(135deg, rgba(34,197,94,0.04) 0%, transparent 100%)',
        'card-glow-purple': 'linear-gradient(135deg, rgba(124,92,255,0.04) 0%, transparent 100%)',
        'hero-gradient': 'linear-gradient(135deg, rgba(79,124,255,0.03) 0%, rgba(124,92,255,0.02) 50%, rgba(6,182,212,0.02) 100%)',
        'shimmer': 'linear-gradient(90deg, transparent 0%, rgba(0,0,0,0.03) 50%, transparent 100%)',
      },
      boxShadow: {
        'glass': '0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03)',
        'glass-sm': '0 1px 2px rgba(0,0,0,0.04)',
        'glass-lg': '0 4px 16px rgba(0,0,0,0.06), 0 2px 8px rgba(0,0,0,0.04)',
        'glow-blue': '0 0 16px rgba(79,124,255,0.15)',
        'card': '0 1px 3px rgba(0,0,0,0.06)',
        'card-hover': '0 4px 12px rgba(0,0,0,0.08)',
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
