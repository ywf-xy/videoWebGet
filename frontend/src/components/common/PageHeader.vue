<script setup lang="ts">
/**
 * 页面标题栏：标题 + 副标题 + 右侧操作区插槽（PRD 6.1 布局：面包屑下方页面标题栏）。
 */
withDefaults(
  defineProps<{
    title: string
    description?: string
    /** 标题前图标（Element Plus 图标名） */
    icon?: string
  }>(),
  { description: '', icon: '' },
)
</script>

<template>
  <div class="page-header">
    <div class="page-header__main">
      <div class="page-header__title-row">
        <el-icon v-if="icon" class="page-header__icon"><component :is="icon" /></el-icon>
        <h2 class="page-header__title">{{ title }}</h2>
        <slot name="tag" />
      </div>
      <p v-if="description" class="page-header__desc">{{ description }}</p>
    </div>
    <div class="page-header__extra">
      <slot name="extra" />
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;

  &__main {
    min-width: 0;
  }

  &__title-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  &__icon {
    color: $color-primary;
    font-size: 20px;
  }

  &__title {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    line-height: 26px;
    color: $color-text-primary;
  }

  &__desc {
    margin: 4px 0 0;
    font-size: 13px;
    color: $color-text-secondary;
    line-height: 1.6;
  }

  &__extra {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }
}
</style>
