import json

from app.providers import OpenRouterProvider
from app.providers.types import (
    ProviderFunctionCallInputItem,
    ProviderFunctionCallOutputInputItem,
    ProviderMessageInputItem,
    ProviderRequest,
)


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


def test_build_messages_groups_parallel_tool_calls_into_one_assistant() -> None:
    """OpenAI rejects history where two consecutive assistant messages each carry one tool_call —
    parallel tool_calls must live in a single assistant message. Regression for the 400 caused by
    `An assistant message with 'tool_calls' must be followed by tool messages…`."""

    request = ProviderRequest(
        model="openai/gpt-4o-mini",
        instructions="sys",
        input=[
            ProviderMessageInputItem(role="user", content="hi"),
            ProviderFunctionCallInputItem(
                call_id="call_X", name="count_tokens", arguments={"path": "workspace/files/x"}
            ),
            ProviderFunctionCallInputItem(
                call_id="call_Y", name="search_file", arguments={"path": "workspace/files/x", "query": "q"}
            ),
            ProviderFunctionCallOutputInputItem(call_id="call_X", name="count_tokens", output="100"),
            ProviderFunctionCallOutputInputItem(call_id="call_Y", name="search_file", output="matches"),
        ],
        tools=[],
    )

    messages = OpenRouterProvider._build_messages(request)

    assistant_messages = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_messages) == 1, "parallel tool_calls must share one assistant message"
    tool_calls = assistant_messages[0]["tool_calls"]
    assert [tc["id"] for tc in tool_calls] == ["call_X", "call_Y"]

    tool_messages = [m for m in messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["call_X", "call_Y"]


def test_build_messages_keeps_solo_tool_call_intact() -> None:
    request = ProviderRequest(
        model="openai/gpt-4o-mini",
        instructions="sys",
        input=[
            ProviderFunctionCallInputItem(
                call_id="call_Z", name="submit_task", arguments={"task": "failure", "answer": "x"}
            ),
            ProviderFunctionCallOutputInputItem(call_id="call_Z", name="submit_task", output="{FLG:OK}"),
        ],
        tools=[],
    )

    messages = OpenRouterProvider._build_messages(request)

    assistant_messages = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_messages) == 1
    assert [tc["id"] for tc in assistant_messages[0]["tool_calls"]] == ["call_Z"]


def test_build_messages_separates_tool_call_groups_by_intervening_message() -> None:
    """Two tool_call rounds separated by a user/tool message must NOT be merged."""

    request = ProviderRequest(
        model="openai/gpt-4o-mini",
        instructions="sys",
        input=[
            ProviderFunctionCallInputItem(call_id="call_A", name="t", arguments={}),
            ProviderFunctionCallOutputInputItem(call_id="call_A", name="t", output="ok"),
            ProviderMessageInputItem(role="user", content="next"),
            ProviderFunctionCallInputItem(call_id="call_B", name="t", arguments={}),
            ProviderFunctionCallOutputInputItem(call_id="call_B", name="t", output="ok"),
        ],
        tools=[],
    )

    messages = OpenRouterProvider._build_messages(request)
    assistant_ids = [[tc["id"] for tc in m["tool_calls"]] for m in messages if m["role"] == "assistant"]
    assert assistant_ids == [["call_A"], ["call_B"]]
