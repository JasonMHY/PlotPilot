"""
幕级规划服务
负责为具体的幕生成章节规划，并关联 Bible 元素
"""

import json
import uuid
from typing import Dict, List, Optional
from datetime import datetime

from domain.structure.story_node import StoryNode, NodeType, PlanningStatus, PlanningSource
from domain.structure.chapter_element import ChapterElement, ElementType, RelationType, Importance
from infrastructure.persistence.database.story_node_repository import StoryNodeRepository
from infrastructure.persistence.database.chapter_element_repository import ChapterElementRepository
from infrastructure.ai.llm_client import LLMClient


class ActPlanningService:
    """幕级规划服务"""

    def __init__(
        self,
        story_node_repo: StoryNodeRepository,
        chapter_element_repo: ChapterElementRepository,
        llm_client: LLMClient
    ):
        self.story_node_repo = story_node_repo
        self.chapter_element_repo = chapter_element_repo
        self.llm_client = llm_client

    async def generate_act_plan(
        self,
        act_id: str,
        bible_context: Dict,
        previous_summary: Optional[str] = None
    ) -> Dict:
        """
        生成幕级规划

        Args:
            act_id: 幕节点 ID
            bible_context: Bible 上下文（人物、地点、道具等）
            previous_summary: 前面章节的摘要

        Returns:
            规划结果字典
        """
        # 获取幕节点信息
        act_node = await self.story_node_repo.get_by_id(act_id)
        if not act_node:
            raise ValueError(f"幕节点不存在: {act_id}")

        # 构建提示词
        prompt = self._build_act_planning_prompt(
            act_node,
            bible_context,
            previous_summary
        )

        # 调用 LLM 生成规划
        response = await self.llm_client.generate(prompt)

        # 解析 JSON 响应
        try:
            plan = self._parse_llm_response(response)
            return {
                "act_id": act_id,
                "chapters": plan.get("chapters", []),
                "narrative_arc": plan.get("narrative_arc"),
                "conflicts": plan.get("conflicts", [])
            }
        except Exception as e:
            raise ValueError(f"解析 LLM 响应失败: {e}")

    async def confirm_act_plan(
        self,
        act_id: str,
        chapters: List[Dict]
    ) -> Dict:
        """
        确认幕级规划，创建章节节点和元素关联

        Args:
            act_id: 幕节点 ID
            chapters: 用户编辑后的章节列表

        Returns:
            创建结果
        """
        # 获取幕节点
        act_node = await self.story_node_repo.get_by_id(act_id)
        if not act_node:
            raise ValueError(f"幕节点不存在: {act_id}")

        # 获取当前幕的 order_index，用于计算章节的 order_index
        base_order_index = act_node.order_index + 1

        created_chapters = []
        created_elements = []

        # 创建章节节点
        for idx, chapter_data in enumerate(chapters):
            chapter_id = f"chapter-{uuid.uuid4().hex[:8]}"

            # 创建章节节点
            chapter_node = StoryNode(
                id=chapter_id,
                novel_id=act_node.novel_id,
                parent_id=act_id,
                node_type=NodeType.CHAPTER,
                number=chapter_data["number"],
                title=chapter_data["title"],
                description=None,
                order_index=base_order_index + idx,

                # 规划相关
                planning_status=PlanningStatus.CONFIRMED,
                planning_source=PlanningSource.AI_ACT,

                # 章节内容
                outline=chapter_data.get("outline"),
                pov_character_id=chapter_data.get("pov_character_id"),
            )
            created_chapters.append(chapter_node)

            # 创建章节元素关联
            elements_data = chapter_data.get("elements", {})

            # 人物关联
            for char_data in elements_data.get("characters", []):
                element = ChapterElement(
                    id=f"elem-{uuid.uuid4().hex[:8]}",
                    chapter_id=chapter_id,
                    element_type=ElementType.CHARACTER,
                    element_id=char_data["id"],
                    relation_type=RelationType(char_data.get("relation", "appears")),
                    importance=Importance(char_data.get("importance", "normal")),
                )
                created_elements.append(element)

            # 地点关联
            for loc_data in elements_data.get("locations", []):
                element = ChapterElement(
                    id=f"elem-{uuid.uuid4().hex[:8]}",
                    chapter_id=chapter_id,
                    element_type=ElementType.LOCATION,
                    element_id=loc_data["id"],
                    relation_type=RelationType(loc_data.get("relation", "scene")),
                    importance=Importance.NORMAL,
                )
                created_elements.append(element)

            # 道具关联
            for item_data in elements_data.get("items", []):
                element = ChapterElement(
                    id=f"elem-{uuid.uuid4().hex[:8]}",
                    chapter_id=chapter_id,
                    element_type=ElementType.ITEM,
                    element_id=item_data["id"],
                    relation_type=RelationType(item_data.get("relation", "uses")),
                    importance=Importance.NORMAL,
                )
                created_elements.append(element)

            # 组织关联
            for org_data in elements_data.get("organizations", []):
                element = ChapterElement(
                    id=f"elem-{uuid.uuid4().hex[:8]}",
                    chapter_id=chapter_id,
                    element_type=ElementType.ORGANIZATION,
                    element_id=org_data["id"],
                    relation_type=RelationType(org_data.get("relation", "involved")),
                    importance=Importance.NORMAL,
                )
                created_elements.append(element)

            # 事件关联
            for event_data in elements_data.get("events", []):
                element = ChapterElement(
                    id=f"elem-{uuid.uuid4().hex[:8]}",
                    chapter_id=chapter_id,
                    element_type=ElementType.EVENT,
                    element_id=event_data["id"],
                    relation_type=RelationType(event_data.get("relation", "occurs")),
                    importance=Importance.MAJOR,
                )
                created_elements.append(element)

        # 批量保存到数据库
        await self.story_node_repo.save_batch(created_chapters)
        await self.chapter_element_repo.save_batch(created_elements)

        # 更新幕节点的章节范围
        act_node.chapter_count = len(created_chapters)
        await self.story_node_repo.update(act_node)

        return {
            "act_id": act_id,
            "created_chapters": len(created_chapters),
            "created_elements": len(created_elements),
            "chapters": [ch.to_dict() for ch in created_chapters]
        }

    def _build_act_planning_prompt(
        self,
        act_node: StoryNode,
        bible_context: Dict,
        previous_summary: Optional[str] = None
    ) -> str:
        """构建幕级规划提示词"""
        # 格式化 Bible 信息
        characters_info = self._format_bible_elements(
            bible_context.get("characters", []),
            "人物"
        )
        locations_info = self._format_bible_elements(
            bible_context.get("locations", []),
            "地点"
        )
        items_info = self._format_bible_elements(
            bible_context.get("items", []),
            "道具"
        )
        organizations_info = self._format_bible_elements(
            bible_context.get("organizations", []),
            "组织"
        )

        previous_context = ""
        if previous_summary:
            previous_context = f"\n前面章节摘要：\n{previous_summary}\n"

        prompt = f"""你是一位资深的小说章节规划师。请为以下幕规划具体的章节内容。

幕信息：
标题：{act_node.title}
描述：{act_node.description}
关键事件：{', '.join(act_node.key_events)}
叙事弧线：{act_node.narrative_arc}
冲突：{', '.join(act_node.conflicts)}
预计章节数：{act_node.suggested_chapter_count}

可用的 Bible 元素：

{characters_info}

{locations_info}

{items_info}

{organizations_info}

{previous_context}

请规划 {act_node.suggested_chapter_count} 个章节，每个章节需要包含：
1. 标题和大纲（大纲 2-3 句话）
2. POV 视角人物（从人物列表中选择 ID）
3. 主要出场人物（标注重要性：major/normal/minor）
4. 场景地点（从地点列表中选择 ID）
5. 使用的道具（如果有，从道具列表中选择 ID）
6. 涉及的组织（如果有，从组织列表中选择 ID）

输出格式（JSON）：
{{
  "chapters": [
    {{
      "number": 1,
      "title": "章节标题",
      "outline": "章节大纲，2-3句话描述主要情节",
      "pov_character_id": "char-xxx",
      "elements": {{
        "characters": [
          {{"id": "char-xxx", "importance": "major", "relation": "appears"}},
          {{"id": "char-yyy", "importance": "normal", "relation": "appears"}}
        ],
        "locations": [
          {{"id": "loc-xxx", "relation": "scene"}}
        ],
        "items": [
          {{"id": "item-xxx", "relation": "uses"}}
        ],
        "organizations": [
          {{"id": "org-xxx", "relation": "involved"}}
        ]
      }}
    }}
  ],
  "narrative_arc": "整个幕的叙事弧线总结",
  "conflicts": ["冲突1", "冲突2"]
}}

要求：
1. 所有描述必须是单行字符串，不能包含换行符
2. 确保 JSON 格式完全正确
3. 章节标题要有吸引力，大纲要简洁明了
4. 元素 ID 必须从提供的列表中选择
5. 章节之间要有连贯性和递进关系

只输出 JSON，不要有任何解释文字。"""

        return prompt

    def _format_bible_elements(self, elements: List[Dict], category: str) -> str:
        """格式化 Bible 元素列表"""
        if not elements:
            return f"{category}：无"

        lines = [f"{category}："]
        for elem in elements:
            lines.append(f"  - {elem['name']} (ID: {elem['id']}): {elem.get('description', '无描述')}")

        return "\n".join(lines)

    def _parse_llm_response(self, response: str) -> Dict:
        """解析 LLM 响应"""
        # 清理响应
        content = response.strip()

        # 移除可能的 markdown 标记
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        content = content.strip()

        # 清理换行符和多余空格
        content = ' '.join(content.split())

        # 解析 JSON
        try:
            data = json.loads(content)
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析失败: {e}\n原始内容: {content[:200]}")
