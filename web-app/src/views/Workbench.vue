<template>
  <div class="workbench">
    <n-spin :show="pageLoading" class="workbench-spin" description="加载工作台…">
      <div class="workbench-inner">
        <n-split direction="horizontal" :min="0.14" :max="0.42" :default-size="0.22">
          <template #1>
            <ChapterList
              :slug="slug"
              :chapters="chapters"
              :current-chapter-id="currentChapterId"
              @select="goToChapter"
              @back="goHome"
            />
          </template>

          <template #2>
            <n-split direction="horizontal" :min="0.28" :max="0.72" :default-size="0.55">
              <template #1>
                <ChatArea
                  ref="chatAreaRef"
                  :slug="slug"
                  :book-title="bookTitle"
                  :chapters="chapters"
                  :current-chapter-id="currentChapterId"
                  @set-right-panel="setRightPanel"
                  @open-plan-modal="openPlanModal"
                  @start-write="startWrite"
                  @messages-updated="onMessagesUpdated"
                />
              </template>

              <template #2>
                <SettingsPanel :slug="slug" :current-panel="rightPanel" :bible-key="biblePanelKey" />
              </template>
            </n-split>
          </template>
        </n-split>
      </div>
    </n-spin>

    <n-modal
      v-model:show="showPlanModal"
      preset="card"
      style="width: min(460px, 94vw)"
      :mask-closable="false"
      title="结构规划"
    >
      <n-space vertical :size="16">
        <n-text depth="3">
          首次生成适用于尚无圣经与大纲；「再规划」会结合滚动摘要、编务远期摘要与已完成章节信息，修订 bible 与分章大纲。
        </n-text>
        <n-radio-group v-model:value="planMode">
          <n-space vertical :size="8">
            <n-radio value="initial">首次生成圣经与分章大纲</n-radio>
            <n-radio value="revise" :disabled="!hasStructure">基于进度再规划（需已有 bible / outline）</n-radio>
          </n-space>
        </n-radio-group>
        <n-checkbox v-model:checked="planDryRun">预演（dry-run，不调用模型）</n-checkbox>
        <n-space justify="end" :size="10">
          <n-button @click="showPlanModal = false">取消</n-button>
          <n-button type="primary" @click="confirmPlan">开始</n-button>
        </n-space>
      </n-space>
    </n-modal>

    <n-modal
      v-model:show="showTaskModal"
      preset="card"
      style="width: min(420px, 92vw)"
      :mask-closable="false"
      :segmented="{ content: true }"
      title="任务进行中"
    >
      <n-space vertical :size="16">
        <n-progress type="line" :percentage="taskProgress" :processing="taskProgress < 100" :height="10" />
        <n-text>{{ taskMessage }}</n-text>
        <n-button size="small" secondary @click="cancelRunningTask">终止任务</n-button>
      </n-space>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { bookApi, jobApi } from '../api/book'
import ChapterList from '../components/workbench/ChapterList.vue'
import ChatArea from '../components/workbench/ChatArea.vue'
import SettingsPanel from '../components/workbench/SettingsPanel.vue'

const route = useRoute()
const router = useRouter()
const message = useMessage()

const slug = route.params.slug as string
const bookTitle = ref('')
const chapters = ref<any[]>([])

const rightPanel = ref<'bible' | 'knowledge'>('knowledge')
const biblePanelKey = ref(0)
const pageLoading = ref(true)

const chatAreaRef = ref<InstanceType<typeof ChatArea> | null>(null)

const showPlanModal = ref(false)
const planMode = ref<'initial' | 'revise'>('initial')
const planDryRun = ref(false)
const bookMeta = ref<{ has_bible?: boolean; has_outline?: boolean }>({})
const hasStructure = computed<boolean>(
  () => !!(bookMeta.value.has_bible && bookMeta.value.has_outline)
)

const showTaskModal = ref(false)
const taskProgress = ref(0)
const taskMessage = ref('')
const currentJobId = ref<string | null>(null)
let taskTimer: number | null = null

const currentChapterId = computed(() => {
  if (route.name === 'Chapter') return Number(route.params.id)
  return null
})

const setRightPanel = (p: 'bible' | 'knowledge') => {
  rightPanel.value = p
}

const onMessagesUpdated = () => {
  // Messages have been updated in ChatArea, trigger any parent-side updates if needed
}

const loadDesk = async () => {
  const res = await bookApi.getDesk(slug)
  bookTitle.value = res.book?.title || slug
  chapters.value = res.chapters || []
  bookMeta.value = {
    has_bible: res.book?.has_bible,
    has_outline: res.book?.has_outline,
  }
}

const openPlanModal = () => {
  planMode.value = hasStructure.value ? 'revise' : 'initial'
  planDryRun.value = false
  showPlanModal.value = true
}

const confirmPlan = async () => {
  showPlanModal.value = false
  try {
    const res = await jobApi.startPlan(slug, planDryRun.value, planMode.value)
    startPolling(res.job_id)
  } catch (error: any) {
    message.error(error.response?.data?.detail || '启动失败')
  }
}

const startWrite = async () => {
  try {
    const res = await jobApi.startWrite(slug, 1)
    startPolling(res.job_id)
  } catch (error: any) {
    message.error(error.response?.data?.detail || '启动失败')
  }
}

const startPolling = (jobId: string) => {
  currentJobId.value = jobId
  showTaskModal.value = true
  taskProgress.value = 6
  taskMessage.value = '任务启动中…'
  let bump = 6

  taskTimer = window.setInterval(async () => {
    bump = Math.min(93, bump + 2 + Math.random() * 6)
    taskProgress.value = Math.floor(bump)
    try {
      const status = await jobApi.getStatus(jobId)
      taskMessage.value = status.message || status.phase || '执行中…'

      if (status.status === 'done') {
        taskProgress.value = 100
        stopPolling()
        message.success('任务完成')
        await loadDesk()
        await chatAreaRef.value?.fetchMessages()
        biblePanelKey.value += 1
      } else if (status.status === 'cancelled') {
        taskProgress.value = 100
        stopPolling()
        message.info('任务已终止')
        await loadDesk()
      } else if (status.status === 'error') {
        stopPolling()
        message.error(status.error || '任务失败')
      }
    } catch {
      stopPolling()
    }
  }, 1000)
}

const cancelRunningTask = async () => {
  const jid = currentJobId.value
  if (!jid) return
  try {
    await jobApi.cancelJob(jid)
    taskMessage.value = '正在终止…'
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '终止失败')
  }
}

const stopPolling = () => {
  if (taskTimer) {
    clearInterval(taskTimer)
    taskTimer = null
  }
  currentJobId.value = null
  showTaskModal.value = false
}

const goHome = () => {
  router.push('/')
}

const goToChapter = (id: number) => {
  router.push(`/book/${slug}/chapter/${id}`)
}

onMounted(async () => {
  try {
    await loadDesk()
  } catch {
    message.error('加载失败，请检查网络与后端是否已启动')
    bookTitle.value = slug
  } finally {
    pageLoading.value = false
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.workbench {
  height: 100vh;
  min-height: 0;
  background: var(--app-page-bg, #f0f2f8);
}

.workbench-spin {
  height: 100%;
  min-height: 0;
}

.workbench-spin :deep(.n-spin-content) {
  min-height: 100%;
  height: 100%;
}

.workbench-inner {
  height: 100%;
  min-height: 0;
}

.workbench-inner :deep(.n-split) {
  height: 100%;
}

.workbench-inner :deep(.n-split-pane-1) {
  min-height: 0;
  overflow: hidden;
}
</style>
