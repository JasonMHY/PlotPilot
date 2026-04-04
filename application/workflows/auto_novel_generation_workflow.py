"""自动小说生成工作流

整合所有子项目组件，实现完整的章节生成流程。
"""
import logging
from typing import Tuple, Dict, Any, AsyncIterator, Optional
from application.services.context_builder import ContextBuilder
from application.services.state_extractor import StateExtractor
from application.services.state_updater import StateUpdater
from application.dtos.generation_result import GenerationResult
from application.dtos.scene_director_dto import SceneDirectorAnalysis
from domain.novel.services.consistency_checker import ConsistencyChecker
from domain.novel.services.storyline_manager import StorylineManager
from domain.novel.repositories.plot_arc_repository import PlotArcRepository
from domain.bible.repositories.bible_repository import BibleRepository
from domain.novel.repositories.foreshadowing_repository import ForeshadowingRepository
from domain.novel.value_objects.consistency_report import ConsistencyReport
from domain.novel.value_objects.chapter_state import ChapterState
from domain.novel.value_objects.consistency_context import ConsistencyContext
from domain.novel.value_objects.novel_id import NovelId
from domain.ai.services.llm_service import LLMService, GenerationConfig
from domain.ai.value_objects.prompt import Prompt

logger = logging.getLogger(__name__)


def _consistency_report_to_dict(report: ConsistencyReport) -> Dict[str, Any]:
    """供 SSE / JSON 序列化。"""
    return {
        "issues": [
            {
                "type": issue.type.value,
                "severity": issue.severity.value,
                "description": issue.description,
                "location": issue.location,
            }
            for issue in report.issues
        ],
        "warnings": [
            {
                "type": w.type.value,
                "severity": w.severity.value,
                "description": w.description,
                "location": w.location,
            }
            for w in report.warnings
        ],
        "suggestions": list(report.suggestions),
    }


class AutoNovelGenerationWorkflow:
    """自动小说生成工作流

    整合所有组件完成完整的章节生成流程：
    1. Planning Phase: 获取故事线上下文、情节弧张力
    2. Pre-Generation: 使用 ContextBuilder 构建 35K token 上下文
    3. Generation: 调用 LLM 生成内容
    4. Post-Generation: 提取状态、检查一致性、更新状态
    5. Review Phase: 返回一致性报告
    """

    def __init__(
        self,
        context_builder: ContextBuilder,
        consistency_checker: ConsistencyChecker,
        storyline_manager: StorylineManager,
        plot_arc_repository: PlotArcRepository,
        llm_service: LLMService,
        state_extractor: Optional[StateExtractor] = None,
        state_updater: Optional[StateUpdater] = None,
        bible_repository: Optional[BibleRepository] = None,
        foreshadowing_repository: Optional[ForeshadowingRepository] = None
    ):
        """初始化工作流

        Args:
            context_builder: 上下文构建器
            consistency_checker: 一致性检查器
            storyline_manager: 故事线管理器
            plot_arc_repository: 情节弧仓储
            llm_service: LLM 服务
            state_extractor: 状态提取器（可选）
            state_updater: 状态更新器（可选）
            bible_repository: Bible 仓储（用于一致性检查，可选）
            foreshadowing_repository: Foreshadowing 仓储（用于一致性检查，可选）
        """
        self.context_builder = context_builder
        self.consistency_checker = consistency_checker
        self.storyline_manager = storyline_manager
        self.plot_arc_repository = plot_arc_repository
        self.llm_service = llm_service
        self.state_extractor = state_extractor
        self.state_updater = state_updater
        self.bible_repository = bible_repository
        self.foreshadowing_repository = foreshadowing_repository

    async def generate_chapter(
        self,
        novel_id: str,
        chapter_number: int,
        outline: str,
        scene_director: Optional[SceneDirectorAnalysis] = None
    ) -> GenerationResult:
        """生成章节（完整工作流）

        Args:
            novel_id: 小说 ID
            chapter_number: 章节号
            outline: 章节大纲
            scene_director: 可选的场记分析结果，用于过滤角色和地点

        Returns:
            GenerationResult 包含内容、一致性报告、上下文和 token 数

        Raises:
            ValueError: 如果参数无效
            RuntimeError: 如果生成失败
        """
        # 验证输入
        if chapter_number < 1:
            raise ValueError("chapter_number must be positive")
        if not outline or not outline.strip():
            raise ValueError("outline cannot be empty")

        logger.info(f"========================================")
        logger.info(f"开始生成章节: 小说={novel_id}, 章节={chapter_number}")
        logger.info(f"大纲: {outline[:100]}...")
        logger.info(f"========================================")

        # Phase 1: Planning - 获取故事线和情节弧信息
        logger.info("阶段 1: 规划 - 获取故事线和情节上下文")
        storyline_context = self._get_storyline_context(novel_id, chapter_number)
        logger.info(f"  ✓ 故事线上下文: {len(storyline_context)} 字符")
        plot_tension = self._get_plot_tension(novel_id, chapter_number)
        logger.info(f"  ✓ 情节张力: {plot_tension[:100]}...")

        # Phase 2: Pre-Generation - 构建上下文
        logger.info("阶段 2: 预生成 - 构建上下文")
        payload = self.context_builder.build_structured_context(
            novel_id=novel_id,
            chapter_number=chapter_number,
            outline=outline,
            max_tokens=35000,
            scene_director=scene_director
        )
        context = f"{payload['layer1_text']}\n\n=== SMART RETRIEVAL ===\n{payload['layer2_text']}\n\n=== RECENT CONTEXT ===\n{payload['layer3_text']}"
        context_tokens = payload['token_usage']['total']
        logger.info(f"  ✓ 上下文已构建: {len(context)} 字符, 约 {context_tokens} tokens")

        # Phase 3: Generation - 调用 LLM
        logger.info("阶段 3: 生成 - 调用 LLM")
        prompt = self._build_prompt(
            context,
            outline,
            storyline_context=storyline_context,
            plot_tension=plot_tension,
        )
        config = GenerationConfig()
        logger.info(f"  → 发送请求到 LLM (max_tokens={config.max_tokens}, temperature={config.temperature})")
        llm_result = await self.llm_service.generate(prompt, config)
        content = llm_result.content
        logger.info(f"  ✓ LLM 响应已接收: {len(content)} 字符")

        # Phase 4: Post-Generation - 提取状态和检查一致性
        logger.info("阶段 4: 后处理 - 提取状态和检查一致性")
        chapter_state = await self._extract_chapter_state(content, chapter_number)
        logger.info(f"  ✓ 状态已提取: {len(chapter_state.new_characters)} 个新角色, {len(chapter_state.events)} 个事件")
        consistency_report = self._check_consistency(chapter_state, novel_id)
        logger.info(f"  ✓ 一致性检查: {len(consistency_report.issues)} 个问题, {len(consistency_report.warnings)} 个警告")

        # Phase 4.5: Update State - 更新 Bible 和 Knowledge
        if self.state_updater:
            try:
                logger.info(f"阶段 4.5: 更新状态 - 更新 Bible 和 Knowledge (章节 {chapter_number})")
                self.state_updater.update_from_chapter(novel_id, chapter_number, chapter_state)
                logger.info("  ✓ 状态更新完成")
            except Exception as e:
                logger.warning(f"  × StateUpdater 失败: {e}")

        # Phase 5: Review - 返回结果
        logger.info(f"阶段 5: 完成 - 章节生成完成")
        token_count = context_tokens
        logger.info(f"  ✓ 总计: {len(content)} 字符, {token_count} tokens")
        logger.info(f"========================================")
        logger.info(f"章节生成完成: 小说={novel_id}, 章节={chapter_number}")
        logger.info(f"========================================")

        return GenerationResult(
            content=content,
            consistency_report=consistency_report,
            context_used=context,
            token_count=token_count
        )

    async def generate_chapter_stream(
        self,
        novel_id: str,
        chapter_number: int,
        outline: str,
        scene_director: Optional[SceneDirectorAnalysis] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式生成章节：阶段事件 + 正文 token 流 + 最终 done（含一致性报告）。

        事件类型：
        - phase: planning | context | llm | post
        - chunk: { text }
        - done: { content, consistency_report, token_count }
        - error: { message }
        """
        try:
            if chapter_number < 1:
                raise ValueError("chapter_number must be positive")
            if not outline or not outline.strip():
                raise ValueError("outline cannot be empty")

            logger.info(f"========================================")
            logger.info(f"开始流式生成章节: 小说={novel_id}, 章节={chapter_number}")
            logger.info(f"========================================")

            yield {"type": "phase", "phase": "planning"}
            logger.info("阶段 1: 规划 - 获取故事线和情节上下文")
            storyline_context = self._get_storyline_context(novel_id, chapter_number)
            plot_tension = self._get_plot_tension(novel_id, chapter_number)
            logger.info("  ✓ 规划阶段完成")

            yield {"type": "phase", "phase": "context"}
            logger.info("阶段 2: 预生成 - 构建上下文")
            payload = self.context_builder.build_structured_context(
                novel_id=novel_id,
                chapter_number=chapter_number,
                outline=outline,
                max_tokens=35000,
                scene_director=scene_director
            )
            context = f"{payload['layer1_text']}\n\n=== SMART RETRIEVAL ===\n{payload['layer2_text']}\n\n=== RECENT CONTEXT ===\n{payload['layer3_text']}"
            context_tokens = payload['token_usage']['total']
            logger.info(f"  ✓ 上下文已构建: {len(context)} 字符, 约 {context_tokens} tokens")

            yield {"type": "phase", "phase": "llm"}
            logger.info("阶段 3: 生成 - 调用 LLM 流式生成")
            prompt = self._build_prompt(
                context,
                outline,
                storyline_context=storyline_context,
                plot_tension=plot_tension,
            )
            config = GenerationConfig()
            logger.info(f"  → 发送流式请求到 LLM")
            parts: list[str] = []
            chunk_count = 0
            async for piece in self.llm_service.stream_generate(prompt, config):
                parts.append(piece)
                chunk_count += 1
                yield {"type": "chunk", "text": piece}

            content = "".join(parts)
            logger.info(f"  ✓ LLM 流式响应完成: {chunk_count} 个块, {len(content)} 字符")

            if not content.strip():
                logger.error("  × 模型返回空内容")
                yield {"type": "error", "message": "模型返回空内容"}
                return

            yield {"type": "phase", "phase": "post"}
            logger.info("阶段 4: 后处理 - 提取状态和检查一致性")
            chapter_state = await self._extract_chapter_state(content, chapter_number)
            logger.info(f"  ✓ 状态已提取: {len(chapter_state.new_characters)} 个新角色, {len(chapter_state.events)} 个事件")
            consistency_report = self._check_consistency(chapter_state, novel_id)
            logger.info(f"  ✓ 一致性检查: {len(consistency_report.issues)} 个问题, {len(consistency_report.warnings)} 个警告")

            # Phase 4.5: Update State - 更新 Bible 和 Knowledge
            if self.state_updater:
                try:
                    logger.info(f"阶段 4.5: 更新状态 - 更新 Bible 和 Knowledge")
                    self.state_updater.update_from_chapter(novel_id, chapter_number, chapter_state)
                    logger.info("  ✓ 状态更新完成")
                except Exception as e:
                    logger.warning(f"  × StateUpdater 失败: {e}")

            token_count = context_tokens
            logger.info(f"========================================")
            logger.info(f"流式章节生成完成: 小说={novel_id}, 章节={chapter_number}")
            logger.info(f"========================================")

            yield {
                "type": "done",
                "content": content,
                "consistency_report": _consistency_report_to_dict(consistency_report),
                "token_count": token_count,
            }
        except ValueError as e:
            logger.error(f"参数错误: {e}")
            yield {"type": "error", "message": str(e)}
        except Exception as e:
            logger.exception("流式生成章节失败")
            yield {"type": "error", "message": str(e)}

    async def suggest_outline(self, novel_id: str, chapter_number: int) -> str:
        """托管模式：用全书上下文让模型生成本章要点大纲；失败则回退为简短占位。"""
        seed = f"第{chapter_number}章：承接前情，推进主线与人物节拍；保持人设与叙事节奏一致。"
        try:
            context = self.context_builder.build_context(
                novel_id=novel_id,
                chapter_number=chapter_number,
                outline=seed,
                max_tokens=28000,
            )
            cap = min(len(context), 28000)
            outline_prompt = Prompt(
                system=(
                    "你是小说主编。只输出本章的要点大纲（中文），用 1-6 条编号列表，"
                    "每条一行；不要写正文或对话。"
                ),
                user=(
                    f"以下为背景信息（节选）：\n\n{context[:cap]}\n\n"
                    f"请写第{chapter_number}章的要点大纲。"
                ),
            )
            cfg = GenerationConfig(max_tokens=1024, temperature=0.7)
            out = await self.llm_service.generate(outline_prompt, cfg)
            text = (out.content or "").strip()
            if text:
                return text
        except Exception as e:
            logger.warning("suggest_outline failed: %s", e)
        return seed

    async def generate_chapter_with_review(
        self,
        novel_id: str,
        chapter_number: int,
        outline: str
    ) -> Tuple[str, ConsistencyReport]:
        """生成章节并返回一致性审查

        Args:
            novel_id: 小说 ID
            chapter_number: 章节号
            outline: 章节大纲

        Returns:
            (content, consistency_report) 元组
        """
        result = await self.generate_chapter(novel_id, chapter_number, outline)
        return result.content, result.consistency_report

    def _get_storyline_context(self, novel_id: str, chapter_number: int) -> str:
        """获取故事线上下文

        Args:
            novel_id: 小说 ID
            chapter_number: 章节号

        Returns:
            故事线上下文字符串
        """
        try:
            # 检查 storyline_manager 是否有 repository 属性
            if not hasattr(self.storyline_manager, 'repository'):
                return "Storyline context unavailable"

            # 获取所有活跃的故事线
            storylines = self.storyline_manager.repository.get_by_novel_id(NovelId(novel_id))
            active_storylines = [
                s for s in storylines
                if s.status.value == "active"
                and s.estimated_chapter_start <= chapter_number <= s.estimated_chapter_end
            ]

            if not active_storylines:
                return "No active storylines for this chapter"

            context_parts = []
            for storyline in active_storylines:
                context = self.storyline_manager.get_storyline_context(storyline.id)
                context_parts.append(context)

            return "\n\n".join(context_parts)
        except Exception as e:
            logger.warning(f"Failed to get storyline context: {e}")
            return "Storyline context unavailable"

    def _get_plot_tension(self, novel_id: str, chapter_number: int) -> str:
        """获取情节张力信息

        Args:
            novel_id: 小说 ID
            chapter_number: 章节号

        Returns:
            情节张力描述
        """
        try:
            plot_arc = self.plot_arc_repository.get_by_novel_id(NovelId(novel_id))
            if plot_arc:
                tension = plot_arc.get_expected_tension(chapter_number)
                next_point = plot_arc.get_next_plot_point(chapter_number)

                tension_info = f"Expected tension: {tension.value}"
                if next_point:
                    tension_info += f"\nNext plot point at chapter {next_point.chapter_number}: {next_point.description}"

                return tension_info
            return "No plot arc defined"
        except Exception as e:
            logger.warning(f"Failed to get plot tension: {e}")
            return "Plot tension unavailable"

    def _build_prompt(
        self,
        context: str,
        outline: str,
        *,
        storyline_context: str = "",
        plot_tension: str = "",
    ) -> Prompt:
        """构建 LLM 提示词

        Args:
            context: 完整上下文
            outline: 章节大纲
            storyline_context: 当前章相关故事线与里程碑（Phase 1）
            plot_tension: 情节弧期望张力与下一锚点（Phase 1）

        Returns:
            Prompt 对象
        """
        sc = (storyline_context or "").strip()
        pt = (plot_tension or "").strip()
        planning_parts: list[str] = []
        if sc and sc not in ("Storyline context unavailable",):
            planning_parts.append(f"【故事线 / 里程碑】\n{sc}")
        if pt and pt not in ("Plot tension unavailable",):
            planning_parts.append(f"【情节节奏 / 期望张力】\n{pt}")
        planning_section = ""
        if planning_parts:
            planning_section = (
                "\n".join(planning_parts)
                + "\n\n以上约束须与本章大纲及后文 Bible/摘要一致；不得与之矛盾。\n"
            )

        system_message = f"""你是一位专业的网络小说作家。根据以下上下文撰写章节内容。

{planning_section}{context}

写作要求：
1. 必须有多个人物互动（至少2-3个角色出场）
2. 必须有对话（不能只有独白和叙述）
3. 必须有冲突或张力（人物之间的矛盾、目标阻碍、悬念等）
4. 保持人物性格一致
5. 推进情节发展
6. 使用生动的场景描写和细节
7. 章节长度：2000-3000字
8. 用中文写作，使用第三人称叙事"""

        user_message = f"""请根据以下大纲撰写本章内容：

{outline}

关键要求（必须遵守）：
- 至少2-3个角色出场并互动
- 必须包含对话场景（不少于3段对话）
- 必须有明确的冲突或戏剧张力
- 场景要具体生动，不要空泛叙述
- 推进主线情节，不要原地踏步
- 结尾要有悬念或转折

开始撰写："""

        return Prompt(system=system_message, user=user_message)

    async def _extract_chapter_state(self, content: str, chapter_number: int) -> ChapterState:
        """从生成的内容中提取章节状态

        Args:
            content: 生成的章节内容
            chapter_number: 章节号

        Returns:
            ChapterState 对象
        """
        # 如果有 StateExtractor，使用它提取状态
        if self.state_extractor:
            try:
                logger.info(f"Extracting chapter state using StateExtractor for chapter {chapter_number}")
                return await self.state_extractor.extract_chapter_state(content)
            except Exception as e:
                logger.warning(f"StateExtractor failed: {e}, returning empty state")

        # 降级：返回空状态
        return ChapterState(
            new_characters=[],
            character_actions=[],
            relationship_changes=[],
            foreshadowing_planted=[],
            foreshadowing_resolved=[],
            events=[]
        )

    def _check_consistency(
        self,
        chapter_state: ChapterState,
        novel_id: str
    ) -> ConsistencyReport:
        """检查章节一致性

        Args:
            chapter_state: 章节状态
            novel_id: 小说 ID

        Returns:
            ConsistencyReport
        """
        from domain.bible.entities.bible import Bible
        from domain.bible.entities.character_registry import CharacterRegistry
        from domain.novel.entities.foreshadowing_registry import ForeshadowingRegistry
        from domain.novel.entities.plot_arc import PlotArc
        from domain.novel.value_objects.event_timeline import EventTimeline
        from domain.bible.value_objects.relationship_graph import RelationshipGraph

        novel_id_obj = NovelId(novel_id)

        try:
            # 尝试从仓储加载真实数据
            if self.bible_repository:
                bible = self.bible_repository.get_by_novel_id(novel_id_obj)
                logger.debug(f"Loaded real Bible for consistency check: {bible is not None}")
            else:
                bible = None

            if self.foreshadowing_repository:
                foreshadowing_registry = self.foreshadowing_repository.get_by_novel_id(novel_id_obj)
                logger.debug(f"Loaded real ForeshadowingRegistry for consistency check: {foreshadowing_registry is not None}")
            else:
                foreshadowing_registry = None

            context = ConsistencyContext(
                bible=bible or Bible(id="temp", novel_id=novel_id_obj),
                character_registry=CharacterRegistry(id="temp"),
                foreshadowing_registry=foreshadowing_registry or ForeshadowingRegistry(id="temp", novel_id=novel_id_obj),
                plot_arc=PlotArc(id="temp", novel_id=novel_id_obj),
                event_timeline=EventTimeline(events=[]),
                relationship_graph=RelationshipGraph()
            )

            return self.consistency_checker.check_all(chapter_state, context)
        except Exception as e:
            logger.warning(f"Consistency check failed: {e}")
            return ConsistencyReport(issues=[], warnings=[], suggestions=[])
