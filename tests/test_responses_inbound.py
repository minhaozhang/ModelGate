"""Unit tests for the OpenAI Responses inbound translation layer.

Covers the spec: docs/specs/2026-08-24-openai-responses-inbound-design.md §9.1-§9.3.
"""
import json
import unittest

from app.services.responses_inbound import (
    ResponsesStreamTranslator,
    build_responses_error,
    openai_to_responses_error,
    openai_to_responses_response,
    responses_to_openai_request,
    translate_openai_sse_to_responses,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def chunk(delta=None, finish=None, usage=None):
    c = {}
    choice = {}
    if delta is not None:
        choice["delta"] = delta
    if finish is not None:
        choice["finish_reason"] = finish
    if choice:
        c["choices"] = [choice]
    if usage is not None:
        c["usage"] = usage
    return c


def run_chunks(chunks, done=True):
    translator = ResponsesStreamTranslator("gpt-test")
    events: list[str] = []
    for c in chunks:
        events.extend(translator.consume_openai_chunk(c))
    if done:
        events.extend(translator.close_events())
    return events, translator


def parse_frames(events):
    frames = []
    for raw in events:
        lines = raw.strip().split("\n")
        name = lines[0][len("event: "):]
        data = json.loads(lines[1][len("data: "):])
        frames.append((name, data))
    return frames


def names(frames):
    return [n for n, _ in frames]


# ---------------------------------------------------------------------------
# Request translation (R series)
# ---------------------------------------------------------------------------


class RequestTranslationTests(unittest.TestCase):
    def test_r1_string_input(self):
        body = responses_to_openai_request({"model": "m1", "input": "hello"})
        self.assertEqual(body["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(body["model"], "m1")

    def test_r2_instructions_and_prompt_fallback(self):
        body = responses_to_openai_request(
            {"model": "m", "instructions": "be nice", "input": "hi"}
        )
        self.assertEqual(body["messages"][0], {"role": "system", "content": "be nice"})
        body2 = responses_to_openai_request(
            {"model": "m", "prompt": "be nice", "input": "hi"}
        )
        self.assertEqual(body2["messages"][0]["role"], "system")

    def test_r3_role_mapping(self):
        body = responses_to_openai_request(
            {
                "model": "m",
                "input": [
                    {"type": "message", "role": "developer", "content": "dev rules"},
                    {"type": "message", "role": "user", "content": "q"},
                    {"type": "message", "role": "assistant", "content": "a"},
                ],
            }
        )
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant"])

    def test_r4_content_part_array(self):
        body = responses_to_openai_request(
            {
                "model": "m",
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "look at this"},
                            {"type": "input_file", "file_id": "file-1"},
                            {
                                "type": "input_image",
                                "image_url": "data:image/png;base64,xxx",
                                "detail": "high",
                            },
                        ],
                    }
                ],
            }
        )
        content = body["messages"][0]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[0], {"type": "text", "text": "look at this"})
        self.assertEqual(
            content[1],
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,xxx", "detail": "high"},
            },
        )
        self.assertEqual(len(content), 2)  # input_file dropped

        # all-text array folds to a joined string
        body2 = responses_to_openai_request(
            {
                "model": "m",
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "a"},
                            {"type": "input_text", "text": "b"},
                        ],
                    }
                ],
            }
        )
        self.assertEqual(body2["messages"][0]["content"], "a\nb")

    def test_r5_consecutive_function_calls_merge(self):
        body = responses_to_openai_request(
            {
                "model": "m",
                "input": [
                    {"type": "message", "role": "user", "content": "list files"},
                    {"type": "function_call", "call_id": "call_1", "name": "ls", "arguments": "{\"path\":\"/\"}"},
                    {"type": "function_call", "call_id": "call_2", "name": "pwd", "arguments": "{}"},
                ],
            }
        )
        self.assertEqual(
            [m["role"] for m in body["messages"]], ["user", "assistant"]
        )
        tool_calls = body["messages"][1]["tool_calls"]
        self.assertEqual(len(tool_calls), 2)
        self.assertEqual(tool_calls[0]["id"], "call_1")
        self.assertEqual(tool_calls[0]["function"]["name"], "ls")

    def test_r6_function_call_output(self):
        body = responses_to_openai_request(
            {
                "model": "m",
                "input": [
                    {"type": "function_call_output", "call_id": "c1", "output": "file1\nfile2"},
                ],
            }
        )
        msg = body["messages"][0]
        self.assertEqual(msg["role"], "tool")
        self.assertEqual(msg["tool_call_id"], "c1")
        self.assertEqual(msg["content"], "file1\nfile2")

        # array output extracts text
        body2 = responses_to_openai_request(
            {
                "model": "m",
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": "c1",
                        "output": [{"type": "output_text", "text": "result text"}],
                    },
                ],
            }
        )
        self.assertEqual(body2["messages"][0]["content"], "result text")

    def test_r7_reasoning_dropped_item_reference_rejected(self):
        body = responses_to_openai_request(
            {
                "model": "m",
                "input": [
                    {"type": "reasoning", "id": "rs_1", "summary": []},
                    {"type": "message", "role": "user", "content": "hi"},
                ],
            }
        )
        self.assertEqual(len(body["messages"]), 1)

        with self.assertRaises(ValueError):
            responses_to_openai_request(
                {
                    "model": "m",
                    "input": [
                        {"type": "message", "role": "user", "content": "hi"},
                        {"type": "item_reference", "id": "msg_1"},
                    ],
                }
            )

    def test_r8_tools(self):
        body = responses_to_openai_request(
            {
                "model": "m",
                "input": "hi",
                "tools": [
                    {
                        "type": "function",
                        "name": "shell",
                        "description": "run shell",
                        "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
                        "strict": True,
                    },
                    {"type": "function", "name": "no_params"},
                    {"type": "local_shell"},
                ],
            }
        )
        tools = body["tools"]
        self.assertEqual(len(tools), 2)
        self.assertEqual(tools[0]["function"]["name"], "shell")
        self.assertTrue(tools[0]["function"]["strict"])
        self.assertEqual(
            tools[1]["function"]["parameters"],
            {"type": "object", "properties": {}},
        )

    def test_r9_tool_choice(self):
        for choice in ("auto", "none", "required"):
            body = responses_to_openai_request(
                {"model": "m", "input": "hi", "tool_choice": choice}
            )
            self.assertEqual(body["tool_choice"], choice)
        body = responses_to_openai_request(
            {
                "model": "m",
                "input": "hi",
                "tool_choice": {"type": "function", "name": "shell"},
            }
        )
        self.assertEqual(
            body["tool_choice"], {"type": "function", "function": {"name": "shell"}}
        )

    def test_r10_scalar_params(self):
        body = responses_to_openai_request(
            {
                "model": "m",
                "input": "hi",
                "max_output_tokens": 123,
                "temperature": 0.5,
                "top_p": 0.9,
                "parallel_tool_calls": False,
                "service_tier": "auto",
            }
        )
        self.assertEqual(body["max_tokens"], 123)
        self.assertEqual(body["temperature"], 0.5)
        self.assertEqual(body["top_p"], 0.9)
        self.assertIs(body["parallel_tool_calls"], False)
        self.assertEqual(body["service_tier"], "auto")

    def test_r11_reasoning_effort(self):
        body = responses_to_openai_request(
            {"model": "m", "input": "hi", "reasoning": {"effort": "max"}}
        )
        self.assertEqual(body["reasoning_effort"], "high")
        body2 = responses_to_openai_request(
            {"model": "m", "input": "hi", "reasoning": {"effort": "high"}}
        )
        self.assertEqual(body2["reasoning_effort"], "high")
        body3 = responses_to_openai_request({"model": "m", "input": "hi"})
        self.assertNotIn("reasoning_effort", body3)

    def test_r12_text_format(self):
        body = responses_to_openai_request(
            {
                "model": "m",
                "input": "hi",
                "text": {
                    "verbosity": "low",
                    "format": {
                        "type": "json_schema",
                        "name": "out",
                        "schema": {"type": "object"},
                        "strict": True,
                    },
                },
            }
        )
        self.assertEqual(body["verbosity"], "low")
        self.assertEqual(
            body["response_format"],
            {
                "type": "json_schema",
                "json_schema": {"name": "out", "schema": {"type": "object"}, "strict": True},
            },
        )
        body2 = responses_to_openai_request(
            {
                "model": "m",
                "input": "hi",
                "text": {"format": {"type": "json_object"}},
            }
        )
        self.assertEqual(body2["response_format"], {"type": "json_object"})

    def test_r13_dropped_fields_and_validation(self):
        body = responses_to_openai_request(
            {
                "model": "m",
                "input": "hi",
                "store": True,
                "previous_response_id": "resp_old",
                "include": ["reasoning.encrypted_content"],
                "truncation": "auto",
                "background": False,
                "metadata": {"user": "u-1"},
            }
        )
        for key in ("store", "previous_response_id", "include", "truncation", "background"):
            self.assertNotIn(key, body)
        self.assertEqual(body["user"], "u-1")

        with self.assertRaises(ValueError):
            responses_to_openai_request({"input": "no model"})
        with self.assertRaises(ValueError):
            responses_to_openai_request({"model": "m"})
        with self.assertRaises(ValueError):
            responses_to_openai_request({"model": "m", "input": []})

    def test_r14_stream_options(self):
        body = responses_to_openai_request(
            {"model": "m", "input": "hi", "stream": True}
        )
        self.assertEqual(body["stream_options"], {"include_usage": True})
        body2 = responses_to_openai_request({"model": "m", "input": "hi"})
        self.assertNotIn("stream_options", body2)


# ---------------------------------------------------------------------------
# Non-streaming response translation (N series)
# ---------------------------------------------------------------------------


class ResponseTranslationTests(unittest.TestCase):
    def _chat_response(self, **overrides):
        payload = {
            "id": "chatcmpl-1",
            "model": "upstream-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        payload.update(overrides)
        return payload

    def test_n1_text_response_shape(self):
        out = openai_to_responses_response(self._chat_response(), "m")
        self.assertTrue(out["id"].startswith("resp_"))
        self.assertEqual(out["object"], "response")
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["model"], "upstream-model")
        self.assertEqual(len(out["output"]), 1)
        item = out["output"][0]
        self.assertEqual(item["type"], "message")
        self.assertTrue(item["id"].startswith("msg_"))
        self.assertEqual(item["content"][0]["type"], "output_text")
        self.assertEqual(item["content"][0]["text"], "Hello!")

    def test_n2_tool_calls(self):
        payload = self._chat_response()
        payload["choices"][0]["message"] = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_9",
                    "type": "function",
                    "function": {"name": "shell", "arguments": "{\"cmd\":\"ls\"}"},
                }
            ],
        }
        payload["choices"][0]["finish_reason"] = "tool_calls"
        out = openai_to_responses_response(payload, "m")
        fc = out["output"][0]
        self.assertEqual(fc["type"], "function_call")
        self.assertEqual(fc["call_id"], "call_9")
        self.assertEqual(fc["name"], "shell")
        self.assertEqual(fc["arguments"], "{\"cmd\":\"ls\"}")

    def test_n3_reasoning_content(self):
        payload = self._chat_response()
        payload["choices"][0]["message"]["reasoning_content"] = "thinking..."
        out = openai_to_responses_response(payload, "m")
        self.assertEqual(out["output"][0]["type"], "reasoning")
        self.assertEqual(out["output"][0]["summary"][0]["text"], "thinking...")

    def test_n4_usage_mapping(self):
        payload = self._chat_response()
        payload["usage"] = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "prompt_tokens_details": {"cached_tokens": 40},
            "completion_tokens_details": {"reasoning_tokens": 20},
        }
        out = openai_to_responses_response(payload, "m")
        usage = out["usage"]
        self.assertEqual(usage["input_tokens"], 100)
        self.assertEqual(usage["output_tokens"], 50)
        self.assertEqual(usage["total_tokens"], 150)
        self.assertEqual(usage["input_tokens_details"], {"cached_tokens": 40})
        self.assertEqual(usage["output_tokens_details"], {"reasoning_tokens": 20})

    def test_n5_incomplete_reasons(self):
        payload = self._chat_response()
        payload["choices"][0]["finish_reason"] = "length"
        out = openai_to_responses_response(payload, "m")
        self.assertEqual(out["status"], "incomplete")
        self.assertEqual(out["incomplete_details"], {"reason": "max_output_tokens"})

        payload2 = self._chat_response()
        payload2["choices"][0]["finish_reason"] = "content_filter"
        out2 = openai_to_responses_response(payload2, "m")
        self.assertEqual(out2["incomplete_details"], {"reason": "content_filter"})

    def test_n6_error_mapping(self):
        err = openai_to_responses_error(
            {
                "error": {
                    "message": "bad key",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
            401,
        )
        self.assertEqual(err["error"]["message"], "bad key")
        self.assertEqual(err["error"]["type"], "invalid_request_error")
        self.assertEqual(err["error"]["code"], "invalid_api_key")

        err2 = openai_to_responses_error({}, 500)
        self.assertEqual(err2["error"]["type"], "server_error")

        err3 = openai_to_responses_error({}, 401)
        self.assertEqual(err3["error"]["type"], "invalid_request_error")
        self.assertEqual(err3["error"]["code"], "invalid_api_key")

        built = build_responses_error("nope", 404, code="response_not_found")
        self.assertEqual(built["error"]["code"], "response_not_found")


# ---------------------------------------------------------------------------
# Stream translation (S series)
# ---------------------------------------------------------------------------


class StreamTranslationTests(unittest.TestCase):
    def _frames(self, chunks, done=True):
        events, _ = run_chunks(chunks, done=done)
        return parse_frames(events)

    def test_s1_start_sequence(self):
        frames = self._frames(
            [
                chunk(delta={"role": "assistant", "content": "hi"}),
                chunk(finish="stop"),
            ]
        )
        self.assertEqual(names(frames)[:2], ["response.created", "response.in_progress"])
        seqs = [d["sequence_number"] for _, d in frames]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(seqs), len(set(seqs)))
        created = frames[0][1]["response"]
        self.assertEqual(created["object"], "response")
        self.assertEqual(created["status"], "in_progress")
        self.assertEqual(created["model"], "gpt-test")
        self.assertIsNone(created["usage"])
        completed = frames[-1][1]["response"]
        self.assertEqual(created["id"], completed["id"])

    def test_s2_text_lifecycle(self):
        frames = self._frames(
            [
                chunk(delta={"content": "Hel"}),
                chunk(delta={"content": "lo"}),
                chunk(finish="stop"),
            ]
        )
        expected = [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.content_part.added",
            "response.output_text.delta",
            "response.output_text.delta",
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
            "response.completed",
        ]
        self.assertEqual(names(frames), expected)
        done_evt = [d for n, d in frames if n == "response.output_text.done"][0]
        self.assertEqual(done_evt["text"], "Hello")

    def test_s3_tool_lifecycle(self):
        frames = self._frames(
            [
                chunk(
                    delta={
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "shell", "arguments": "{\"cm"},
                            }
                        ]
                    }
                ),
                chunk(
                    delta={
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": "d\":\"ls\"}"}}
                        ]
                    }
                ),
                chunk(finish="tool_calls"),
            ]
        )
        n = names(frames)
        self.assertIn("response.output_item.added", n)
        self.assertIn("response.function_call_arguments.delta", n)
        self.assertIn("response.function_call_arguments.done", n)
        self.assertIn("response.output_item.done", n)
        added = [d for name, d in frames if name == "response.output_item.added"][0]
        self.assertEqual(added["item"]["type"], "function_call")
        self.assertEqual(added["item"]["call_id"], "call_1")
        args_done = [
            d for name, d in frames if name == "response.function_call_arguments.done"
        ][0]
        self.assertEqual(args_done["arguments"], "{\"cmd\":\"ls\"}")

    def test_s4_completed_usage_and_consistency(self):
        frames = self._frames(
            [
                chunk(delta={"content": "ok"}),
                chunk(finish="stop"),
                chunk(
                    usage={
                        "prompt_tokens": 7,
                        "completion_tokens": 3,
                        "total_tokens": 10,
                    }
                ),
            ]
        )
        final_name, final = frames[-1]
        self.assertEqual(final_name, "response.completed")
        self.assertEqual(final["response"]["usage"]["input_tokens"], 7)
        self.assertEqual(final["response"]["usage"]["output_tokens"], 3)
        # final output items match the incremental items (id and text)
        added_ids = [
            d["item"]["id"] for name, d in frames if name == "response.output_item.added"
        ]
        done_items = [
            d["item"] for name, d in frames if name == "response.output_item.done"
        ]
        final_items = final["response"]["output"]
        self.assertEqual(len(final_items), 1)
        self.assertEqual(final_items[0]["id"], added_ids[0])
        self.assertEqual(final_items[0]["id"], done_items[0]["id"])
        self.assertEqual(final_items[0]["content"][0]["text"], "ok")

    def test_s5_incomplete(self):
        frames = self._frames(
            [chunk(delta={"content": "partial"}), chunk(finish="length")]
        )
        final_name, final = frames[-1]
        self.assertEqual(final_name, "response.incomplete")
        self.assertEqual(
            final["response"]["incomplete_details"], {"reason": "max_output_tokens"}
        )
        self.assertEqual(final["response"]["status"], "incomplete")

    def test_s6_upstream_error(self):
        frames = self._frames(
            [
                chunk(delta={"content": "so far"}),
                {"error": {"message": "boom", "type": "server_error"}},
            ]
        )
        final_name, final = frames[-1]
        self.assertEqual(final_name, "response.failed")
        self.assertEqual(final["response"]["status"], "failed")
        self.assertEqual(final["response"]["error"]["code"], "server_error")
        self.assertEqual(final["response"]["error"]["message"], "boom")
        # failed is the last event; no per-item close events after it
        self.assertEqual(names(frames)[-1], "response.failed")
        self.assertEqual(names(frames).count("response.failed"), 1)

    def test_s7_done_then_close_once(self):
        frames = self._frames(
            [chunk(delta={"content": "x"}), chunk(finish="stop"), chunk()]
        )
        terminal = [n for n in names(frames) if n.startswith("response.completed")]
        self.assertEqual(len(terminal), 1)
        self.assertEqual(names(frames)[-1], "response.completed")

    def test_s8_frame_format(self):
        frames = self._frames([chunk(delta={"content": "a"}), chunk(finish="stop")])
        for name, data in frames:
            self.assertEqual(data["type"], name)

    def test_s9_empty_stream(self):
        frames = self._frames([chunk(usage={"prompt_tokens": 1, "completion_tokens": 0})])
        self.assertEqual(
            names(frames),
            ["response.created", "response.in_progress", "response.completed"],
        )
        self.assertEqual(frames[-1][1]["response"]["output"], [])

    def test_s10_reasoning_aggregation(self):
        frames = self._frames(
            [
                chunk(delta={"reasoning_content": "think "}),
                chunk(delta={"reasoning_content": "hard"}),
                chunk(delta={"content": "answer"}),
                chunk(finish="stop"),
            ]
        )
        final = frames[-1][1]["response"]
        reasoning_items = [i for i in final["output"] if i["type"] == "reasoning"]
        self.assertEqual(len(reasoning_items), 1)
        self.assertEqual(reasoning_items[0]["summary"][0]["text"], "think hard")

    def test_s11_mixed_text_and_tool(self):
        frames = self._frames(
            [
                chunk(delta={"content": "let me check"}),
                chunk(
                    delta={
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "shell", "arguments": "{}"},
                            }
                        ]
                    }
                ),
                chunk(finish="tool_calls"),
            ]
        )
        final = frames[-1][1]["response"]
        types = [i["type"] for i in final["output"]]
        self.assertEqual(types, ["message", "function_call"])
        added_ids = [
            d["item"]["id"]
            for name, d in frames
            if name == "response.output_item.added"
        ]
        final_ids = [i["id"] for i in final["output"]]
        self.assertEqual(added_ids, final_ids)

    def test_s12_content_array_form(self):
        frames = self._frames(
            [
                chunk(delta={"content": [{"type": "text", "text": "arr "}]}),
                chunk(delta={"content": [{"type": "text", "text": "form"}]}),
                chunk(finish="stop"),
            ]
        )
        deltas = [d for n, d in frames if n == "response.output_text.delta"]
        self.assertEqual("".join(d["delta"] for d in deltas), "arr form")

    def test_s13_golden_codex_session(self):
        # Turn 1 request translation (Codex style): instructions + tools + user text
        request = {
            "model": "gpt-test",
            "instructions": "You are a coding agent.",
            "input": [
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "run ls"}]},
            ],
            "tools": [
                {
                    "type": "function",
                    "name": "shell",
                    "description": "run a shell command",
                    "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
                    "strict": False,
                }
            ],
            "tool_choice": "auto",
            "reasoning": {"effort": "medium"},
            "store": False,
            "stream": True,
        }
        openai_body = responses_to_openai_request(request)
        self.assertEqual(openai_body["messages"][0]["role"], "system")
        self.assertEqual(openai_body["messages"][1]["content"], "run ls")
        self.assertEqual(openai_body["tools"][0]["function"]["name"], "shell")
        self.assertEqual(openai_body["reasoning_effort"], "medium")
        self.assertNotIn("store", openai_body)

        # Turn 1 stream: model answers with a function call
        frames = self._frames(
            [
                chunk(delta={"reasoning_content": "need ls"}),
                chunk(
                    delta={
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "shell", "arguments": "{\"command\":\"ls\"}"},
                            }
                        ]
                    }
                ),
                chunk(finish="tool_calls"),
                chunk(usage={"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}),
            ]
        )
        n = names(frames)
        self.assertEqual(n[0], "response.created")
        self.assertEqual(n[1], "response.in_progress")
        self.assertIn("response.function_call_arguments.delta", n)
        self.assertEqual(n[-1], "response.completed")
        final_items = frames[-1][1]["response"]["output"]
        self.assertEqual(
            [i["type"] for i in final_items], ["reasoning", "function_call"]
        )

        # Turn 2 request: history replay with function_call + output + reasoning
        request2 = {
            "model": "gpt-test",
            "instructions": "You are a coding agent.",
            "input": [
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "run ls"}]},
                {"type": "reasoning", "id": "rs_1", "summary": []},
                {"type": "function_call", "call_id": "call_1", "name": "shell", "arguments": "{\"command\":\"ls\"}"},
                {"type": "function_call_output", "call_id": "call_1", "output": "file1\nfile2"},
            ],
            "tools": request["tools"],
            "store": False,
        }
        openai_body2 = responses_to_openai_request(request2)
        roles = [m["role"] for m in openai_body2["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "tool"])
        self.assertEqual(openai_body2["messages"][2]["tool_calls"][0]["id"], "call_1")
        self.assertEqual(openai_body2["messages"][3]["content"], "file1\nfile2")


# ---------------------------------------------------------------------------
# SSE byte-level translation (generator)
# ---------------------------------------------------------------------------


class AsyncChunkIterator:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        self._iter = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class SseGeneratorTests(unittest.TestCase):
    def _run(self, source_items):
        import asyncio

        async def collect():
            out = []
            async for evt in translate_openai_sse_to_responses(
                AsyncChunkIterator(source_items), "gpt-test"
            ):
                out.append(evt.decode("utf-8"))
            return out

        return asyncio.run(collect())

    def test_full_stream_bytes(self):
        upstream = (
            b'data: {"choices":[{"delta":{"role":"assistant","content":"Hi"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":" there"}}]}\n\n'
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}\n\n'
            b"data: [DONE]\n\n"
        )
        events = self._run([upstream])
        frames = parse_frames(events)
        self.assertEqual(frames[0][0], "response.created")
        self.assertEqual(frames[-1][0], "response.completed")
        deltas = "".join(
            d["delta"] for n, d in frames if n == "response.output_text.delta"
        )
        self.assertEqual(deltas, "Hi there")
        self.assertEqual(frames[-1][1]["response"]["usage"]["total_tokens"], 6)
        # exactly one terminal event, nothing after it
        self.assertEqual(
            [n for n, _ in frames].count("response.completed"), 1
        )

    def test_upstream_mid_stream_error(self):
        upstream = (
            b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            b'data: {"error":{"message":"upstream died"}}\n\n'
        )
        events = self._run([upstream])
        frames = parse_frames(events)
        self.assertEqual(frames[-1][0], "response.failed")
        self.assertEqual(
            frames[-1][1]["response"]["error"]["message"], "upstream died"
        )


if __name__ == "__main__":
    unittest.main()
