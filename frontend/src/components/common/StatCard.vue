<script setup lang="ts">
/**
 * 指标卡（首页 4 列）：值 / 单位 / 图标 / 加载态 / 失败降级（显示「--」+ 重试）。
 * 失败时不影响其他卡片（ARCHITECTURE §8.3 单卡失败置 null）。
 */
withDefaults(
  defineProps<{
    label: string
    value?: string | number | null
    suffix?: string
    icon?: string
    color?: string
    loading?: boolean
    error?: boolean
    /** 底部补充说明 */
    hint?: string
    clickable?: boolean
  }>(),
  {
    value: null,
    suffix: '',
    icon: 'DataLine',
    color: '#409eff',
    loading: false,
    error: false,
    hint: '',
    clickable: false,
  },
)

const emit = defineEmits<{ (event: 'click'): void; (event: 'retry'): void }>()

function handleClick(): void {
  emit('click')
}
</script>

<template>
  <div
    class="stat-card"
    :class="{ 'stat-card--clickable': clickable }"
    :style="{ '--stat-color': color }"
    @click="clickable ? handleClick() : undefined"
  >
    <div class="stat-card__head">
      <span class="stat-card__label">{{ label }}</span>
      <span class="stat-card__icon">
        <el-icon :size="18"><component :is="icon" /></el-icon>
      </span>
    </div>

    <div class="stat-card__body">
      <template v-if="loading">
        <el-skeleton :rows="0" animated style="width: 60%">
          <template #template>
            <el-skeleton-item variant="h1" style="height: 28px" />
          </template>
        </el-skeleton>
      </template>
      <template v-else-if="error">
        <span class="stat-card__value stat-card__value--empty">--</span>
        <el-button class="stat-card__retry" link type="primary" @click.stop="emit('retry')">
          <el-icon><Refresh /></el-icon>
          重试
        </el-button>
      </template>
      <template v-else>
        <span class="stat-card__value">{{ value ?? '--' }}</span>
        <span v-if="suffix" class="stat-card__suffix">{{ suffix }}</span>
      </template>
    </div>

    <p v-if="hint" class="stat-card__hint">{{ hint }}</p>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.stat-card {
  background: $color-bg-card;
  border-radius: $radius-card;
  box-shadow: $shadow-card;
  padding: 16px 18px;
  border-left: 3px solid var(--stat-color, #{$color-primary});
  transition:
    box-shadow 0.2s ease,
    transform 0.2s ease;
  height: 100%;

  &--clickable {
    cursor: pointer;

    &:hover {
      box-shadow: $shadow-hover;
      transform: translateY(-2px);
    }
  }

  &__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
  }

  &__label {
    font-size: 13px;
    color: $color-text-secondary;
  }

  &__icon {
    width: 30px;
    height: 30px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--stat-color, #{$color-primary});
    background: color-mix(in srgb, var(--stat-color, #{$color-primary}) 12%, #ffffff);
  }

  &__body {
    display: flex;
    align-items: baseline;
    gap: 6px;
    min-height: 34px;
  }

  &__value {
    font-size: 26px;
    font-weight: 600;
    line-height: 1.2;
    color: $color-text-primary;
    font-variant-numeric: tabular-nums;

    &--empty {
      color: $color-text-placeholder;
    }
  }

  &__suffix {
    font-size: 13px;
    color: $color-text-secondary;
  }

  &__retry {
    font-size: 12px;
    padding: 0;
  }

  &__hint {
    margin: 6px 0 0;
    font-size: 12px;
    color: $color-text-secondary;
  }
}
</style>
