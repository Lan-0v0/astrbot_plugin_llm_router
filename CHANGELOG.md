# Changelog

本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [v0.0.2] - 2026-08-12

### 变更

- 路由条目改为直接选择 AstrBot 已配置的聊天模型提供商。
- 移除条目中的 API Base URL、API Key 和模型名称配置。
- 移除 OpenAI 兼容、Gemini、DeepSeek 与 Zhipu 的独立客户端适配代码。
- 类型判断与目标模型调用统一使用 AstrBot 的 `llm_generate` 接口。
- 将四种提供商模板合并为一个更简洁的“路由条目”模板。

### 兼容性

- 从 v0.0.1 升级时会自动清理旧凭据并保留匹配条件，但需要为每个条目重新选择 AstrBot 路由模型。
- 路由模型的地址、密钥和具体模型名称改由 AstrBot 提供商配置统一管理。

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

[v0.0.2]: https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases/tag/v0.0.2
[v0.0.1]: https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases/tag/v0.0.1
