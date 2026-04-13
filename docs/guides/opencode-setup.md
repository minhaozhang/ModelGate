# OpenCode 配置指南

## 完整 opencode.json 示例

```json
{
  "$schema": "https://opencode.ai/config.json",
  "compaction": {
    "threshold": 0.5,
    "strategy": "summarize",
    "preserveRecentMessages": 10,
    "preserveSystemPrompt": true
  },
  "provider": {
    "modelgate": {
      "name": "ModelGate",
      "options": {
        "baseURL": "https://leturx.cc/modelgate/v1",
        "apiKey": "YOUR_API_KEY"
      },
      "models": {
        "zhipu/glm-5": {
          "name": "zhipu/glm-5",
          "modalities": {"input": ["text"], "output": ["text"]},
          "limit": {"context": 131072, "output": 16384},
          "options": {"thinking": {"type": "enabled"}}
        },
        "zhipu/glm-5-turbo": {
          "name": "zhipu/glm-5-turbo",
          "modalities": {"input": ["text"], "output": ["text"]},
          "limit": {"context": 131072, "output": 16384},
          "options": {"thinking": {"type": "enabled"}}
        },
        "zhipu/glm-5.1": {
          "name": "zhipu/glm-5.1",
          "modalities": {"input": ["text"], "output": ["text"]},
          "limit": {"context": 131072, "output": 16384},
          "options": {"thinking": {"type": "enabled"}}
        },
        "minimax/MiniMax-M2.5": {
          "name": "minimax/MiniMax-M2.5",
          "modalities": {"input": ["text"], "output": ["text"]},
          "limit": {"context": 202752, "output": 131072},
          "options": {"thinking": {"type": "enabled"}}
        },
        "minimax/MiniMax-M2.7": {
          "name": "minimax/MiniMax-M2.7",
          "modalities": {"input": ["text"], "output": ["text"]},
          "limit": {"context": 204800, "output": 131072},
          "options": {"thinking": {"type": "enabled"}}
        }
      }
    }
  }
}
```

## compaction 配置说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `threshold` | 0.75 | 上下文达到 context window 的 50%~75% 时触发压缩。设置为 0.5 表示 50% 时触发 |
| `strategy` | summarize | 压缩策略：`summarize`（摘要）、`truncate`（截断）、`archive`（归档） |
| `preserveRecentMessages` | 10 | 始终保留的最新消息条数 |
| `preserveSystemPrompt` | true | 是否始终保留 system prompt |

## 使用方法

1. 访问 ModelGate 用户面板 → OpenCode 配置页
2. 复制生成的配置文本
3. 粘贴到 `~/.config/opencode/opencode.json` 中，替换 `YOUR_API_KEY` 为你的 API Key
4. 添加 `compaction` 配置段（可选）
5. 重启 OpenCode 使配置生效

## 按需生成配置

访问以下地址获取你账户对应的实时配置：

```
https://leturx.cc/modelgate/opencode/setup.md?api_key=YOUR_API_KEY
```

发送给你的 OpenCode 即可自动配置。
