import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

/**
 * Vite 配置（ARCHITECTURE §8.4 / T12）。
 * - dev：5173 端口，`/api` 代理到后端 127.0.0.1:8000；
 * - build：产物输出 dist/，由后端单端口 8000 静态托管；
 * - manualChunks：element-plus / echarts / vendor 三段拆分，单 chunk 控制在 800KB 以下。
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        /**
         * 分包策略（T12 验收⑤ / 单 chunk ≤ 800KB）：
         * - `@element-plus/icons-vue` 单独成块（图标不反向依赖 EP 组件，拆出后不产生循环 chunk）；
         * - element-plus 组件库独立成块，与业务代码分离；
         * - echarts 独立（仅首页使用，其余页面按需懒加载）；
         * - 其余三方库合并进 vendor。
         */
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('@element-plus/icons-vue')) return 'ep-icons'
          if (id.includes('element-plus') || id.includes('@element-plus')) return 'element-plus'
          if (id.includes('echarts') || id.includes('zrender')) return 'echarts'
          return 'vendor'
        },
      },
    },
  },
})
