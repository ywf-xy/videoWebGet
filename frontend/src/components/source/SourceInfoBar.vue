<script setup lang="ts">
/**
 * 数据源信息条（PRD 6.3.2）：名称 / 分类 / 当前网址（可切备用）/ 健康度。
 * 切换地址后顶部提示「已切换至：xxx」，并把 current_url 持久化（下一批次生效）。
 */
import { computed, ref, watch } from 'vue'

import HealthBadge from '@/components/common/HealthBadge.vue'
import { CONTENT_TYPE_MAP } from '@/utils/constants'
import type { DataSourceDetail, HealthResp } from '@/api/types'

const props = defineProps<{
  source: DataSourceDetail | null
  health: HealthResp | null
  loading?: boolean
}>()

const emit = defineEmits<{ (event: 'switch-url', url: string): void }>()

const switchedTip = ref('')

const urlOptions = computed(() => {
  if (!props.source) return []
  const list = [props.source.homepage_url, ...(props.source.alt_urls ?? [])]
  return Array.from(new Set(list.filter(Boolean)))
})

const currentUrl = computed({
  get: () => props.source?.current_url || props.source?.homepage_url || '',
  set: (url: string) => {
    if (!props.source || url === currentUrl.value) return
    switchedTip.value = url
    emit('switch-url', url)
  },
})

const typeLabel = computed(() =>
  props.source && CONTENT_TYPE_MAP[props.source.type]
    ? CONTENT_TYPE_MAP[props.source.type].label
    : '--',
)

const healthScore = computed(() => {
  if (props.health) return props.health.health_score
  return props.source?.health_score ?? null
})

const successRate = computed(() => {
  if (props.health) return props.health.success_rate_20
  return props.source?.success_rate_20 ?? null
})

watch(
  () => props.source?.id,
  () => {
    switchedTip.value = ''
  },
)
</script>

<template>
  <div v-loading="loading" class="source-info card">
    <div class="source-info__main">
      <div class="source-info__title-row">
        <el-tag size="small" effect="plain">{{ typeLabel }}</el-tag>
        <h3 class="source-info__name">{{ source?.name ?? '--' }}</h3>
        <el-tag v-if="source?.category" size="small" type="info" effect="plain">
          {{ source.category }}
        </el-tag>
        <el-tag v-if="source && !source.enabled" size="small" type="danger" effect="plain">
          已停用
        </el-tag>
        <el-tag v-if="source?.is_novel" size="small" type="success" effect="plain">小说类</el-tag>
        <el-tag v-if="source?.script" size="small" type="warning" effect="plain">
          自定义脚本
        </el-tag>
      </div>

      <div class="source-info__url-row">
        <span class="text-secondary source-info__label">当前网址</span>
        <el-select
          v-model="currentUrl"
          class="source-info__select"
          size="small"
          :disabled="!source || !source.enabled"
          placeholder="请选择采集地址"
        >
          <el-option v-for="url in urlOptions" :key="url" :label="url" :value="url" />
        </el-select>
        <el-tooltip content="切换后本批次立即生效，并记录为数据源的当前地址">
          <el-icon class="text-secondary"><QuestionFilled /></el-icon>
        </el-tooltip>
      </div>

      <el-alert
        v-if="switchedTip"
        class="mt-8"
        type="success"
        :closable="true"
        show-icon
        :title="`已切换至：${switchedTip}`"
        @close="switchedTip = ''"
      />
    </div>

    <div class="source-info__aside">
      <div class="source-info__health">
        <span class="text-secondary">健康度</span>
        <HealthBadge :score="healthScore" :success-rate="successRate" show-rate />
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.source-info {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;

  &__main {
    min-width: 0;
    flex: 1;
  }

  &__title-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  &__name {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }

  &__url-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
  }

  &__label {
    flex-shrink: 0;
    font-size: 13px;
  }

  &__select {
    width: 100%;
    max-width: 520px;
  }

  &__aside {
    flex-shrink: 0;
  }

  &__health {
    display: flex;
    flex-direction: column;
    gap: 6px;
    align-items: flex-end;
    font-size: 13px;
  }
}
</style>
