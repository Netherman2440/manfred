from __future__ import annotations

import json
from typing import Any
from urllib import error, parse, request

from app.config import Settings
from app.domain.tool import FunctionToolDefinition, Tool, ToolResult, tool_error, tool_ok


VERIFY_TASK_DEFINITION = FunctionToolDefinition(
    name="verify_task",
    description=(
        "Send an answer for an AI Devs task to the Central verification endpoint /verify, "
        "and return the hub response."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "AI Devs task name for the payload sent to Centrala via /verify, "
                    "for example people, findhim, sendit, or proxy."
                ),
            },
            "answer": {
                "description": (
                    "Answer payload that should be sent do sprawdzenia do Centrali via /verify. "
                    "It can be a string, number, object, or array. "
                    "If you already have JSON as text, pass valid JSON text and the tool will parse it before sending."
                ),
            },
        },
        "required": ["task", "answer"],
        "additionalProperties": False,
    },
)


def build_verify_task_tool(settings: Settings) -> Tool:
    async def verify_task_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
        del signal

        if not settings.AI_DEVS_API_KEY:
            return tool_error(
                "AI_DEVS_API_KEY is not configured.",
                hint="Skonfiguruj klucz AI_DEVS_API_KEY zanim użyjesz verify_task.",
                details={"tool": "verify_task"},
                retryable=False,
            )

        task = args.get("task")
        if not isinstance(task, str) or task.strip() == "":
            return tool_error(
                "verify_task expects a non-empty string argument: 'task'.",
                hint="Podaj pole 'task' jako niepusty string, np. 'people'.",
                details={
                    "received": {"task": task},
                    "expected": {"task": "non-empty string"},
                },
            )

        normalized_task = task.strip()
        normalized_answer = _normalize_answer(args.get("answer"))
        validated_answer = _validate_answer(normalized_task, normalized_answer)
        if isinstance(validated_answer, dict) and validated_answer.get("ok") is False:
            return validated_answer

        url = parse.urljoin(f"{settings.AI_DEVS_HUB_URL.rstrip('/')}/", "verify")
        body = json.dumps(
            {
                "apikey": settings.AI_DEVS_API_KEY,
                "task": normalized_task,
                "answer": validated_answer,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
            "Content-Type": "application/json; charset=utf-8",
        }
        http_request = request.Request(url=url, data=body, headers=headers, method="POST")

        try:
            with request.urlopen(http_request, timeout=30.0) as response:
                response_body = response.read()
                status_code = response.status
                content_type = response.headers.get("Content-Type", "application/json")
        except error.HTTPError as exc:
            response_body = exc.read()
            status_code = exc.code
            content_type = exc.headers.get("Content-Type", "application/json")
        except error.URLError as exc:
            return tool_error(
                f"Could not reach AI Devs verify endpoint: {exc.reason}",
                hint="Sprawdź dostępność Centrali i spróbuj ponownie później.",
                details={
                    "task": normalized_task,
                    "url": url,
                    "reason": str(exc.reason),
                },
            )

        parsed_response = _parse_response_body(response_body, content_type)
        status_ok = 200 <= status_code < 300

        result = {
            "task": normalized_task,
            "url": url,
            "status_code": status_code,
            "response": parsed_response,
        }

        if isinstance(validated_answer, list):
            result["submitted_answer_count"] = len(validated_answer)

        if status_ok:
            return tool_ok(result)

        return tool_error(
            f"AI Devs verify endpoint returned HTTP {status_code}.",
            hint="Sprawdź odpowiedź Centrali w details.response i popraw answer albo spróbuj ponownie później.",
            details=result,
            retryable=status_code in {408, 409, 425, 429} or 500 <= status_code < 600,
        )

    return Tool(
        type="sync",
        definition=VERIFY_TASK_DEFINITION,
        handler=verify_task_handler,
    )


def _normalize_answer(answer: Any) -> Any:
    if not isinstance(answer, str):
        return answer

    stripped_answer = answer.strip()
    if not stripped_answer or not stripped_answer.startswith(("{", "[")):
        return answer

    try:
        return json.loads(stripped_answer)
    except json.JSONDecodeError:
        return answer


def _validate_answer(task: str, answer: Any) -> Any | ToolResult:
    if task != "people":
        return answer

    if not isinstance(answer, list):
        return tool_error(
            "verify_task expects 'answer' to be a list of people objects for task 'people'.",
            hint=(
                "Dla tasku 'people' podaj listę obiektów z polami "
                "name, surname, gender, born, city, tags."
            ),
            details={
                "task": task,
                "received": {"answer": answer},
                "expected": {
                    "answer": [
                        {
                            "name": "string",
                            "surname": "string",
                            "gender": "M | F",
                            "born": "integer year",
                            "city": "string",
                            "tags": ["non-empty string"],
                        }
                    ]
                },
            },
        )

    normalized_people: list[dict[str, Any]] = []
    for index, person in enumerate(answer, start=1):
        if not isinstance(person, dict):
            return _people_validation_error(
                index,
                "object",
                received=person,
                task=task,
            )

        name_result = _ensure_string_field(person, "name", index=index, task=task)
        if isinstance(name_result, dict):
            return name_result

        surname_result = _ensure_string_field(person, "surname", index=index, task=task)
        if isinstance(surname_result, dict):
            return surname_result

        gender = _ensure_string_field(person, "gender", index=index, task=task)
        if isinstance(gender, dict):
            return gender
        if gender not in {"M", "F"}:
            return tool_error(
                f"verify_task expects item {index} field 'gender' to be 'M' or 'F'.",
                hint="Dla tasku 'people' ustaw gender jako 'M' albo 'F'.",
                details={
                    "task": task,
                    "index": index,
                    "field": "gender",
                    "received": person.get("gender"),
                    "expected": ["M", "F"],
                },
            )

        born = person.get("born")
        if not isinstance(born, int):
            return tool_error(
                f"verify_task expects item {index} field 'born' to be an integer year.",
                hint="Dla tasku 'people' ustaw born jako rok w formacie integer, np. 1990.",
                details={
                    "task": task,
                    "index": index,
                    "field": "born",
                    "received": born,
                    "expected": "integer year",
                },
            )

        city_result = _ensure_string_field(person, "city", index=index, task=task)
        if isinstance(city_result, dict):
            return city_result

        tags = person.get("tags")
        if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
            return tool_error(
                f"verify_task expects item {index} field 'tags' to be a list of non-empty strings.",
                hint="Dla tasku 'people' ustaw tags jako listę niepustych stringów.",
                details={
                    "task": task,
                    "index": index,
                    "field": "tags",
                    "received": tags,
                    "expected": "list of non-empty strings",
                },
            )

        normalized_people.append(person)

    return normalized_people


def _ensure_string_field(person: dict[str, Any], field_name: str, *, index: int, task: str) -> str | ToolResult:
    value = person.get(field_name)
    if not isinstance(value, str) or value.strip() == "":
        return tool_error(
            f"verify_task expects item {index} field '{field_name}' to be a non-empty string.",
            hint=f"Dla tasku 'people' uzupełnij pole '{field_name}' niepustym stringiem.",
            details={
                "task": task,
                "index": index,
                "field": field_name,
                "received": value,
                "expected": "non-empty string",
            },
        )
    return value


def _people_validation_error(index: int, expected: str, *, received: Any, task: str) -> ToolResult:
    return tool_error(
        f"verify_task expects item {index} in 'answer' to be an object.",
        hint="Dla tasku 'people' każde pole listy 'answer' musi być obiektem osoby.",
        details={
            "task": task,
            "index": index,
            "received": received,
            "expected": expected,
        },
    )


def _parse_response_body(response_body: bytes, content_type: str) -> Any:
    charset = "utf-8"
    lowered_content_type = content_type.lower()
    if "charset=" in lowered_content_type:
        charset = lowered_content_type.split("charset=", maxsplit=1)[1].split(";", maxsplit=1)[0].strip() or "utf-8"

    decoded_body = response_body.decode(charset, errors="replace").strip()
    if not decoded_body:
        return None

    if "json" in lowered_content_type:
        try:
            return json.loads(decoded_body)
        except json.JSONDecodeError:
            return decoded_body

    try:
        return json.loads(decoded_body)
    except json.JSONDecodeError:
        return decoded_body
