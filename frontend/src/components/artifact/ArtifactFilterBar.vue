<script setup lang="ts">
/**
 * 产物筛选区（PRD 6.6 / T17-①）：数据源 / 类型 / 名称模糊 / 日期区间 / 状态 五条件 + 查询 / 重置。
 * 组件只维护本地表单值，点击查询时把条件交给父组件的 store。
 */
import { onMounted, ref } from 'vue'

import { fetchDataSources } from '@/api/dataSource'
import { ARTIFACT_TYPE_OPTIONS, ARTIFACT_STATUS_MAP } from '@/utils/constants'
import type { ArtifactQuery, DataSourceItem } from '@/api/types'

const props = defineProps<{ loading?: boolean }>()

const emit = defineEmits<{
  (event: 'search', query: ArtifactQuery): void
  (event: 'reset'): void
}>()

const dataSourceId = ref<number | undefined>(undefined)
const type = ref<string>('')
const name = ref('')
const dateRange = ref<[string, string] | null>(null)
const status = ref<string>('')
const sourceOptions = ref<DataSourceItem[]>([])
const sourceLoading = ref(false)

const statusOptions = Object.entries(ARTIFACT_STATUS_MAP).map(([value, meta]) => ({
  value,
  label: meta.label,
}))

async function loadSources(): Promise<void> {
  sourceLoading.value = true
  try {
    const data = await fetchDataSources({ page: 1, pageSize: 200 })
    sourceOptions.value = data.items
  } catch {
    sourceOptions.value = []
  } finally {
    sourceLoading.value = false
  }
}

function buildQuery(): ArtifactQuery {
  return {
    data_source_id: dataSourceId.value,
    type: type.value || undefined,
    name: name.value.trim() || undefined,
    date_from: dateRange.value?.[0],
    date_to: dateRange.value?.[1],
    status: status.value || undefined,
  }
}

function handleSearch(): void {
  emit('search', buildQuery())
}

function handleReset(): void {
  dataSourceId.value = undefined
  type.value = ''
  name.value = ''
  dateRange.value = null
  status.value = ''
  emit('reset')
}

onMounted(() => {
  void loadSources()
})

defineExpose({ loadSources })
</script>

<template>
  <div class="artifact-filter card">
    <el-form :inline="true" class="artifact-filter__form" @submit.prevent>
      <el-form-item label="数据源">
        <el-select
          v-model="dataSourceId"
          placeholder="全部数据源"
          clearable
          filterable
          :loading="sourceLoading"
          style="width: 200px"
        >
          <el-option
            v-for="item in sourceOptions"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="类型">
        <el-select v-model="type" placeholder="全部类型" clearable style="width: 130px">
          <el-option
            v-for="item in ARTIFACT_TYPE_OPTIONS"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="名称">
        <el-input
          v-model="name"
          placeholder="名称模糊匹配"
          clearable
          style="width: 180px"
          @keyup.enter="handleSearch"
        />
      </el-form-item>

      <el-form-item label="日期">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="width: 260px"
        />
      </el-form-item>

      <el-form-item label="状态">
        <el-select v-model="status" placeholder="全部状态" clearable style="width: 130px">
          <el-option
            v-for="item in statusOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </el-form-item>

      <el-form-item>
        <el-button type="primary" :loading="props.loading" @click="handleSearch">
          <el-icon><Search /></el-icon>
          查询
        </el-button>
        <el-button @click="handleReset">
          <el-icon><RefreshLeft /></el-icon>
          重置
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<style scoped lang="scss">
.artifact-filter {
  &__form {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 8px;

    :deep(.el-form-item) {
      margin-bottom: 8px;
      margin-right: 8px;
    }
  }
}
</style>
