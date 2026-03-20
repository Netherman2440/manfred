from __future__ import annotations

import json
from typing import Any
from urllib import error, parse, request

from app.config import Settings
from app.domain.tool import FunctionToolDefinition, Tool


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
            raise ValueError("AI_DEVS_API_KEY is not configured.")

        task = args.get("task")
        if not isinstance(task, str) or task.strip() == "":
            raise ValueError("verify_task expects a non-empty string argument: 'task'.")

        normalized_task = task.strip()
        normalized_answer = _normalize_answer(args.get("answer"))
        validated_answer = _validate_answer(normalized_task, normalized_answer)

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
            return {
                "ok": False,
                "error": f"Could not reach AI Devs verify endpoint: {exc.reason}",
                "output": {
                    "task": normalized_task,
                    "url": url,
                },
            }

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
            return {
                "ok": True,
                "output": result,
            }

        return {
            "ok": False,
            "error": f"AI Devs verify endpoint returned HTTP {status_code}.",
            "output": result,
        }

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


def _validate_answer(task: str, answer: Any) -> Any:
    if task != "people":
        return answer

    if not isinstance(answer, list):
        raise ValueError("verify_task expects 'answer' to be a list of people objects for task 'people'.")

    normalized_people: list[dict[str, Any]] = []
    for index, person in enumerate(answer, start=1):
        if not isinstance(person, dict):
            raise ValueError(f"verify_task expects item {index} in 'answer' to be an object.")

        _ensure_string_field(person, "name", index=index)
        _ensure_string_field(person, "surname", index=index)
        gender = _ensure_string_field(person, "gender", index=index)
        if gender not in {"M", "F"}:
            raise ValueError(f"verify_task expects item {index} field 'gender' to be 'M' or 'F'.")

        born = person.get("born")
        if not isinstance(born, int):
            raise ValueError(f"verify_task expects item {index} field 'born' to be an integer year.")

        _ensure_string_field(person, "city", index=index)

        tags = person.get("tags")
        if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
            raise ValueError(f"verify_task expects item {index} field 'tags' to be a list of non-empty strings.")

        normalized_people.append(person)

    return normalized_people


def _ensure_string_field(person: dict[str, Any], field_name: str, *, index: int) -> str:
    value = person.get(field_name)
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"verify_task expects item {index} field '{field_name}' to be a non-empty string.")
    return value


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
