<script setup lang="ts">
/** 404 页（路由 `/:pathMatch(.*)*`）。 */
import { useRouter } from 'vue-router'

import EmptyState from '@/components/common/EmptyState.vue'

const router = useRouter()
</script>

<template>
  <div class="page not-found">
    <el-result icon="warning" title="404" sub-title="抱歉，你访问的页面不存在或已被移除">
      <template #extra>
        <el-button type="primary" @click="router.push('/')">返回首页</el-button>
        <el-button @click="router.back()">返回上一页</el-button>
      </template>
    </el-result>
    <EmptyState
      compact
      icon="Compass"
      title="也可以从左侧导航继续操作"
      description="首页 / 视频 / 文字 / 图片 / 产物 / 数据源 / 设置"
    />
  </div>
</template>

<style scoped>
.not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 70vh;
}
</style>
