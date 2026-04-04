"""
宏观规划服务
负责生成和确认小说的宏观结构（部-卷-幕）
"""

import json
import uuid
from typing import Dict, List, Optional
from datetime import datetime

from domain.structure.story_node import StoryNode, NodeType, PlanningStatus, PlanningSource
from infrastructure.persistence.database.story_node_repository import StoryNodeRepository
from infrastructure.ai.llm_client import LLMClient


class MacroPlanningService:
    """宏观规划服务"""

    def __init__(
        self,
        story_node_repo: StoryNodeRepository,
        llm_client: LLMClient
    ):
        self.story_node_repo = story_node_repo
        self.llm_client = llm_client

    async def generate_macro_plan(
        self,
        novel_id: str,
        premise: str,
        target_chapters: int,
        structure_preference: Dict[str, int],
        bible_context: Optional[Dict] = None
    ) -> Dict:
        """
        生成宏观规划

        Args:
            novel_id: 小说 ID
            premise: 小说前提
            target_chapters: 目标章节数
            structure_preference: 结构偏好 {"parts": 3, "volumes_per_part": 3, "acts_per_volume": 3}
            bible_context: Bible 上下文（主角、地点、冲突等）

        Returns:
            规划结果字典
        """
        # 构建提示词
        prompt = self._build_macro_planning_prompt(
            premise,
            target_chapters,
            structure_preference,
            bible_context
        )

        # 调用 LLM 生成规划
        response = await self.llm_client.generate(prompt)

        # 解析 JSON 响应
        try:
            structure = self._parse_llm_response(response)
            return {
                "novel_id": novel_id,
                "structure": structure
            }
        except Exception as e:
            raise ValueError(f"解析 LLM 响应失败: {e}")

    async def confirm_macro_plan(
        self,
        novel_id: str,
        structure: List[Dict]
    ) -> Dict:
        """
        确认宏观规划，创建所有节点

        Args:
            novel_id: 小说 ID
            structure: 用户编辑后的结构（部-卷-幕）

        Returns:
            创建结果
        """
        created_nodes = []
        order_index = 0

        # 遍历部
        for part_data in structure:
            # 创建部节点
            part_node = self._create_node_from_data(
                novel_id=novel_id,
                parent_id=None,
                node_type=NodeType.PART,
                data=part_data,
                order_index=order_index
            )
            created_nodes.append(part_node)
            order_index += 1

            # 遍历卷
            for volume_data in part_data.get("volumes", []):
                volume_node = self._create_node_from_data(
                    novel_id=novel_id,
                    parent_id=part_node.id,
                    node_type=NodeType.VOLUME,
                    data=volume_data,
                    order_index=order_index
                )
                created_nodes.append(volume_node)
                order_index += 1

                # 遍历幕
                for act_data in volume_data.get("acts", []):
                    act_node = self._create_node_from_data(
                        novel_id=novel_id,
                        parent_id=volume_node.id,
                        node_type=NodeType.ACT,
                        data=act_data,
                        order_index=order_index
                    )
                    created_nodes.append(act_node)
                    order_index += 1

        # 批量保存到数据库
        await self.story_node_repo.save_batch(created_nodes)

        return {
            "novel_id": novel_id,
            "created_nodes": len(created_nodes),
            "nodes": [node.to_dict() for node in created_nodes]
        }

    def _build_macro_planning_prompt(
        self,
        premise: str,
        target_chapters: int,
        structure_preference: Dict[str, int],
        bible_context: Optional[Dict] = None
    ) -> str:
        """构建宏观规划提示词"""
        parts = structure_preference.get("parts", 3)
        volumes_per_part = structure_preference.get("volumes_per_part", 3)
        acts_per_volume = structure_preference.get("acts_per_volume", 3)

        bible_info = ""
        if bible_context:
            bible_info = f"""
可用的 Bible 信息：
主要人物：{', '.join(bible_context.get('characters', []))}
主要地点：{', '.join(bible_context.get('locations', []))}
核心冲突：{', '.join(bible_context.get('conflicts', []))}
"""

        prompt = f"""你是一位资深的小说结构规划师。请根据以下信息为小说设计完整的宏观结构框架。

小说前提：
{premise}

目标章节数：{target_chapters}

结构偏好：
- {parts} 部
- 每部 {volumes_per_part} 卷
- 每卷 {acts_per_volume} 幕

{bible_info}

请设计一个完整的结构框架，包括：
1. 每个部/卷/幕的标题和描述
2. 每个层级的预计章节数（总和应接近 {target_chapters}）
3. 每个部的主题标签（2-3个）
4. 每个幕的关键事件（2-3个）
5. 每个幕的叙事弧线描述
6. 每个幕的主要冲突（1-2个）

输出格式（JSON）：
{{
  "parts": [
    {{
      "number": 1,
      "title": "第一部：标题",
      "description": "描述",
      "suggested_chapter_count": 30,
      "themes": ["主题1", "主题2"],
      "volumes": [
        {{
          "number": 1,
          "title": "第一卷：标题",
          "description": "描述",
          "suggested_chapter_count": 10,
          "themes": ["主题1"],
          "acts": [
            {{
              "number": 1,
              "title": "第一幕：标题",
              "description": "描述",
              "suggested_chapter_count": 3,
              "key_events": ["事件1", "事件2"],
              "narrative_arc": "叙事弧线描述",
              "conflicts": ["冲突1"]
            }}
          ]
        }}
      ]
    }}
  ]
}}

要求：
1. 所有描述必须是单行字符串，不能包含换行符
2. 确保 JSON 格式完全正确
3. 章节数分配要合理，总和接近目标章节数
4. 标题要有吸引力，描述要简洁明了

只输出 JSON，不要有任何解释文字。"""

        return prompt

    def _parse_llm_response(self, response: str) -> List[Dict]:
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
            return data.get("parts", [])
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析失败: {e}\n原始内容: {content[:200]}")

    def _create_node_from_data(
        self,
        novel_id: str,
        parent_id: Optional[str],
        node_type: NodeType,
        data: Dict,
        order_index: int
    ) -> StoryNode:
        """从数据字典创建节点"""
        node_id = f"{node_type.value}-{uuid.uuid4().hex[:8]}"

        node = StoryNode(
            id=node_id,
            novel_id=novel_id,
            parent_id=parent_id,
            node_type=node_type,
            number=data["number"],
            title=data["title"],
            description=data.get("description"),
            order_index=order_index,

            # 规划相关
            planning_status=PlanningStatus.CONFIRMED,
            planning_source=PlanningSource.AI_MACRO,

            # 预计章节数
            suggested_chapter_count=data.get("suggested_chapter_count"),

            # 主题
            themes=data.get("themes", []),

            # 幕级字段
            key_events=data.get("key_events", []) if node_type == NodeType.ACT else [],
            narrative_arc=data.get("narrative_arc") if node_type == NodeType.ACT else None,
            conflicts=data.get("conflicts", []) if node_type == NodeType.ACT else [],
        )

        return node
