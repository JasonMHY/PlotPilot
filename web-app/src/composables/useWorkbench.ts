import { ref, computed, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { bookApi, jobApi } from '../api/book'
import { novelApi } from '../api/novel'
import { chapterApi } from '../api/chapter'
import { useStatsStore } from '../stores/statsStore'

// Constants for magic numbers
const PROGRESS_INITIAL = 6
const PROGRESS_MAX = 93
const PROGRESS_MIN_STEP = 2
const PROGRESS_MAX_STEP = 6
const STATS_DAYS = 30
const DEFAULT_CHAPTER_ID = 1
const POLLING_INTERVAL = 1000

// Type definitions
export interface BookMeta {
  has_bible?: boolean
  has_outline?: boolean
}

export interface UseWorkbenchOptions {
  slug: string
  chatAreaRef?: { fetchMessages?: () => Promise<void> } | null
}

export function useWorkbench(options: UseWorkbenchOptions) {
  const { slug, chatAreaRef } = options
  const router = useRouter()
  const message = useMessage()
  const statsStore = useStatsStore()

  // State - Business logic only, no UI state
  const bookTitle = ref('')
  const chapters = ref<{ id: number; title: string }[]>([])
  const bookMeta = ref<BookMeta>({})
  const pageLoading = ref(true)

  // UI state that should be in components, not composable
  // Kept for backward compatibility but marked for future migration
  const rightPanel = ref<'bible' | 'knowledge'>('knowledge')
  const biblePanelKey = ref(0)
  const showPlanModal = ref(false)
  const planMode = ref<'initial' | 'revise'>('initial')
  const planDryRun = ref(false)
  const showTaskModal = ref(false)
  const taskProgress = ref(0)
  const taskMessage = ref('')
  const currentJobId = ref<string | null>(null)


  const currentChapterId = computed(() => {
    // This will be provided by the route in the component
    return null
  })

  const hasStructure = computed(() => {
    return bookMeta.value.has_bible || bookMeta.value.has_outline
  })

  // Methods
  const setRightPanel = (panel: 'bible' | 'knowledge') => {
    rightPanel.value = panel
  }

  const loadDesk = async () => {
    // Use new novelApi and chapterApi instead of bookApi.getDesk
    const [novelData, chaptersData] = await Promise.all([
      novelApi.getNovel(slug),
      chapterApi.listChapters(slug)
    ])

    bookTitle.value = novelData.title || slug

    // Map ChapterDTO[] to the format expected by the UI
    chapters.value = chaptersData.map(ch => ({
      id: ch.number,
      title: ch.title
    }))

    // Note: has_bible and has_outline are not in NovelDTO yet
    // For now, we'll need to keep using bookApi.getDesk or add these fields to NovelDTO
    // Temporary: fetch from old API for metadata
    const deskData = await bookApi.getDesk(slug)
    bookMeta.value = {
      has_bible: deskData.book?.has_bible,
      has_outline: deskData.book?.has_outline,
    }
  }

  const loadData = async (includeStats = false) => {
    pageLoading.value = true
    try {
      // Parallel API calls for performance
      const promises = [loadDesk()]
      if (includeStats) {
        promises.push(statsStore.loadBookAllStats(slug, STATS_DAYS, true))
      }
      await Promise.all(promises)
    } finally {
      pageLoading.value = false
    }
  }

  const handleJobCompleted = async () => {
    // Notify stats store to invalidate cache and reload
    statsStore.onJobCompleted(slug)
    // Refresh workbench data
    await loadDesk()
    // Refresh chat messages if reference available
    await chatAreaRef?.fetchMessages?.()
    // Force Bible panel refresh if visible
    if (rightPanel.value === 'bible') {
      biblePanelKey.value += 1
    }
  }

  const restoreJobState = () => {
    // Note: localStorage recovery not currently used in the architecture
    // Job state is managed through API polling and component lifecycle
    // This method is a no-op but preserved for future expansion
  }

  const openPlanModal = () => {
    planMode.value = (bookMeta.value.has_bible && bookMeta.value.has_outline) ? 'revise' : 'initial'
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
      const res = await jobApi.startWrite(slug, DEFAULT_CHAPTER_ID)
      startPolling(res.job_id)
    } catch (error: any) {
      message.error(error.response?.data?.detail || '启动失败')
    }
  }

  // Polling logic - Should be migrated to JobStatusIndicator component per spec
  // Kept here for backward compatibility during refactoring
  const taskTimer = ref<number | null>(null)

  const startPolling = (jobId: string) => {
    currentJobId.value = jobId
    showTaskModal.value = true
    taskProgress.value = PROGRESS_INITIAL
    taskMessage.value = '任务启动中…'
    let bump = PROGRESS_INITIAL

    // Clear any existing timer to prevent memory leaks
    if (taskTimer.value) {
      window.clearInterval(taskTimer.value)
      taskTimer.value = null
    }

    taskTimer.value = window.setInterval(async () => {
      bump = Math.min(PROGRESS_MAX, bump + PROGRESS_MIN_STEP + Math.random() * PROGRESS_MAX_STEP)
      taskProgress.value = Math.floor(bump)
      try {
        const status = await jobApi.getStatus(jobId)
        taskMessage.value = status.message || status.phase || '执行中…'

        if (status.status === 'done') {
          taskProgress.value = 100
          stopPolling()
          message.success('任务完成')
          await handleJobCompleted()
        } else if (status.status === 'cancelled') {
          taskProgress.value = 100
          stopPolling()
          message.info('任务已终止')
          await loadDesk()
        } else if (status.status === 'error') {
          stopPolling()
          message.error(status.error || '任务失败')
        }
      } catch (error) {
        console.error('Polling error:', error)
        stopPolling()
        message.error('任务状态更新失败')
      }
    }, POLLING_INTERVAL)
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
    if (taskTimer.value) {
      window.clearInterval(taskTimer.value)
      taskTimer.value = null
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

  const handleChapterSelect = (chapterId: number) => {
    // Chapter selection is handled through routing
    // This method provides a consistent interface
    goToChapter(chapterId)
  }

  const handleSendMessage = async (content: string) => {
    // Message sending is handled by ChatArea component
    // This method provides a consistent interface for future use
    // Currently, ChatArea manages its own message state
  }

  const handleUpdateSettings = async (settings: Record<string, any>) => {
    // Settings are managed by child components (BiblePanel, KnowledgePanel)
    // This method provides a consistent interface for future use
    // Current architecture uses delegation pattern
  }

  const onMessagesUpdated = () => {
    // Callback for when chat messages are updated
    // Can be used to trigger side effects or refresh data
  }

  // Cleanup on unmount
  onUnmounted(() => {
    stopPolling()
  })

  return {
    // State
    bookTitle,
    chapters,
    rightPanel,
    biblePanelKey,
    pageLoading,
    showPlanModal,
    planMode,
    planDryRun,
    bookMeta,
    showTaskModal,
    taskProgress,
    taskMessage,
    currentJobId,

    // Computed
    currentChapterId,
    hasStructure,

    // Methods
    setRightPanel,
    onMessagesUpdated,
    loadDesk,
    loadData,
    handleJobCompleted,
    restoreJobState,
    handleChapterSelect,
    handleSendMessage,
    handleUpdateSettings,
    openPlanModal,
    confirmPlan,
    startWrite,
    startPolling,
    cancelRunningTask,
    stopPolling,
    goHome,
    goToChapter,
  }
}
