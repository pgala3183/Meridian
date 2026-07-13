import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#07131F",
          soft: "#0F2233",
          mist: "#1A3347",
        },
        fog: "#D7E2EA",
        brass: {
          DEFAULT: "#C8924A",
          bright: "#E0A85C",
        },
        sea: "#3F8F8A",
      },
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
      backgroundImage: {
        meridian:
          "radial-gradient(ellipse 80% 50% at 50% -10%, rgba(63,143,138,0.28), transparent)," +
          "radial-gradient(ellipse 60% 40% at 100% 0%, rgba(200,146,74,0.12), transparent)," +
          "linear-gradient(160deg, #07131F 0%, #0B1C2C 45%, #102636 100%)",
        grid:
          "linear-gradient(rgba(215,226,234,0.05) 1px, transparent 1px)," +
          "linear-gradient(90deg, rgba(215,226,234,0.05) 1px, transparent 1px)",
      },
      backgroundSize: {
        grid: "48px 48px",
      },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseGlow: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(63,143,138,0.35)" },
          "50%": { boxShadow: "0 0 0 10px rgba(63,143,138,0)" },
        },
        stageIn: {
          "0%": { opacity: "0.35", transform: "scale(0.98)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
      },
      animation: {
        rise: "rise 0.7s ease-out both",
        "pulse-glow": "pulseGlow 2s ease-in-out infinite",
        "stage-in": "stageIn 0.45s ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
