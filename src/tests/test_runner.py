import json
import unittest

from app.runtime.runner import AgentRunner


class AgentRunnerToolSerializationTest(unittest.TestCase):
    def test_verify_task_error_keeps_full_payload_for_model(self) -> None:
        serialized = AgentRunner._serialize_tool_result_output(
            "verify_task",
            {
                "ok": False,
                "error": "AI Devs verify endpoint returned HTTP 429.",
                "output": {
                    "status_code": 429,
                    "response": {
                        "code": -985,
                        "message": "API rate limit exceeded. Please retry later.",
                        "retry_after": 29,
                    },
                },
            },
        )

        parsed = json.loads(serialized)
        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["error"], "AI Devs verify endpoint returned HTTP 429.")
        self.assertEqual(parsed["output"]["status_code"], 429)
        self.assertEqual(parsed["output"]["response"]["retry_after"], 29)

    def test_other_tool_error_stays_plain_error_string(self) -> None:
        serialized = AgentRunner._serialize_tool_result_output(
            "wait",
            {
                "ok": False,
                "error": "wait expects a numeric argument: 'time'.",
                "output": {"time": "soon"},
            },
        )

        self.assertEqual(serialized, "wait expects a numeric argument: 'time'.")


if __name__ == "__main__":
    unittest.main()
