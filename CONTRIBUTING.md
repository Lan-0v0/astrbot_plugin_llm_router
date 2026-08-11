# 贡献指南

感谢你改进 AstrBot LLM Router。

## 开发流程

1. Fork 仓库并从 `main` 创建分支。
2. 保持路由核心逻辑与 AstrBot 框架适配层分离。
3. 修改行为时补充有价值的回归测试。
4. 提交前运行：

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
ruff check .
ruff format --check .
```

Windows 上若 `python` 命令不可用，可使用 `py -3`。

## Pull Request 要求

- 清楚说明改动目的、兼容性影响和验证方式。
- 不要提交 API Key、访问令牌、聊天记录或本地配置。
- 路由失败应保持失败开放，不得无故阻断 AstrBot 原模型流程。
- 新增提供商时应包含请求构造、响应解析和错误回退测试。
