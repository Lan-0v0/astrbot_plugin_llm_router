# Changelog

本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [v0.0.1] - 2026-08-11

### 新增

- 支持规则匹配和 LLM 类型判断两种路由方式。
- 同时启用两种方式时，规则匹配优先，未命中后再调用分类模型。
- 支持 OpenAI 兼容、Gemini、DeepSeek 和 Zhipu 路由模型条目。
- 支持条目级类型、规则词汇、白名单和黑名单。
- 支持多个 API Key 轮换及可重试错误下的 Key 故障转移。
- 支持分类、模型调用及消息发送异常时回退 AstrBot 原模型。
- 支持将成功的路由回复写回 AstrBot 会话历史。
- 增加 AstrBot WebUI 配置 Schema、使用文档、测试和 GitHub 发布工作流。

[v0.0.1]: https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases/tag/v0.0.1
