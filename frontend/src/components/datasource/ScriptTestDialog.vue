<script setup lang="ts">
/**
 * 脚本试运行弹窗（PRD P1-02 / T17-⑥）：对单个网址试运行，回显前 5 条解析结果与字段名。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import EmptyState from '@/components/common/EmptyState.vue'
import { testScript } from '@/api/dataSource'
import type { ScriptTestResp } from '@/api/types'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    sourceId: number | null
    script: string
    entry?: string
    defaultUrl?: string
  }>(),
  { entry: 'parse', defaultUrl: '' },
)

const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const url = ref('')
const loading = ref(false)
const result = ref<ScriptTestResp | null>(null)
const errorText = ref('')

async function run(): Promise<void> {
  if (!props.sourceId) {
    ElMessage.warning('请先保存数据源后再试运行')
    return
  }
  if (!url.value.trim()) {
    ElMessage.warning('请输入要试运行的网址')
    return
  }
  loading.value = true
  errorText.value = ''
  result.value = null
  try {
    result.value = await testScript(props.sourceId, props.script, url.value.trim(), props.entry)
    if (result.value.count === 0) {
      ElMessage.warning('解析成功但未取到条目，请检查选择器或脚本')
    }
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : '试运行失败'
  } finally {
    loading.value = false
  }
}

function sampleColumns(sample: Record<string, unknown>): string[] {
  return Object.keys(sample)
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    url.value = props.defaultUrl
    result.value = null
    errorText.value = ''
  },
)
</script>

<template>
  <el-dialog v-model="visible" title="脚本试运行" width="680px" :destroy-on-close="true">
    <div class="script-test">
      <div class="script-test__row">
        <el-input v-model="url" placeholder="要试运行的网址（列表页地址）" clearable>
          <template #prefix>
            <el-icon><Link /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" :loading="loading" @click="run">开始试运行</el-button>
      </div>

      <el-alert
        class="mt-12"
        type="info"
        :closable="false"
        show-icon
        title="试运行会真实请求该网址，超时时间 60s；成功时回显前 5 条解析结果"
      />

      <el-alert v-if="errorText" class="mt-12" type="error" :closable="false" show-icon :title="errorText" />

      <template v-if="result">
        <div class="script-test__summary mt-12">
          <el-tag type="success" effect="plain">解析到 {{ result.count }} 条</el-tag>
          <el-tag v-for="field in result.fields" :key="field" type="info" effect="plain">
            {{ field }}
          </el-tag>
        </div>

        <el-table
          v-if="result.samples.length > 0"
          :data="result.samples"
          size="small"
          class="mt-12"
          max-height="320"
        >
          <el-table-column
            v-for="column in sampleColumns(result.samples[0])"
            :key="column"
            :prop="column"
            :label="column"
            min-width="140"
            show-overflow-tooltip
          />
        </el-table>

        <EmptyState
          v-else
          compact
          icon="Search"
          title="未解析到条目"
          description="请检查选择器配置，或脚本返回的 items 结构"
        />
      </template>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.script-test {
  &__row {
    display: flex;
    gap: 8px;
  }

  &__summary {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
}

.mt-12 {
  margin-top: 12px;
}
</style>
