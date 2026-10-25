<script setup lang="ts">
/**
 * 解析脚本编辑器（PRD 6.7 新增/编辑抽屉）：等宽字体 + 行号 + 滚动同步。
 * 纯文本编辑，不做代码高亮（本期不引入 CodeMirror，控制体积）。
 */
import { computed, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: string
    height?: string
    placeholder?: string
    readonly?: boolean
  }>(),
  {
    height: '260px',
    placeholder: '请输入解析脚本，例如：\ndef parse(args):\n    ...',
    readonly: false,
  },
)

const emit = defineEmits<{ (event: 'update:modelValue', value: string): void }>()

const gutter = ref<HTMLDivElement | null>(null)
const textarea = ref<HTMLTextAreaElement | null>(null)

const text = computed({
  get: () => props.modelValue ?? '',
  set: (value: string) => emit('update:modelValue', value),
})

const lineCount = computed(() => Math.max(1, text.value.split('\n').length))

function syncScroll(): void {
  if (gutter.value && textarea.value) {
    gutter.value.scrollTop = textarea.value.scrollTop
  }
}

function handleTab(event: KeyboardEvent): void {
  // Tab 插入 4 空格，避免焦点跳走
  event.preventDefault()
  const target = event.target as HTMLTextAreaElement
  const start = target.selectionStart
  const end = target.selectionEnd
  const next = `${text.value.slice(0, start)}    ${text.value.slice(end)}`
  emit('update:modelValue', next)
  requestAnimationFrame(() => {
    target.selectionStart = start + 4
    target.selectionEnd = start + 4
  })
}
</script>

<template>
  <div class="script-editor" :style="{ height }">
    <div ref="gutter" class="script-editor__gutter">
      <div v-for="line in lineCount" :key="line">{{ line }}</div>
    </div>
    <textarea
      ref="textarea"
      v-model="text"
      class="script-editor__area"
      :placeholder="placeholder"
      :readonly="readonly"
      spellcheck="false"
      @scroll="syncScroll"
      @keydown.tab="handleTab"
    />
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.script-editor {
  display: flex;
  border: 1px solid $color-border;
  border-radius: $radius-sm;
  overflow: hidden;
  background: #1e1e1e;
  width: 100%;

  &__gutter {
    flex-shrink: 0;
    width: 44px;
    padding: 10px 8px 10px 0;
    text-align: right;
    color: #6b7280;
    font-family: $font-mono;
    font-size: 12px;
    line-height: 20px;
    background: #252526;
    overflow: hidden;
    user-select: none;
  }

  &__area {
    flex: 1;
    min-width: 0;
    border: none;
    outline: none;
    resize: none;
    padding: 10px 12px;
    background: #1e1e1e;
    color: #d4d4d4;
    font-family: $font-mono;
    font-size: 12px;
    line-height: 20px;
    white-space: pre;
    overflow: auto;
    tab-size: 4;

    &::placeholder {
      color: #6b7280;
    }
  }
}
</style>
