<script setup lang="ts">
/**
 * 应用根组件：只承载路由出口。
 * 布局（侧边栏 / 面包屑 / 全局错误条）由 MainLayout.vue 通过路由父级提供（ARCHITECTURE §8.2）。
 */
</script>

<template>
  <router-view />
</template>
