<script setup lang="ts">
/**
 * 数据源健康度徽标（NFR-10）：≥80 绿 / 60-79 黄 / <60 红 / 无记录灰。
 * 纯展示组件，输入 0-100 或 null。
 */
import { computed } from 'vue'

import { HEALTH_LEVEL_MAP } from '@/utils/constants'
import { formatRatio } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    score?: number | null
    successRate?: number | null
    /** 是否在分数后追加「近 20 次成功率」 */
    showRate?: boolean
    /** 是否显示进度条 */
    showBar?: boolean
  }>(),
  { score: null, successRate: null, showRate: false, showBar: true },
)

const level = computed(() => {
  const score = props.score
  if (score === null || score === undefined) return 'unknown'
  if (score >= 80) return 'healthy'
  if (score >= 60) return 'sub_healthy'
  return 'unhealthy'
})

const meta = computed(() => HEALTH_LEVEL_MAP[level.value])

const scoreText = computed(() => (props.score === null || props.score === undefined ? '未知' : `${props.score}`))

const rateText = computed(() => {
  if (props.successRate === null || props.successRate === undefined) return '--'
  return formatRatio(props.successRate)
})

const barColor = computed(() => meta.value.color)
</script>

<template>
  <div class="health-badge">
    <div class="health-badge__row">
      <span class="health-badge__dot" :style="{ backgroundColor: meta.color }" />
      <span class="health-badge__score" :style="{ color: meta.color }">{{ scoreText }}</span>
      <span v-if="showRate" class="health-badge__rate text-secondary">
        {{ rateText }}
      </span>
    </div>
    <el-progress
      v-if="showBar"
      class="health-badge__bar"
      :percentage="score ?? 0"
      :color="barColor"
      :stroke-width="4"
      :show-text="false"
    />
  </div>
</template>

<style scoped lang="scss">
.health-badge {
  display: inline-flex;
  flex-direction: column;
  gap: 4px;
  min-width: 72px;

  &__row {
    display: flex;
    align-items: center;
    gap: 6px;
    line-height: 1;
  }

  &__dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  &__score {
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }

  &__rate {
    font-size: 12px;
  }

  &__bar {
    width: 100%;
  }
}
</style>
