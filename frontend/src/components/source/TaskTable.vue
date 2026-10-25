<script setup lang="ts">
/**
 * 任务表格（PRD 6.3.2 / 6.4 / 6.5）：序号 / 标题 / 状态 / 步骤进度 / 重试次数 / 耗时 / 大小 / 操作。
 * 文字类附加「字数」列、图片类附加「图片数」列。
 */
import { ref } from 'vue'

import EmptyState from '@/components/common/EmptyState.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { PAGE_SIZES } from '@/utils/constants'
import { formatBytes, formatDuration, formatNumber } from '@/utils/format'
import type { TaskItem } from '@/api/types'

const props = withDefaults(
  defineProps<{
    tasks: TaskItem[]
    total: number
    page: number
    pageSize: number
    type: string
    loading?: boolean
    /** 空态时是否因为暂无批次（区分「未开始」与「无任务」） */
    noBatch?: boolean
  }>(),
  { loading: false, noBatch: false },
)

const emit = defineEmits<{
  (event: 'page-change', page: number): void
  (event: 'size-change', size: number): void
  (event: 'view-log', task: TaskItem): void
  (event: 'retry', task: TaskItem): void
  (event: 'retry-selected', rows: TaskItem[]): void
}>()

const selected = ref<TaskItem[]>([])

function handleSelectionChange(rows: TaskItem[]): void {
  selected.value = rows
}

function stepPercent(task: TaskItem): number {
  if (!task.step_total) return 0
  return Math.min(100, Math.round((task.step_done / task.step_total) * 100))
}

function handlePageChange(page: number): void {
  emit('page-change', page)
}

function handleSizeChange(size: number): void {
  emit('size-change', size)
}
</script>

<template>
  <div class="task-table card">
    <div class="card-title">
      <div class="card-title__left">
        <span>任务列表</span>
        <el-tag size="small" type="info" effect="plain">共 {{ formatNumber(props.total) }} 条</el-tag>
      </div>
      <div class="flex-center gap-8">
        <el-button
          v-if="selected.some((row) => row.status === 'failed')"
          size="small"
          type="danger"
          plain
          @click="emit('retry-selected', selected)"
        >
          重试选中（{{ selected.filter((row) => row.status === 'failed').length }}）
        </el-button>
        <slot name="extra" />
      </div>
    </div>

    <el-table
      v-loading="loading"
      :data="tasks"
      size="small"
      row-key="id"
      @selection-change="handleSelectionChange"
    >
      <el-table-column type="selection" width="42" :selectable="() => true" />
      <el-table-column prop="seq_no" label="序号" width="70" />

      <el-table-column label="条目标题" min-width="200">
        <template #default="{ row }">
          <el-tooltip :content="row.source_url" placement="top" :show-after="300">
            <span class="ellipsis task-table__title">{{ row.title }}</span>
          </el-tooltip>
        </template>
      </el-table-column>

      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tooltip
            v-if="row.status === 'failed' && row.error_msg"
            :content="`[${row.error_code ?? '-'}] ${row.error_msg}`"
            placement="top"
          >
            <span><StatusTag kind="task" :status="row.status" /></span>
          </el-tooltip>
          <StatusTag v-else kind="task" :status="row.status" />
        </template>
      </el-table-column>

      <el-table-column label="进度" width="130">
        <template #default="{ row }">
          <div class="task-table__step">
            <el-progress
              :percentage="stepPercent(row)"
              :stroke-width="6"
              :show-text="false"
              :status="row.status === 'failed' ? 'exception' : undefined"
            />
            <span class="text-secondary task-table__step-text">
              {{ row.step_done }}/{{ row.step_total }}
            </span>
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="attempt_count" label="重试" width="70" />

      <el-table-column v-if="type === 'text'" label="字数" width="90">
        <template #default="{ row }">{{ row.word_count ? formatNumber(row.word_count) : '--' }}</template>
      </el-table-column>

      <el-table-column v-if="type === 'image'" label="图片数" width="90">
        <template #default="{ row }">
          {{ row.image_count ? formatNumber(row.image_count) : '--' }}
        </template>
      </el-table-column>

      <el-table-column label="耗时" width="90">
        <template #default="{ row }">
          {{ row.duration_ms ? formatDuration(row.duration_ms) : '--' }}
        </template>
      </el-table-column>

      <el-table-column label="大小" width="100">
        <template #default="{ row }">{{ row.file_size ? formatBytes(row.file_size) : '--' }}</template>
      </el-table-column>

      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="emit('view-log', row)">日志</el-button>
          <el-button
            v-if="row.status === 'failed'"
            link
            type="danger"
            size="small"
            @click="emit('retry', row)"
          >
            重试
          </el-button>
        </template>
      </el-table-column>

      <template #empty>
        <EmptyState
          compact
          icon="List"
          :title="noBatch ? '还没有任务' : '当前筛选下没有任务'"
          :description="noBatch ? '发起一次采集后，这里会显示每条任务的执行情况' : '试试清空筛选条件'"
        />
      </template>
    </el-table>

    <div v-if="total > 0" class="task-table__pager">
      <el-pagination
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="PAGE_SIZES"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.task-table {
  &__title {
    display: inline-block;
    max-width: 100%;
    vertical-align: middle;
  }

  &__step {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  &__step-text {
    font-size: 12px;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  &__pager {
    display: flex;
    justify-content: flex-end;
    margin-top: 12px;
  }
}
</style>
