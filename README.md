# AstrBot LLM Router

[![Release](https://img.shields.io/github/v/release/Lan-0v0/astrbot_plugin_llm_router)](https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases)
[![CI](https://github.com/Lan-0v0/astrbot_plugin_llm_router/actions/workflows/ci.yml/badge.svg)](https://github.com/Lan-0v0/astrbot_plugin_llm_router/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/Lan-0v0/astrbot_plugin_llm_router)](LICENSE)
[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.10.4-blue)](https://github.com/AstrBotDevs/AstrBot)

一个 AstrBot 模型路由插件。它在 AstrBot 即将调用原聊天模型前检查当前消息，并可将命中的消息改由独立配置的 OpenAI 兼容、Gemini、DeepSeek 或 Zhipu 模型处理。

当前版本：`v0.0.1`

## 主要特性

- 规则匹配优先，规则未命中后才进行 LLM 类型判断。
- 未命中或路由失败时自动回退 AstrBot 原模型。
- 支持 OpenAI 兼容、Gemini、DeepSeek 和 Zhipu。
- 支持每个条目配置多个类型、规则词汇和 API Key。
- 支持条目级白名单与黑名单，且黑名单优先。
- 支持 API Key 轮换及限流、鉴权失败、超时和服务端错误下的故障转移。

## 路由顺序

1. 过滤未启用、不满足白名单或命中黑名单的条目。
2. 若启用“规则匹配”，按配置列表顺序检查“规则词汇”。
3. 规则未命中且启用“LLM判断”时，调用“类型判断 LLM”，判断消息是否属于某条目的“类型”。
4. 命中后请求对应路由模型并发送回复。
5. 未命中、配置不完整、分类失败、路由接口失败或回复发送失败时，不中断事件，继续使用 AstrBot 原本设置的 LLM。

因此，同时勾选两种判断方式时始终是**规则优先，LLM 判断兜底**。

## 配置说明

### 判断方式

- `规则匹配`：消息包含条目中的任一规则词汇即命中，英文不区分大小写。
- `LLM判断`：使用所选的现有 AstrBot 聊天模型，将消息分类到条目配置的类型之一。

### 路由模型

每个条目包含：

- 名称与启用开关；
- API Base URL；
- 模型名称；
- 一个或多个 API Key；
- 一个或多个类型；
- 一个或多个规则词汇；
- 白名单和黑名单。

API 调用无法仅凭 Base URL 确定模型，因此配置中额外提供了必要的“模型名称”字段。

多个 API Key 会轮换作为首选 Key。遇到鉴权失败、限流、超时或服务端错误时，插件会继续尝试同一条目的下一个 Key。Key 不会写入插件日志。

## 白名单与黑名单

留空表示不启用。黑名单优先于白名单。

未加前缀的值会与用户 ID、群 ID、会话 ID、统一消息来源进行精确匹配。也可使用以下前缀明确指定：

- `user:123456`
- `group:987654`
- `session:session-id`
- `umo:统一消息来源`
- `name:发送者名称`
- `platform:平台适配器名称`

带 `name:` 的匹配依赖平台提供的显示名，权限控制场景更建议使用不可随意修改的用户 ID。

## 接口兼容性

- OpenAI 兼容、DeepSeek、Zhipu 使用 `POST /chat/completions`。
- Gemini 使用原生 `POST /models/{model}:generateContent`。
- OpenAI 兼容接口支持 HTTP(S)、data URL 和本地图片路径；本地图片会转换为 data URL。
- Gemini 支持 data URL 与本地图片/音频文件。远程媒体 URL 不会由插件主动下载，避免额外的网络访问风险。
- 路由回复会尽力写回 AstrBot 当前会话历史；写入失败不会影响已发送的回复。

当前路由调用不接管 AstrBot Agent 的工具调用循环；目标模型用于直接生成本轮文本回复。未命中路由时，AstrBot 原 Agent/LLM 流程保持不变。

## 安装

### 从 GitHub Release 安装

1. 前往 [Releases](https://github.com/Lan-0v0/astrbot_plugin_llm_router/releases) 下载最新的 `astrbot_plugin_llm_router-v*.zip`。
2. 在 AstrBot WebUI 的插件管理页面上传压缩包，或解压到 `AstrBot/data/plugins/astrbot_plugin_llm_router`。
3. 重载插件后进入插件配置页面。
4. 选择判断方式和类型判断 LLM，并添加至少一个路由模型条目。

### 从源码安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/Lan-0v0/astrbot_plugin_llm_router.git
```

AstrBot 会依据 `requirements.txt` 安装插件依赖。如需手动安装：

```bash
python -m pip install -r requirements.txt
```

## 兼容性

- AstrBot：`>=4.10.4,<5`
- Python：建议使用 AstrBot 当前支持的 Python 版本
- 发布包遵循 AstrBot 插件市场不超过 16 MB 的限制

## 开发与测试

开发约定参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

本地回归测试：

```bash
py -3 -m unittest discover -s tests -v
```

基础语法冒烟测试：

```bash
py -3 -m compileall -q .
```

静态检查与格式检查：

```bash
py -3 -m ruff check .
py -3 -m ruff format --check .
```

## 发布与变更

- 版本历史见 [CHANGELOG.md](CHANGELOG.md)。
- 推送与 `metadata.yaml` 一致的 `v*` 标签后，GitHub Actions 会执行测试、构建 AstrBot 安装压缩包并上传至对应 Release。
- 安全问题请按照 [SECURITY.md](SECURITY.md) 私密报告。

## 许可证

本项目使用 [MIT License](LICENSE)。
