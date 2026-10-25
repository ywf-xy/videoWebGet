<script setup lang="ts">
/**
 * 内容列表页（PRD 6.3.1 / 6.4 / 6.5）：视频 / 文字 / 图片三套页面复用，靠路由参数 `:type` 区分。
 * 差异：标题、累计数量列名与单位、空态文案（映射见 utils/constants.ts）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import EmptyState from '@/components/common/EmptyState.vue'
import HealthBadge from '@/components/common/HealthBadge.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { fetchDataSource } from '@/api/dataSource'
import { useDataSourceStore } from '@/stores/dataSource'
import { CONTENT_TYPE_MAP, PAGE_SIZES } from '@/utils/constants'
import { formatDateTime, formatNumber } from '@/utils/format'
import type { DataSourceDetail, DataSourceItem } from '@/api/types'

const route = useRoute()
const router = useRouter()
const store = useDataSourceStore()

const type = computed(() => String(route.params.type ?? 'video'))
const typeMeta = computed(() => CONTENT_TYPE_MAP[type.value])

const keyword = ref('')
const category = ref('')
const enabledFilter = ref<string>('all')
const debounceTimer = ref<number | null>(null)

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<DataSourceDetail | null>(null)

const enabledOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'enabled', label: '已启用' },
  { value: 'disabled', label: '已停用' },
]

function buildQuery(): void {
  const enabled =
    enabledFilter.value === 'all' ? undefined : enabledFilter.value === 'enabled'
  void store.fetchList({
    type: type.value,
    keyword: keyword.value.trim() || undefined,
    category: category.value.trim() || undefined,
    enabled,
    page: 1,
  })
}

function scheduleSearch(): void {
  if (debounceTimer.value !== null) window.clearTimeout(debounceTimer.value)
  debounceTimer.value = window.setTimeout(() => {
    buildQuery()
  }, 300)
}

function resetFilters(): void {
  keyword.value = ''
  category.value = ''
  enabledFilter.value = 'all'
  buildQuery()
}

function goWorkbench(row: DataSourceItem): void {
  if (!row.enabled) {
    ElMessage.warning('数据源已停用，请先在数据源页启用')
    return
  }
  router.push({ name: 'workbench', params: { type: type.value, id: row.id } })
}

async function openDetail(row: DataSourceItem): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await fetchDataSource(row.id)
  } finally {
    detailLoading.value = false
  }
}

function goDataSourcePage(): void {
  router.push('/data-sources')
}

function rowClassName({ row }: { row: DataSourceItem }): string {
  return row.enabled ? '' : 'table-row-disabled'
}

function goImport(): void {
  router.push({ path: '/data-sources', query: { import: '1' } })
}

function handlePageChange(page: number): void {
  void store.fetchList({ page })
}

function handleSizeChange(size: number): void {
  void store.fetchList({ page: 1, pageSize: size })
}

const configPreview = computed(() => {
  if (!detail.value) return ''
  try {
    return JSON.stringify(detail.value.config_json ?? {}, null, 2)
  } catch {
    return ''
  }
})

watch(
  () => route.params.type,
  (next) => {
    if (!next || !CONTENT_TYPE_MAP[String(next)]) {
      void router.replace('/content/video')
      return
    }
    keyword.value = String(route.query.keyword ?? '')
    buildQuery()
  },
)

watch([enabledFilter], () => buildQuery())

onMounted(() => {
  keyword.value = String(route.query.keyword ?? '')
  buildQuery()
})
</script>

<template>
  <div class="page content-list">
    <PageHeader
      :title="`${typeMeta?.label ?? '内容'}采集`"
      :description="`共 ${formatNumber(store.total)} 个${typeMeta?.label ?? ''}类数据源，选择后进入工作页发起采集`"
      :icon="typeMeta?.icon"
    >
      <template #extra>
        <el-button @click="goImport">
          <el-icon><Upload /></el-icon>
          导入数据源
        </el-button>
        <el-button type="primary" plain @click="goDataSourcePage">
          <el-icon><Plus /></el-icon>
          新增数据源
        </el-button>
      </template>
    </PageHeader>

    <div class="card">
      <div class="content-list__filters">
        <el-input
          v-model="keyword"
          placeholder="搜索数据源名称或地址"
          clearable
          style="width: 240px"
          @input="scheduleSearch"
          @clear="scheduleSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-input
          v-model="category"
          placeholder="分类"
          clearable
          style="width: 140px"
          @input="scheduleSearch"
          @clear="scheduleSearch"
        />
        <el-select v-model="enabledFilter" style="width: 140px">
          <el-option
            v-for="option in enabledOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-button @click="resetFilters">
          <el-icon><RefreshLeft /></el-icon>
          重置
        </el-button>
      </div>

      <el-table
        v-loading="store.loading"
        :data="store.list"
        size="default"
        row-key="id"
        :row-class-name="rowClassName"
      >
        <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link type="primary" :underline="false" @click="goWorkbench(row)">
              {{ row.name }}
            </el-link>
          </template>
        </el-table-column>

        <el-table-column prop="category" label="分类" width="110">
          <template #default="{ row }">{{ row.category || '未分类' }}</template>
        </el-table-column>

        <el-table-column label="主地址" min-width="220">
          <template #default="{ row }">
            <el-tooltip :content="row.homepage_url" placement="top" :show-after="300">
              <span class="ellipsis content-list__url">{{ row.homepage_url }}</span>
            </el-tooltip>
          </template>
        </el-table-column>

        <el-table-column label="备用地址" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.alt_urls_count > 0" size="small" type="info" effect="plain">
              {{ row.alt_urls_count }} 个
            </el-tag>
            <span v-else class="text-secondary">--</span>
          </template>
        </el-table-column>

        <el-table-column label="健康度" width="140">
          <template #default="{ row }">
            <HealthBadge :score="row.health_score" :show-bar="false" show-rate />
          </template>
        </el-table-column>

        <el-table-column label="上次采集" width="150">
          <template #default="{ row }">{{ formatDateTime(row.last_crawled_at) }}</template>
        </el-table-column>

        <el-table-column :label="typeMeta?.countLabel ?? '累计采集'" width="130">
          <template #default="{ row }">
            {{ formatNumber(row.total_items) }} {{ typeMeta?.countUnit ?? '' }}
          </template>
        </el-table-column>

        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small" effect="plain">
              {{ row.enabled ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-tooltip :disabled="row.enabled" content="数据源已停用" placement="top">
              <span>
                <el-button
                  type="primary"
                  size="small"
                  :disabled="!row.enabled"
                  @click="goWorkbench(row)"
                >
                  开始爬取
                </el-button>
              </span>
            </el-tooltip>
            <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>

        <template #empty>
          <EmptyState
            v-if="!store.loading"
            icon="FolderAdd"
            :title="typeMeta?.emptyTip ?? '暂无数据源'"
            description="数据源是采集的起点：配置名称、地址与解析规则后即可发起采集"
            action-text="去数据源页添加"
            @action="goDataSourcePage"
          />
        </template>
      </el-table>

      <div v-if="store.total > 0" class="content-list__pager">
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

    <!-- 数据源详情抽屉（PRD 6.3.1 操作列「详情」） -->
    <el-drawer v-model="detailVisible" title="数据源详情" size="520px">
      <div v-loading="detailLoading" class="content-list__detail">
        <template v-if="detail">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="名称">{{ detail.name }}</el-descriptions-item>
            <el-descriptions-item label="类型">
              {{ CONTENT_TYPE_MAP[detail.type]?.label ?? detail.type }}
            </el-descriptions-item>
            <el-descriptions-item label="分类">{{ detail.category || '未分类' }}</el-descriptions-item>
            <el-descriptions-item label="主地址">{{ detail.homepage_url }}</el-descriptions-item>
            <el-descriptions-item label="当前地址">
              {{ detail.current_url || detail.homepage_url }}
            </el-descriptions-item>
            <el-descriptions-item label="备用地址">
              {{ detail.alt_urls.length > 0 ? detail.alt_urls.join('、') : '--' }}
            </el-descriptions-item>
            <el-descriptions-item label="解析方式">
              {{ detail.script ? `自定义脚本（入口 ${detail.script_entry}）` : '内置选择器解析' }}
            </el-descriptions-item>
            <el-descriptions-item label="小说类">
              {{ detail.is_novel ? '是' : '否' }}
            </el-descriptions-item>
            <el-descriptions-item label="游标">
              第 {{ detail.cursor_last_item_no }} 条 / 第 {{ detail.cursor_last_page }} 页 /
              {{ detail.cursor_last_success_date || '--' }}
            </el-descriptions-item>
            <el-descriptions-item label="累计采集">
              {{ detail.total_items }}
            </el-descriptions-item>
            <el-descriptions-item label="备注">{{ detail.notes || '--' }}</el-descriptions-item>
          </el-descriptions>

          <div class="mt-16">
            <div class="text-secondary mb-8">选择器配置（config_json）</div>
            <pre class="content-list__pre">{{ configPreview || '{}' }}</pre>
          </div>
        </template>
        <EmptyState v-else-if="!detailLoading" compact title="详情加载失败" description="请稍后重试" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.content-list {
  &__filters {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
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

  &__pre {
    background: #1e1e1e;
    color: #d4d4d4;
    border-radius: $radius-sm;
    padding: 12px;
    font-family: $font-mono;
    font-size: 12px;
    line-height: 1.6;
    max-height: 320px;
    overflow: auto;
    margin: 0;
    white-space: pre-wrap;
    word-break: break-all;
  }

  &__detail {
    min-height: 200px;
  }
}
</style>
