<script setup lang="ts">
/**
 * 产物页（PRD 6.6 / T17）：5 条件筛选 + 分页（10/20/50）+ 操作（打开目录 / 重新下载 / 删除）。
 * 文件缺失（is_file_exists=false 或 status=missing）时禁用「打开目录」并标红提示。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import ArtifactFilterBar from '@/components/artifact/ArtifactFilterBar.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { useArtifactStore } from '@/stores/artifact'
import { ARTIFACT_TYPE_OPTIONS, CONTENT_TYPE_MAP, PAGE_SIZES } from '@/utils/constants'
import { formatBytes, formatDateTime, formatNumber } from '@/utils/format'
import type { ArtifactItem, ArtifactQuery } from '@/api/types'

const router = useRouter()
const store = useArtifactStore()

const filterBar = ref<InstanceType<typeof ArtifactFilterBar> | null>(null)
const actionLoading = ref<number | null>(null)
const hasFilter = computed(() => {
  const f = store.filters
  return Boolean(f.data_source_id || f.type || f.name || f.date_from || f.date_to || f.status)
})

const typeLabel = (value: string): string => {
  const item = ARTIFACT_TYPE_OPTIONS.find((option) => option.value === value)
  return item ? item.label : CONTENT_TYPE_MAP[value]?.label ?? value
}

function isMissing(row: ArtifactItem): boolean {
  return row.status === 'missing' || row.is_file_exists === false
}

async function handleSearch(query: ArtifactQuery): Promise<void> {
  await store.applyFilters(query)
}

async function handleReset(): Promise<void> {
  store.resetFilters()
  await store.fetchList()
}

function handlePageChange(page: number): void {
  void store.fetchList({ page })
}

function handleSizeChange(size: number): void {
  void store.fetchList({ page: 1, pageSize: size })
}

async function handleOpenDir(row: ArtifactItem): Promise<void> {
  actionLoading.value = row.id
  try {
    const result = await store.openDir(row.id)
    if (result.opened) {
      ElMessage.success('已在文件管理器中打开')
    } else {
      if (navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(result.path)
          ElMessage.warning('无法自动打开文件管理器，路径已复制到剪贴板')
          return
        } catch {
          // 落到下方降级提示
        }
      }
      ElMessage.warning(`无法自动打开文件管理器，路径：${result.path}`)
    }
  } finally {
    actionLoading.value = null
  }
}

async function handleRedownload(row: ArtifactItem): Promise<void> {
  actionLoading.value = row.id
  try {
    await store.redownload(row.id)
    ElMessage.success('已重新加入下载队列')
    await store.fetchList()
  } finally {
    actionLoading.value = null
  }
}

async function handleDelete(row: ArtifactItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除产物「${row.name}」吗？将同时删除磁盘文件，且不可恢复。`,
      '删除产物',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  actionLoading.value = row.id
  try {
    await store.remove(row.id)
    ElMessage.success('已删除')
  } finally {
    actionLoading.value = null
  }
}

function goContent(): void {
  router.push('/content/video')
}

onMounted(() => {
  void store.fetchList()
})
</script>

<template>
  <div class="page artifacts">
    <PageHeader
      title="产物"
      description="采集成功后落盘的文件，可按数据源、类型、名称、日期与状态组合检索"
      icon="FolderOpened"
    >
      <template #extra>
        <el-button :loading="store.loading" @click="store.fetchList()">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </template>
    </PageHeader>

    <ArtifactFilterBar ref="filterBar" :loading="store.loading" @search="handleSearch" @reset="handleReset" />

    <div class="card mt-16">
      <div class="card-title">
        <div class="card-title__left">
          <span>产物列表</span>
          <el-tag size="small" type="info" effect="plain">共 {{ formatNumber(store.total) }} 条</el-tag>
        </div>
        <span v-if="store.errorMessage" class="text-danger">{{ store.errorMessage }}</span>
      </div>

      <el-table v-loading="store.loading" :data="store.list" size="default" row-key="id">
        <el-table-column label="产物名称" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.name }}</span>
            <el-tag v-if="isMissing(row)" size="small" type="info" effect="plain" class="ml-8">
              文件缺失
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ typeLabel(row.type) }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="data_source_name" label="数据源" width="150" show-overflow-tooltip />
        <el-table-column label="分类" width="110">
          <template #default="{ row }">{{ row.category || '未分类' }}</template>
        </el-table-column>

        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <StatusTag kind="artifact" :status="row.status" />
          </template>
        </el-table-column>

        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ formatBytes(row.size) }}</template>
        </el-table-column>

        <el-table-column label="落盘路径" min-width="240">
          <template #default="{ row }">
            <el-tooltip :content="row.path || '（尚未生成）'" placement="top" :show-after="300">
              <span class="ellipsis artifacts__path">{{ row.path || '--' }}</span>
            </el-tooltip>
          </template>
        </el-table-column>

        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>

        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-tooltip :disabled="!isMissing(row)" content="文件已被移动或删除" placement="top">
              <span>
                <el-button
                  link
                  type="primary"
                  size="small"
                  :disabled="isMissing(row)"
                  :loading="actionLoading === row.id"
                  @click="handleOpenDir(row)"
                >
                  打开目录
                </el-button>
              </span>
            </el-tooltip>
            <el-button
              v-if="row.status === 'failed'"
              link
              type="warning"
              size="small"
              :loading="actionLoading === row.id"
              @click="handleRedownload(row)"
            >
              重新下载
            </el-button>
            <el-button
              link
              type="danger"
              size="small"
              :loading="actionLoading === row.id"
              @click="handleDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>

        <template #empty>
          <EmptyState
            v-if="!store.loading"
            icon="FolderOpened"
            :title="hasFilter ? '没有符合条件的产物' : '还没有产物'"
            :description="
              hasFilter ? '试试放宽筛选条件，或清空筛选查看全部' : '去视频/文字/图片页发起一次爬取吧'
            "
            :action-text="hasFilter ? '清空筛选' : '去发起采集'"
            @action="hasFilter ? handleReset() : goContent()"
          />
        </template>
      </el-table>

      <div v-if="store.total > 0" class="artifacts__pager">
        <el-pagination
          :current-page="store.filters.page ?? 1"
          :page-size="store.filters.pageSize ?? 10"
          :page-sizes="PAGE_SIZES"
          :total="store.total"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.artifacts {
  &__path {
    display: inline-block;
    max-width: 100%;
    vertical-align: middle;
    font-family: $font-mono;
    font-size: 12px;
    color: $color-text-regular;
  }

  &__pager {
    display: flex;
    justify-content: flex-end;
    margin-top: 16px;
  }
}

.ml-8 {
  margin-left: 8px;
}
</style>
