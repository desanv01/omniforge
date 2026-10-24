import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// One fixed loopback upstream: browser input cannot redirect bearer credentials.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1', port: 64110, strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:64111', changeOrigin: false } },
    fs: { allow: ['../..'] },
  },
  preview: { host: '127.0.0.1', port: 64110, strictPort: true },
});
