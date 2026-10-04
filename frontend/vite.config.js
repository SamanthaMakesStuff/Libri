import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Build → frontend/dist. Served two ways:
//   • single-origin: FastAPI serves dist/index.html and mounts /assets (VITE_API_BASE unset)
//   • split: deploy this folder to Vercel, set VITE_API_BASE to the backend URL
export default defineConfig({
  plugins: [react()],
  server: {
    // `npm run dev` proxies API/auth calls to the local FastAPI so the dev
    // server and backend behave like one origin.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/auth': 'http://127.0.0.1:8000',
    },
  },
});
