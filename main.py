"""Oimage 图像生成插件主模块"""

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
    "oimage", "Brzngzing", "AI图像生成插件（文生图/图生图/多图/LLM工具）", "1.1.0"
)
class OImagePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.generate = Generate(context, config)
        logger.info("OImage v1.1.0 初始化完成")

    async def initialize(self):
        """注册 LLM Tool"""
        self.context.add_llm_tools(OimageTool(plugin=self))
        logger.info("OImage v1.1.0 插件加载成功")

    async def terminate(self):
        """释放资源"""
        await self.generate.close()
        logger.info("OImage v1.1.0 资源已释放")

    @filter.command("Oimage")
    async def Oimage(self, event: AstrMessageEvent):
        """/Oimage 指令入口"""
        async for result in self.generate.draw(event):
            yield result


@dataclass
class OimageTool(FunctionTool[AstrAgentContext]):
    """LLM 调用的生图工具"""

    name: str = "oimage_tool"
    description: str = (
        '根据提示词生成图片。支持图生图、指定数量、尺寸。'
        '重要：只使用用户的需求文本作为关键词，不要自行添加任何场景描述、画面细节或艺术风格设定。'
        '不要猜测、扩展或美化用户提示词，仅对用户的提示词进行整理。'
        '如果生图成功，请把图片返回给用户。'
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "用户原始需求文本。不要添加自己的场景描述、画面细节或艺术风格设定，只传递用户本来说的话。",
                },
                "reference_images": {
                    "type": "array",
                    "description": "参考图 URL。直接传入即可，不要对图片内容做任何描述或猜测。",
                    "items": {"type": "string"},
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

        ref_images: list[tuple[bytes, str]] = []
        try:
            event = context.context.event
            if event:
                ref_images = await plugin.generate.collect_references(event)
        except Exception:
            pass

        refs = kwargs.get("reference_images")
        if refs and isinstance(refs, list):
            for url in refs:
                if url and (img := await plugin.generate.download_image(str(url))):
                    if img not in ref_images:
                        ref_images.append(img)

        result = await plugin.generate.draw_tool(
            keywords, n=n, size=image_size, ref_images=ref_images,
        )
        return result
