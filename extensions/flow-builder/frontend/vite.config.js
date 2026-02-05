import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  build: {
    // Output to Uderia's static folder
    outDir: path.resolve(__dirname, '../../../static/js/flowBuilder/dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'src/main.jsx'),
      output: {
        entryFileNames: 'flowBuilder.bundle.js',
        chunkFileNames: 'flowBuilder.[name].js',
        assetFileNames: 'flowBuilder.[name].[ext]',
        // Single bundle for lazy loading
        manualChunks: undefined
      }
    },
    // Inline assets to avoid additional file requests
    assetsInlineLimit: 100000
  },
  define: {
    // Make env vars available
    'process.env': {}
  },
  server: {
    port: 5173,
    // Proxy API requests to Flow Builder backend
    proxy: {
      '/api/v1/flows': {
        target: 'http://localhost:5051',
        changeOrigin: true
      },
      '/api/v1/flow-': {
        target: 'http://localhost:5051',
        changeOrigin: true
      }
    }
  }
});
