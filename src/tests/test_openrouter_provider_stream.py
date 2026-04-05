import json

from app.providers import OpenRouterProvider


def test_openrouter_stream_parser_emits_text_and_done() -> None:
    payloads = [
        '{"id":"resp-1","model":"openai/gpt-4o-mini","choices":[{"delta":{"content":"Hel"},"finish_reason":null}]}',
        '{"id":"resp-1","model":"openai/gpt-4o-mini","choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}',
    ]

    events = list(OpenRouterProvider._iter_stream_events_from_payloads(payloads))

    assert [event.type for event in events] == [
        "text_delta",
        "text_delta",
        "text_done",
        "done",
    ]
    assert events[2].text == "Hello"
    assert events[3].response.output[0].text == "Hello"
    assert events[3].response.usage.total_tokens == 5


def test_openrouter_stream_parser_emits_function_call_events() -> None:
    payloads = [
        json.dumps(
            {
                "id": "resp-2",
                "model": "openai/gpt-4o-mini",
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "calculator",
                                        "arguments": '{"a":',
                                    },
                                }
                            ]
                        }
                    }
                ],
            }
        ),
        json.dumps(
            {
                "id": "resp-2",
                "model": "openai/gpt-4o-mini",
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {
                                        "arguments": " 7}",
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 3,
                    "total_tokens": 7,
                },
            }
        ),
    ]

    events = list(OpenRouterProvider._iter_stream_events_from_payloads(payloads))

    assert [event.type for event in events] == [
        "function_call_delta",
        "function_call_delta",
        "function_call_done",
        "done",
    ]
    assert events[2].arguments == {"a": 7}
    assert events[3].response.output[0].name == "calculator"
    assert events[3].response.output[0].arguments == {"a": 7}
    assert events[3].response.finish_reason == "tool_calls"


def test_openrouter_stream_parser_maps_error_payload() -> None:
    payloads = ['{"error":{"message":"bad request","code":"bad_request"}}']

    events = list(OpenRouterProvider._iter_stream_events_from_payloads(payloads))

    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].error == "bad request"
    assert events[0].code == "bad_request"
