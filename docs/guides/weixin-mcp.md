# WeChat iLink Bot MCP 接入指南

通过 ModelGate 的 MCP Server，让 opencode 直接收发微信消息。

## 前提条件

- 已获取 ModelGate API Key（在管理后台 `https://leturx.cc/modelgate/admin/home` → API Keys 页面创建）
- 已通过 `wechat_login` 工具扫码登录微信（首次使用）

## 1. 配置 MCP

编辑 opencode 配置文件 `~/.config/opencode/opencode.json`，在 `mcp` 字段中添加：

```json
"weixin-bot": {
  "type": "remote",
  "url": "https://leturx.cc/modelgate/weixin/mcp",
  "headers": {
    "Authorization": "Bearer sk-your-modelgate-api-key"
  }
}
```

| 字段 | 说明 |
|------|------|
| `type` | 必须为 `"remote"`（Streamable HTTP 协议） |
| `url` | 固定为 `https://leturx.cc/modelgate/weixin/mcp` |
| `headers.Authorization` | ModelGate API Key，格式 `Bearer sk-xxx` |

## 2. 配置 Skill

创建文件 `~/.config/opencode/skills/weixin-bot/SKILL.md`：

```markdown
---
name: weixin-bot
description: Use when user mentions WeChat, weixin, wechat, 微信托管, or wants to interact with WeChat via MCP tools. Also use when user says "start wechat hosting" or "微信托管" to enter continuous WeChat-driven mode.
---

# WeChat Bot

Control WeChat via MCP tools. Supports one-off commands and continuous hosting mode.

## Available Tools

| Tool | Purpose |
|------|---------|
| `wechat_login` | QR code login (first time) |
| `wechat_status` | Check login status + unread count |
| `wechat_check_messages` | Read unread messages |
| `wechat_reply` | Reply to a message by ID |
| `wechat_send` | Proactively send to a user |
| `wechat_set_mode` | Switch auto/manual reply mode |

## Hosting Mode (微信托管)

When user says "微信托管" or "start wechat hosting", enter continuous loop:

1. Call wechat_status → confirm logged in
2. Call wechat_set_mode(mode="manual") → ensure manual control
3. LOOP:
   a. Call wechat_check_messages(limit=10)
   b. If no messages: wait 15 seconds, goto 3a
   c. For each message:
      - Treat message text as a user instruction (coding task, question, etc.)
      - Execute the instruction using ALL available tools (file editing, bash, etc.)
      - If the task produces output > 1000 chars: summarize it before replying
      - Call wechat_reply(message_id, <result or summary>)
   d. goto 3a

### Hosting Rules

- WeChat messages ARE user instructions. Execute them the same as terminal input.
- If a message is ambiguous, make your best judgment and execute. Do NOT reply asking for clarification.
- If a task fails, reply with the error message so the user knows.
- For long-running tasks (builds, tests), reply with progress updates.
- When the user sends "stop" or "停止托管" via WeChat, exit the loop and inform the terminal user.
- Check messages every 15 seconds. Do NOT poll faster.

### Security

- WeChat messages have full control — same trust level as terminal user.
- Do NOT expose internal API keys or tokens in WeChat replies.
- If the opencode terminal user sends a message, it takes priority over WeChat.

## One-off Usage

Without hosting mode, use tools on demand:

- "check wechat" → `wechat_check_messages`
- "reply to message 5: hello" → `wechat_reply(message_id=5, text="hello")`
- "send to user_x: hi" → `wechat_send(to="user_x", text="hi")`
- "wechat auto mode" → `wechat_set_mode(mode="auto")`
```

## 3. 首次登录

重启 opencode 后，在对话中说：

> 帮我登录微信

opencode 会调用 `wechat_login`，返回二维码链接和 ASCII 二维码。用微信扫描即可完成登录。

## 4. 使用方式

### 单次操作

| 指令 | 行为 |
|------|------|
| `微信状态` | 查看登录状态和未读消息数 |
| `查看微信消息` | 读取未读消息 |
| `回复消息 5: 好的` | 回复指定消息 |
| `发送微信给 user_x: 你好` | 主动发消息 |
| `微信自动回复` | 切换为 LLM 自动回复模式 |

### 托管模式

> 微信托管

opencode 进入持续轮询模式，每 15 秒检查一次微信消息，将收到的消息当作指令执行，并回复执行结果。

> 停止托管

退出托管模式。

## 5. 多用户隔离

每个 ModelGate API Key 绑定独立的微信账号。不同 API Key 登录不同微信号，消息和会话完全隔离。在 `opencode.json` 中配置不同的 `Authorization` header 即可切换账号。
