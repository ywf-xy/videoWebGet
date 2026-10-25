<script setup lang="ts">
/**
 * 数据源管理页（PRD 6.7 / T17）：手动维护 + 导入导出 + 脚本试运行 + 启停与软删除。
 * 「可视化创建」为 P2-01 占位入口（禁用态），占位页可从顶部说明进入。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import EmptyState from '@/components/common/EmptyState.vue'
import HealthBadge from '@/components/common/HealthBadge.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import ExportDialog from '@/components/datasource/ExportDialog.vue'
import ImportDialog from '@/components/datasource/ImportDialog.vue'
import ScriptTestDialog from '@/components/datasource/ScriptTestDialog.vue'
import SourceFormDrawer from '@/components/datasource/SourceFormDrawer.vue'
import { fetchDataSource } from '@/api/dataSource'
import { useDataSourceStore } from '@/stores/dataSource'
import { CONTENT_TYPE_MAP, PAGE_SIZES, SOURCE_TYPE_OPTIONS } from '@/utils/constants'
import { formatDateTime, formatNumber } from '@/utils/format'
import type { DataSourceItem, SourceType } from '@/api/types'

const route = useRoute()
const router = useRouter()
const store = useDataSourceStore()

const keyword = ref('')
const typeFilter = ref<string>('')
const selectedIds = ref<number[]>([])
const actionLoading = ref<number | null>(null)

const formVisible = ref(false)
const editingId = ref<number | null>(null)
const importVisible = ref(false)
const exportVisible = ref(false)
const testVisible = ref(false)
const testScript = ref('')
const testEntry = ref('parse')
const testUrl = ref('')
const testSourceId = ref<number | null>(null)

let debounceTimer: number | null = null

const typeLabel = (value: string): string =>
  CONTENT_TYPE_MAP[value]?.label ?? SOURCE_TYPE_OPTIONS.find((o) => o.value === value)?.label ?? value

const hasRows = computed(() => store.list.length > 0)

function buildQuery(): void {
  void store.fetchList({
    keyword: keyword.value.trim() || undefined,
    type: typeFilter.value || undefined,
    page: 1,
  })
}

function scheduleSearch(): void {
  if (debounceTimer !== null) window.clearTimeout(debounceTimer)
  debounceTimer = window.setTimeout(buildQuery, 300)
}

function openCreate(): void {
  editingId.value = null
  formVisible.value = true
}

function openEdit(row: DataSourceItem): void {
  editingId.value = row.id
  formVisible.value = true
}

async function handleSaved(id: number, isCreate: boolean): Promise<void> {
  await store.fetchList()
  if (isCreate) {
    ElMessage.success(`数据源已创建（#${id}），可到对应列表页发起采集`)
  }
}

async function handleToggle(row: DataSourceItem): Promise<void> {
  actionLoading.value = row.id
  try {
    const enabled = await store.toggle(row.id, !row.enabled)
    ElMessage.success(enabled ? '已启用' : '已停用，该数据源将无法发起采集')
  } finally {
    actionLoading.value = null
  }
}

async function handleDelete(row: DataSourceItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除数据源「${row.name}」吗？删除后历史任务与产物仍可查询（软删除）。`,
      '删除数据源',
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

async function handleTestScript(row: DataSourceItem): Promise<void> {
  actionLoading.value = row.id
  try {
    const detail = await fetchDataSource(row.id)
    testScript.value = detail.script ?? ''
    testEntry.value = detail.script_entry || 'parse'
    testUrl.value = detail.current_url || detail.homepage_url
    testSourceId.value = row.id
    testVisible.value = true
  } finally {
    actionLoading.value = null
  }
}

function goWorkbench(row: DataSourceItem): void {
  router.push({ name: 'workbench', params: { type: row.type, id: row.id } })
}

function handleSelectionChange(rows: DataSourceItem[]): void {
  selectedIds.value = rows.map((row) => row.id)
}

function handlePageChange(page: number): void {
  void store.fetchList({ page })
}

function handleSizeChange(size: number): void {
  void store.fetchList({ page: 1, pageSize: size })
}

function handleImported(): void {
  void store.fetchList()
}

function resetFilters(): void {
  keyword.value = ''
  typeFilter.value = ''
  buildQuery()
}

// 内容列表页「导入数据源」跳转过来时自动打开导入弹窗
watch(
  () => route.query.import,
  (value) => {
    if (value === '1') {
      importVisible.value = true
      void router.replace({ path: '/data-sources' })
    }
  },
)

watch(typeFilter, () => buildQuery())

onMounted(() => {
  void store.fetchList()
  if (route.query.import === '1') {
    importVisible.value = true
    void router.replace({ path: '/data-sources' })
  }
})
</script>

<template>
  <div class="page data-sources">
    <PageHeader
      title="数据源管理"
      description="一个数据源 = 一个站点/栏目的采集配置；视频/文字/图片页从这里读取可采集列表"
      icon="Coin"
    >
      <template #extra>
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>
          新增数据源
        </el-button>
        <el-button @click="importVisible = true">
          <el-icon><Upload /></el-icon>
          导入
        </el-button>
        <el-button :disabled="!hasRows" @click="exportVisible = true">
          <el-icon><Download /></el-icon>
          导出
        </el-button>
        <el-tooltip content="P2-01 能力预告，敬请期待" placement="bottom">
          <span>
            <el-button disabled>
              <el-icon><MagicStick /></el-icon>
              可视化创建
            </el-button>
          </span>
        </el-tooltip>
      </template>
    </PageHeader>

    <div class="card">
      <div class="data-sources__filters">
        <el-input
          v-model="keyword"
          placeholder="搜索名称或地址"
          clearable
          style="width: 240px"
          @input="scheduleSearch"
          @clear="scheduleSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-select v-model="typeFilter" placeholder="全部类型" clearable style="width: 140px">
          <el-option
            v-for="option in SOURCE_TYPE_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-button @click="resetFilters">
          <el-icon><RefreshLeft /></el-icon>
          重置
        </el-button>
        <span class="text-secondary data-sources__count">
          共 {{ formatNumber(store.total) }} 个数据源
          <template v-if="selectedIds.length > 0">· 已选 {{ selectedIds.length }} 个</template>
        </span>
      </div>

      <el-table
        v-loading="store.loading"
        :data="store.list"
        row-key="id"
        size="default"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="46" reserve-selection />

        <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link type="primary" :underline="false" @click="openEdit(row)">{{ row.name }}</el-link>
          </template>
        </el-table-column>

        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ typeLabel(row.type) }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="分类" width="110">
          <template #default="{ row }">{{ row.category || '未分类' }}</template>
        </el-table-column>

        <el-table-column label="主地址" min-width="220">
          <template #default="{ row }">
            <el-tooltip :content="row.homepage_url" placement="top" :show-after="300">
              <span class="ellipsis data-sources__url">{{ row.homepage_url }}</span>
            </el-tooltip>
          </template>
        </el-table-column>

        <el-table-column label="备用" width="80">
          <template #default="{ row }">{{ row.alt_urls_count || '--' }}</template>
        </el-table-column>

        <el-table-column label="解析脚本" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.has_script" size="small" type="warning" effect="plain">自有脚本</el-tag>
            <el-tag v-else size="small" type="info" effect="plain">内置</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="健康度" width="130">
          <template #default="{ row }">
            <HealthBadge :score="row.health_score" :show-bar="false" />
          </template>
        </el-table-column>

        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small" effect="plain">
              {{ row.enabled ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="更新时间" width="150">
          <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
        </el-table-column>

        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button
              link
              :type="row.enabled ? 'warning' : 'success'"
              size="small"
              :loading="actionLoading === row.id"
              @click="handleToggle(row)"
            >
              {{ row.enabled ? '停用' : '启用' }}
            </el-button>
            <el-button
              v-if="row.has_script"
              link
              type="primary"
              size="small"
              :loading="actionLoading === row.id"
              @click="handleTestScript(row)"
            >
              试运行
            </el-button>
            <el-button link type="info" size="small" @click="goWorkbench(row)">采集</el-button>
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
            icon="Coin"
            title="还没有数据源"
            description="手动新增、导入 JSON/CSV，或下载模板后批量导入"
          >
            <template #actions>
              <el-button type="primary" @click="openCreate">手动新增</el-button>
              <el-button @click="importVisible = true">导入文件</el-button>
              <el-button text type="primary" @click="router.push('/data-sources/visual-create')">
                能力预告
              </el-button>
            </template>
          </EmptyState>
        </template>
      </el-table>

      <div v-if="store.total > 0" class="data-sources__pager">
        <el-pagination
          :current-page="store.query.page ?? 1"
          :page-size="store.query.pageSize ?? 10"
          :page-sizes="PAGE_SIZES"
          :total="store.total"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </div>

    <SourceFormDrawer
      v-model="formVisible"
      :source-id="editingId"
      :default-type="(typeFilter as SourceType) || 'video'"
      @saved="handleSaved"
    />
    <ImportDialog v-model="importVisible" @imported="handleImported" />
    <ExportDialog v-model="exportVisible" :selected-ids="selectedIds" />
    <ScriptTestDialog
      v-model="testVisible"
      :source-id="testSourceId"
      :script="testScript"
      :entry="testEntry"
      :default-url="testUrl"
    />
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.data-sources {
  &__filters {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }

  &__count {
    margin-left: auto;
    font-size: 12px;
  }

  &__url {
    display: inline-block;
    max-width: 100%;
    vertical-align: middle;
    color: $color-text-regular;
  }

  &__pager {
    display: flex;
    justify-content: flex-end;
    margin-top: 16px;
  }
}
</style>
