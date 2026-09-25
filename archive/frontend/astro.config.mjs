import { defineConfig } from 'astro/config';
import react from '@astrojs/react';

export default defineConfig({
  integrations: [react()],
  output: 'static',
  outDir: '../docs',
  vite: {
    define: {
      'process.env.API_URL': JSON.stringify(
        process.env.FRONTEND_API_URL || 'http://localhost:8001'
      ),
    },
  },
});
