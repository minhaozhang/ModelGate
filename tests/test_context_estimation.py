import pytest

from app.services.tokens import estimate_request_context_tokens


def _multimodal_body(image_chars: int) -> dict:
    base64_blob = "iVBORw0KGgoAAAANSUhEUg==" * (image_chars // 20 + 1)
    return {
        "model": "glm-5.3",
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "这是什么图片？"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_blob[:image_chars]}"
                        },
                    },
                ],
            },
        ],
    }


def test_image_base64_not_counted_as_text_tokens():
    body = _multimodal_body(1_000_000)
    estimate = estimate_request_context_tokens(body)
    assert estimate < 5000


def test_image_counted_with_fixed_allowance():
    small = estimate_request_context_tokens(_multimodal_body(200))
    text_only = estimate_request_context_tokens(
        {"messages": [{"role": "user", "content": "这是什么图片？"}]}
    )
    assert small > text_only


def test_text_only_estimate_unchanged():
    body = {"messages": [{"role": "user", "content": "hello world" * 100}]}
    serialized = '{"messages":[{"role":"user","content":"' + "hello world" * 100 + '"}]}'
    assert estimate_request_context_tokens(body) == len(serialized) // 4


def test_anthropic_native_base64_source_not_counted_as_text():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看图"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "iVBORw0KGgoAAAANSUhEUg==" * 40,
                        },
                    },
                ],
            }
        ]
    }
    assert estimate_request_context_tokens(body) < 2000


def test_short_data_values_untouched():
    body = {"messages": [{"role": "user", "content": 'extra "data":"abc" here'}]}
    estimate = estimate_request_context_tokens(body)
    assert estimate == max(len(
        '{"messages":[{"role":"user","content":"extra \\"data\\":\\"abc\\" here"}]}'
    ) // 4, 1)
