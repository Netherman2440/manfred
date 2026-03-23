import json
import unittest

from app.runtime.runner import AgentRunner


class AgentRunnerToolSerializationTest(unittest.TestCase):
    def test_tool_error_keeps_full_payload_for_model(self) -> None:
        serialized = AgentRunner._serialize_tool_result_output(
            "verify_task",
            {
                "ok": False,
                "error": "AI Devs verify endpoint returned HTTP 429.",
                "hint": "Check details.response before retrying.",
                "details": {
                    "status_code": 429,
                    "response": {
                        "code": -985,
                        "message": "API rate limit exceeded. Please retry later.",
                        "retry_after": 29,
                    },
                },
                "retryable": True,
            },
        )

        parsed = json.loads(serialized)
        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["error"], "AI Devs verify endpoint returned HTTP 429.")
        self.assertEqual(parsed["hint"], "Check details.response before retrying.")
        self.assertEqual(parsed["details"]["status_code"], 429)
        self.assertEqual(parsed["details"]["response"]["retry_after"], 29)
        self.assertTrue(parsed["retryable"])

    def test_other_tool_error_also_stays_structured(self) -> None:
        serialized = AgentRunner._serialize_tool_result_output(
            "wait",
            {
                "ok": False,
                "error": "wait expects a numeric argument: 'time'.",
                "hint": "Pass time as a number >= 0.",
                "details": {"received": {"time": "soon"}},
                "retryable": True,
            },
        )

        parsed = json.loads(serialized)
        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["error"], "wait expects a numeric argument: 'time'.")
        self.assertEqual(parsed["details"]["received"]["time"], "soon")


if __name__ == "__main__":
    unittest.main()
