# OpenAI Responses API 入站兼容层设计

- 日期：2026-08-24
- 状态：已实现并通过全部测试（单测 43/43，E2E 全过；测试记录见 docs/test-records/2026-08-25-openai-responses-inbound.md）
- 目标版本：随下次镜像发布

## 1. 背景与目标

ModelGate 目前对外暴露两套入站协议：

- OpenAI Chat Completions：`POST /v1/chat/completions`（`app/routes/proxy.py`）
- Anthropic Messages：`POST /v1/messages`（`app/routes/anthropic_proxy.py` + `app/services/anthropic_inbound.py`）

Codex CLI、以及越来越多 OpenAI 生态客户端默认使用 **Responses API**（`POST /v1/responses`）。落地页已宣称支持 Responses，需要实现入站兼容，使 Responses 客户端把 `base_url` 指到 `https://leturx.cc/modelgate/v1` 即可工作。

**目标**：新增 `/v1/responses` 入站端点，请求翻译为 chat completions 走现有代理管线（鉴权、选 Key、健康路由、并发控制、统计、日志全部复用、零改动），响应（JSON 或 SSE）再翻译回 Responses 格式。

**非目标**：

- 不做 `store`/`previous_response_id` 服务端状态（网关无状态；Codex 默认 `store=false`，历史由客户端在 `input` 里回放）
- 不做 `background` 模式、`truncation` 策略、`include: ["reasoning.encrypted_content"]`（忽略并丢弃 reasoning item）
- 不做 Responses 专用出站适配（上游统一走 chat completions，现有供应商零改动）
- `local_shell`/`web_search`/`computer_use` 等内置工具类型不翻译（丢弃，vLLM 上游也不支持）

## 2. 架构

完全镜像 Anthropic 入站方案（已验证的两层结构）：

```
Responses 客户端 (Codex 等)
   │ POST /v1/responses   (input[] / instructions / tools / reasoning / stream)
   ▼
app/routes/responses_proxy.py        ← 薯条薄路由：解析、调用翻译、转发、回译
   │ responses_to_openai_request()
   ▼
app/services/proxy.py proxy_request(inner, "/chat/completions")   ← 现有管线复用
   │
   ▼
app/services/responses_inbound.py
   ├─ openai_to_responses_response()      非流式回译
   └─ ResponsesStreamTranslator           流式回译（chat SSE → Responses 事件流）
```

辅助：`app/services/inbound_http.py`（新）收拢 `_normalize_auth_header` / `_build_inner_request` / `_strip_hop_headers` 三个纯函数，anthropic_proxy 与 responses_proxy 共用（从 anthropic_proxy 原样搬移，行为不变）。

内部请求头加 `x-inbound-protocol: responses`（与 anthropic 对齐，便于日志观测）。

**请求体重建**：路由层对翻译后的 body 重写 `content-type: application/json` 与 `content-length`（ anthropic_proxy.py 现行做法，随 inbound_http 搬移时不得丢失）。

**流式请求遇上游 JSON 错误**：`stream:true` 但管线返回非 SSE 的 JSON 错误（鉴权 401、忙限 429、上下文超限 400 等，proxy.py 现行为）时，路由按非流式回译路径处理，返回对应 HTTP 状态码 + Responses 错误 JSON——Codex 对每次坏 key 都走这条路径。

## 3. 端点契约

| 路由 | 方法 | 行为 |
|---|---|---|
| `/v1/responses` | POST | 主端点，翻译并代理 |
| `/v1/responses` | OPTIONS | 空响应（CORS 预检） |
| `/v1/responses/{id}` | GET | 404：无状态网关不存储响应 |
| `/v1/responses/{id}` | DELETE | 404：同上 |

鉴权：`Authorization: Bearer sk-...`（与 chat completions 一致；也接受 `x-api-key` 头，宽松处理）。

## 4. 请求翻译：Responses → Chat Completions

`responses_to_openai_request(body) -> dict`，抛 `ValueError` 表示 400 级错误（路由层捕获转错误响应）。

### 4.1 顶层参数

| Responses 字段 | 去向 |
|---|---|
| `model` | 原样（必填，缺失/为空 → ValueError） |
| `input` | 翻译为 `messages`（见 4.2）；字符串 = 单条 user 消息 |
| `instructions` 或 `prompt` | 首条 `system` 消息 |
| `max_output_tokens` | `max_tokens` |
| `temperature` / `top_p` | 原样 |
| `stream` | 原样；为 true 时强制 `stream_options.include_usage=true`（绝大多数 OpenAI 兼容上游支持，保证 usage 回传） |
| `parallel_tool_calls` | 原样 |
| `service_tier` | 原样 |
| `metadata.user` | `user` |
| `reasoning.effort` | `reasoning_effort`；**`"max"` 归一化为 `"high"`**（vLLM 拒绝 max，也顺带解决既有遗留） |
| `text.verbosity` | 顶层 `verbosity`（仅在存在时传递） |
| `text.format` | `json_schema` → `response_format: {type: json_schema, json_schema: {name, schema, strict, description}}`；`json_object` → `{type: json_object}`；`text` → 不动 |
| `tools` / `tool_choice` | 见 4.3 / 4.4 |
| `store` / `previous_response_id` / `include` / `truncation` / `background` / 其他未知字段 | **丢弃**（白名单式转发，防上游 400） |

### 4.2 input items → messages

| item 类型 | 翻译 |
|---|---|
| `{type: message, role: user}` | user 消息；content 字符串原样，分块数组则 `input_text`/`output_text`→文本、`input_image`→`{type: image_url, image_url: {url, detail}}`（data: URL 直传）、`input_file`→丢弃 |
| `{type: message, role: assistant}` | assistant 消息（content 分块同上） |
| `{type: message, role: system/developer}` | system 消息 |
| `{type: function_call}` | assistant 消息的 `tool_calls` 条目 `{id: call_id, type: function, function: {name, arguments}}`；**连续多个 function_call 合并为同一条 assistant 消息**（chat 协议规范形态） |
| `{type: function_call_output}` | `{role: tool, tool_call_id: call_id, content: output}`；output 为分块数组时抽取其中 `output_text`/`input_text` 文本拼接，其他非字符串形态 `json.dumps` |
| `{type: reasoning}` | 丢弃（无状态网关；summary/encrypted 内容无下游用途） |
| `{type: item_reference}` | ValueError（语义上依赖服务端存储，无法无状态回放） |
| 其他未知类型 | 丢弃并继续（前向兼容） |

**校验**：翻译后 `messages` 为空（`input` 缺失/空串/空数组/全部被丢弃）→ ValueError（400）。

### 4.3 tools

`{type: function, name, description?, parameters?, strict?}` →
`{type: function, function: {name, description, parameters, strict}}`（无 parameters 时补 `{"type":"object","properties":{}}`）。

`local_shell` / `web_search` / 自定义（`custom`/grammar）工具：丢弃（记录 warning 日志）。

### 4.4 tool_choice

- `"auto"` / `"none"` / `"required"`：原样
- `{type: function, name}` → `{type: function, function: {name}}`
- 其他：丢弃

## 5. 响应翻译（非流式）：Chat Completions → Responses

`openai_to_responses_response(payload, requested_model) -> dict`

```
{
  "id": "resp_" + uuid24,
  "object": "response",
  "created_at": int(time.time()),
  "status": "completed" | "incomplete"(finish_reason 为 length 或 content_filter),
  "incomplete_details": {"reason": "max_output_tokens" | "content_filter"} | null,
  "model": 上游 model 或 requested_model,
  "output": [
    reasoning_content 非空 → {"type":"reasoning","id":"rs_...","summary":[{"type":"summary_text","text":...}]},
    content → {"type":"message","id":"msg_...","role":"assistant","status":"completed",
               "content":[{"type":"output_text","text":...,"annotations":[]}]},
    tool_calls[] → {"type":"function_call","id":"fc_...","call_id":原id,"name":...,"arguments":原字符串,"status":"completed"}
  ],
  "usage": {"input_tokens", "input_tokens_details": {"cached_tokens"},
            "output_tokens", "output_tokens_details": {"reasoning_tokens"}, "total_tokens"},
  "error": null, "temperature": null, "top_p": null, "metadata": {}
}
```

## 6. 流式翻译：chat SSE → Responses 事件流

`ResponsesStreamTranslator` 状态机（镜像 `AnthropicStreamTranslator` 的成熟模式）。SSE 帧：`event: <type>\ndata: <json>\n\n`，data 内含 `type` 与严格递增的 `sequence_number`（从 0 起）。

| 上游信号 | 输出事件序列 |
|---|---|
| 首个 chunk | `response.created`（response 外壳，字段全枚举：`id`、`object:"response"`、`created_at`、`status:"in_progress"`、`model`、`output:[]`、`error:null`、`usage:null`、`incomplete_details:null`；id 与终态 response 一致）→ `response.in_progress` |
| 首个 content delta | `response.output_item.added`(message, status=in_progress) → `response.content_part.added`(output_text, 空文本) |
| 后续 content delta | `response.output_text.delta` |
| 首个 tool_call index 片段 | `response.output_item.added`(function_call, arguments="") |
| tool_call arguments 片段 | `response.function_call_arguments.delta` |
| usage chunk（任意位置） | 记账，不直接出事件 |
| `[DONE]` / 流自然结束 | 关闭开着的 item（`output_text.done`+`content_part.done`+`output_item.done`；`function_call_arguments.done`+`output_item.done`）→ 终态事件 |
| finish_reason=stop/tool_calls | `response.completed`（含完整 output[] 与 usage） |
| finish_reason=length/content_filter | `response.incomplete`（status=incomplete, incomplete_details.reason 相应为 max_output_tokens/content_filter） |
| 上游 error chunk / 翻译异常 | `response.failed`：**不**补发 item 级关闭事件，直接携带完整 response 对象（status=failed、error{code:"server_error", message}、output=已完整关闭的 items） |

规则细节：

- output_index 分配：**按 item 创建顺序递增**（0,1,2,...；纯工具回复首个 item 即 index 0）
- 每类 item 的 id：`msg_`/`fc_`/`rs_` + uuid24；`response.completed` 里的 output[] 与增量事件内容、id 完全一致
- 上游 `delta.content` 字符串与分块数组两种形态都处理；`delta.reasoning_content` 聚合后并入终态 response 的 reasoning item（流中不发增量，Codex 不依赖）
- 终态事件（completed/incomplete/failed）之后不再输出任何事件

## 7. 错误翻译

`openai_to_responses_error(payload, status) -> {"error": {message, type, code, param}}`

- 上游 error 对象里有 `type`/`code` 则尽量保留
- 状态码兜底：401→`invalid_request_error`/`invalid_api_key`；429→`rate_limit_error`；5xx→`server_error`；其余 4xx→`invalid_request_error`
- 流中错误：`response.failed` 事件（§6）
- 网关自身错误（JSON 解析失败、翻译异常、代理异常）：同结构，400/502

## 8. 涉及文件

| 文件 | 动作 |
|---|---|
| `app/services/responses_inbound.py` | 新建：请求/响应/流式翻译（§4-§7） |
| `app/services/inbound_http.py` | 新建：共享的请求包装/头处理工具（从 anthropic_proxy 搬移） |
| `app/routes/responses_proxy.py` | 新建：§3 路由 |
| `app/routes/anthropic_proxy.py` | 改：改用 inbound_http（行为不变） |
| `app/main.py` | 改：注册 responses_proxy 路由 |
| `tests/test_responses_inbound.py` | 新建：§9 单测 |
| `tests/test_responses_route.py` | 新建：§9 路由测试（mock proxy_request） |

## 9. 测试用例（实现前先写，红→绿）

### 9.1 请求翻译（test_responses_inbound.py，纯函数，无 DB）

| # | 用例 | 断言 |
|---|---|---|
| R1 | `input` 为字符串 | messages=[{role:user, content:原文}] |
| R2 | `instructions` | 首条 system；`prompt` 作为 fallback 同样生效 |
| R3 | 数组 input 混合角色 | user/assistant 原序；system/developer→system |
| R4 | content 分块数组 | input_text/output_text→文本；input_image(data:URL)→image_url（含 detail）；input_file 丢弃 |
| R5 | 连续 function_call×2 | 合并为**一条** assistant 消息、tool_calls 长度 2、id=call_id |
| R6 | function_call_output | role=tool、tool_call_id、content=output；output 为分块数组时抽取文本拼接 |
| R7 | reasoning item 丢弃；item_reference → ValueError | |
| R8 | function 工具翻译 | 含 strict 透传；无 parameters 时补空 schema；local_shell 丢弃 |
| R9 | tool_choice 三种字符串 + 对象形态 | 正确映射 |
| R10 | max_output_tokens→max_tokens；temperature/top_p/parallel_tool_calls/service_tier 原样 | |
| R11 | reasoning.effort：max→high；high 原样；无 reasoning 不产生字段 | |
| R12 | text.verbosity→verbosity；json_schema→response_format（name/schema/strict）；json_object→json_object | |
| R13 | store/previous_response_id/include/truncation 不出现在输出；metadata.user→user；缺 model → ValueError；input 缺失/空 → ValueError | |
| R14 | stream=true 时 stream_options.include_usage=true | |

### 9.2 非流式响应翻译

| # | 用例 | 断言 |
|---|---|---|
| N1 | 纯文本回复 | output=[message(output_text)]，id 前缀 resp_/msg_，status=completed |
| N2 | tool_calls | 每个变 function_call item，call_id/arguments 原样 |
| N3 | reasoning_content | 首位 reasoning item（summary_text） |
| N4 | usage 四级映射 | prompt→input、cached_tokens、completion→output、reasoning_tokens、total |
| N5 | finish=length | status=incomplete + incomplete_details.reason=max_output_tokens；finish=content_filter → reason=content_filter |
| N6 | 错误映射 | 上游 error message/type/code 保留；401/429/500 状态兜底类型 |

### 9.3 流式翻译

| # | 用例 | 断言 |
|---|---|---|
| S1 | 首块触发 | 事件序 response.created→response.in_progress，sequence_number 从 0 严格递增；created 与 completed 的 response.id 一致 |
| S2 | 文本增量全链 | added→part.added→delta×n→text.done(全文)→part.done→item.done，顺序正确 |
| S3 | 工具增量 | function_call item added→arguments.delta→arguments.done(全参)→item.done |
| S4 | finish=stop+usage | 终态 response.completed；output[] 与增量事件内容/id 一致；usage 正确 |
| S5 | finish=length | response.incomplete + incomplete_details |
| S6 | 上游 error chunk | response.failed（含 status=failed 的 response 对象、error.code=server_error；无补发 item 事件） |
| S7 | [DONE] 后关闭 | 终态事件恰好一次，其后无事件 |
| S8 | 帧格式 | 每帧都有 `event:` 行且与 data.type 一致 |
| S9 | 空流（无 choices） | 仍产出 created→in_progress→completed(output=[]) |
| S10 | 流中 reasoning_content | 聚合并入终态 response 的 reasoning item |
| S11 | 混合流：文本+工具 | 终态 output[] 与增量 items 完全一致、id 稳定 |
| S12 | delta.content 数组形态 | 与字符串形态等价产出 delta 事件 |
| S13 | 黄金事件流 | 模拟 Codex 会话（instructions+user→assistant function_call→tool 结果→final）整段翻译，断言完整事件序列 |

### 9.4 路由（test_responses_route.py，mock proxy_request）

| # | 用例 | 断言 |
|---|---|---|
| P1 | 合法非流式请求 | 200；上游收到翻译后 body（不含 stream_options）与 x-inbound-protocol: responses 头 |
| P2 | 非法 JSON / 非对象 | 400 Responses 错误结构 |
| P3 | item_reference / 缺 model / input 缺失或空 | 400 |
| P4 | GET/DELETE /v1/responses/{id} | 404 + error.code=response_not_found |
| P5 | 流式 | content-type=text/event-stream；首帧 response.created；上游 body 含 stream_options.include_usage=true |
| P6 | 上游 401 | 回译 401 + invalid_api_key |
| P7 | anthropic_proxy 回归 | 搬移 inbound_http 后 /v1/messages 路由测试仍过（本仓库现有 anthropic 相关测试 + P 系列全绿） |
| P8 | stream:true 但管线返回 JSON 401/400 | 非 SSE 回译：HTTP 401/400 + Responses 错误 JSON |
| P9 | OPTIONS /v1/responses | 200 空响应 |

### 9.5 端到端（dev server，真实 DB/上游，手工脚本记录到 docs/test-records/）

| # | 用例 |
|---|---|
| E1 | curl 非流式（test key + 真实模型）：200、结构合法、token 统计入库 |
| E2 | curl 流式：事件序合法、response.completed 带 usage |
| E3 | Codex CLI 实连冒烟（本机未装则用 S13 黄金事件流替代）：配置自定义 provider 指向网关跑一轮工具调用问答 |

## 10. 风险与取舍

- **usage 流式可能为 0**：若上游不支持 stream_options.include_usage，response.completed.usage 为 0——与 Anthropic 入站同等限制，非回归
- **`verbosity` 直传**：个别严格上游可能 400；白名单内字段仅在客户端显式传递时转发，风险可控（与 top_k 直传同策略）
- **`custom`/freeform 工具被丢弃**（含 Codex `include_apply_patch_tool` 场景）：vLLM 上游不支持 grammar 形态；依赖该特性的 Codex 配置会退化为无该工具，正常 function 工具不受影响
- **reasoning effort 归一化只做 max→high**：minimal/low/medium/high 原样，超集值由上游裁决
- **GET/DELETE 404**：依赖服务端存储的客户端（store=true 模式）不可用——Codex 默认 store=false，不受影响；错误信息中说明无状态原因

## Review 记录（2026-08-24）

独立评审 18 条（0 blocker / 3 MAJOR / 14 MINOR+OK-note），全部采纳并已并入正文：

1. [MAJOR] P1 与 §4.1 stream_options 矛盾 → P1 不再断言 stream_options，移至 P5（已修）
2. [MAJOR] input 空校验未定义 → §4.2 增补"翻译后 messages 为空 → ValueError"（已修）
3. [MAJOR] stream+管线 JSON 错误路径未定义未测 → §2 增补行为 + P8（已修）
4. [MINOR] output_index 改为按 item 创建顺序递增（已修）
5. [MINOR] response.failed 载荷全枚举、不补发 item 事件（已修）
6. [MINOR] response.created 外壳字段全枚举 + id 一致性断言（S1/S4，已修）
7. [MINOR] custom 工具丢弃列入 §10 风险（已修）
8. [MINOR] content_filter → incomplete 映射 + N5（已修）
9. [MINOR] function_call_output 分块数组抽文本（R6，已修）
10. [MINOR] 路由重建 body 时 content-type/content-length 重写显式写入 §2（已修）
11. [MINOR] 新增 S10/S11/S12（reasoning 聚合、混合流、数组 content）（已修）
12. [MINOR] E3 改为"Codex 未装则 S13 黄金事件流替代"（已修）
13. [MINOR] OPTIONS 测试 P9（已修）
14. [OK-note] x-inbound-protocol 自由字符串、proxy_request 复用可行性已确认（无需改动）
