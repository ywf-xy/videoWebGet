<script setup lang="ts">
/**
 * 状态标签（ARCHITECTURE §11.6）：全站唯一的状态文案 / 颜色出口。
 * 禁止在业务组件里直接写 el-tag 的颜色与中文。
 */
import { computed } from 'vue'

import {
  ARTIFACT_STATUS_MAP,
  BATCH_STATUS_MAP,
  TASK_STATUS_MAP,
  type StatusMeta,
} from '@/utils/constants'

const props = withDefaults(
  defineProps<{
    kind?: 'task' | 'batch' | 'artifact'
    status?: string | null
    size?: 'small' | 'default' | 'large'
  }>(),
  { kind: 'task', status: '', size: 'small' },
)

const meta = computed<StatusMeta>(() => {
  const map =
    props.kind === 'batch'
      ? BATCH_STATUS_MAP
      : props.kind === 'artifact'
        ? ARTIFACT_STATUS_MAP
        : TASK_STATUS_MAP
  const key = String(props.status ?? '')
  return map[key] ?? { label: key || '未知', type: 'info' }
})
</script>

<template>
  <el-tag :type="meta.type" :effect="meta.plain ? 'plain' : 'light'" :size="size" disable-transitions>
    {{ meta.label }}
  </el-tag>
</template>
