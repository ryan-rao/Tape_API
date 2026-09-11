import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { host: '0.0.0.0', port: 5173 },
  build: {
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            antd: ['antd', '@ant-design/icons'],
            echarts: ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'],
          },
        },
      }, outDir: 'dist', sourcemap: false },
  test: {
    environment: 'jsdom',
    exclude: ["tests/e2e/**", "node_modules/**"],
    globals: true,
  },
});
