"""
Oimage 图像生成插件主模块

支持四大核心能力：
1. 文生图 — 根据提示词生成图片
2. 图生图 — 携带参考图片生成
3. 多图生成 — 一次生成多张
4. LLM Tool 调用 — 供 AI 对话调用
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from .generate import Generate


@register(
    "oimage", "Brzngzing", "AI图像生成插件（文生图/图生图/多图/LLM工具）", "1.0.1"
)
class OImagePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.generate = Generate(context, config)
        logger.info("OImage v0.3.0 初始化完成")

    async def initialize(self):
        """插件加载时注册 LLM Tool"""
        self.context.add_llm_tools(OimageTool(plugin=self))
        logger.info("OImage v0.3.0 插件加载成功，LLM Tool 已注册")

    async def terminate(self):
        """插件卸载时释放资源"""
        await self.generate.close()
        logger.info("OImage v0.3.0 资源已释放")

    @filter.command("Oimage")
    async def Oimage(self, event: AstrMessageEvent):
        """/Oimage 指令 — 支持带参考图、多图生成"""
        async for result in self.generate.draw(event):
            yield result


@dataclass
class OimageTool(FunctionTool[AstrAgentContext]):
    """LLM 图片生成工具 — 机器人通过对话调用生图"""

    name: str = "oimage_tool"
    description: str = "根据提示词生成图片。支持指定数量、尺寸。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "图片生成提示词，详细描述想要的内容",
                },
                "n": {
                    "type": "integer",
                    "description": "生成图片数量，范围 1-10，默认 1",
                    "default": 1,
                },
                "size": {
                    "type": "string",
                    "description": "图片尺寸，如 1024x1024、1536x1024、1792x1024",
                    "default": "1024x1024",
                },
            },
            "required": ["keywords"],
        }
    )
    plugin: Any = None

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs: Any
    ) -> ToolExecResult:
        plugin = self.plugin
        if not plugin:
            return "❌ 插件未正确初始化"

        keywords = str(kwargs.get("keywords", "") or "").strip()
        if not keywords:
            return "请提供关键词"

        raw_n = kwargs.get("n", 1)
        try:
            n = max(1, min(int(raw_n), 10))
        except (TypeError, ValueError):
            n = 1

        raw_size = kwargs.get("size", "")
        image_size: str | None = (
            raw_size.strip() if raw_size and raw_size.strip() else None
        )

        result = await plugin.generate.draw_tool(keywords, n=n, size=image_size)
        return result
