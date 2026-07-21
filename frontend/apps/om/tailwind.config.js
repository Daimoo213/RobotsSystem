/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{ts,tsx}', '../../packages/ui/src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: { cyan: { DEFAULT: '#2FD7FF' }, bg: { DEFAULT: '#050B13' } },
      fontFamily: { sans: ['"PingFang SC"', 'sans-serif'], mono: ['"Fira Code"', 'monospace'] },
    },
  },
  plugins: [],
};
