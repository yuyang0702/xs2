# 火山方舟模型接入

在“配置 → 模型 → 添加供应商”选择“火山方舟”，会预填：

- API Base URL：`https://ark.cn-beijing.volces.com/api/v3`
- 模型：`doubao-seed-character-260628`

填写方舟 API Key，或在本地模型配置的 `api_key` 使用 `${ARK_API_KEY}`，由运行启动器的进程环境或本地 `.env` 提供密钥。设置环境变量后重新启动服务。密钥、个人配置和运行数据不应提交 Git。

本地供应商配置例子：

```json
{
  "name": "火山方舟",
  "provider_type": "volcengine",
  "base_url": "https://ark.cn-beijing.volces.com/api/v3",
  "api_key": "${ARK_API_KEY}",
  "models": ["doubao-seed-character-260628"],
  "maxContextTokens": 128000,
  "hyperparameter_values": {"max_completion_tokens": 32768}
}
```

这是 Chat Completions 接口配置。调用发送到 `/api/v3/chat/completions`，使用 Bearer API Key 鉴权。角色及工作流可以选择 `volcengine:doubao-seed-character-260628`；新增供应商不会自动改变已有角色、工作流或全局默认模型。

思考开关映射到 `thinking.type`；开启时支持思考力度，关闭时不发送继承的思考力度。遵循当前 Seed 模型接口，只发送适用的采样、结构化输出和流式参数。

官方参考（2026-11-01 核对）：[Base URL 及鉴权](https://console.volcengine.com/ark/region:cn-beijing/docs/base-url-and-authentication)、[对话 Chat API](https://console.volcengine.com/ark/region:cn-beijing/docs/chat-api)、[模型列表](https://console.volcengine.com/ark/region:cn-beijing/docs/model-list)、[深度思考](https://console.volcengine.com/ark/region:cn-beijing/docs/deep-thinking)。
