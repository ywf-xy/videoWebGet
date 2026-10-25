<script setup lang="ts">
/**
 * 上次采集进度卡（PRD 6.3.2 / P0-07）：
 * 「上次采集到：第 N 条（条目名）· 第 M 页 · 时间」，无历史时显示起点引导文案。
 */
import { computed } from 'vue'

import { CONTENT_TYPE_MAP } from '@/utils/constants'
import { formatDateTime, formatNumber } from '@/utils/format'
import type { DataSourceDetail, LatestBatchResp } from '@/api/types'

const props = defineProps<{
  latest: LatestBatchResp | null
  source: DataSourceDetail | null
  type: string
}>()

const hasHistory = computed(() => props.latest?.has_history === true)

const typeMeta = computed(() => CONTENT_TYPE_MAP[props.type])

/** 条目单位：视频=条 / 文字=章 / 图片=个图集 */
const itemUnit = computed(() => {
  if (props.type === 'text') return '章'
  if (props.type === 'image') return '个图集'
  return '条'
})

const lastItemNo = computed(() => props.latest?.last_item_no ?? props.source?.cursor_last_item_no ?? 0)
const lastPage = computed(() => props.latest?.last_page ?? props.source?.cursor_last_page ?? 0)
const lastDate = computed(
  () => props.latest?.last_success_date ?? props.source?.cursor_last_success_date ?? null,
)
</script>

<template>
  <div class="cursor-card card">
    <div class="card-title">
      <div class="card-title__left">
        <span>上次采集进度</span>
        <el-tag v-if="hasHistory" size="small" type="info" effect="plain">
          {{ formatDateTime(latest?.finished_at) }}
        </el-tag>
      </div>
    </div>

    <div v-if="hasHistory" class="cursor-card__grid">
      <div class="cursor-card__item">
        <span class="cursor-card__label">上次采集到</span>
        <span class="cursor-card__value">
          第 {{ formatNumber(lastItemNo) }} {{ itemUnit }}
          <em v-if="latest?.last_item_title" class="cursor-card__sub">
            · {{ latest.last_item_title }}
          </em>
        </span>
      </div>
      <div class="cursor-card__item">
        <span class="cursor-card__label">页码</span>
        <span class="cursor-card__value">第 {{ formatNumber(lastPage) }} 页</span>
      </div>
      <div class="cursor-card__item">
        <span class="cursor-card__label">最后成功日期</span>
        <span class="cursor-card__value">{{ lastDate || '--' }}</span>
      </div>
      <div class="cursor-card__item">
        <span class="cursor-card__label">上次批次成功 / 失败</span>
        <span class="cursor-card__value">
          {{ formatNumber(latest?.done_tasks ?? 0) }} / {{ formatNumber(latest?.failed_tasks ?? 0) }}
        </span>
      </div>
      <div class="cursor-card__item">
        <span class="cursor-card__label">累计成功采集</span>
        <span class="cursor-card__value">
          {{ formatNumber(source?.total_items ?? 0) }}
          {{ typeMeta?.countUnit ?? '条' }}
        </span>
      </div>
    </div>

    <el-alert v-else type="info" :closable="false" show-icon>
      <template #title>暂无历史记录，本次将从起点开始</template>
    </el-alert>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.cursor-card {
  &__grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
  }

  &__item {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px 12px;
    background: $color-bg-page;
    border-radius: $radius-sm;
  }

  &__label {
    font-size: 12px;
    color: $color-text-secondary;
  }

  &__value {
    font-size: 14px;
    font-weight: 600;
    color: $color-text-primary;
    font-variant-numeric: tabular-nums;
  }

  &__sub {
    font-style: normal;
    font-weight: 400;
    color: $color-text-regular;
  }
}
</style>
