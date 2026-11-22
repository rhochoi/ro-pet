// Builds the /pro hero into one static script + stylesheet (no requests to other sites at runtime).
// npm ci && npx vite build   →   ../assets/ro-hero/ro-hero.js, ro-hero.css
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  define: { 'process.env.NODE_ENV': '"production"' },
  build: {
    outDir: '../assets/ro-hero',
    emptyOutDir: true,
    cssCodeSplit: false,
    lib: { entry: 'main.tsx', name: 'roHero', formats: ['iife'], fileName: () => 'ro-hero.js', cssFileName: 'ro-hero' },
  },
})
