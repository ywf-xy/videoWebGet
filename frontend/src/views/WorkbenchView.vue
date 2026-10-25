<script setup lang="ts">
/**
 * 采集工作页（PRD 6.3.2 / 6.4 / 6.5 / T16）。
 *
 * 结构：数据源信息条 → 上次采集进度 → 策略表单 → 执行进度（含实时日志）→ 任务列表。
 * 轮询只走 `stores/batch.ts`（2s，终态自停）；任务列表随轮询节拍刷新。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { fetchBatches, fetchLatestBatch } from '@/api/batch'
import { fetchDataSource, fetchDataSourceHealth, updateDataSource } from '@/api/dataSource'
import { fetchTaskDetail, fetchTasks, retryTask, retryTasks } from '@/api/task'
import PageHeader from '@/components/common/PageHeader.vue'
import LastCursorCard from '@/components/source/LastCursorCard.vue'
import SourceInfoBar from '@/components/source/SourceInfoBar.vue'
import StageProgress from '@/components/source/StageProgress.vue'
import StrategyForm from '@/components/source/StrategyForm.vue'
import TaskLogDrawer from '@/components/source/TaskLogDrawer.vue'
import TaskTable from '@/components/source/TaskTable.vue'
import { useBatchStore } from '@/stores/batch'
import { useSettingStore } from '@/stores/setting'
import { BUSY_BATCH_STATUSES, CONTENT_TYPE_MAP, DEFAULT_PAGE_SIZE } from '@/utils/constants'
import type {
  BatchCreatePayload,
  DataSourceDetail,
  HealthResp,
  LatestBatchResp,
  TaskDetail,
  TaskItem,
} from '@/api/types'

const route = useRoute()
const router = useRouter()
const batchStore = useBatchStore()
const settingStore = useSettingStore()

const sourceId = computed(() => Number(route.params.id))
const type = computed(() => String(route.params.type ?? 'video'))
const typeMeta = computed(() => CONTENT_TYPE_MAP[type.value])

const source = ref<DataSourceDetail | null>(null)
const health = ref<HealthResp | null>(null)
const latest = ref<LatestBatchResp | null>(null)
const sourceLoading = ref(false)
const submitting = ref(false)

const tasks = ref<TaskItem[]>([])
const taskTotal = ref(0)
const taskPage = ref(1)
const taskPageSize = ref(DEFAULT_PAGE_SIZE)
const taskLoading = ref(false)

const logDrawerVisible = ref(false)
const logTask = ref<TaskItem | null>(null)
const logTaskDetail = ref<TaskDetail | null>(null)

const summaryVisible = ref(false)
const summaryText = ref('')

const maxThreads = computed(() => settingStore.settings?.max_threads ?? 4)
const ffmpegAvailable = computed(() => settingStore.systemInfo?.ffmpeg.available ?? null)
const outputRoot = computed(() => settingStore.systemInfo?.output_root ?? '')

const formDisabled = computed(
  () => batchStore.isRunning || batchStore.isPaused || !source.value?.enabled,
)
const batchActive = computed(() => batchStore.batchId !== null)

async function loadSource(): Promise<void> {
  if (!Number.isFinite(sourceId.value) || sourceId.value <= 0) return
  sourceLoading.value = true
  try {
    const [detail, healthData, latestData] = await Promise.all([
      fetchDataSource(sourceId.value),
      fetchDataSourceHealth(sourceId.value).catch(() => null),
      fetchLatestBatch(sourceId.value).catch(() => null),
    ])
    source.value = detail
    health.value = healthData
    latest.value = latestData
  } catch {
    source.value = null
  } finally {
    sourceLoading.value = false
  }
}

/** 刷新「上次采集进度」（批次结束后需要更新） */
async function reloadLatest(): Promise<void> {
  try {
    latest.value = await fetchLatestBatch(sourceId.value)
  } catch {
    latest.value = null
  }
}

async function loadTasks(): Promise<void> {
  if (batchStore.batchId === null) {
    tasks.value = []
    taskTotal.value = 0
    return
  }
  taskLoading.value = true
  try {
    const data = await fetchTasks({
      batch_id: batchStore.batchId,
      page: taskPage.value,
      pageSize: taskPageSize.value,
    })
    tasks.value = data.items
    taskTotal.value = data.total
  } catch {
    tasks.value = []
    taskTotal.value = 0
  } finally {
    taskLoading.value = false
  }
}

/** 进入页面时若存在进行中的批次，自动续上轮询（刷新页面不丢进度） */
async function resumeExistingBatch(): Promise<void> {
  try {
    const page = await fetchBatches({ data_source_id: sourceId.value, page: 1, pageSize: 1 })
    const last = page.items[0]
    if (!last) return
    if (BUSY_BATCH_STATUSES.includes(last.status)) {
      batchStore.startPolling(last.id)
      await loadTasks()
    }
  } catch {
    // 无历史批次 / 请求失败都不影响发起新采集
  }
}

async function handleSubmit(payload: BatchCreatePayload): Promise<void> {
  if (!source.value) return
  submitting.value = true
  try {
    const created = await batchStore.create({
      ...payload,
      data_source_id: source.value.id,
    })
    ElMessage.success(`已创建批次 #${created.batch_id}，开始解析列表…`)
    batchStore.startPolling(created.batch_id)
    taskPage.value = 1
    await loadTasks()
  } finally {
    submitting.value = false
  }
}

async function handleSwitchUrl(url: string): Promise<void> {
  if (!source.value) return
  await updateDataSource(source.value.id, { current_url: url })
  source.value.current_url = url
  ElMessage.success(`已切换采集地址：${url}`)
}

async function handlePause(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '暂停后不再领取新任务，运行中的任务会在当前步骤结束后停止并回退为待执行。',
      '暂停采集',
      { type: 'warning', confirmButtonText: '暂停', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await batchStore.pause()
  ElMessage.success('已请求暂停')
}

async function handleResume(): Promise<void> {
  await batchStore.resume()
  ElMessage.success('已恢复采集')
}

async function handleRetryFailed(): Promise<void> {
  const count = await batchStore.retryFailed()
  ElMessage.success(`已提交 ${count} 条失败任务重新入队`)
  await loadTasks()
}

async function handleRetryOne(task: TaskItem): Promise<void> {
  await retryTask(task.id)
  ElMessage.success('已提交重试')
  await batchStore.refreshOnce(false)
  await loadTasks()
}

async function handleViewLog(task: TaskItem): Promise<void> {
  logTask.value = task
  logTaskDetail.value = null
  logDrawerVisible.value = true
  await batchStore.loadTaskLogs(task.id)
  try {
    logTaskDetail.value = await fetchTaskDetail(task.id)
  } catch {
    logTaskDetail.value = null
  }
}

/** 批量重试勾选的失败任务（POST /tasks/retry） */
async function handleRetrySelected(rows: TaskItem[]): Promise<void> {
  const ids = rows.filter((row) => row.status === 'failed').map((row) => row.id)
  if (ids.length === 0) {
    ElMessage.warning('所选任务中没有失败任务')
    return
  }
  const result = await retryTasks(ids)
  ElMessage.success(`已提交 ${result.submitted} 条失败任务重新入队`)
  await batchStore.refreshOnce(false)
  await loadTasks()
}

function handleLogRefresh(filters: { level: string; keyword: string }): void {
  if (!logTask.value) return
  void batchStore.loadTaskLogs(logTask.value.id, filters)
}

function handleTaskPage(page: number): void {
  taskPage.value = page
  void loadTasks()
}

function handleTaskSize(size: number): void {
  taskPageSize.value = size
  taskPage.value = 1
  void loadTasks()
}

function backToList(): void {
  router.push(typeMeta.value?.route ?? '/content/video')
}

function goArtifacts(): void {
  summaryVisible.value = false
  router.push('/artifacts')
}

/** 终态弹出结果摘要（PRD 6.3.2：阶段二结束提示成功/失败与产物目录） */
watch(
  () => batchStore.isTerminal,
  async (terminal) => {
    if (!terminal || !batchStore.batchId) return
    await reloadLatest()
    await loadTasks()
    const progress = batchStore.progress
    if (!progress) return
    summaryText.value = [
      `状态：${progress.status === 'failed' ? '失败' : '完成'}`,
      `成功 ${progress.done} 条 / 失败 ${progress.failed} 条 / 跳过 ${progress.skipped} 条`,
      outputRoot.value ? `产物目录：${outputRoot.value}` : '',
    ]
      .filter(Boolean)
      .join('\n')
    summaryVisible.value = true
  },
)

/** 任务列表跟随轮询节拍刷新（2s 一次） */
watch(
  () => batchStore.pollTick,
  () => {
    void loadTasks()
  },
)

function handleVisibility(): void {
  batchStore.handleVisibility()
}

watch(sourceId, async () => {
  batchStore.reset()
  await loadSource()
  await resumeExistingBatch()
})

onMounted(async () => {
  if (!CONTENT_TYPE_MAP[type.value]) {
    void router.replace('/content/video')
    return
  }
  await Promise.all([settingStore.load(), settingStore.loadSystemInfo()])
  await loadSource()
  if (!source.value) {
    ElMessage.error('数据源不存在或已删除')
    return
  }
  await resumeExistingBatch()
  document.addEventListener('visibilitychange', handleVisibility)
})

onBeforeUnmount(() => {
  batchStore.stopPolling()
  document.removeEventListener('visibilitychange', handleVisibility)
})

onBeforeRouteLeave(() => {
  batchStore.stopPolling()
})
</script>

<template>
  <div class="page workbench">
    <PageHeader
      :title="`${typeMeta?.label ?? ''}采集 · ${source?.name ?? ''}`"
      description="两阶段执行：先解析列表生成任务，再按线程数并发下载"
      :icon="typeMeta?.icon"
    >
      <template #extra>
        <el-button @click="backToList">
          <el-icon><Back /></el-icon>
          返回列表
        </el-button>
        <el-button :loading="sourceLoading" @click="loadSource">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="source && !source.enabled"
      class="mb-16"
      type="warning"
      show-icon
      :closable="false"
      title="该数据源已停用"
      description="停用状态下无法发起采集，请到数据源页启用后再试。"
    />

    <SourceInfoBar
      :source="source"
      :health="health"
      :loading="sourceLoading"
      @switch-url="handleSwitchUrl"
    />

    <LastCursorCard class="mt-16" :latest="latest" :source="source" :type="type" />

    <StrategyForm
      class="mt-16"
      :type="type"
      :max-threads="maxThreads"
      :disabled="formDisabled"
      :loading="submitting || batchStore.busy"
      :ffmpeg-available="ffmpegAvailable"
      @submit="handleSubmit"
    />

    <StageProgress
      class="mt-16"
      :batch="batchStore.progress"
      :batch-id="batchStore.batchId"
      :active="batchStore.activeTasks"
      :logs="batchStore.logs"
      :polling="batchStore.polling"
      :busy="batchStore.busy"
      :warnings="batchStore.current?.warnings ?? []"
      :error-code="batchStore.current?.error_code ?? null"
      :error-msg="batchStore.current?.error_msg ?? null"
      @pause="handlePause"
      @resume="handleResume"
      @retry-failed="handleRetryFailed"
      @refresh="batchStore.refreshOnce(false)"
    />

    <TaskTable
      class="mt-16"
      :tasks="tasks"
      :total="taskTotal"
      :page="taskPage"
      :page-size="taskPageSize"
      :type="type"
      :loading="taskLoading"
      :no-batch="!batchActive"
      @page-change="handleTaskPage"
      @size-change="handleTaskSize"
      @view-log="handleViewLog"
      @retry="handleRetryOne"
      @retry-selected="handleRetrySelected"
    />

    <TaskLogDrawer
      v-model="logDrawerVisible"
      :task="logTask"
      :detail="logTaskDetail"
      :logs="batchStore.taskLogs"
      :loading="batchStore.taskLogsLoading"
      @refresh="handleLogRefresh"
    />

    <el-dialog v-model="summaryVisible" title="采集结果" width="440px">
      <pre class="workbench__summary">{{ summaryText }}</pre>
      <template #footer>
        <el-button @click="summaryVisible = false">关闭</el-button>
        <el-button type="primary" @click="goArtifacts">查看产物</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.workbench {
  &__summary {
    margin: 0;
    font-family: $font-mono;
    font-size: 13px;
    line-height: 1.8;
    white-space: pre-wrap;
    word-break: break-all;
    background: $color-bg-page;
    border-radius: $radius-sm;
    padding: 12px;
  }
}
</style>
