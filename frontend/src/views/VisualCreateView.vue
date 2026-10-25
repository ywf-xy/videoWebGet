<script setup lang="ts">
/**
 * 可视化创建占位页（PRD P2-01）：本期仅提供入口与能力预告，不影响其他功能。
 */
import { useRouter } from 'vue-router'

import PageHeader from '@/components/common/PageHeader.vue'

const router = useRouter()

const previews = [
  {
    icon: 'Pointer',
    title: '点选式字段映射',
    desc: '在页面上直接点选列表项、标题、正文与图片，自动生成选择器配置',
  },
  {
    icon: 'MagicStick',
    title: '站点结构识别',
    desc: '自动识别分页结构、详情页跳转方式与 m3u8 地址位置',
  },
  {
    icon: 'Files',
    title: '一键生成解析脚本',
    desc: '把点选结果固化为可复用的解析脚本，随时二次编辑',
  },
]
</script>

<template>
  <div class="page visual-create">
    <PageHeader title="可视化创建数据源" description="P2-01 能力预告，敬请期待" icon="MagicStick">
      <template #extra>
        <el-button @click="router.push('/data-sources')">
          <el-icon><Back /></el-icon>
          返回数据源页
        </el-button>
      </template>
    </PageHeader>

    <div class="card visual-create__hero">
      <el-icon :size="42" class="visual-create__icon"><MagicStick /></el-icon>
      <h3 class="visual-create__title">敬请期待</h3>
      <p class="visual-create__desc">
        本期请通过「手动新增」或「导入 JSON / CSV」维护数据源；
        可视化创建将在后续版本提供，不影响现有采集能力。
      </p>
      <div class="visual-create__actions">
        <el-button type="primary" @click="router.push('/data-sources')">去手动新增</el-button>
        <el-button @click="router.push({ path: '/data-sources', query: { import: '1' } })">
          去导入文件
        </el-button>
      </div>
    </div>

    <el-row :gutter="16" class="mt-16">
      <el-col v-for="item in previews" :key="item.title" :xs="24" :md="8">
        <div class="card visual-create__preview">
          <el-icon :size="20" class="visual-create__preview-icon"><component :is="item.icon" /></el-icon>
          <span class="visual-create__preview-title">{{ item.title }}</span>
          <span class="text-secondary">{{ item.desc }}</span>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.visual-create {
  &__hero {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding: 48px 24px;
    text-align: center;
  }

  &__icon {
    color: $color-primary;
  }

  &__title {
    margin: 0;
    font-size: 20px;
    font-weight: 600;
  }

  &__desc {
    margin: 0;
    max-width: 560px;
    color: $color-text-secondary;
    line-height: 1.7;
  }

  &__actions {
    margin-top: 8px;
    display: flex;
    gap: 8px;
  }

  &__preview {
    display: flex;
    flex-direction: column;
    gap: 6px;
    height: 100%;
    font-size: 13px;
  }

  &__preview-icon {
    color: $color-primary;
  }

  &__preview-title {
    font-weight: 600;
    color: $color-text-primary;
  }
}
</style>
