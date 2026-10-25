import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

import MainLayout from '@/layouts/MainLayout.vue'

/**
 * 路由表（ARCHITECTURE §8.1，8 条路由，全部懒加载）。
 * 视频 / 文字 / 图片三套页面共用 ContentListView 与 WorkbenchView，由 `:type` 区分。
 */
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: MainLayout,
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '首页', order: 1 },
      },
      {
        path: 'content/:type(video|text|image)',
        name: 'content-list',
        component: () => import('@/views/ContentListView.vue'),
        meta: { title: '内容列表', order: 2, menuKey: 'content' },
      },
      {
        path: 'content/:type(video|text|image)/:id(\\d+)/workbench',
        name: 'workbench',
        component: () => import('@/views/WorkbenchView.vue'),
        meta: { title: '采集工作页', parent: 'content-list' },
      },
      {
        path: 'artifacts',
        name: 'artifacts',
        component: () => import('@/views/ArtifactView.vue'),
        meta: { title: '产物', order: 5 },
      },
      {
        path: 'data-sources',
        name: 'data-sources',
        component: () => import('@/views/DataSourceView.vue'),
        meta: { title: '数据源', order: 6 },
      },
      {
        path: 'data-sources/visual-create',
        name: 'visual-create',
        component: () => import('@/views/VisualCreateView.vue'),
        meta: { title: '可视化创建', order: 7 },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingView.vue'),
        meta: { title: '设置', order: 8 },
      },
      {
        path: ':pathMatch(.*)*',
        name: 'not-found',
        component: () => import('@/views/NotFoundView.vue'),
        meta: { title: '页面不存在' },
      },
    ],
  },
]

const router = createRouter({
  /**
   * 使用 hash 模式：后端以 StaticFiles(html=True) 单端口托管 dist，未提供
   * 「未知路径 → index.html」的 SPA fallback（`/artifacts` 直连会 404）。
   * hash 模式下服务端路径恒为 `/`，因此刷新/深链在任何端口都可用。
   */
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  const title = (to.meta.title as string | undefined) ?? 'CrawlerHub'
  document.title = `${title} · CrawlerHub`
})

export default router
