# OpenAI Responses 入站兼容层测试记录

- 日期：2026-08-25
- 对应 spec：docs/specs/2026-08-24-openai-responses-inbound-design.md
- 环境：dev server（uvicorn 127.0.0.1:8766）+ 共享 PostgreSQL（生产库）+ 真实上游 ZHIPU glm-5

## 单元测试（tests/test_responses_inbound.py + tests/test_responses_route.py）

```
Ran 43 tests ... OK
```

覆盖 spec §9.1（R1-R14 请求翻译）、§9.2（N1-N6 响应翻译）、§9.3（S1-S13 流式状态机含黄金事件流）、§9.4（P1-P9 路由，mock proxy_request）。

全量回归：`unittest discover` 200 tests，6 failures + 7 errors —— 与改动前基线完全一致（stash 验证），全部为预存问题（test_admin_models / test_model_name_routing 等），与本次无关。

## E2E（真实上游）

| # | 用例 | 结果 |
|---|---|---|
| E1 | 非流式 `{"model":"glm-5","input":"Say exactly: ping ok"}` | 200；output=[reasoning, message(output_text="ping ok")]，status=completed，id resp_* 格式正确 |
| E2 | 流式同请求 stream=true | 200；事件序 created→in_progress→output_item.added→content_part.added→output_text.delta→done→part.done→item.done→completed；completed.usage input=17/output=40 |
| E3' | 真实工具调用流（tools=[get_weather], tool_choice=auto） | 事件链含 function_call_arguments.delta/done；completed 内 function_call item：call_id=call_*、name=get_weather、arguments={"city":"Beijing"}；usage 含 reasoning_tokens |
| E3'' | 多轮回放（function_call + function_call_output + reasoning 丢弃） | 200；模型正确消费工具结果（"Sunny, 25C"→"sunny with a temperature of 25°C"）；messages=[system,user,assistant(tool_calls),tool] 翻译正确 |
| 错误1 | 无权限模型 local_model | 403 + Responses error JSON（message 保留，type=permission_error） |
| 错误2 | 不存在模型 no-such-model | 400 + model_not_found（Responses 结构） |
| 错误3 | 坏 key（流式请求） | 401 JSON（非 SSE），invalid_api_key —— P8 路径实测 |
| GET /v1/responses/{id} | | 404 + code=response_not_found |

## token 统计入库验证

request_logs 表（api_key_id=4）：

- 流式行：inbound_protocol='responses' ✓（改动前后均正常）
- 非流式行：改动前为 None ✗ → **发现并修复预存 bug**：`handle_normal`（proxy_runtime/normal.py 及 proxy.py:1300 legacy 包装）未透传 inbound_protocol；修复后非流式行 inbound_protocol='responses' ✓（该 bug 同样影响 Anthropic 非流式入站，一并修复）

## Codex CLI 冒烟

本机未装 Codex CLI，按 spec 以 E3'/E3''（真实工具调用 + 多轮回放，即 Codex 的实际工作流：instructions + tools + function_call/function_call_output 回放）替代 S13 黄金事件流实测通过。
