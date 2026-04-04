<template>
  <n-modal v-model:show="showModal" :style="{ width: '90%', maxWidth: '1200px' }">
    <n-card :title="modalTitle" :bordered="false">
      <!-- 第一步：生成章节规划 -->
      <div v-if="step === 1">
        <n-alert type="info" style="margin-bottom: 16px">
          AI 将为这一幕生成详细的章节规划，包括标题、大纲、出场人物、场景地点等
        </n-alert>

        <n-form label-placement="left" label-width="100">
          <n-form-item label="章节数量">
            <n-input-number v-model:value="chapterCount" :min="3" :max="15" style="width: 200px" />
            <n-text depth="3" style="margin-left: 12px">建议 3-10 章</n-text>
          </n-form-item>
        </n-form>

        <n-space style="margin-top: 24px">
          <n-button @click="handleClose">取消</n-button>
          <n-button type="primary" @click="generateChapters" :loading="generating">
            生成章节规划
          </n-button>
        </n-space>
      </div>

      <!-- 第二步：编辑章节规划 -->
      <div v-if="step === 2">
        <n-alert type="success" style="margin-bottom: 16px">
          AI 已生成章节规划，您可以编辑标题、大纲、出场人物等信息
        </n-alert>

        <n-list bordered style="margin-bottom: 16px">
          <n-list-item v-for="(chapter, index) in chapters" :key="index">
            <n-space vertical style="width: 100%">
              <n-space align="center">
                <n-tag type="info">第 {{ chapter.number }} 章</n-tag>
                <n-input
                  v-model:value="chapter.title"
                  placeholder="章节标题"
                  style="flex: 1"
                />
              </n-space>

              <n-input
                v-model:value="chapter.outline"
                type="textarea"
                :rows="3"
                placeholder="章节大纲"
              />

              <n-space vertical style="width: 100%">
                <n-form-item label="POV 视角人物" label-placement="left" label-width="120">
                  <n-select
                    v-model:value="chapter.pov_character_id"
                    :options="characterOptions"
                    placeholder="选择视角人物"
                    clearable
                  />
                </n-form-item>

                <n-form-item label="出场人物" label-placement="left" label-width="120">
                  <n-dynamic-tags v-model:value="chapter.characterTags" @create="(label) => handleAddCharacter(index, label)" />
                  <n-text depth="3" style="margin-left: 8px; font-size: 12px">
                    已选: {{ getCharacterNames(chapter.elements?.characters || []) }}
                  </n-text>
                </n-form-item>

                <n-form-item label="场景地点" label-placement="left" label-width="120">
                  <n-dynamic-tags v-model:value="chapter.locationTags" @create="(label) => handleAddLocation(index, label)" />
                  <n-text depth="3" style="margin-left: 8px; font-size: 12px">
                    已选: {{ getLocationNames(chapter.elements?.locations || []) }}
                  </n-text>
                </n-form-item>
              </n-space>
            </n-space>
          </n-list-item>
        </n-list>

        <n-space>
          <n-button @click="step = 1">重新生成</n-button>
          <n-button type="primary" @click="confirmChapters" :loading="confirming">
            确认并创建章节
          </n-button>
        </n-space>
      </div>

      <!-- 第三步：完成 -->
      <div v-if="step === 3">
        <n-result status="success" title="章节规划已完成" :description="`已创建 ${chapters.length} 个章节`">
          <template #footer>
            <n-button type="primary" @click="handleSuccess">
              开始写作
            </n-button>
          </template>
        </n-result>
      </div>
    </n-card>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { planningApi } from '@/api/planning'

const props = defineProps<{
  show: boolean
  actId: string
  actTitle: string
  novelId: string
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  success: []
}>()

const message = useMessage()

const showModal = computed({
  get: () => props.show,
  set: (val) => emit('update:show', val)
})

const modalTitle = computed(() => `规划章节 - ${props.actTitle}`)

const step = ref(1)
const chapterCount = ref(5)
const chapters = ref<any[]>([])
const generating = ref(false)
const confirming = ref(false)

// Bible 数据（需要从 API 获取）
const characterOptions = ref<any[]>([])
const locationOptions = ref<any[]>([])
const bibleCharacters = ref<any[]>([])
const bibleLocations = ref<any[]>([])

// 监听弹窗打开，加载 Bible 数据
watch(() => props.show, async (show) => {
  if (show) {
    await loadBibleData()
  }
})

// 加载 Bible 数据
const loadBibleData = async () => {
  try {
    // TODO: 调用 Bible API 获取人物和地点
    // const bible = await bibleApi.getBible(props.novelId)
    // bibleCharacters.value = bible.characters
    // bibleLocations.value = bible.locations

    // 临时模拟数据
    bibleCharacters.value = [
      { id: 'char-1', name: '李明' },
      { id: 'char-2', name: '神秘老人' },
      { id: 'char-3', name: '测试长老' }
    ]
    bibleLocations.value = [
      { id: 'loc-1', name: '破旧酒馆' },
      { id: 'loc-2', name: '青云宗' },
      { id: 'loc-3', name: '试炼场' }
    ]

    characterOptions.value = bibleCharacters.value.map(c => ({
      label: c.name,
      value: c.id
    }))

    locationOptions.value = bibleLocations.value.map(l => ({
      label: l.name,
      value: l.id
    }))
  } catch (e: any) {
    console.error('Failed to load bible data:', e)
  }
}

// 生成章节规划
const generateChapters = async () => {
  generating.value = true
  try {
    const res = await planningApi.generateActChapters(props.actId, {
      chapter_count: chapterCount.value
    })

    if (res.success) {
      chapters.value = res.chapters.map((ch: any) => ({
        ...ch,
        characterTags: [],
        locationTags: []
      }))
      step.value = 2
      message.success('章节规划已生成')
    }
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '生成章节规划失败')
  } finally {
    generating.value = false
  }
}

// 确认章节规划
const confirmChapters = async () => {
  confirming.value = true
  try {
    const res = await planningApi.confirmActChapters(props.actId, {
      chapters: chapters.value
    })

    if (res.success) {
      step.value = 3
      message.success(res.message || '章节已创建')
    }
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '确认章节规划失败')
  } finally {
    confirming.value = false
  }
}

// 添加人物
const handleAddCharacter = (chapterIndex: number, label: string) => {
  const char = bibleCharacters.value.find(c => c.name === label)
  if (char) {
    if (!chapters.value[chapterIndex].elements) {
      chapters.value[chapterIndex].elements = { characters: [], locations: [] }
    }
    if (!chapters.value[chapterIndex].elements.characters) {
      chapters.value[chapterIndex].elements.characters = []
    }
    chapters.value[chapterIndex].elements.characters.push({
      id: char.id,
      importance: 'normal',
      relation: 'appears'
    })
  }
}

// 添加地点
const handleAddLocation = (chapterIndex: number, label: string) => {
  const loc = bibleLocations.value.find(l => l.name === label)
  if (loc) {
    if (!chapters.value[chapterIndex].elements) {
      chapters.value[chapterIndex].elements = { characters: [], locations: [] }
    }
    if (!chapters.value[chapterIndex].elements.locations) {
      chapters.value[chapterIndex].elements.locations = []
    }
    chapters.value[chapterIndex].elements.locations.push({
      id: loc.id,
      relation: 'scene'
    })
  }
}

// 获取人物名称
const getCharacterNames = (characters: any[]) => {
  return characters
    .map(c => bibleCharacters.value.find(bc => bc.id === c.id)?.name)
    .filter(Boolean)
    .join(', ') || '无'
}

// 获取地点名称
const getLocationNames = (locations: any[]) => {
  return locations
    .map(l => bibleLocations.value.find(bl => bl.id === l.id)?.name)
    .filter(Boolean)
    .join(', ') || '无'
}

// 关闭弹窗
const handleClose = () => {
  showModal.value = false
  // 重置状态
  setTimeout(() => {
    step.value = 1
    chapters.value = []
  }, 300)
}

// 成功回调
const handleSuccess = () => {
  emit('success')
  handleClose()
}
</script>

<style scoped>
.n-list-item {
  padding: 16px;
}
</style>
