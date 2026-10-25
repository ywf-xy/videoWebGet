<script setup lang="ts">
/**
 * 数据源导出弹窗（PRD 6.7 / T17-⑤）：范围（全部 / 选中 / 按类型）→ 下载 UTF-8 JSON。
 * 导出文件可直接被「导入」接口回读，字段无损（P0-23②）。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { useDataSourceStore } from '@/stores/dataSource'
import { saveBlob } from '@/utils/download'
import type { ExportQuery } from '@/api/types'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    selectedIds: number[]
  }>(),
  { selectedIds: () => [] },
)

const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()

const store = useDataSourceStore()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const scope = ref<'all' | 'selected' | 'type'>('all')
const type = ref<string>('video')
const exporting = ref(false)

const hasSelection = computed(() => props.selectedIds.length > 0)

const typeOptions = [
  { value: 'video', label: '视频' },
  { value: 'text', label: '文字' },
  { value: 'image', label: '图片' },
]

async function handleExport(): Promise<void> {
  const query: ExportQuery = { scope: scope.value }
  if (scope.value === 'selected') {
    if (!hasSelection.value) {
      ElMessage.warning('请先在列表勾选要导出的数据源')
      return
    }
    query.ids = props.selectedIds
  }
  if (scope.value === 'type') {
    query.type = type.value
  }

  exporting.value = true
  try {
    const { blob, filename } = await store.exportFile(query)
    saveBlob(blob, filename)
    ElMessage.success('导出成功')
    visible.value = false
  } finally {
    exporting.value = false
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    scope.value = hasSelection.value ? 'selected' : 'all'
  },
)
</script>

<template>
  <el-dialog v-model="visible" title="导出数据源" width="460px" :destroy-on-close="true">
    <div class="export-dialog">
      <el-radio-group v-model="scope" class="export-dialog__scopes">
        <el-radio value="all">全部数据源</el-radio>
        <el-radio value="selected">
          当前勾选（{{ selectedIds.length }} 个）
          <span v-if="!hasSelection" class="text-secondary">（未勾选）</span>
        </el-radio>
        <el-radio value="type">按类型导出</el-radio>
      </el-radio-group>

      <div v-if="scope === 'type'" class="mt-12">
        <el-select v-model="type" style="width: 180px">
          <el-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </div>

      <el-alert
        class="mt-16"
        type="info"
        :closable="false"
        show-icon
        title="导出为 UTF-8 JSON 数组，可直接通过「导入」还原（含脚本与选择器配置）"
      />
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="exporting" @click="handleExport">导出</el-button>
    </template>
  </el-dialog>
</template>

<style scoped lang="scss">
.export-dialog {
  &__scopes {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
}

.mt-12 {
  margin-top: 12px;
}
</style>
