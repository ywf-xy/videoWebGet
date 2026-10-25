<script setup lang="ts">
/**
 * 设置页危险操作区（PRD 6.8 / T18）：清空历史任务日志（保留近 N 天）、重建统计缓存。
 * 两项都必须二次确认，成功后回写提示。
 */
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { useSettingStore } from '@/stores/setting'

const emit = defineEmits<{ (event: 'changed'): void }>()

const store = useSettingStore()
const keepDays = ref(7)
const purging = ref(false)
const rebuilding = ref(false)

async function handlePurge(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `将永久删除 ${keepDays.value} 天前的任务日志，删除后不可恢复。是否继续？`,
      '清空历史日志',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  purging.value = true
  try {
    const deleted = await store.purgeLogs(keepDays.value)
    ElMessage.success(`已清理 ${deleted} 条历史日志`)
    emit('changed')
  } finally {
    purging.value = false
  }
}

async function handleRebuild(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '将重新计算全部数据源的健康度与近 20 次成功率。耗时与数据源数量相关，是否继续？',
      '重建统计缓存',
      { type: 'warning', confirmButtonText: '重建', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  rebuilding.value = true
  try {
    const updated = await store.rebuildStats()
    ElMessage.success(`已重建 ${updated} 个数据源的统计`)
    emit('changed')
  } finally {
    rebuilding.value = false
  }
}
</script>

<template>
  <div class="danger-zone">
    <div class="danger-zone__item">
      <div class="danger-zone__info">
        <span class="danger-zone__title">清空历史任务日志</span>
        <span class="text-secondary">
          仅保留最近 N 天的任务日志，更早的记录会被永久删除（批次与产物不受影响）
        </span>
      </div>
      <div class="danger-zone__actions">
        <el-input-number v-model="keepDays" :min="0" :max="365" size="small" style="width: 110px" />
        <span class="text-secondary">天</span>
        <el-button type="danger" plain :loading="purging" @click="handlePurge">清空日志</el-button>
      </div>
    </div>

    <el-divider />

    <div class="danger-zone__item">
      <div class="danger-zone__info">
        <span class="danger-zone__title">重建统计缓存</span>
        <span class="text-secondary">
          按「近 20 次成功率 × 70% + 最近成功时间衰减 × 30%」重算所有数据源的健康分
        </span>
      </div>
      <div class="danger-zone__actions">
        <el-button type="warning" plain :loading="rebuilding" @click="handleRebuild">
          重建统计
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.danger-zone {
  &__item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }

  &__info {
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-width: 560px;
    font-size: 13px;
  }

  &__title {
    font-weight: 600;
    color: $color-text-primary;
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }
}
</style>
