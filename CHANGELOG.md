# Changelog

本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [v0.1.0] - 2026-08-12

### 重大变更

- 路由命中后不再由插件独立调用目标模型、发送回复或停止事件，而是仅为本次请求设置 AstrBot 的 `selected_provider`。
- 最终生成完全回归 AstrBot 主 Agent：工具调用、模型 fallback、流式输出、内容安全、上下文管理、TTS、发送与会话历史持久化均继续使用 AstrBot 原生流程。

### 变更

- 路由决策迁移到 `on_waiting_llm_request` 前置钩子，人格覆盖保留在后续 `on_llm_request` 请求钩子中。
- 插件只切换本次聊天模型，不修改 AstrBot 的图片描述模型、STT、TTS 或其他提供商配置。
- 对不支持图片、音频或视频的路由聊天模型，仅清理历史上下文中对应的媒体内容块；同一消息中的文本、已有图片描述以及工具载荷均保留。
- 当前消息携带的图片、音频、额外内容和工具对象不由插件删除，继续由 AstrBot 根据所选模型能力处理。
- 最低 AstrBot 版本提升至 `v4.11.0`，以使用 `on_waiting_llm_request` 钩子。

### 修复

- 避免纯文本路由模型因历史上下文残留 OpenAI `image_url` 内容块而在请求解析阶段返回 HTTP 400。

## [v0.0.5] - 2026-08-12

### 新增

- 配置面板底部新增“无需匹配/判断直接路由”开关，默认开启；未设置规则词汇和类型的公共条目可接管所有未被规则或 LLM 命中的消息。
- 主开关开启时显示“白名单直接路由”开关，默认开启；命中白名单且没有匹配条件的绑定条目可直接路由。
- 即使未启用规则匹配和 LLM 判断，只要对应直接路由开关有效，空条件条目仍可完成路由。

### 变更

- 所有涉及优先级的路由顺序均改为高优先级优先、同优先级随机，不再按面板顺序固定决胜。
- 规则匹配和 LLM 判断保持在直接路由之前执行；直接路由只作为空条件条目的兜底路径。

## [v0.0.4] - 2026-08-12

### 变更

- 只有路由条目未选择人格时才跟随当前 AstrBot 请求实际生效的人格。
- 在路由条目中选择“默认人格”时，改为明确使用 AstrBot 自带默认人格，不再沿用当前会话选择的其他人格。

## [v0.0.3] - 2026-08-12

### 新增

- 路由条目新增 AstrBot 人格选择；留空或选择默认人格时沿用当前请求的人格，选择其他人格时仅覆盖命中路由模型的系统提示词。
- 路由条目新增 0～100 优先级配置，默认值为 100。
- 规则匹配和 LLM 判断均按优先级从高到低执行，同优先级保持面板顺序。

### 变更

- 白名单改为绑定语义：命中白名单后只在所有命中的白名单条目中路由，公共条目不再参与。
- 同一用户命中多个白名单条目时，按照优先级决定路由顺序。

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

[v0.1.0]: https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases/tag/v0.1.0
[v0.0.5]: https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases/tag/v0.0.5
[v0.0.4]: https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases/tag/v0.0.4
[v0.0.3]: https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases/tag/v0.0.3
[v0.0.2]: https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases/tag/v0.0.2
[v0.0.1]: https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases/tag/v0.0.1
