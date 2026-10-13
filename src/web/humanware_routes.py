"""Humanware Engine API Routes

提供角色声音管理和人味评分的 Web API 接口
调用 xs2-novel-flywheel 插件中的 humanware_helper 脚本
"""

from fastapi import APIRouter, HTTPException, Body
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
import logging
import subprocess
import json
import sys

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/humanware", tags=["humanware"])


# ===== Request Models =====

class GenerateVoiceFileRequest(BaseModel):
    workspace_id: str
    from_profiles: bool = True
    from_references: bool = False


class CheckDialogueRequest(BaseModel):
    workspace_id: str
    character: str
    dialogue: str


class ScoreContentRequest(BaseModel):
    workspace_id: str
    character: str
    content: str
    content_type: str = "dialogue"


class ScoreChapterRequest(BaseModel):
    workspace_id: str
    chapter_file: str  # 相对于工作区的路径


# ===== Helper Functions =====

def _get_workspace_root(workspace_id: str) -> Path:
    """获取工作区根目录"""
    root = Path("data/workspaces/books") / workspace_id
    if not root.exists():
        raise HTTPException(status_code=404, detail=f"工作区 {workspace_id} 不存在")
    return root


def _get_humanware_cli_path() -> Path:
    """获取 humanware CLI 脚本路径"""
    cli_path = Path("data/plugins/runtime-resources/xs2-novel-flywheel/script-libraries/0/xs2-novel-flywheel-xs2/humanware_helper/humanware_cli.py")
    if not cli_path.exists():
        raise HTTPException(status_code=500, detail="Humanware CLI 脚本不存在")
    return cli_path


def _run_humanware_command(command: str, *args) -> Dict[str, Any]:
    """运行 humanware CLI 命令"""
    try:
        cli_path = _get_humanware_cli_path()

        # 构建命令
        cmd = [sys.executable, str(cli_path), command] + list(args)

        # 执行命令
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=False  # 获取字节以避免编码问题
        )

        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', errors='ignore')
            logger.error(f"命令执行失败: {stderr}")
            return {
                "status": "error",
                "message": f"执行失败: {stderr}"
            }

        # 解析 JSON 输出（处理 Windows 编码问题）
        try:
            stdout = result.stdout.decode('utf-8', errors='ignore')
            if not stdout or not stdout.strip():
                logger.error("命令没有输出")
                return {
                    "status": "error",
                    "message": "命令执行成功但没有输出"
                }
            return json.loads(stdout)
        except json.JSONDecodeError:
            logger.error(f"无法解析输出: {result.stdout}")
            return {
                "status": "error",
                "message": "无法解析命令输出",
                "raw_output": result.stdout
            }

    except Exception as e:
        logger.error(f"运行命令失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e)
        }


# ===== API Endpoints =====

@router.post("/generate-voice-file")
async def generate_voice_file(request: GenerateVoiceFileRequest) -> Dict[str, Any]:
    """生成 character_voice.md 文件

    Args:
        request: 包含工作区ID和生成选项

    Returns:
        生成结果
    """
    try:
        workspace_root = _get_workspace_root(request.workspace_id)

        if request.from_references:
            # 从参考资料分析生成
            result = _run_humanware_command("analyze-voice", str(workspace_root))
        else:
            # 从 character_profiles.md 生成模板
            result = _run_humanware_command("generate-voice", str(workspace_root))

        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("message", "生成失败"))

        voice_file = workspace_root / "meta/character_voice.md"

        return {
            "status": "success",
            "message": result.get("message", "生成成功"),
            "file_path": str(voice_file),
            "exists": voice_file.exists(),
            "character_count": result.get("character_count", 0)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成角色声音文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


@router.get("/voice-file/{workspace_id}")
async def get_voice_file(workspace_id: str) -> Dict[str, Any]:
    """获取 character_voice.md 文件内容

    Args:
        workspace_id: 工作区ID

    Returns:
        文件内容和状态
    """
    try:
        workspace_root = _get_workspace_root(workspace_id)
        voice_file = workspace_root / "meta/character_voice.md"

        if not voice_file.exists():
            return {
                "status": "not_found",
                "message": "character_voice.md 文件不存在",
                "content": None
            }

        content = voice_file.read_text(encoding="utf-8")

        return {
            "status": "success",
            "content": content,
            "file_path": str(voice_file)
        }

    except Exception as e:
        logger.error(f"读取角色声音文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取失败: {str(e)}")


@router.post("/score-content")
async def score_content(request: ScoreContentRequest) -> Dict[str, Any]:
    """评估内容的人味得分

    Args:
        request: 包含内容和评分参数

    Returns:
        评分结果
    """
    try:
        workspace_root = _get_workspace_root(request.workspace_id)

        # 调用评分命令
        result = _run_humanware_command(
            "score-text",
            str(workspace_root),
            request.character,
            request.content
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("message", "评分失败"))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"评分失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"评分失败: {str(e)}")


@router.post("/score-chapter")
async def score_chapter(request: ScoreChapterRequest) -> Dict[str, Any]:
    """批量评估章节中所有对话

    Args:
        request: 包含工作区ID和章节文件路径

    Returns:
        批量评分结果
    """
    try:
        workspace_root = _get_workspace_root(request.workspace_id)

        # 调用批量评分命令
        result = _run_humanware_command(
            "score-chapter",
            str(workspace_root),
            request.chapter_file
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("message", "评分失败"))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量评分失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"批量评分失败: {str(e)}")


@router.get("/status/{workspace_id}")
async def get_humanware_status(workspace_id: str) -> Dict[str, Any]:
    """获取人味功能的启用状态

    Args:
        workspace_id: 工作区ID

    Returns:
        状态信息
    """
    try:
        workspace_root = _get_workspace_root(workspace_id)

        voice_file = workspace_root / "meta/character_voice.md"
        profiles_file = workspace_root / "meta/character_profiles.md"

        status = {
            "voice_file_exists": voice_file.exists(),
            "profiles_file_exists": profiles_file.exists(),
            "humanware_enabled": voice_file.exists()
        }

        if voice_file.exists():
            content = voice_file.read_text(encoding="utf-8")
            # 统计角色数量（简单计数 ## 开头的行）
            import re
            character_count = len(re.findall(r'^## [^#\s]', content, re.MULTILINE))
            status["character_count"] = character_count
        else:
            status["character_count"] = 0

        return status

    except Exception as e:
        logger.error(f"获取状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")
