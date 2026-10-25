<script setup lang="ts">
/**
 * 首页看板（PRD 6.2 / T15）。
 *
 * 布局：4 指标卡 → 趋势 + 系统信息 → 运行中批次 → 数据源健康度。
 * 降级：`/overview` 失败时指标卡显示「--」+ 重试，不影响趋势与健康度两卡。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { pauseBatch, resumeBatch } from '@/api/batch'
import LoadGauge from '@/components/charts/LoadGauge.vue'
import TrendChart from '@/components/charts/TrendChart.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import HealthBadge from '@/components/common/HealthBadge.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import StatCard from '@/components/common/StatCard.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { type TrendGranularity } from '@/api/types'
import { useAppStore } from '@/stores/app'
import { useDashboardStore } from '@/stores/dashboard'
import { CONTENT_TYPE_MAP, STRATEGY_MAP } from '@/utils/constants'
import { formatDateTime, formatDuration, formatNumber, formatRatio } from '@/utils/format'

const router = useRouter()
const appStore = useAppStore()
const dashboard = useDashboardStore()

const actionLoading = ref<number | null>(null)
let overviewTimer: number | null = null

const overview = computed(() => dashboard.overview)
const healthyText = computed(() => {
  if (!overview.value) return '--'
  return `${overview.value.health.healthy}`
})
const totalText = computed(() => (overview.value ? `/${overview.value.health.total}` : ''))

const hasAnySource = computed(() => (overview.value?.health.total ?? 0) > 0)

const strategyLabel = (value: string): string =>
  STRATEGY_MAP.find((item) => item.value === value)?.label ?? value

const typeLabel = (value: string | null): string =>
  value && CONTENT_TYPE_MAP[value] ? CONTENT_TYPE_MAP[value].label : '--'

function startOverviewTimer(): void {
  stopOverviewTimer()
  if (!appStore.autoRefresh) return
  overviewTimer = window.setInterval(() => {
    if (document.hidden) return
    void dashboard.loadOverview()
  }, 5000)
}

function stopOverviewTimer(): void {
  if (overviewTimer !== null) {
    window.clearInterval(overviewTimer)
    overviewTimer = null
  }
}

function handleGranularity(value: TrendGranularity): void {
  void dashboard.loadTrend(value)
}

function goSource(): void {
  router.push('/data-sources')
}

function goWorkbench(batch: { data_source_id: number; data_source_type: string | null }): void {
  const type = batch.data_source_type ?? 'video'
  router.push({ name: 'workbench', params: { type, id: batch.data_source_id } })
}

async function handlePause(batchId: number): Promise<void> {
  actionLoading.value = batchId
  try {
    await pauseBatch(batchId)
    ElMessage.success('已请求暂停，运行中的任务会在当前步骤结束后停止')
    await dashboard.loadOverview()
  } finally {
    actionLoading.value = null
  }
}

async function handleResume(batchId: number): Promise<void> {
  actionLoading.value = batchId
  try {
    await resumeBatch(batchId)
    ElMessage.success('已恢复采集')
    await dashboard.loadOverview()
  } finally {
    actionLoading.value = null
  }
}

async function handleHealthSort({ order }: { order: string | null }): Promise<void> {
  await dashboard.loadHealth(order === 'descending' ? 'desc' : 'asc')
}

function handleToggleAuto(): void {
  appStore.setAutoRefresh(!appStore.autoRefresh)
  ElMessage.info(appStore.autoRefresh ? '已开启自动刷新' : '已关闭自动刷新')
}

watch(
  () => appStore.autoRefresh,
  () => startOverviewTimer(),
)

onMounted(async () => {
  await dashboard.loadAll()
  startOverviewTimer()
})

onBeforeUnmount(() => {
  stopOverviewTimer()
})

/** 供模板使用的暂停二次确认（避免误操作） */
async function confirmPause(batchId: number): Promise<void> {
  try {
    await ElMessageBox.confirm('暂停后不再领取新任务，运行中的任务会在当前步骤结束后停止。', '暂停采集', {
      type: 'warning',
      confirmButtonText: '暂停',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await handlePause(batchId)
}
</script>

<template>
  <div class="page dashboard">
    <PageHeader title="首页概览" description="数据源健康度、采集量与系统负载一屏掌握" icon="Odometer">
      <template #extra>
        <el-button :loading="dashboard.loading" @click="dashboard.loadAll()">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="overview && !hasAnySource"
      class="mb-16"
      type="info"
      :closable="false"
      show-icon
      title="还没有数据源"
      description="先去数据源页添加第一个数据源，然后到视频 / 文字 / 图片页发起采集。"
    >
      <template #default>
        <el-button type="primary" size="small" @click="goSource">去添加数据源</el-button>
      </template>
    </el-alert>

    <!-- 4 指标卡 -->
    <el-row :gutter="16">
      <el-col :xs="24" :sm="12" :md="6">
        <StatCard
          label="健康数据源"
          :value="healthyText"
          :suffix="totalText"
          icon="CircleCheck"
          color="#67c23a"
          :loading="dashboard.loading && !overview"
          :error="dashboard.overviewError"
          hint="健康分 ≥ 80 视为健康"
          clickable
          @click="goSource"
          @retry="dashboard.loadOverview()"
        />
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <StatCard
          label="今日采集量"
          :value="overview ? formatNumber(overview.today) : null"
          suffix="条"
          icon="Sunny"
          color="#409eff"
          :loading="dashboard.loading && !overview"
          :error="dashboard.overviewError"
          hint="按任务成功数统计"
          clickable
          @click="router.push('/artifacts')"
          @retry="dashboard.loadOverview()"
        />
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <StatCard
          label="本周采集量"
          :value="overview ? formatNumber(overview.week) : null"
          suffix="条"
          icon="Calendar"
          color="#e6a23c"
          :loading="dashboard.loading && !overview"
          :error="dashboard.overviewError"
          hint="自然周（周一起）"
          clickable
          @click="router.push('/artifacts')"
          @retry="dashboard.loadOverview()"
        />
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <StatCard
          label="本月采集量"
          :value="overview ? formatNumber(overview.month) : null"
          suffix="条"
          icon="TrendCharts"
          color="#909399"
          :loading="dashboard.loading && !overview"
          :error="dashboard.overviewError"
          hint="自然月起算"
          clickable
          @click="router.push('/artifacts')"
          @retry="dashboard.loadOverview()"
        />
      </el-col>
    </el-row>

    <!-- 趋势 + 系统信息 -->
    <el-row :gutter="16" class="mt-16">
      <el-col :xs="24" :md="16">
        <TrendChart
          :points="dashboard.trend?.points ?? []"
          :granularity="dashboard.granularity"
          :loading="dashboard.trendLoading"
          :error="dashboard.trendError"
          @update:granularity="handleGranularity"
          @retry="dashboard.loadTrend()"
        />
      </el-col>
      <el-col :xs="24" :md="8">
        <LoadGauge
          :cpu="appStore.cpuPercent"
          :memory-percent="appStore.memory.percent"
          :memory-used="appStore.memory.used"
          :memory-total="appStore.memory.total"
          :thread-active="appStore.threads.active"
          :thread-max="appStore.threads.max"
          :loading="appStore.metricsLoading && !appStore.threads.max"
          :error="appStore.metricsError"
          @retry="appStore.fetchOnce()"
          @toggle-auto="handleToggleAuto"
        />
      </el-col>
    </el-row>

    <!-- 运行中批次 -->
    <div class="card mt-16">
      <div class="card-title">
        <div class="card-title__left">
          <span>运行中的任务</span>
          <el-tag size="small" type="info" effect="plain">
            {{ overview?.running.length ?? 0 }} 个批次
          </el-tag>
        </div>
        <el-button link type="primary" size="small" @click="dashboard.loadOverview()">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>

      <el-table
        v-if="(overview?.running.length ?? 0) > 0"
        :data="overview?.running ?? []"
        size="small"
        row-key="batch_id"
      >
        <el-table-column prop="batch_id" label="批次" width="80">
          <template #default="{ row }">#{{ row.batch_id }}</template>
        </el-table-column>
        <el-table-column prop="data_source_name" label="数据源" min-width="140">
          <template #default="{ row }">
            <el-link type="primary" :underline="false" @click="goWorkbench(row)">
              {{ row.data_source_name ?? '--' }}
            </el-link>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="80">
          <template #default="{ row }">{{ typeLabel(row.data_source_type) }}</template>
        </el-table-column>
        <el-table-column label="策略" width="110">
          <template #default="{ row }">{{ strategyLabel(row.strategy) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StatusTag kind="batch" :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="进度" min-width="200">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress
                :percentage="row.progress"
                :stroke-width="8"
                :status="row.status === 'failed' ? 'exception' : undefined"
              />
              <span class="progress-cell__text text-secondary">
                {{ row.done }}/{{ row.total }} · 失败 {{ row.failed }} · 跳过 {{ row.skipped }}
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">{{ formatDuration(row.elapsed_ms) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'running' || row.status === 'pending'"
              link
              type="warning"
              size="small"
              :loading="actionLoading === row.batch_id"
              @click="confirmPause(row.batch_id)"
            >
              暂停
            </el-button>
            <el-button
              v-else
              link
              type="primary"
              size="small"
              :loading="actionLoading === row.batch_id"
              @click="handleResume(row.batch_id)"
            >
              继续
            </el-button>
            <el-button link type="primary" size="small" @click="goWorkbench(row)">查看日志</el-button>
          </template>
        </el-table-column>
      </el-table>

      <EmptyState
        v-else
        compact
        icon="VideoPlay"
        title="当前没有运行中的任务"
        description="到视频 / 文字 / 图片页选择策略后点击「开始爬取」"
        action-text="去发起采集"
        @action="router.push('/content/video')"
      />
    </div>

    <!-- 数据源健康度 -->
    <div class="card mt-16">
      <div class="card-title">
        <div class="card-title__left">
          <span>数据源健康度</span>
          <el-tag size="small" type="info" effect="plain">近 20 次成功率 × 70% + 最近成功时间 × 30%</el-tag>
        </div>
        <el-button link type="primary" size="small" @click="goSource">管理数据源</el-button>
      </div>

      <el-table
        v-loading="dashboard.healthLoading"
        :data="dashboard.healthList"
        size="small"
        row-key="data_source_id"
        @sort-change="handleHealthSort"
      >
        <el-table-column prop="name" label="数据源" min-width="160" show-overflow-tooltip />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">{{ typeLabel(row.type) }}</template>
        </el-table-column>
        <el-table-column label="健康分" width="150" sortable="custom" prop="health_score">
          <template #default="{ row }">
            <HealthBadge :score="row.health_score" />
          </template>
        </el-table-column>
        <el-table-column label="近 20 次成功率" width="140">
          <template #default="{ row }">{{ formatRatio(row.success_rate_20) }}</template>
        </el-table-column>
        <el-table-column label="最近成功" width="160">
          <template #default="{ row }">{{ formatDateTime(row.last_success_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              size="small"
              @click="router.push({ name: 'workbench', params: { type: row.type, id: row.data_source_id } })"
            >
              去采集
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <EmptyState
            compact
            icon="DataLine"
            title="暂无数据源"
            description="添加数据源并完成一次采集后，这里会显示健康度"
            action-text="去添加"
            @action="goSource"
          />
        </template>
      </el-table>
    </div>
  </div>
</template>

<style scoped lang="scss">
.progress-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;

  &__text {
    font-size: 12px;
  }
}
</style>
