<template>
  <div class="right-panel">
    <n-tabs v-model:value="activeTab" type="line" size="medium" animated class="settings-tabs">
      <n-tab-pane name="worldbuilding" tab="世界观">
        <WorldbuildingPanel :slug="slug" />
      </n-tab-pane>

      <n-tab-pane name="bible" tab="作品设定">
        <BiblePanel :key="bibleKey" :slug="slug" />
      </n-tab-pane>

      <n-tab-pane name="knowledge" tab="知识库">
        <KnowledgePanel :slug="slug" />
      </n-tab-pane>

      <n-tab-pane name="storylines" tab="故事线">
        <StorylinePanel :slug="slug" />
      </n-tab-pane>

      <n-tab-pane name="plot-arc" tab="情节弧线">
        <PlotArcPanel :slug="slug" />
      </n-tab-pane>

      <n-tab-pane name="timeline" tab="时间线">
        <TimelinePanel :slug="slug" />
      </n-tab-pane>
    </n-tabs>

    <!-- Chapter Info Card -->
    <div v-if="currentChapter" class="chapter-info-card">
      <n-card size="small" :bordered="false" title="当前章节">
        <n-space vertical :size="12">
          <div class="info-row">
            <n-text depth="3">章节号:</n-text>
            <n-text strong>第{{ currentChapter.number }}章</n-text>
          </div>
          <div class="info-row">
            <n-text depth="3">标题:</n-text>
            <n-text>{{ currentChapter.title || '未设置' }}</n-text>
          </div>
          <div class="info-row">
            <n-text depth="3">字数:</n-text>
            <n-tag :type="currentChapter.word_count > 0 ? 'success' : 'default'" size="small">
              {{ currentChapter.word_count }} 字
            </n-tag>
          </div>
          <div class="info-row">
            <n-text depth="3">状态:</n-text>
            <n-tag :type="currentChapter.word_count > 0 ? 'success' : 'default'" size="small" round>
              {{ currentChapter.word_count > 0 ? '已收稿' : '未收稿' }}
            </n-tag>
          </div>
        </n-space>
      </n-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import BiblePanel from '../panels/BiblePanel.vue'
import KnowledgePanel from '../knowledge/KnowledgePanel.vue'
import WorldbuildingPanel from './WorldbuildingPanel.vue'
import StorylinePanel from './StorylinePanel.vue'
import PlotArcPanel from './PlotArcPanel.vue'
import TimelinePanel from './TimelinePanel.vue'

interface Chapter {
  id: number
  number: number
  title: string
  word_count: number
}

interface Props {
  slug: string
  /** 与 Workbench 的 `current-panel` 对应 */
  currentPanel?: 'bible' | 'knowledge'
  bibleKey?: number
  currentChapter?: Chapter | null
}

const props = withDefaults(defineProps<Props>(), {
  currentPanel: 'bible',
  bibleKey: 0,
  currentChapter: null,
})

const activeTab = ref<string>(props.currentPanel)

watch(() => props.currentPanel, (newVal) => {
  activeTab.value = newVal
})
</script>

<style scoped>
.right-panel {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--aitext-panel-muted);
  border-left: 1px solid var(--aitext-split-border);
}

.settings-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.settings-tabs :deep(.n-tabs-nav) {
  padding: 0 16px;
  background: var(--app-surface);
  border-bottom: 1px solid var(--aitext-split-border);
}

.settings-tabs :deep(.n-tabs-content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.settings-tabs :deep(.n-tab-pane) {
  height: 100%;
  overflow: hidden;
}

.chapter-info-card {
  padding: 12px;
  border-top: 1px solid var(--aitext-split-border);
  background: var(--app-surface);
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
</style>