from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger

from .generate import Generate


@register("oimage", "Brzngzing", "AI图像生成插件", "0.0.1")
class OImagePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.generate = Generate(context, config)
        logger.info("OImage 插件加载成功")

    # 注册指令
    @filter.command("Oimage")
    async def Oimage(self, event: AstrMessageEvent):
        """委托给 Generate 类的 draw 方法处理"""
        async for result in self.generate.draw(event):  # ← 调用 draw 方法
            yield result
