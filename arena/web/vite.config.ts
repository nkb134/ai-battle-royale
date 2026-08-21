import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Pages serves a project site from /<repo>/, so assets must be requested from there.
// Overridable for local preview and for a future custom domain.
const base = process.env.ARENA_BASE ?? '/ai-battle-royale/'

export default defineConfig({
  base,
  plugins: [react()],
  build: { outDir: 'dist', sourcemap: true },
})
