import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';

export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === 'single' ? [viteSingleFile()] : [])],
  /* Relative base: one build works from a Vercel root, from GitHub Pages'
     /<repo>/deck/ subpath, and from `npx serve dist`. No env-specific config. */
  base: './',
  /* 5173 is the kiosk. The deck must never fight the thing it is demoing. */
  server: { port: 5174 },
  build: {
    outDir: 'dist',
    /* In single-file mode the three woff2 files must inline as base64. */
    assetsInlineLimit: mode === 'single' ? 1_000_000 : 4096,
  },
}));
