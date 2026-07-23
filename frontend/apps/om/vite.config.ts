import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@robots/ui': resolve(__dirname, '../../packages/ui/src'),
      '@robots/three-scene': resolve(__dirname, '../../packages/three-scene/src'),
      '@robots/api-client': resolve(__dirname, '../../packages/api-client/src'),
      '@robots/shared-types': resolve(__dirname, '../../packages/shared-types/src'),
      '@robots/utils': resolve(__dirname, '../../packages/utils/src'),
    },
  },
  server: {
    port: 5174,
    host: '0.0.0.0',
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
});
