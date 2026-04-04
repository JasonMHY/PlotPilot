"""
故事结构规划 API 路由
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict

from application.services.macro_planning_service import MacroPlanningService
from application.services.act_planning_service import ActPlanningService
from infrastructure.persistence.database.story_node_repository import StoryNodeRepository
from infrastructure.persistence.database.chapter_element_repository import ChapterElementRepository
from infrastructure.ai.llm_client import LLMClient
from infrastructure.config import get_db_path


router = APIRouter(prefix="/api/v1/planning", tags=["planning"])


# ==================== DTOs ====================

class StructurePreference(BaseModel):
    """结构偏好"""
    parts: int = Field(3, ge=1, le=10, description="部数")
    volumes_per_part: int = Field(3, ge=1, le=10, description="每部卷数")
    acts_per_volume: int = Field(3, ge=1, le=10, description="每卷幕数")


class MacroPlanRequest(BaseModel):
    """宏观规划请求"""
    target_chapters: int = Field(100, ge=10, le=1000, description="目标章节数")
    structure: StructurePreference = Field(default_factory=StructurePreference, description="结构偏好")
    bible_context: Optional[Dict] = Field(None, description="Bible 上下文")


class MacroPlanConfirmRequest(BaseModel):
    """宏观规划确认请求"""
    structure: List[Dict] = Field(..., description="用户编辑后的结构")


class ActPlanRequest(BaseModel):
    """幕级规划请求"""
    bible_context: Dict = Field(..., description="Bible 上下文")
    previous_summary: Optional[str] = Field(None, description="前面章节摘要")


class ActPlanConfirmRequest(BaseModel):
    """幕级规划确认请求"""
    chapters: List[Dict] = Field(..., description="用户编辑后的章节列表")


# ==================== 依赖注入 ====================

def get_macro_planning_service() -> MacroPlanningService:
    """获取宏观规划服务"""
    db_path = get_db_path()
    story_node_repo = StoryNodeRepository(db_path)
    llm_client = LLMClient()
    return MacroPlanningService(story_node_repo, llm_client)


def get_act_planning_service() -> ActPlanningService:
    """获取幕级规划服务"""
    db_path = get_db_path()
    story_node_repo = StoryNodeRepository(db_path)
    chapter_element_repo = ChapterElementRepository(db_path)
    llm_client = LLMClient()
    return ActPlanningService(story_node_repo, chapter_element_repo, llm_client)


# ==================== 宏观规划 API ====================

@router.post("/novels/{novel_id}/macro")
async def generate_macro_plan(
    novel_id: str,
    request: MacroPlanRequest,
    service: MacroPlanningService = Depends(get_macro_planning_service)
):
    """
    生成宏观规划

    生成小说的部-卷-幕结构框架，不保存到数据库。
    用户可以编辑后再调用确认接口保存。
    """
    try:
        # 获取小说信息（包括 premise）
        from infrastructure.persistence.database.sqlite_novel_repository import SQLiteNovelRepository
        novel_repo = SQLiteNovelRepository(get_db_path())
        novel = await novel_repo.get_by_id(novel_id)
        if not novel:
            raise HTTPException(status_code=404, detail="小说不存在")

        # 生成宏观规划
        result = await service.generate_macro_plan(
            novel_id=novel_id,
            premise=novel.premise or novel.title,
            target_chapters=request.target_chapters,
            structure_preference=request.structure.dict(),
            bible_context=request.bible_context
        )

        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成宏观规划失败: {str(e)}")


@router.post("/novels/{novel_id}/macro/confirm")
async def confirm_macro_plan(
    novel_id: str,
    request: MacroPlanConfirmRequest,
    service: MacroPlanningService = Depends(get_macro_planning_service)
):
    """
    确认宏观规划

    将用户编辑后的结构保存到数据库，创建所有节点。
    """
    try:
        result = await service.confirm_macro_plan(
            novel_id=novel_id,
            structure=request.structure
        )

        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"确认宏观规划失败: {str(e)}")


# ==================== 幕级规划 API ====================

@router.post("/acts/{act_id}/plan")
async def generate_act_plan(
    act_id: str,
    request: ActPlanRequest,
    service: ActPlanningService = Depends(get_act_planning_service)
):
    """
    生成幕级规划

    为指定的幕生成章节规划，包括章节标题、大纲、关联的 Bible 元素等。
    不保存到数据库，用户可以编辑后再调用确认接口保存。
    """
    try:
        result = await service.generate_act_plan(
            act_id=act_id,
            bible_context=request.bible_context,
            previous_summary=request.previous_summary
        )

        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成幕级规划失败: {str(e)}")


@router.post("/acts/{act_id}/plan/confirm")
async def confirm_act_plan(
    act_id: str,
    request: ActPlanConfirmRequest,
    service: ActPlanningService = Depends(get_act_planning_service)
):
    """
    确认幕级规划

    将用户编辑后的章节列表保存到数据库，创建章节节点和元素关联。
    """
    try:
        result = await service.confirm_act_plan(
            act_id=act_id,
            chapters=request.chapters
        )

        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"确认幕级规划失败: {str(e)}")


# ==================== 查询 API ====================

@router.get("/novels/{novel_id}/structure")
async def get_novel_structure(novel_id: str):
    """
    获取小说的完整结构树

    返回层级化的结构，包含所有部-卷-幕-章节。
    """
    try:
        db_path = get_db_path()
        story_node_repo = StoryNodeRepository(db_path)

        tree = await story_node_repo.get_tree(novel_id)

        return {
            "success": True,
            "data": tree.to_hierarchical_dict()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取结构树失败: {str(e)}")


@router.get("/acts/{act_id}")
async def get_act_detail(act_id: str):
    """
    获取幕的详细信息

    包括幕的基本信息、关键事件、叙事弧线、冲突等。
    """
    try:
        db_path = get_db_path()
        story_node_repo = StoryNodeRepository(db_path)

        act = await story_node_repo.get_by_id(act_id)
        if not act:
            raise HTTPException(status_code=404, detail="幕不存在")

        return {
            "success": True,
            "data": act.to_dict()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取幕详情失败: {str(e)}")


@router.get("/chapters/{chapter_id}")
async def get_chapter_detail(chapter_id: str):
    """
    获取章节的详细信息

    包括章节基本信息、大纲、关联的 Bible 元素等。
    """
    try:
        db_path = get_db_path()
        story_node_repo = StoryNodeRepository(db_path)
        chapter_element_repo = ChapterElementRepository(db_path)

        chapter = await story_node_repo.get_by_id(chapter_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")

        # 获取关联的元素
        elements = await chapter_element_repo.get_by_chapter(chapter_id)

        return {
            "success": True,
            "data": {
                "chapter": chapter.to_dict(),
                "elements": [elem.to_dict() for elem in elements]
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取章节详情失败: {str(e)}")
