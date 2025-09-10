import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,                     // permet l'accès externe
    port: 5173,                     // ton port dev
    allowedHosts: [
      'dev.srv539174.hstgr.cloud',  // ton domaine
      'localhost',                  // garde localhost
    ]
  }
})