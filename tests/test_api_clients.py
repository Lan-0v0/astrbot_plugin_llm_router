import json
import unittest
from collections.abc import Mapping
from typing import Any

from api_clients import RoutedModelClient
from router_core import GenerationInput, RouteEntry


class FakeResponse:
    def __init__(self, status: int, payload: Mapping[str, Any]) -> None:
        self.status = status
        self._response_text = json.dumps(payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exception_type, exception, traceback) -> None:
        return None

    async def text(self) -> str:
        return self._response_text


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.closed = False
        self._responses = responses
        self.requests: list[dict[str, Any]] = []

    def post(
        self,
        request_url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> FakeResponse:
        self.requests.append(
            {
                "url": request_url,
                "headers": headers,
                "json": json,
            }
        )
        return self._responses.pop(0)


def make_route_entry(
    *,
    provider_kind: str = "openai_compatible",
    api_keys: tuple[str, ...] = ("key-one",),
) -> RouteEntry:
    return RouteEntry(
        route_id="route_0",
        provider_kind=provider_kind,
        name="test route",
        enabled=True,
        api_base_url=(
            "https://generativelanguage.googleapis.com/v1beta"
            if provider_kind == "gemini"
            else "https://example.com/v1"
        ),
        model_name="test-model",
        api_keys=api_keys,
        content_types=("test",),
        rule_keywords=("test",),
        whitelist=(),
        blacklist=(),
    )


def make_generation_input() -> GenerationInput:
    return GenerationInput(
        prompt="current question",
        system_prompt="system instruction",
        contexts=(
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ),
        image_urls=(),
        audio_urls=(),
        extra_user_texts=("dynamic context",),
    )


class RoutedModelClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_request_preserves_context_and_current_prompt(self) -> None:
        fake_session = FakeSession(
            [
                FakeResponse(
                    200,
                    {"choices": [{"message": {"content": "routed answer"}}]},
                )
            ]
        )
        model_client = RoutedModelClient(session=fake_session)  # type: ignore[arg-type]

        response_text = await model_client.generate(
            make_route_entry(),
            make_generation_input(),
        )

        self.assertEqual(response_text, "routed answer")
        request_record = fake_session.requests[0]
        self.assertEqual(
            request_record["url"], "https://example.com/v1/chat/completions"
        )
        self.assertEqual(request_record["headers"]["Authorization"], "Bearer key-one")
        messages = request_record["json"]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[-1]["content"], "current question\ndynamic context")

    async def test_retryable_error_uses_next_api_key(self) -> None:
        fake_session = FakeSession(
            [
                FakeResponse(429, {"error": {"message": "rate limited"}}),
                FakeResponse(
                    200,
                    {"choices": [{"message": {"content": "second key worked"}}]},
                ),
            ]
        )
        model_client = RoutedModelClient(session=fake_session)  # type: ignore[arg-type]

        response_text = await model_client.generate(
            make_route_entry(api_keys=("key-one", "key-two")),
            make_generation_input(),
        )

        self.assertEqual(response_text, "second key worked")
        authorization_headers = [
            request_record["headers"]["Authorization"]
            for request_record in fake_session.requests
        ]
        self.assertEqual(
            authorization_headers,
            ["Bearer key-one", "Bearer key-two"],
        )

    async def test_api_key_rotation_changes_first_key_between_requests(self) -> None:
        successful_payload = {"choices": [{"message": {"content": "answer"}}]}
        fake_session = FakeSession(
            [
                FakeResponse(200, successful_payload),
                FakeResponse(200, successful_payload),
            ]
        )
        model_client = RoutedModelClient(session=fake_session)  # type: ignore[arg-type]
        route_entry = make_route_entry(api_keys=("key-one", "key-two"))

        await model_client.generate(route_entry, make_generation_input())
        await model_client.generate(route_entry, make_generation_input())

        authorization_headers = [
            request_record["headers"]["Authorization"]
            for request_record in fake_session.requests
        ]
        self.assertEqual(
            authorization_headers,
            ["Bearer key-one", "Bearer key-two"],
        )

    async def test_gemini_native_response_is_extracted(self) -> None:
        fake_session = FakeSession(
            [
                FakeResponse(
                    200,
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {"text": "Gemini "},
                                        {"text": "answer"},
                                    ]
                                }
                            }
                        ]
                    },
                )
            ]
        )
        model_client = RoutedModelClient(session=fake_session)  # type: ignore[arg-type]

        response_text = await model_client.generate(
            make_route_entry(provider_kind="gemini"),
            make_generation_input(),
        )

        self.assertEqual(response_text, "Gemini answer")
        request_record = fake_session.requests[0]
        self.assertEqual(
            request_record["url"],
            "https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent",
        )
        self.assertEqual(request_record["headers"]["x-goog-api-key"], "key-one")
        self.assertEqual(
            request_record["json"]["systemInstruction"]["parts"][0]["text"],
            "system instruction",
        )


if __name__ == "__main__":
    unittest.main()
