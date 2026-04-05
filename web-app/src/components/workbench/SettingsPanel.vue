<template>
  <div class="right-panel">
    <!-- 一级分组切换 -->
    <div class="group-bar">
      <n-radio-group v-model:value="activeGroup" size="small" class="group-switch">
        <n-radio-button value="settings">创作设定</n-radio-button>
        <n-radio-button value="tools">辅助工具</n-radio-button>
      </n-radio-group>
      <n-text v-if="currentChapter" depth="3" style="font-size:11px;flex-shrink:0">
        第{{ currentChapter.number }}章
        <n-tag :type="currentChapter.word_count > 0 ? 'success' : 'default'" size="tiny" round style="margin-left:4px">
          {{ currentChapter.word_count > 0 ? '已收稿' : '未收稿' }}
        </n-tag>
      </n-text>
    </div>

    <!-- 创作设定：世界观 / 作品设定 / 知识库 / 故事线 / 情节弧线 / 时间线 / 伏笔 -->
    <n-tabs
      v-if="activeGroup === 'settings'"
      v-model:value="settingsTab"
      type="line"
      size="small"
      class="settings-tabs"
      :tabs-padding="8"
    >
      <n-tab-pane name="bible" tab="作品设定">
        <BiblePanel :key="bibleKey" :slug="slug" />
      </n-tab-pane>
      <n-tab-pane name="worldbuilding" tab="世界观">
        <WorldbuildingPanel :slug="slug" />
      </n-tab-pane>
      <n-tab-pane name="knowledge" tab="知识库">
        <KnowledgePanel :slug="slug" />
      </n-tab-pane>
      <n-tab-pane name="storylines" tab="故事线">
        <StorylinePanel :slug="slug" />
      </n-tab-pane>
      <n-tab-pane name="plot-arc" tab="情节弧">
        <PlotArcPanel :slug="slug" />
      </n-tab-pane>
      <n-tab-pane name="timeline" tab="时间线">
        <TimelinePanel :slug="slug" />
      </n-tab-pane>
      <n-tab-pane name="foreshadow" tab="伏笔">
        <ForeshadowLedgerPanel :slug="slug" />
      </n-tab-pane>
    </n-tabs>

    <!-- 辅助工具：章节元素 / 对话沙盒 / 重构扫描 / 文风漂移 -->
    <n-tabs
      v-if="activeGroup === 'tools'"
      v-model:value="toolsTab"
      type="line"
      size="small"
      class="settings-tabs"
      :tabs-padding="8"
    >
      <n-tab-pane name="chapter-elements" tab="章节元素">
        <ChapterElementPanel
          :slug="slug"
          :current-chapter-number="currentChapter?.number ?? null"
        />
      </n-tab-pane>
      <n-tab-pane name="sandbox" tab="对话沙盒">
        <SandboxDialoguePanel :slug="slug" />
      </n-tab-pane>
      <n-tab-pane name="voice-drift" tab="文风漂移">
        <VoiceDriftPanel :slug="slug" />
      </n-tab-pane>
      <n-tab-pane name="macro-refactor" tab="重构扫描">
        <MacroRefactorPanel :slug="slug" />
      </n-tab-pane>
    </n-tabs>
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
import ForeshadowLedgerPanel from './ForeshadowLedgerPanel.vue'
import MacroRefactorPanel from './MacroRefactorPanel.vue'
import ChapterElementPanel from './ChapterElementPanel.vue'
import SandboxDialoguePanel from './SandboxDialoguePanel.vue'
import VoiceDriftPanel from './VoiceDriftPanel.vue'

const SETTINGS_TABS = new Set(['bible', 'worldbuilding', 'knowledge', 'storylines', 'plot-arc', 'timeline', 'foreshadow'])
const TOOLS_TABS = new Set(['chapter-elements', 'sandbox', 'voice-drift', 'macro-refactor'])

interface Chapter {
  id: number
  number: number
  title: string
  word_count: number
}

interface Props {
  slug: string
  currentPanel?: string
  bibleKey?: number
  currentChapter?: Chapter | null
}

const props = withDefaults(defineProps<Props>(), {
  currentPanel: 'bible',
  bibleKey: 0,
  currentChapter: null,
})

const activeGroup = ref<'settings' | 'tools'>(
  TOOLS_TABS.has(props.currentPanel ?? '') ? 'tools' : 'settings'
)
const settingsTab = ref(SETTINGS_TABS.has(props.currentPanel ?? '') ? props.currentPanel! : 'bible')
const toolsTab = ref(TOOLS_TABS.has(props.currentPanel ?? '') ? props.currentPanel! : 'chapter-elements')

watch(() => props.currentPanel, (newVal) => {
  if (!newVal) return
  if (TOOLS_TABS.has(newVal)) {
    activeGroup.value = 'tools'
    toolsTab.value = newVal
  } else {
    activeGroup.value = 'settings'
    settingsTab.value = newVal
  }
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

.group-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 10px;
  background: var(--app-surface);
  border-bottom: 1px solid var(--aitext-split-border);
  flex-shrink: 0;
}

.group-switch {
  flex-shrink: 0;
}

.settings-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.settings-tabs :deep(.n-tabs-nav) {
  padding: 0 8px;
  background: var(--app-surface);
  border-bottom: 1px solid var(--aitext-split-border);
  overflow-x: auto;
  scrollbar-width: none;
}
.settings-tabs :deep(.n-tabs-nav::-webkit-scrollbar) {
  display: none;
}

.settings-tabs :deep(.n-tabs-content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* Naive UI 动画容器，必须锁死不让溢出覆盖 tab 导航栏 */
.settings-tabs :deep(.n-tabs-content-wrapper) {
  height: 100%;
  overflow: hidden;
}

.settings-tabs :deep(.n-tabs-pane-wrapper) {
  height: 100%;
  overflow: hidden;
}

.settings-tabs :deep(.n-tab-pane) {
  height: 100%;
  overflow: hidden;
}
</style>