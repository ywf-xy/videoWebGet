<script setup lang="ts">
/**
 * 获取策略表单（PRD 6.3.3 / T16-④）。
 *
 * - 三张卡片式单选，字段随策略切换动态显隐，切换时保留已填值；
 * - 校验不通过 → 「开始爬取」禁用并给出字段级提示；
 * - 线程数为**只读展示**（PRD 6.3.3：只读展示全局值，附「去设置」链接），
 *   因为后端 `POST /api/batches` 不接受 threads，并发由设置页的 max_threads 决定。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { LIMITS, STRATEGY_MAP } from '@/utils/constants'
import type { BatchCreatePayload, ExportFormat, StrategyType } from '@/api/types'

const props = withDefaults(
  defineProps<{
    type: string
    maxThreads: number
    /** 运行中 / 已暂停时锁定表单 */
    disabled?: boolean
    loading?: boolean
    /** 剩余可采条数（来自上次游标，用于 n 的提示） */
    remaining?: number | null
    ffmpegAvailable?: boolean | null
  }>(),
  { disabled: false, loading: false, remaining: null, ffmpegAvailable: null },
)

const emit = defineEmits<{ (event: 'submit', payload: BatchCreatePayload): void }>()

const router = useRouter()

const strategy = ref<StrategyType>('count')
const count = ref<number>(10)
const startPage = ref<number>(1)
const pages = ref<number>(5)
const dateRange = ref<[string, string] | null>(null)
const exportFormat = ref<ExportFormat>('txt')

const isText = computed(() => props.type === 'text')
const ffmpegMissing = computed(() => props.type === 'video' && props.ffmpegAvailable === false)

const countError = computed(() => {
  if (strategy.value !== 'count') return ''
  if (count.value === null || Number.isNaN(count.value)) return '请填写条数'
  if (count.value < 1) return '条数需 ≥ 1'
  if (count.value > LIMITS.countMax) return `条数不能超过 ${LIMITS.countMax}`
  return ''
})

const pageError = computed(() => {
  if (strategy.value !== 'page') return ''
  if (startPage.value === null || Number.isNaN(startPage.value) || startPage.value < 1) {
    return '起始页需 ≥ 1'
  }
  if (pages.value === null || Number.isNaN(pages.value)) return '请填写页数'
  if (pages.value < 1 || pages.value > LIMITS.pagesMax) return `页数需在 1-${LIMITS.pagesMax} 之间`
  return ''
})

const dateError = computed(() => {
  if (strategy.value !== 'date') return ''
  if (!dateRange.value || dateRange.value.length !== 2) return '请选择开始与结束日期'
  const [from, to] = dateRange.value
  if (!from || !to) return '请选择开始与结束日期'
  const startTime = new Date(`${from}T00:00:00`).getTime()
  const endTime = new Date(`${to}T00:00:00`).getTime()
  if (Number.isNaN(startTime) || Number.isNaN(endTime)) return '日期格式不合法'
  if (endTime < startTime) return '结束日期不能早于开始日期'
  const span = Math.round((endTime - startTime) / 86400000)
  if (span > LIMITS.dateSpanDays) return `日期跨度不能超过 ${LIMITS.dateSpanDays} 天`
  return ''
})

const errorText = computed(() => countError.value || pageError.value || dateError.value)

const countHint = computed(() => {
  if (strategy.value !== 'count') return ''
  if (props.remaining === null || props.remaining === undefined || props.remaining <= 0) return ''
  if (count.value > props.remaining) {
    return `上次记录之后仅剩 ${props.remaining} 条，超出部分会以「已到列表末尾」告警结束`
  }
  return `上次记录之后约有 ${props.remaining} 条可采`
})

const canSubmit = computed(
  () => !props.disabled && !props.loading && errorText.value === '' && !ffmpegMissing.value,
)

function buildPayload(): BatchCreatePayload {
  const params: Record<string, unknown> = {}
  if (strategy.value === 'count') {
    params.n = Number(count.value)
  } else if (strategy.value === 'page') {
    params.start = Number(startPage.value)
    params.pages = Number(pages.value)
  } else if (dateRange.value) {
    params.from = dateRange.value[0]
    params.to = dateRange.value[1]
  }
  return {
    data_source_id: 0, // 由父组件补全
    strategy: strategy.value,
    strategy_params: params,
    export_format: isText.value ? exportFormat.value : null,
  }
}

function handleSubmit(): void {
  if (!canSubmit.value) return
  emit('submit', buildPayload())
}

function goSettings(): void {
  router.push('/settings')
}

// 文字类型才显示导出格式，切走时保持默认值
watch(isText, (value) => {
  if (!value) exportFormat.value = 'txt'
})
</script>

<template>
  <div class="strategy card">
    <div class="card-title">
      <div class="card-title__left">
        <span>获取策略</span>
        <el-tag size="small" type="info" effect="plain">保存后立即开始解析列表</el-tag>
      </div>
      <el-tooltip content="并发由「设置 → 最大线程数」统一控制，修改后新批次立即生效">
        <span class="text-secondary">线程数：{{ maxThreads }}</span>
      </el-tooltip>
    </div>

    <el-alert
      v-if="ffmpegMissing"
      class="mb-12"
      type="error"
      :closable="false"
      show-icon
      title="未检测到 ffmpeg，视频任务无法转为 MP4"
      description="当前环境只能产出可播放的 .ts 文件，任务会标记失败(3003)。请安装 ffmpeg 并加入 PATH 后重试。"
    />

    <el-radio-group v-model="strategy" class="strategy__group" :disabled="disabled">
      <div
        v-for="item in STRATEGY_MAP"
        :key="item.value"
        class="strategy__card"
        :class="{ 'strategy__card--active': strategy === item.value }"
        @click="strategy = item.value"
      >
        <el-radio :value="item.value" class="strategy__radio">
          <span class="strategy__card-title">
            <el-icon><component :is="item.icon" /></el-icon>
            {{ item.label }}
          </span>
        </el-radio>
        <p class="strategy__card-desc">{{ item.desc }}</p>
      </div>
    </el-radio-group>

    <div class="strategy__fields">
      <template v-if="strategy === 'count'">
        <el-form-item label="条数" :error="countError">
          <el-input-number
            v-model="count"
            :min="1"
            :max="LIMITS.countMax"
            :step="1"
            step-strictly
            :disabled="disabled"
            controls-position="right"
            class="strategy__number"
          />
          <span class="strategy__hint">爬取上次记录之后的 n 条</span>
        </el-form-item>
        <p v-if="countHint" class="strategy__notice">{{ countHint }}</p>
      </template>

      <template v-else-if="strategy === 'page'">
        <el-form-item label="起始页" :error="pageError">
          <el-input-number
            v-model="startPage"
            :min="1"
            :step="1"
            step-strictly
            :disabled="disabled"
            controls-position="right"
            class="strategy__number"
          />
        </el-form-item>
        <el-form-item label="页数">
          <el-input-number
            v-model="pages"
            :min="1"
            :max="LIMITS.pagesMax"
            :step="1"
            step-strictly
            :disabled="disabled"
            controls-position="right"
            class="strategy__number"
          />
          <span class="strategy__hint">从起始页连续取 N 页，超出最后一页会自动截断</span>
        </el-form-item>
      </template>

      <template v-else>
        <el-form-item label="日期区间" :error="dateError">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            :disabled="disabled"
            :clearable="false"
          />
          <span class="strategy__hint">会自动过滤已成功过的条目</span>
        </el-form-item>
      </template>

      <el-form-item v-if="isText" label="导出格式">
        <el-radio-group v-model="exportFormat" :disabled="disabled">
          <el-radio-button value="txt">TXT</el-radio-button>
          <el-radio-button value="pdf">PDF</el-radio-button>
        </el-radio-group>
        <span class="strategy__hint">PDF 生成失败时会自动保留 TXT</span>
      </el-form-item>

      <el-form-item label="并发线程">
        <span class="strategy__thread">{{ maxThreads }}</span>
        <el-button link type="primary" size="small" @click="goSettings">去设置</el-button>
        <span class="strategy__hint">全局上限，同一时刻最多跑这么多个任务</span>
      </el-form-item>
    </div>

    <div class="strategy__footer">
      <el-button
        type="primary"
        size="large"
        :disabled="!canSubmit"
        :loading="loading"
        @click="handleSubmit"
      >
        <el-icon v-if="!loading"><VideoPlay /></el-icon>
        开始爬取
      </el-button>
      <span v-if="errorText" class="text-danger strategy__error">{{ errorText }}</span>
      <span v-else-if="disabled" class="text-secondary strategy__error">
        批次运行中，策略表单已锁定
      </span>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.strategy {
  &__group {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 12px;
    width: 100%;
    margin-bottom: 16px;
  }

  &__card {
    display: block;
    border: 1px solid $color-border;
    border-radius: $radius-card;
    padding: 12px 14px;
    cursor: pointer;
    transition: all 0.2s ease;
    margin: 0;

    &:hover {
      border-color: $color-primary;
      box-shadow: $shadow-card;
    }

    &--active {
      border-color: $color-primary;
      background: #f2f8ff;
    }
  }

  &__radio {
    width: 100%;
    height: auto;

    :deep(.el-radio__label) {
      width: 100%;
    }
  }

  &__card-title {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-weight: 600;
    color: $color-text-primary;
  }

  &__card-desc {
    margin: 6px 0 0 22px;
    font-size: 12px;
    color: $color-text-secondary;
    line-height: 1.5;
  }

  &__fields {
    border-top: 1px dashed $color-border-light;
    padding-top: 16px;

    :deep(.el-form-item) {
      margin-bottom: 14px;
    }
  }

  &__number {
    width: 160px;
  }

  &__hint {
    margin-left: 10px;
    font-size: 12px;
    color: $color-text-secondary;
  }

  &__notice {
    margin: -6px 0 12px;
    font-size: 12px;
    color: $color-warning;
  }

  &__thread {
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    margin-right: 6px;
  }

  &__footer {
    display: flex;
    align-items: center;
    gap: 12px;
    border-top: 1px dashed $color-border-light;
    padding-top: 16px;
  }

  &__error {
    font-size: 13px;
  }
}
</style>
