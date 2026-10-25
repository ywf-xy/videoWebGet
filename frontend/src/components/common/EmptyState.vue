<script setup lang="ts">
/**
 * 空态三件套（PRD 6.1 空态规范）：插画 + 一句说明 + 主操作按钮。
 * 组件只负责展示，按钮点击通过 slot / emit 交回业务页。
 */
withDefaults(
  defineProps<{
    title?: string
    description?: string
    icon?: string
    /** 主操作按钮文案（传空则不显示按钮，改用 actions 插槽） */
    actionText?: string
    /** 紧凑模式（表格内空态用，高度更小） */
    compact?: boolean
  }>(),
  {
    title: '暂无数据',
    description: '',
    icon: 'Box',
    actionText: '',
    compact: false,
  },
)

const emit = defineEmits<{ (event: 'action'): void }>()
</script>

<template>
  <div class="empty-state" :class="{ 'empty-state--compact': compact }">
    <div class="empty-state__illustration">
      <el-icon :size="compact ? 28 : 44"><component :is="icon" /></el-icon>
    </div>
    <p class="empty-state__title">{{ title }}</p>
    <p v-if="description" class="empty-state__desc">{{ description }}</p>
    <div v-if="$slots.actions || actionText" class="empty-state__actions">
      <slot name="actions">
        <el-button type="primary" plain @click="emit('action')">{{ actionText }}</el-button>
      </slot>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 48px 16px;
  text-align: center;

  &--compact {
    padding: 20px 12px;
    gap: 6px;
  }

  &__illustration {
    width: 84px;
    height: 84px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #eef3ff 0%, #f6f8fb 100%);
    color: $color-primary;
    margin-bottom: 4px;
  }

  &--compact &__illustration {
    width: 52px;
    height: 52px;
  }

  &__title {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: $color-text-regular;
  }

  &__desc {
    margin: 0;
    font-size: 13px;
    color: $color-text-secondary;
    max-width: 420px;
    line-height: 1.6;
  }

  &__actions {
    margin-top: 6px;
    display: flex;
    gap: 8px;
  }
}
</style>
