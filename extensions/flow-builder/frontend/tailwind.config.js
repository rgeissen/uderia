/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Uderia color system
        'uderia': {
          'bg': '#0f0f0f',
          'panel': 'rgba(17, 24, 39, 0.8)',
          'border': 'rgba(255, 255, 255, 0.1)',
          'orange': '#F15F22',
          'orange-light': '#ff7f45',
        },
        // Profile type colors
        'profile': {
          'tool': '#9333ea',      // Purple - tool_enabled
          'llm': '#4ade80',       // Green - llm_only
          'rag': '#3b82f6',       // Blue - rag_focused
          'genie': '#F15F22',     // Orange - genie
        },
        // Node state colors
        'node': {
          'pending': '#6b7280',   // Gray
          'running': '#f59e0b',   // Amber
          'success': '#10b981',   // Emerald
          'error': '#ef4444',     // Red
          'condition': '#06b6d4', // Cyan
        }
      },
      backdropBlur: {
        'glass': '12px',
      },
      animation: {
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 1.5s ease-in-out infinite alternate',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px currentColor, 0 0 10px currentColor' },
          '100%': { boxShadow: '0 0 10px currentColor, 0 0 20px currentColor' },
        }
      }
    },
  },
  plugins: [],
}
