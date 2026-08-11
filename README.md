# AstrBot LLM Router

[![Release](https://img.shields.io/github/v/release/Lan-0v0/astrbot_plugin_llm_router)](https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases)
[![CI](https://github.com/Lan-0v0/astrbot_plugin_llm_router/actions/workflows/ci.yml/badge.svg)](https://github.com/Lan-0v0/astrbot_plugin_llm_router/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/Lan-0v0/astrbot_plugin_llm_router)](LICENSE)
[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.10.4-blue)](https://github.com/AstrBotDevs/AstrBot)

一个 AstrBot 模型路由插件。它在 AstrBot 即将调用原聊天模型前判断当前消息，并将命中的消息交给所选的 AstrBot 已有聊天模型提供商处理。

当前版本：`v0.0.2`

## 主要特性

- 规则匹配优先，规则未命中后才进行 LLM 类型判断。
- 每个路由条目直接选择 AstrBot 已配置的聊天模型。
- 模型地址、API Key 和具体模型名称由 AstrBot 统一管理，无需在插件中重复填写。
- 未命中或分类、模型调用、消息发送失败时自动回退 AstrBot 原模型。
- 支持每个条目配置多个内容类型和规则词汇。
- 支持条目级白名单与黑名单，且黑名单优先。

## 路由顺序

1. 过滤未启用、未选择路由模型、不满足白名单或命中黑名单的条目。
2. 若启用“规则匹配”，按配置列表顺序检查“规则词汇”。
3. 规则未命中且启用“LLM判断”时，调用“类型判断 LLM”，判断消息是否属于某条目的“类型”。
4. 命中后通过 AstrBot 的统一 LLM 接口调用该条目选择的“路由模型”。
5. 未命中或任何路由环节失败时，不中断事件，继续使用 AstrBot 原本设置的 LLM。

因此，同时勾选两种判断方式时始终是**规则优先，LLM 判断兜底**。

## 配置说明

### 判断方式

- `规则匹配`：消息包含条目中的任一规则词汇即命中，英文不区分大小写。
- `LLM判断`：使用所选的现有 AstrBot 聊天模型，将消息分类到条目配置的类型之一。

### 类型判断 LLM

选择一个已在 AstrBot 中配置的聊天模型。只有规则未命中且启用了 LLM 判断时才会调用。

### 路由条目

每个条目包含：

- 名称与启用开关；
- 路由模型：选择一个 AstrBot 已有聊天模型提供商；
- 一个或多个内容类型；
- 一个或多个规则词汇；
- 白名单和黑名单。

`类型`留空时，该条目不参与 LLM 判断；`规则词汇`留空时，该条目不参与规则匹配。两者都留空时，该条目不会被路由命中。

> 从 `v0.0.1` 升级时，插件会自动移除旧条目中保存的地址、密钥和模型名称，并保留名称及匹配条件。升级后需要为每个条目重新选择 AstrBot 路由模型。

## 白名单与黑名单

留空表示不启用。黑名单优先于白名单。

未加前缀的值会与用户 ID、群 ID、会话 ID、统一消息来源进行精确匹配。也可使用以下前缀明确指定：

- `user:123456`
- `group:987654`
- `session:session-id`
- `umo:统一消息来源`
- `name:发送者名称`
- `platform:平台适配器名称`

带 `name:` 的匹配依赖平台提供的显示名，权限控制场景更建议使用稳定用户 ID。

## AstrBot 模型调用

- 类型判断和目标模型生成均使用 AstrBot 公开的 `llm_generate` 接口。
- 插件会传递本轮提示、系统提示、对话上下文、图片、音频和额外用户内容。
- 路由回复会尽力写回 AstrBot 当前会话历史；写入失败不会影响已经发送的回复。
- 当前路由调用不接管 AstrBot Agent 的工具调用循环；目标模型用于直接生成本轮文本回复。

## 安装

### 从 GitHub Release 安装

1. 前往 [Releases](https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases) 下载最新的 `astrbot_plugin_llm_router-v*.zip`。
2. 在 AstrBot WebUI 的插件管理页面上传压缩包，或解压到 `AstrBot/data/plugins/astrbot_plugin_llm_router`。
3. 重载插件后进入插件配置页面。
4. 选择判断方式和类型判断 LLM，并添加至少一个路由条目。

### 从源码安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/Lan-0v0/astrbot_plugin_llm_router.git
```

`v0.0.2` 不包含额外的第三方 Python 依赖。

## 兼容性

- AstrBot：`>=4.10.4,<5`
- Python：建议使用 AstrBot 当前支持的 Python 版本
- 发布包遵循 AstrBot 插件市场不超过 16 MB 的限制

## 开发与测试

开发约定参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

```bash
py -3 -m unittest discover -s tests -v
py -3 -m compileall -q .
py -3 -m ruff check .
py -3 -m ruff format --check .
```

## 发布与变更

- 版本历史见 [CHANGELOG.md](CHANGELOG.md)。
- 发布 GitHub Release 后，GitHub Actions 会执行测试、构建 AstrBot 安装压缩包并上传至对应 Release。
- 安全问题请按照 [SECURITY.md](SECURITY.md) 私密报告。

## 许可证

本项目使用 [MIT License](LICENSE)。
