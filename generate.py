"""Oimage — 文生图 / 图生图 / 多图并发 / AI 工具调用"""

import asyncio
import base64
import os
import time
from io import BytesIO

import aiohttp
from PIL import Image

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

LOG = "[OImage]"

# 宽高比 → 像素尺寸映射
GPT_SIZES = {
    "1:1": "1024x1024",
    "3:2": "1536x1024",
    "16:9": "1536x1024",
    "4:3": "1536x1024",
    "21:9": "1536x1024",
    "2:3": "1024x1536",
    "3:4": "1024x1536",
    "9:16": "1024x1536",
}
DALLE_SIZES = {
    "1:1": "1024x1024",
    "3:2": "1792x1024",
    "16:9": "1792x1024",
    "4:3": "1792x1024",
    "21:9": "1792x1024",
    "2:3": "1024x1792",
    "3:4": "1024x1792",
    "9:16": "1024x1792",
}


class Generate:
    def __init__(self, context, config):
        self.config = config
        self._session = None
        self._sem = None
        astrbot_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.data_dir = os.path.join(astrbot_dir, "data", "plugin_data", "oimage")
        os.makedirs(self.data_dir, exist_ok=True)
        self.max_stored_images = int(
            self.config.get("storage", {}).get("max_stored_images", 30)
        )

    # ── 基础设施 ──

    def cfg(self, key, default=""):
        """读取 openai_config 配置项。"""
        return self.config.get("openai_config", {}).get(key, default)

    @property
    def session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @property
    def semaphore(self):
        if self._sem is None:
            n = int(self.config.get("generation", {}).get("max_concurrent_tasks", 3))
            self._sem = asyncio.Semaphore(n)
        return self._sem

    @property
    def _is_gpt(self) -> bool:
        """当前模型是否为 GPT-Image 系列。"""
        m = self.cfg("model", "").lower()
        return "gpt-image" in m or self.cfg("model_family", "") == "gpt-image"

    def _resolve_size(self, size: str | None) -> str:
        """用户可能传宽高比（1:1）或像素尺寸（1024x1024），统一为像素尺寸。"""
        if size and ":" in size:
            return (GPT_SIZES if self._is_gpt else DALLE_SIZES).get(size, size)
        return size or self.cfg("size", "1024x1024")

    # ── 指令解析 ──

    def parse_command(self, text: str):
        """从指令文本提取 (prompt, count, size)。"""
        tokens = text.strip().split()
        if not tokens:
            return "", 1, None
        count, size, end = 1, None, 0
        for i, t in enumerate(tokens):
            if t.isdecimal() and 1 <= int(t) <= 10:
                count, end = int(t), i + 1
            elif "x" in t and t.replace("x", "").replace("X", "").isdigit():
                size, end = t.lower(), i + 1
            else:
                end = i
                break
        return " ".join(tokens[end:]).strip(), count, size

    # ── 参考图下载 ──

    async def download_image(self, url: str):
        """下载一张图片，返回 (bytes, mime)，不支持的格式转 JPEG。"""
        if not url:
            return None
        try:
            async with self.session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as r:
                if r.status != 200:
                    return None
                data = await r.read()
                if len(data) > 10 * 1024 * 1024:
                    return None
                mime = self._detect_mime(data) or r.content_type or "image/png"
                return await self._ensure_jpeg(data, mime)
        except Exception:
            return None

    def _detect_mime(self, data: bytes) -> str | None:
        if data.startswith(b"\xff\xd8"):
            return "image/jpeg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data[:4] == b"GIF8":
            return "image/gif"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return "image/webp"
        return None

    async def _ensure_jpeg(self, data: bytes, mime: str):
        if mime in ("image/png", "image/jpeg", "image/webp"):
            return data, mime
        try:
            img = Image.open(BytesIO(data))
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                alpha = img.split()[3]
                bg.paste(img, mask=alpha)
                img = bg
            out = BytesIO()
            img.save(out, format="JPEG", quality=95)
            return out.getvalue(), "image/jpeg"
        except Exception:
            return data, mime

    async def collect_references(self, event):
        """从消息事件中提取所有图片作为参考图。"""
        results = []
        if not event.message_obj or not event.message_obj.message:
            return results
        for comp in event.message_obj.message:
            if isinstance(comp, Comp.Image):
                if img := await self.download_image(comp.url or comp.file):
                    results.append(img)
            elif isinstance(comp, Comp.Reply) and comp.chain:
                for sub in comp.chain:
                    if isinstance(sub, Comp.Image):
                        if img := await self.download_image(sub.url or sub.file):
                            results.append(img)
        return results

    # ── API 调用 ──

    async def _post(self, url, headers, **kwargs):
        """通用 POST + 响应提取。"""
        try:
            async with self.session.post(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=int(self.cfg("timeout", 180))),
                **kwargs,
            ) as r:
                return await self._extract(r)
        except asyncio.TimeoutError:
            return None, "请求超时"
        except Exception as e:
            logger.error(f"{LOG} 请求异常: {e}")
            return None, str(e)

    async def _call_api(self, prompt, size, refs):
        """单次生成调用（有参考图走 edits，否则走 generations）。"""
        base = self.cfg("base_url", "https://api.openai.com/v1").rstrip("/")
        key = self.cfg("api_key")
        model = self.cfg("model", "gpt-image-2")

        if refs and self._is_gpt:
            form = aiohttp.FormData()
            form.add_field("model", model)
            form.add_field("prompt", prompt)
            form.add_field("n", "1")
            if size:
                form.add_field("size", size)
            for data, mime in refs:
                form.add_field("image", data, content_type=mime, filename="image.png")
            return await self._post(
                f"{base}/images/edits",
                headers={"Authorization": f"Bearer {key}"},
                data=form,
            )

        payload = {"model": model, "prompt": prompt, "n": 1}
        if size:
            payload["size"] = size
        if not self._is_gpt:
            payload["response_format"] = "b64_json"
        return await self._post(
            f"{base}/images/generations",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    async def _extract(self, resp):
        """HTTP 响应 → (图片列表, 错误信息)。"""
        if resp.status != 200:
            text = await resp.text()
            logger.error(f"{LOG} API {resp.status}: {text[:200]}")
            return None, f"API 错误 ({resp.status})"
        body = await resp.json()
        if "data" not in body:
            return None, "响应中缺少 data 字段"

        images = []
        for item in body["data"]:
            if "b64_json" in item:
                images.append(base64.b64decode(item["b64_json"]))
            elif "url" in item:
                try:
                    async with self.session.get(item["url"]) as ir:
                        if ir.status == 200:
                            images.append(await ir.read())
                except Exception as e:
                    logger.warning(f"{LOG} 下载结果图片失败: {e}")
        return (images, None) if images else (None, "未找到有效图片数据")

    def save_image(self, data: bytes) -> str:
        path = os.path.join(self.data_dir, f"gen_{int(time.time() * 1000)}.png")
        with open(path, "wb") as f:
            f.write(data)
        self._cleanup_old_images()
        return path

    def _cleanup_old_images(self):
        """保留最近 max_stored_images 张图片，删除超出部分（按mtime最旧优先）。"""
        try:
            files = [
                os.path.join(self.data_dir, f)
                for f in os.listdir(self.data_dir)
                if f.startswith("gen_") and f.endswith(".png")
            ]
            if len(files) <= self.max_stored_images:
                return
            files.sort(key=os.path.getmtime)
            for f in files[: len(files) - self.max_stored_images]:
                try:
                    os.remove(f)
                except OSError:
                    pass
        except OSError:
            pass

    # ── 多图并发生成 ──

    NON_RETRYABLE = (
        "invalid",
        "unauthorized",
        "forbidden",
        "not found",
        "unsupported",
        "bad request",
        "permission",
        "safety",
        "参数",
        "无效",
        "不支持",
    )

    async def generate_batch(self, prompt, n, size, refs):
        """并发生成 n 张图，每张独立重试。"""
        max_retry = int(self.config.get("generation", {}).get("max_retry_attempts", 3))

        async def _one():
            for attempt in range(max_retry + 1):
                async with self.semaphore:
                    images, err = await self._call_api(prompt, size, refs)
                if images:
                    return self.save_image(images[0])
                if err and any(kw in err.lower() for kw in self.NON_RETRYABLE):
                    break
                if attempt + 1 < max_retry:
                    await asyncio.sleep(min(2 ** (attempt + 1), 10))
            return None

        results = await asyncio.gather(*[_one() for _ in range(n)])
        return [r for r in results if r]

    # ── 公开接口 ──

    async def draw(self, event: AstrMessageEvent):
        text = event.message_str.replace("/Oimage", "").strip()
        if not text:
            yield event.plain_result(
                "❌ 缺少提示词\n用法：/Oimage <关键词> [数量] [尺寸]"
            )
            return

        prompt, n, raw_size = self.parse_command(text)
        if not prompt:
            yield event.plain_result("❌ 提示词不能为空")
            return
        if not self.cfg("api_key"):
            yield event.plain_result("❌ API Key 未配置")
            return

        refs = await self.collect_references(event)
        mode = "图生图" if (refs and self._is_gpt) else "文生图"
        size = self._resolve_size(raw_size)

        ref_info = f"（参考图 {len(refs)} 张）" if refs and self._is_gpt else ""
        yield event.plain_result(f"🎨 {mode}中{ref_info}：{prompt}...")

        t0 = time.time()
        paths = await self.generate_batch(
            prompt, n, size, refs if self._is_gpt else None
        )
        elapsed = time.time() - t0

        if not paths:
            yield event.plain_result("❌ 生成失败")
            return
        for p in paths:
            yield event.image_result(p)
        yield event.plain_result(
            f"✅ {len(paths)}张 | {prompt} | {self.cfg('model')} | {elapsed:.1f}s"
        )

    async def draw_tool(self, prompt, n=1, size=None, ref_image_urls=None):
        if not self.cfg("api_key"):
            return "❌ API Key 未配置"

        size = self._resolve_size(size or self.cfg("size", "1024x1024"))
        refs = []
        if ref_image_urls and self._is_gpt:
            for url in ref_image_urls:
                if img := await self.download_image(url):
                    refs.append(img)

        paths = await self.generate_batch(
            prompt, n, size, refs if self._is_gpt else None
        )
        if not paths:
            return "❌ 生成失败"
        return "\n".join([f"已生成 {len(paths)} 张图片", *paths])

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
