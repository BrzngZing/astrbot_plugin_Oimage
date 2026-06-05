# 🎨 Oimage — AstrBot 图像生成插件

基于 OpenAI 兼容 API 的图像生成插件，支持文生图、图生图、多图并发。

## 功能

- **文生图** — 根据提示词生成图片
- **图生图** — 携带参考图片生成（需 GPT-Image 系列模型）
- **多图并发** — 一次生成多张，每张独立重试
- **LLM 工具** — 注册为 AI 可调用的工具函数

## 配置

| 配置项 | 说明 |
|--------|------|
| `openai_config.base_url` | API 地址，默认 `https://api.openai.com/v1` |
| `openai_config.api_key` | API 密钥 |
| `openai_config.model` | 模型名，如 `gpt-image-2`、`dall-e-3` |
| `openai_config.model_family` | 模型系列：`auto` / `gpt-image` / `dall-e` |
| `openai_config.n` | 默认生成数量 |
| `openai_config.size` | 默认尺寸，如 `1024x1024` |
| `openai_config.timeout` | 请求超时（秒） |
| `generation.max_concurrent_tasks` | 最大并发数 |
| `generation.max_retry_attempts` | 失败重试次数 |

## 用法

```
/Oimage 一只猫坐在沙发上
/Oimage 一只猫 2
/Oimage 一只猫 1536x1024
```

附带参考图：在消息中上传图片，GPT-Image 模型会自动作为图生图参考。

AI 调用：注册为 `oimage_tool`，AI 可通过对话直接生图。

## 注意
- 该项目为个人学习使用
- 该项目大量使用AI生成

  
## 开源协议
  
[GNU Affero General Public License v3.0](LICENSE)