<script setup lang="ts">
/**
 * 输出根目录「测试可写」（PRD 6.8 / T18-②）：返回具体 errno 原因，便于用户定位权限/磁盘问题。
 */
import { computed, ref } from 'vue'

import { useSettingStore } from '@/stores/setting'

const props = withDefaults(
  defineProps<{
    modelValue: string
  }>(),
  {},
)

const emit = defineEmits<{ (event: 'update:modelValue', value: string): void }>()

const store = useSettingStore()

const testing = ref(false)
const result = ref<{ writable: boolean; reason: string | null; errno: number | null } | null>(null)

const value = computed({
  get: () => props.modelValue,
  set: (next: string) => emit('update:modelValue', next),
})

async function handleTest(): Promise<void> {
  if (!value.value.trim()) {
    result.value = { writable: false, reason: '路径不能为空', errno: null }
    return
  }
  testing.value = true
  try {
    const data = await store.testPath(value.value.trim())
    result.value = { writable: data.writable, reason: data.reason, errno: data.errno }
  } catch {
    result.value = { writable: false, reason: '测试请求失败，请稍后重试', errno: null }
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="path-tester">
    <div class="path-tester__row">
      <el-input v-model="value" placeholder="例如：D:/crawlerhub/output" clearable>
        <template #prefix>
          <el-icon><FolderOpened /></el-icon>
        </template>
      </el-input>
      <el-button :loading="testing" @click="handleTest">测试可写</el-button>
    </div>

    <el-alert
      v-if="result"
      class="mt-8"
      :type="result.writable ? 'success' : 'error'"
      :closable="false"
      show-icon
      :title="
        result.writable
          ? '目录可写，可以保存'
          : `目录不可写：${result.reason ?? '未知原因'}${result.errno ? `（errno=${result.errno}）` : ''}`
      "
    />
  </div>
</template>

<style scoped lang="scss">
.path-tester {
  width: 100%;

  &__row {
    display: flex;
    gap: 8px;
    align-items: center;
  }
}

.mt-8 {
  margin-top: 8px;
}
</style>
