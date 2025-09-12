/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'IBM Plex Sans'", "sans-serif"],
      },
      colors: {
        'cds-background': '#f4f4f4',
        'cds-layer': '#ffffff',
        'cds-layer-hover': '#f4f4f4',
        'cds-border': '#e0e0e0',
        'cds-text': '#161616',
        'cds-interactive': '#0f62fe',
        'cds-interactive-hover': '#0043ce',
      },
    },
  },
  plugins: [],
}
