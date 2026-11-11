import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0c0f0d",
        panel: "#121714",
        line: "#242c27",
        accent: "#bbf36a",
      },
    },
  },
  plugins: [],
};

export default config;
