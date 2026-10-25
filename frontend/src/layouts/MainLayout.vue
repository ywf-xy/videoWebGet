<script setup lang="ts">
/**
 * 主布局（ARCHITECTURE §8.2）：左侧固定导航（可折叠）+ 顶部面包屑 / 全局搜索 / 线程占用 + 内容区。
 * 负责：3s 系统指标轮询的生命周期、后端不可达红条、页面隐藏时暂停轮询。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchHealthCheck } from '@/api/system'
import { useAppStore } from '@/stores/app'
import { CONTENT_TYPE_MAP, MENU_ITEMS } from '@/utils/constants'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()

const searchKeyword = ref('')

/** 侧栏折叠状态跟随 store（持久化在 localStorage） */
const collapsed = computed(() => appStore.sidebarCollapsed)

/** 当前高亮菜单：内容类路由统一映射到 /content/{type} */
const activeMenu = computed(() => {
  const type = route.params.type as string | undefined
  if (type && CONTENT_TYPE_MAP[type]) return CONTENT_TYPE_MAP[type].route
  if (route.name === 'visual-create') return '/data-sources'
  return route.path
})

interface Crumb {
  label: string
  to?: string
}

/** 面包屑（PRD 6.1：内容页两级：视频 / 数据源名） */
const breadcrumbs = computed<Crumb[]>(() => {
  const type = route.params.type as string | undefined
  const typeMeta = type ? CONTENT_TYPE_MAP[type] : undefined
  switch (route.name) {
    case 'dashboard':
      return [{ label: '首页' }]
    case 'content-list':
      return [{ label: typeMeta?.label ?? '内容' }]
    case 'workbench':
      return [
        { label: typeMeta?.label ?? '内容', to: typeMeta?.route },
        { label: '采集工作页' },
      ]
    case 'artifacts':
      return [{ label: '产物' }]
    case 'data-sources':
      return [{ label: '数据源' }]
    case 'visual-create':
      return [{ label: '数据源', to: '/data-sources' }, { label: '可视化创建' }]
    case 'settings':
      return [{ label: '设置' }]
    default:
      return [{ label: (route.meta.title as string) ?? '页面' }]
  }
})

/** 自动刷新开关（PRD P0-04③：关闭后停止所有指标轮询） */
const autoRefresh = computed({
  get: () => appStore.autoRefresh,
  set: (value: boolean) => appStore.setAutoRefresh(value),
})

function handleSearch(): void {
  const keyword = searchKeyword.value.trim()
  router.push({ name: 'data-sources', query: keyword ? { keyword } : {} })
}

/** 离线红条「重新连接」：请求 /health，成功后拦截器会自动恢复在线态 */
async function handleReconnect(): Promise<void> {
  try {
    await fetchHealthCheck()
  } catch {
    // 仍然不可达：拦截器已提示，红条保持
  }
}

function handleVisibility(): void {
  appStore.handleVisibility()
}

// 路由切换时清空搜索框（避免误解为当前页筛选）
watch(
  () => route.fullPath,
  () => {
    searchKeyword.value = ''
  },
)

onMounted(() => {
  appStore.startPolling()
  document.addEventListener('visibilitychange', handleVisibility)
})

onBeforeUnmount(() => {
  appStore.stopPolling()
  document.removeEventListener('visibilitychange', handleVisibility)
})
</script>

<template>
  <div class="layout" :class="{ 'layout--collapsed': collapsed }">
    <aside class="layout__aside">
      <div class="layout__logo" @click="router.push('/')">
        <el-icon :size="22"><Cpu /></el-icon>
        <span v-show="!collapsed" class="layout__logo-text">CrawlerHub</span>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="collapsed"
        :collapse-transition="false"
        router
        class="layout__menu"
        background-color="#1f2d3d"
        text-color="#bfcbd9"
        active-text-color="#ffffff"
      >
        <el-menu-item v-for="item in MENU_ITEMS" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.label }}</template>
        </el-menu-item>
      </el-menu>

      <div v-show="!collapsed" class="layout__aside-footer">
        <span class="text-secondary">线程占用</span>
        <strong>{{ appStore.threadText }}</strong>
      </div>
    </aside>

    <div class="layout__body">
      <header class="layout__header">
        <div class="layout__header-left">
          <el-button text circle @click="appStore.toggleSidebar()">
            <el-icon :size="18">
              <Fold v-if="!collapsed" />
              <Expand v-else />
            </el-icon>
          </el-button>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item v-for="(crumb, index) in breadcrumbs" :key="index" :to="crumb.to">
              {{ crumb.label }}
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="layout__header-right">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索数据源名称或地址"
            clearable
            class="layout__search"
            @keyup.enter="handleSearch"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>

          <el-tooltip content="当前活跃线程 / 最大线程" placement="bottom">
            <el-tag type="info" effect="plain" class="layout__thread-tag">
              <el-icon><Odometer /></el-icon>
              <span class="layout__thread-text">{{ appStore.threadText }}</span>
            </el-tag>
          </el-tooltip>

          <el-switch
            v-model="autoRefresh"
            size="small"
            active-text="自动刷新"
            inline-prompt
            style="--el-switch-on-color: #409eff"
          />
        </div>
      </header>

      <el-alert v-if="!appStore.online" type="error" :closable="false" class="layout__offline">
        <template #title>
          <span>服务连接失败，请确认后端已启动（http://127.0.0.1:8000）</span>
          <el-button link type="primary" size="small" @click="handleReconnect">重新连接</el-button>
        </template>
      </el-alert>

      <main class="layout__content">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;

  &__aside {
    width: $sidebar-width;
    flex-shrink: 0;
    background: $color-bg-aside;
    display: flex;
    flex-direction: column;
    transition: width 0.2s ease;
    overflow: hidden;
  }

  &--collapsed &__aside {
    width: $sidebar-width-collapsed;
  }

  &__logo {
    height: $header-height;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 20px;
    color: #fff;
    font-size: 16px;
    font-weight: 600;
    letter-spacing: 0.5px;
    cursor: pointer;
    flex-shrink: 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  }

  &__logo-text {
    white-space: nowrap;
  }

  &__menu {
    flex: 1;
    border-right: none;
    overflow-y: auto;
    overflow-x: hidden;

    :deep(.el-menu-item.is-active) {
      background-color: $color-primary !important;
    }

    :deep(.el-menu-item:hover) {
      background-color: $color-bg-aside-hover !important;
    }
  }

  &__aside-footer {
    padding: 12px 20px;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    color: #fff;
    font-size: 12px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
  }

  &__body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  &__header {
    height: $header-height;
    flex-shrink: 0;
    background: $color-bg-card;
    border-bottom: 1px solid $color-border-light;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px 0 8px;
    gap: 16px;
  }

  &__header-left {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  &__header-right {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
  }

  &__search {
    width: 220px;
  }

  &__thread-tag {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-variant-numeric: tabular-nums;
  }

  &__thread-text {
    margin-left: 4px;
  }

  &__offline {
    border-radius: 0;
    flex-shrink: 0;
  }

  &__content {
    flex: 1;
    overflow-y: auto;
    background: $color-bg-page;
  }
}

@media (max-width: 1366px) {
  .layout__search {
    width: 160px;
  }
}
</style>
