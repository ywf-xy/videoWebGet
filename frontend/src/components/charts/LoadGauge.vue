<script setup lang="ts">
/**
 * 系统负载卡（ARCHITECTURE §8.6）：ECharts 双环形仪表（CPU / 内存）+ 线程占用进度条。
 * 数据来源 `/system/metrics`（3s 轮询，由 stores/app.ts 统一调度）。
 */
import { GaugeChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { formatBytes, formatPercent } from '@/utils/format'

echarts.use([GaugeChart, TooltipComponent, CanvasRenderer])

const props = withDefaults(
  defineProps<{
    cpu: number
    memoryPercent: number
    memoryUsed: number
    memoryTotal: number
    threadActive: number
    threadMax: number
    loading?: boolean
    error?: boolean
  }>(),
  { loading: false, error: false },
)

const emit = defineEmits<{ (event: 'retry'): void; (event: 'toggle-auto'): void }>()

type ChartInstance = ReturnType<typeof echarts.init>

const container = ref<HTMLDivElement | null>(null)
let chart: ChartInstance | null = null

const threadPercent = computed(() => {
  if (!props.threadMax) return 0
  return Math.min(100, Math.round((props.threadActive / props.threadMax) * 100))
})

const memoryText = computed(
  () => `${formatBytes(props.memoryUsed)} / ${formatBytes(props.memoryTotal)}`,
)

/** 环形仪表公共配置 */
function gaugeSeries(name: string, value: number, center: string, color: string) {
  return {
    type: 'gauge',
    center: [center, '52%'],
    radius: '82%',
    startAngle: 220,
    endAngle: -40,
    min: 0,
    max: 100,
    splitNumber: 4,
    progress: { show: true, width: 9, roundCap: true, itemStyle: { color } },
    axisLine: { lineStyle: { width: 9, color: [[1, '#eef0f4']] } },
    axisTick: { show: false },
    splitLine: { show: false },
    axisLabel: { show: false },
    pointer: { show: false },
    anchor: { show: false },
    title: {
      offsetCenter: [0, '76%'],
      fontSize: 12,
      color: '#909399',
    },
    detail: {
      offsetCenter: [0, '8%'],
      fontSize: 18,
      fontWeight: 600,
      color: '#303133',
      formatter: '{value}%',
    },
    data: [{ value: Number(value.toFixed(0)), name }],
  }
}

function render(): void {
  if (!container.value) return
  if (!chart) chart = echarts.init(container.value)
  const option: any = {
    tooltip: { show: false },
    series: [
      gaugeSeries('CPU', props.cpu, '27%', '#409eff'),
      gaugeSeries('内存', props.memoryPercent, '73%', '#67c23a'),
    ],
  }
  chart.setOption(option, true)
}

function handleResize(): void {
  chart?.resize()
}

watch(
  () => [props.cpu, props.memoryPercent],
  () => render(),
)

onMounted(() => {
  render()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="load-gauge card">
    <div class="card-title">
      <div class="card-title__left">
        <span>系统信息</span>
        <el-tag size="small" type="info" effect="plain">3s 自动刷新</el-tag>
      </div>
      <div class="flex-center gap-8">
        <el-button v-if="error" link type="primary" size="small" @click="emit('retry')">
          <el-icon><Refresh /></el-icon>
          重试
        </el-button>
        <el-button link size="small" @click="emit('toggle-auto')">切换自动刷新</el-button>
      </div>
    </div>

    <div v-loading="loading" class="load-gauge__body">
      <div v-if="error" class="load-gauge__error">
        <span class="load-gauge__error-text">--</span>
        <span class="text-secondary">指标获取失败，请确认后端已启动</span>
      </div>
      <div v-show="!error" ref="container" class="load-gauge__canvas" />

      <div class="load-gauge__thread">
        <div class="flex-between">
          <span class="text-secondary">活跃线程 / 上限</span>
          <span class="load-gauge__thread-value">
            {{ threadMax > 0 ? `${threadActive}/${threadMax}` : '--' }}
          </span>
        </div>
        <el-progress
          :percentage="threadPercent"
          :stroke-width="8"
          :show-text="false"
          :color="threadPercent >= 90 ? '#f56c6c' : threadPercent >= 60 ? '#e6a23c' : '#409eff'"
        />
        <div class="flex-between mt-8">
          <span class="text-secondary">内存</span>
          <span class="text-secondary">{{ memoryText }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.load-gauge {
  height: 100%;
  display: flex;
  flex-direction: column;

  &__body {
    flex: 1;
    display: flex;
    flex-direction: column;
  }

  &__canvas {
    width: 100%;
    height: 150px;
  }

  &__error {
    height: 150px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
  }

  &__error-text {
    font-size: 26px;
    font-weight: 600;
    color: $color-text-placeholder;
  }

  &__thread {
    margin-top: 4px;
  }

  &__thread-value {
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
}
</style>
