"""AI 持续规划服务

整合宏观规划、幕级规划、AI 续规划为统一的服务
"""

import json
import uuid
import logging
from typing import Dict, List, Optional
from datetime import datetime

from domain.structure.story_node import StoryNode, NodeType, PlanningStatus, PlanningSource
from domain.structure.chapter_element import ChapterElement, ElementType, RelationType, Importance
from infrastructure.persistence.database.story_node_repository import StoryNodeRepository
from infrastructure.persistence.database.chapter_element_repository import ChapterElementRepository
from domain.ai.services.llm_service import LLMService, GenerationConfig
from domain.ai.value_objects.prompt import Prompt

logger = logging.getLogger(__name__)


class ContinuousPlanningService:
    """AI 持续规划服务

    统一的规划服务，包含：
    1. 宏观规划：生成部-卷-幕结构框架
    2. 幕级规划：为指定幕生成章节规划
    3. AI 续规划：自动判断何时创建新幕
    """

    def __init__(
        self,
        story_node_repo: StoryNodeRepository,
        chapter_element_repo: ChapterElementRepository,
        llm_service: LLMService,
        bible_service=None
    ):
        self.story_node_repo = story_node_repo
        self.chapter_element_repo = chapter_element_repo
        self.llm_service = llm_service
        self.bible_service = bible_service

    # ==================== 宏观规划 ====================

    async def generate_macro_plan(
        self,
        novel_id: str,
        target_chapters: int,
        structure_preference: Dict[str, int]
    ) -> Dict:
        """生成宏观规划"""
        print(f"[DEBUG] 开始生成宏观规划: novel_id={novel_id}, target_chapters={target_chapters}")
        logger.info(f"Generating macro plan for novel {novel_id}")

        # 获取 Bible 信息
        print(f"[DEBUG] 获取 Bible 上下文...")
        bible_context = self._get_bible_context(novel_id)
        print(f"[DEBUG] Bible 上下文: {bible_context}")

        # 构建提示词
        print(f"[DEBUG] 构建提示词...")
        prompt = self._build_macro_planning_prompt(
            bible_context=bible_context,
            target_chapters=target_chapters,
            structure_preference=structure_preference
        )
        print(f"[DEBUG] 提示词: system={prompt.system[:100]}..., user={prompt.user[:100]}...")

        # 调用 LLM 生成规划
        print(f"[DEBUG] 调用 LLM...")
        config = GenerationConfig(max_tokens=4096, temperature=0.7)
        response = await self.llm_service.generate(prompt, config)
        print(f"[DEBUG] LLM 响应类型: {type(response)}")
        print(f"[DEBUG] LLM 响应内容: {response}")
        structure = self._parse_llm_response(response)

        return {
            "success": True,
            "structure": structure.get("parts", [])
        }

    async def confirm_macro_plan(self, novel_id: str, structure: List[Dict]) -> Dict:
        """确认宏观规划"""
        logger.info(f"Confirming macro plan for novel {novel_id}")

        created_nodes = []
        order_index = 0
        part_number = 0
        volume_number = 0
        act_number = 0

        for part_data in structure:
            part_number += 1
            part_data["number"] = part_number
            part_node = self._create_node_from_data(
                novel_id, None, NodeType.PART, part_data, order_index
            )
            created_nodes.append(part_node)
            order_index += 1

            for volume_data in part_data.get("volumes", []):
                volume_number += 1
                volume_data["number"] = volume_number
                volume_node = self._create_node_from_data(
                    novel_id, part_node.id, NodeType.VOLUME, volume_data, order_index
                )
                created_nodes.append(volume_node)
                order_index += 1

                for act_data in volume_data.get("acts", []):
                    act_number += 1
                    act_data["number"] = act_number
                    act_node = self._create_node_from_data(
                        novel_id, volume_node.id, NodeType.ACT, act_data, order_index
                    )
                    created_nodes.append(act_node)
                    order_index += 1

        await self.story_node_repo.save_batch(created_nodes)

        return {
            "success": True,
            "created_nodes": len(created_nodes),
            "message": f"已创建 {len(created_nodes)} 个结构节点"
        }

    # ==================== 幕级规划 ====================

    async def plan_act_chapters(
        self, act_id: str, custom_chapter_count: Optional[int] = None
    ) -> Dict:
        """为指定幕生成章节规划"""
        logger.info(f"Planning chapters for act {act_id}")

        act_node = await self.story_node_repo.get_by_id(act_id)
        if not act_node:
            raise ValueError(f"幕节点不存在: {act_id}")

        bible_context = self._get_bible_context(act_node.novel_id)
        previous_summary = await self._get_previous_acts_summary(act_node)
        chapter_count = custom_chapter_count or act_node.suggested_chapter_count or 5

        prompt = self._build_act_planning_prompt(
            act_node, bible_context, previous_summary, chapter_count
        )

        response = await self.llm_service.generate(prompt, GenerationConfig(max_tokens=4096, temperature=0.7))
        plan = self._parse_llm_response(response)

        return {
            "success": True,
            "act_id": act_id,
            "chapters": plan.get("chapters", [])
        }

    async def confirm_act_planning(self, act_id: str, chapters: List[Dict]) -> Dict:
        """确认幕级规划"""
        logger.info(f"Confirming act planning for act {act_id}")

        act_node = await self.story_node_repo.get_by_id(act_id)
        if not act_node:
            raise ValueError(f"幕节点不存在: {act_id}")

        created_chapters = []
        created_elements = []

        for idx, chapter_data in enumerate(chapters):
            chapter_id = f"chapter-{uuid.uuid4().hex[:8]}"

            chapter_node = StoryNode(
                id=chapter_id,
                novel_id=act_node.novel_id,
                parent_id=act_id,
                node_type=NodeType.CHAPTER,
                number=chapter_data["number"],
                title=chapter_data["title"],
                order_index=act_node.order_index + 1 + idx,
                planning_status=PlanningStatus.CONFIRMED,
                planning_source=PlanningSource.AI_ACT,
                outline=chapter_data.get("outline"),
                pov_character_id=chapter_data.get("pov_character_id"),
            )
            created_chapters.append(chapter_node)

            # 创建元素关联
            elements = self._create_elements_from_data(
                chapter_id, chapter_data.get("elements", {})
            )
            created_elements.extend(elements)

        await self.story_node_repo.save_batch(created_chapters)
        await self.chapter_element_repo.save_batch(created_elements)

        act_node.chapter_count = len(created_chapters)
        await self.story_node_repo.update(act_node)

        return {
            "success": True,
            "created_chapters": len(created_chapters),
            "created_elements": len(created_elements),
            "message": f"已创建 {len(created_chapters)} 个章节"
        }

    # ==================== AI 续规划 ====================

    async def continue_planning(self, novel_id: str, current_chapter_number: int) -> Dict:
        """AI 续规划"""
        logger.info(f"Continue planning for novel {novel_id}, chapter {current_chapter_number}")

        current_act = await self._find_act_for_chapter(novel_id, current_chapter_number)
        if not current_act:
            return {"success": False, "message": "未找到当前章节所属的幕"}

        chapters_written = await self._count_written_chapters_in_act(current_act.id)
        chapters_planned = await self._count_planned_chapters_in_act(current_act.id)

        should_end = chapters_written >= chapters_planned

        if should_end:
            next_act = await self._get_next_act(current_act)

            if next_act:
                return {
                    "success": True,
                    "act_completed": True,
                    "has_next_act": True,
                    "current_act": current_act.to_dict(),
                    "next_act": next_act.to_dict(),
                    "message": f"第 {current_act.number} 幕已完成，可以开始第 {next_act.number} 幕"
                }
            else:
                return {
                    "success": True,
                    "act_completed": True,
                    "has_next_act": False,
                    "current_act": current_act.to_dict(),
                    "suggest_create_next": True,
                    "message": f"第 {current_act.number} 幕已完成，是否需要 AI 生成下一幕？"
                }
        else:
            return {
                "success": True,
                "act_completed": False,
                "current_act": current_act.to_dict(),
                "progress": f"{chapters_written}/{chapters_planned}",
                "message": f"继续第 {current_act.number} 幕"
            }

    async def create_next_act_auto(self, novel_id: str, current_act_id: str) -> Dict:
        """自动创建下一幕"""
        logger.info(f"Creating next act after {current_act_id}")

        current_act = await self.story_node_repo.get_by_id(current_act_id)
        if not current_act:
            raise ValueError(f"当前幕不存在: {current_act_id}")

        bible_context = self._get_bible_context(novel_id)
        next_act_info = await self._generate_next_act_info(novel_id, current_act, bible_context)

        next_act = self._create_node_from_data(
            novel_id,
            current_act.parent_id,
            NodeType.ACT,
            {
                "number": current_act.number + 1,
                "title": next_act_info["title"],
                "description": next_act_info["description"],
                "suggested_chapter_count": next_act_info.get("suggested_chapter_count", 5),
                "key_events": next_act_info.get("key_events", []),
                "narrative_arc": next_act_info.get("narrative_arc"),
                "conflicts": next_act_info.get("conflicts", []),
            },
            current_act.order_index + 1
        )

        await self.story_node_repo.save(next_act)

        return {
            "success": True,
            "next_act": next_act.to_dict(),
            "message": f"已创建第 {next_act.number} 幕，请为其规划章节"
        }

    # ==================== 辅助方法 ====================

    def _get_bible_context(self, novel_id: str) -> Dict:
        """获取 Bible 上下文"""
        if not self.bible_service:
            return {}

        bible = self.bible_service.get_bible_by_novel(novel_id)
        if not bible:
            return {}

        return {
            "characters": [{"id": c.id, "name": c.name, "description": c.description}
                           for c in bible.characters],
            "world_settings": [{"id": w.id, "name": w.name, "description": w.description}
                               for w in bible.world_settings],
            "locations": [{"id": l.id, "name": l.name, "description": l.description}
                          for l in bible.locations],
            "timeline_notes": [{"id": t.id, "event": t.event, "description": t.description}
                               for t in bible.timeline_notes],
        }

    def _create_node_from_data(
        self, novel_id: str, parent_id: Optional[str], node_type: NodeType,
        data: Dict, order_index: int
    ) -> StoryNode:
        """从数据创建节点"""
        return StoryNode(
            id=f"{node_type.value}-{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            parent_id=parent_id,
            node_type=node_type,
            number=data["number"],
            title=data["title"],
            description=data.get("description"),
            order_index=order_index,
            planning_status=PlanningStatus.CONFIRMED,
            planning_source=PlanningSource.AI_MACRO,
            suggested_chapter_count=data.get("suggested_chapter_count"),
            themes=data.get("themes", []),
            key_events=data.get("key_events", []) if node_type == NodeType.ACT else [],
            narrative_arc=data.get("narrative_arc") if node_type == NodeType.ACT else None,
            conflicts=data.get("conflicts", []) if node_type == NodeType.ACT else [],
        )

    def _create_elements_from_data(self, chapter_id: str, elements_data: Dict) -> List[ChapterElement]:
        """从数据创建章节元素"""
        elements = []

        for char_data in elements_data.get("characters", []):
            elements.append(ChapterElement(
                id=f"elem-{uuid.uuid4().hex[:8]}",
                chapter_id=chapter_id,
                element_type=ElementType.CHARACTER,
                element_id=char_data["id"],
                relation_type=RelationType(char_data.get("relation", "appears")),
                importance=Importance(char_data.get("importance", "normal")),
            ))

        for loc_data in elements_data.get("locations", []):
            elements.append(ChapterElement(
                id=f"elem-{uuid.uuid4().hex[:8]}",
                chapter_id=chapter_id,
                element_type=ElementType.LOCATION,
                element_id=loc_data["id"],
                relation_type=RelationType.SCENE,
                importance=Importance.NORMAL,
            ))

        return elements

    def _parse_llm_response(self, response) -> Dict:
        """解析 LLM 响应"""
        # 如果是 GenerationResult 对象，提取 content 属性
        if hasattr(response, 'content'):
            content = response.content.strip()
        else:
            content = response.strip()

        # 调试日志
        print(f"[DEBUG] LLM 原始响应: {content[:200]}...")

        # 查找 JSON 代码块
        if "```json" in content:
            # 提取 ```json 和 ``` 之间的内容
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end != -1:
                content = content[start:end].strip()
        elif "```" in content:
            # 提取第一个 ``` 和最后一个 ``` 之间的内容
            start = content.find("```") + 3
            end = content.rfind("```")
            if end != -1 and end > start:
                content = content[start:end].strip()

        # 如果还有前缀文字，尝试找到 JSON 开始的位置
        if not content.startswith("{") and not content.startswith("["):
            # 查找第一个 { 或 [
            json_start = min(
                content.find("{") if "{" in content else len(content),
                content.find("[") if "[" in content else len(content)
            )
            if json_start < len(content):
                content = content[json_start:]

        print(f"[DEBUG] 清理后的内容: {content[:200]}...")

        return json.loads(content)

    def _build_macro_planning_prompt(self, bible_context: Dict, target_chapters: int, structure_preference: Dict) -> Prompt:
        """构建宏观规划提示词"""
        system_msg = """你是一个专业的小说结构规划助手，擅长设计合理的故事结构。
你的任务是根据用户提供的参数生成一个结构框架，即使没有详细的世界观信息也要生成。
请直接输出 JSON 格式的结构，不要询问额外信息，不要添加任何解释性文字。"""

        user_msg = f"""请为小说生成宏观规划，要求：
- 目标章节数：{target_chapters}章
- 结构：{structure_preference.get('parts', 3)}部，每部{structure_preference.get('volumes_per_part', 3)}卷，每卷{structure_preference.get('acts_per_volume', 3)}幕

如果没有提供世界观信息，请生成一个通用的结构框架，使用占位符标题（如"第一部"、"第一卷"、"第一幕"等）。

必须严格按照以下 JSON 格式输出，不要添加任何其他文字：
{{
  "parts": [
    {{
      "title": "部标题",
      "volumes": [
        {{
          "title": "卷标题",
          "acts": [
            {{"title": "幕标题", "description": "幕简介"}}
          ]
        }}
      ]
    }}
  ]
}}"""
        return Prompt(system=system_msg, user=user_msg)

    def _build_act_planning_prompt(self, act_node: StoryNode, bible_context: Dict, previous_summary: Optional[str], chapter_count: int) -> Prompt:
        """构建幕级规划提示词"""
        system_msg = """你是一个专业的小说章节规划助手，擅长设计章节大纲和情节安排。
你的任务是根据提供的信息生成章节规划，即使信息不完整也要生成合理的框架。
请直接输出 JSON 格式，不要询问额外信息，不要添加任何解释性文字。"""

        # 构建上下文信息
        context_parts = [f"幕信息：《{act_node.title}》"]
        if act_node.description:
            context_parts.append(f"幕简介：{act_node.description}")

        if previous_summary:
            context_parts.append(f"\n前情提要：{previous_summary}")

        # 添加 Bible 信息
        if bible_context.get("characters"):
            char_list = [f"- {c.get('name', 'Unknown')} (ID: {c.get('id', 'N/A')})" for c in bible_context["characters"][:5]]
            context_parts.append(f"\n可用人物：\n" + "\n".join(char_list))

        if bible_context.get("locations"):
            loc_list = [f"- {l.get('name', 'Unknown')} (ID: {l.get('id', 'N/A')})" for l in bible_context["locations"][:5]]
            context_parts.append(f"\n可用地点：\n" + "\n".join(loc_list))

        context = "\n".join(context_parts)

        user_msg = f"""{context}

请为这一幕规划 {chapter_count} 个章节。如果没有详细的世界观信息，请生成通用的章节框架。

要求：
1. 每个章节需要有标题和大纲
2. 如果有可用的人物和地点，尽量关联；如果没有，可以留空
3. 章节编号从 1 开始递增

请直接输出 JSON 格式，不要添加任何说明文字：
{{
  "chapters": [
    {{
      "number": 1,
      "title": "章节标题",
      "outline": "章节大纲（100-200字）",
      "characters": ["人物ID"],
      "locations": ["地点ID"]
    }}
  ]
}}"""
        return Prompt(system=system_msg, user=user_msg)

    async def _get_previous_acts_summary(self, act_node: StoryNode) -> Optional[str]:
        """获取前面幕的摘要"""
        return None

    async def _find_act_for_chapter(self, novel_id: str, chapter_number: int) -> Optional[StoryNode]:
        """查找章节所属的幕"""
        tree = self.story_node_repo.get_tree(novel_id)
        acts = [n for n in tree.nodes if n.node_type == NodeType.ACT]
        return max(acts, key=lambda x: x.number) if acts else None

    async def _count_written_chapters_in_act(self, act_id: str) -> int:
        """统计已写章节数"""
        children = self.story_node_repo.get_children(act_id, None)
        return sum(1 for n in children if n.node_type == NodeType.CHAPTER and n.word_count and n.word_count > 0)

    async def _count_planned_chapters_in_act(self, act_id: str) -> int:
        """统计已规划章节数"""
        children = self.story_node_repo.get_children(act_id, None)
        return sum(1 for n in children if n.node_type == NodeType.CHAPTER)

    async def _get_next_act(self, current_act: StoryNode) -> Optional[StoryNode]:
        """获取下一幕"""
        tree = self.story_node_repo.get_tree(current_act.novel_id)
        acts = [n for n in tree.nodes if n.node_type == NodeType.ACT and n.number == current_act.number + 1]
        return acts[0] if acts else None

    async def _generate_next_act_info(self, novel_id: str, current_act: StoryNode, bible_context: Dict) -> Dict:
        """生成下一幕信息"""
        prompt = Prompt(
            system="你是一个专业的小说结构规划助手。",
            user=f"""生成第{current_act.number + 1}幕信息。输出JSON格式：{{"title": "幕标题", "description": "幕简介"}}"""
        )
        try:
            response = await self.llm_service.generate(prompt, GenerationConfig(max_tokens=4096, temperature=0.7))
            return self._parse_llm_response(response)
        except:
            return {
                "title": f"第{current_act.number + 1}幕",
                "description": "描述",
                "suggested_chapter_count": 5
            }
