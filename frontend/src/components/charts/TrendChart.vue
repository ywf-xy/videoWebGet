<script setup lang="ts">
/**
 * 采集量趋势图（ECharts 按需引入，ARCHITECTURE §8.6）。
 * 柱 = 成功采集数，线 = 移动均值；tab 切换日 / 周 / 月，X 轴粒度由后端决定（小时 / 天 / 天）。
 */
import { BarChart, LineChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import EmptyState from '@/components/common/EmptyState.vue'
import type { TrendGranularity, TrendPoint } from '@/api/types'

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  CanvasRenderer,
])

const props = withDefaults(
  defineProps<{
    points: TrendPoint[]
    granularity: TrendGranularity
    loading?: boolean
    error?: boolean
  }>(),
  { loading: false, error: false },
)

const emit = defineEmits<{
  (event: 'update:granularity', value: TrendGranularity): void
  (event: 'retry'): void
}>()

type ChartInstance = ReturnType<typeof echarts.init>

const container = ref<HTMLDivElement | null>(null)
let chart: ChartInstance | null = null

const granularityModel = computed<TrendGranularity>({
  get: () => props.granularity,
  set: (value) => emit('update:granularity', value),
})

const hasData = computed(() => props.points.some((point) => point.count > 0))

const axisLabel = computed(() => {
  if (props.granularity === 'day') return '按小时'
  if (props.granularity === 'week') return '按天（本周）'
  return '按天（本月）'
})

/** 移动均值：日视图窗口 3，周/月窗口 7 */
function movingAverage(values: number[]): number[] {
  const windowSize = props.granularity === 'day' ? 3 : 7
  return values.map((_, index) => {
    const start = Math.max(0, index - windowSize + 1)
    const slice = values.slice(start, index + 1)
    const sum = slice.reduce((acc, item) => acc + item, 0)
    return Number((sum / slice.length).toFixed(2))
  })
}

function render(): void {
  if (!container.value) return
  if (!chart) chart = echarts.init(container.value)

  const labels = props.points.map((point) => point.label)
  const counts = props.points.map((point) => point.count)
  const averages = movingAverage(counts)

  // ECharts 配置结构复杂，这里使用宽松类型避免与 echarts 内部类型耦合
  const option: any = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { right: 0, top: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 12 } },
    grid: { left: 8, right: 8, top: 36, bottom: 4, containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e4e7ed' } },
      axisLabel: { color: '#909399', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#f0f2f5' } },
      axisLabel: { color: '#909399', fontSize: 11 },
    },
    series: [
      {
        name: '成功采集数',
        type: 'bar',
        data: counts,
        barMaxWidth: 22,
        itemStyle: { color: '#409eff', borderRadius: [3, 3, 0, 0] },
      },
      {
        name: '移动均值',
        type: 'line',
        data: averages,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#67c23a', width: 2 },
        itemStyle: { color: '#67c23a' },
      },
    ],
  }
  chart.setOption(option, true)
}

function handleResize(): void {
  chart?.resize()
}

watch(() => props.points, () => render(), { deep: true })

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
  <div class="trend-chart">
    <div class="card-title">
      <div class="card-title__left">
        <span>采集量趋势</span>
        <el-tag size="small" type="info" effect="plain">{{ axisLabel }}</el-tag>
      </div>
      <el-radio-group v-model="granularityModel" size="small">
        <el-radio-button value="day">日</el-radio-button>
        <el-radio-button value="week">周</el-radio-button>
        <el-radio-button value="month">月</el-radio-button>
      </el-radio-group>
    </div>

    <div v-loading="loading" class="trend-chart__body">
      <EmptyState
        v-if="error"
        compact
        icon="WarningFilled"
        title="趋势数据加载失败"
        description="请稍后重试，或检查后端服务是否正常"
        action-text="重试"
        @action="emit('retry')"
      />
      <EmptyState
        v-else-if="!hasData && !loading"
        compact
        icon="TrendCharts"
        title="还没有采集数据"
        description="去视频 / 文字 / 图片页发起一次采集，这里会出现趋势"
      />
      <div v-show="!error && (hasData || loading)" ref="container" class="trend-chart__canvas" />
    </div>
  </div>
</template>

<style scoped lang="scss">
.trend-chart {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.06);
  padding: 16px 20px;
  height: 100%;

  &__body {
    position: relative;
    min-height: 240px;
  }

  &__canvas {
    width: 100%;
    height: 240px;
  }
}
</style>
