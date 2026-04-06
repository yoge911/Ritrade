import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8083',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8083',
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
