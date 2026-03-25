import unittest

from app.providers.openai import OpenAIProvider, OpenAIProviderConfig


class OpenAIProviderParsingTest(unittest.TestCase):
    def test_parse_response_keeps_returned_model_name(self) -> None:
        provider = OpenAIProvider(
            OpenAIProviderConfig(
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                timeout_seconds=30,
                provider_name="openai",
                app_name="manfred",
            )
        )

        response = provider._parse_response(
            {
                "model": "gpt-4.1-2026-03-01",
                "choices": [
                    {
                        "message": {
                            "content": "Done",
                        }
                    }
                ],
            }
        )

        self.assertEqual(response.model, "gpt-4.1-2026-03-01")
        self.assertEqual(response.output[0].text, "Done")


if __name__ == "__main__":
    unittest.main()
