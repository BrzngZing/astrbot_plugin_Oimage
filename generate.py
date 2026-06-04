from openai import OpenAI
from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
import base64
import os
import time


class Generate(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        self.plugin_name = "oimage"
        self._client = None  # 客户端初始为 None
        self._init_data_dir()

    def _init_data_dir(self):
        """初始化插件数据目录"""
        astrbot_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.data_dir = os.path.join(
            astrbot_dir, "data", "plugin_data", self.plugin_name
        )
        os.makedirs(self.data_dir, exist_ok=True)
        logger.info(f"插件数据目录: {self.data_dir}")

    def _get_client(self):
        # 如果已经初始化过，直接返回
        if self._client is not None:
            return self._client

        # 读取基础配置
        openai_config = self.config.get("openai_config", {})
        base_url = openai_config.get("base_url", "https://api.openai.com/v1")
        api_key = openai_config.get("api_key", "")
        timeout = openai_config.get("timeout", 180)

        # 检测是否配置api_key
        if not api_key:
            logger.warning("OpenAI API Key 未配置，请用户在 WebUI 中配置")
            return None

        try:
            self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
            logger.info("OpenAI 客户端初始化成功")
            return self._client
        except Exception as e:
            logger.error(f"OpenAI 客户端初始化失败: {e}")
            return None

    async def draw(self, event: AstrMessageEvent):
        """生成图像指令"""
        # 提取提示词
        prompt = event.message_str.replace("/Oimage", "").strip()

        if not prompt:
            yield event.plain_result(
                "❌ 没有提示词输入，请添加描述，例如：/Oimage 一只猫"
            )
            return

        # 获取客户端（延迟初始化）
        client = self._get_client()

        if client is None:
            yield event.plain_result(
                "❌ 插件未初始化\n\n"
                "   请完整配置插件：\n"
                "1. 打开插件→Astrbot插件\n"
                "2. 找到 Oimage 插件\n"
                "3. 点击「⚙」\n"
                "5. 保存配置"
            )
            return

        # 获取配置
        openai_config = self.config.get("openai_config", {})
        model = openai_config.get("model", "gpt-image-2")
        size = openai_config.get("size", "1024x1024")

        yield event.plain_result(f"🎨 正在生成中：{prompt}...")

        try:
            # 发起生图请求
            result = client.images.generate(
                model=model, prompt=prompt, size=size, n=1, response_format="b64_json"
            )
            # 图片处理（转码并保存）
            image_base64 = result.data[0].b64_json
            image_bytes = base64.b64decode(image_base64)

            timestamp = int(time.time())
            user_id = event.get_sender_id()
            filename = f"generated_{user_id}_{timestamp}.png"
            save_path = os.path.join(self.data_dir, filename)

            with open(save_path, "wb") as f:
                f.write(image_bytes)

            logger.info(f"图像已保存: {save_path}")

            yield event.image_result(save_path)
            yield event.plain_result(
                f"✅ 图像生成成功！\n📝 提示词：{prompt}\n📏 尺寸：{size}"
            )

        except Exception as e:
            logger.error(f"生成失败: {e}")
            yield event.plain_result(f"❌ 生成错误：{str(e)}")
