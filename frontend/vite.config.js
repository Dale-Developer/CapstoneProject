import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import basicSsl from '@vitejs/plugin-basic-ssl'

export default defineConfig({
  plugins: [react(), tailwindcss(), basicSsl()],
  server: {
    host: '0.0.0.0',
    https: true,
    proxy: {
      '/api': {
        target: 'http://192.168.1.20:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
