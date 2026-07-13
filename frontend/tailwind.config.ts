import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "hsl(222 47% 6%)",
        foreground: "hsl(210 40% 96%)",
        muted: "hsl(222 30% 18%)",
        accent: { DEFAULT: "hsl(189 90% 55%)", violet: "hsl(265 90% 65%)" },
        card: "hsl(222 47% 9%)",
        border: "hsl(222 30% 22%)",
      },
      fontFamily: { mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
export default config;
