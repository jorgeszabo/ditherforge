import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';

export default defineConfig({
  plugins: [svelte(), tailwindcss()],
  resolve: { alias: { $lib: path.resolve('src/lib') } },
  build: { outDir: 'hybrid-dist', rollupOptions: { input: path.resolve('hybrid.html') } },
});
