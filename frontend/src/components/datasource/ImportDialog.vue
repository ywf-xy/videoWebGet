<script setup lang="ts">
/**
 * 数据源导入弹窗（PRD 6.7 / T17-④）：拖拽上传 JSON/CSV + 覆盖同名开关 + 逐行结果表。
 */
import { computed, ref } from 'vue'
import { ElMessage, type UploadFile } from 'element-plus'

import { downloadTemplate } from '@/api/dataSource'
import { saveBlob } from '@/utils/download'
import { useDataSourceStore } from '@/stores/dataSource'
import type { ImportResultResp } from '@/api/types'

const props = defineProps<{ modelValue: boolean }>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'imported'): void
}>()

const store = useDataSourceStore()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const selectedFile = ref<File | null>(null)
const overwrite = ref(false)
const importing = ref(false)
const result = ref<ImportResultResp | null>(null)
const templateLoading = ref(false)

const MAX_SIZE = 10 * 1024 * 1024

function handleChange(file: UploadFile): void {
  result.value = null
  if (!file.raw) return
  const suffix = file.name.toLowerCase().split('.').pop() ?? ''
  if (!['json', 'csv'].includes(suffix)) {
    ElMessage.error('仅支持 .json / .csv 文件')
    selectedFile.value = null
    return
  }
  if (file.size && file.size > MAX_SIZE) {
    ElMessage.error('文件不能超过 10MB')
    selectedFile.value = null
    return
  }
  selectedFile.value = file.raw
}

async function handleImport(): Promise<void> {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择要导入的文件')
    return
  }
  importing.value = true
  try {
    result.value = await store.importFile(selectedFile.value, overwrite.value)
    const summary = result.value
    if (summary.failed === 0) {
      ElMessage.success(`导入成功 ${summary.success} 条`)
    } else {
      ElMessage.warning(`成功 ${summary.success} 条 / 失败 ${summary.failed} 条，详见结果表`)
    }
    emit('imported')
  } finally {
    importing.value = false
  }
}

async function handleTemplate(): Promise<void> {
  templateLoading.value = true
  try {
    const { blob, filename } = await downloadTemplate()
    saveBlob(blob, filename)
  } finally {
    templateLoading.value = false
  }
}

function handleClose(): void {
  selectedFile.value = null
  result.value = null
  overwrite.value = false
  visible.value = false
}
</script>

<template>
  <el-dialog v-model="visible" title="导入数据源" width="640px" :destroy-on-close="true" @close="handleClose">
    <div class="import-dialog">
      <el-upload
        drag
        :auto-upload="false"
        :show-file-list="false"
        accept=".json,.csv"
        :on-change="handleChange"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">把 JSON / CSV 文件拖到这里，或<em>点击选择</em></div>
        <template #tip>
          <div class="import-dialog__tip">
            支持 .json（UTF-8 数组）与 .csv（表头与字段同名，alt_urls 用竖线分隔）；单文件 ≤ 10MB
          </div>
        </template>
      </el-upload>

      <div v-if="selectedFile" class="import-dialog__file">
        <el-icon><Document /></el-icon>
        <span class="ellipsis">{{ selectedFile.name }}</span>
        <span class="text-secondary">{{ (selectedFile.size / 1024).toFixed(1) }} KB</span>
      </div>

      <div class="import-dialog__options">
        <el-switch v-model="overwrite" active-text="覆盖同名数据源（同 name + 主地址）" />
        <el-button link type="primary" :loading="templateLoading" @click="handleTemplate">
          下载导入模板
        </el-button>
      </div>

      <template v-if="result">
        <el-divider content-position="left">导入结果</el-divider>
        <div class="import-dialog__summary">
          <el-tag type="success" effect="plain">成功 {{ result.success }} 条</el-tag>
          <el-tag type="danger" effect="plain">失败 {{ result.failed }} 条</el-tag>
        </div>
        <el-table :data="result.rows" size="small" max-height="260" class="mt-8">
          <el-table-column prop="line" label="行号" width="70" />
          <el-table-column label="结果" width="90">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.status === 'success' ? 'success' : row.status === 'skipped' ? 'info' : 'danger'"
                effect="plain"
              >
                {{ row.status === 'success' ? '成功' : row.status === 'skipped' ? '跳过' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="说明" min-width="200" show-overflow-tooltip />
        </el-table>
      </template>
    </div>

    <template #footer>
      <el-button @click="handleClose">关闭</el-button>
      <el-button type="primary" :loading="importing" :disabled="!selectedFile" @click="handleImport">
        开始导入
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.import-dialog {
  &__tip {
    font-size: 12px;
    color: $color-text-secondary;
    line-height: 1.6;
    margin-top: 6px;
  }

  &__file {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
    padding: 8px 12px;
    background: $color-bg-page;
    border-radius: $radius-sm;
    font-size: 13px;
  }

  &__options {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 12px;
    gap: 12px;
    flex-wrap: wrap;
  }

  &__summary {
    display: flex;
    gap: 8px;
    margin-bottom: 8px;
  }
}
</style>
