/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "#05080f",
        card: "#0b1324",
        cardSoft: "#111b2f",
        line: "#1f2f4d",
        accentBlue: "#2bc4ff",
        accentGreen: "#32d5a1",
      },
      borderRadius: {
        xl2: "0px",
      },
      boxShadow: {
        panel: "0 18px 60px rgba(0,0,0,0.45)",
      },
      backgroundImage: {
        "hero-grid":
          "radial-gradient(circle at 10% -10%, rgba(43,196,255,0.18), transparent 35%), radial-gradient(circle at 90% 0%, rgba(50,213,161,0.12), transparent 30%), linear-gradient(180deg, #060a13 0%, #04060d 100%)",
      },
    },
  },
  plugins: [],
};
