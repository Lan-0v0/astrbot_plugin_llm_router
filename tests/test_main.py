import sys
import types
import unittest
from types import SimpleNamespace
from typing import Any


class FakeLogger:
    def info(self, *args: Any, **kwargs: Any) -> None:
        return None

    def warning(self, *args: Any, **kwargs: Any) -> None:
        return None

    def error(self, *args: Any, **kwargs: Any) -> None:
        return None


class FakeFilter:
    def on_llm_request(self):
        def decorator(handler):
            return handler

        return decorator


class FakeStar:
    def __init__(self, context) -> None:
        self.context = context


def fake_register(*args: Any, **kwargs: Any):
    def decorator(plugin_class):
        return plugin_class

    return decorator


class FakeTextPart:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeMessageSegment:
    def __init__(self, content: list[FakeTextPart]) -> None:
        self.content = content


def install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    astrbot_api_module = types.ModuleType("astrbot.api")
    astrbot_event_module = types.ModuleType("astrbot.api.event")
    astrbot_provider_module = types.ModuleType("astrbot.api.provider")
    astrbot_star_module = types.ModuleType("astrbot.api.star")
    astrbot_core_module = types.ModuleType("astrbot.core")
    astrbot_agent_module = types.ModuleType("astrbot.core.agent")
    astrbot_message_module = types.ModuleType("astrbot.core.agent.message")

    astrbot_api_module.AstrBotConfig = dict
    astrbot_api_module.logger = FakeLogger()
    astrbot_event_module.AstrMessageEvent = object
    astrbot_event_module.filter = FakeFilter()
    astrbot_provider_module.ProviderRequest = object
    astrbot_star_module.Context = object
    astrbot_star_module.Star = FakeStar
    astrbot_star_module.register = fake_register
    astrbot_message_module.TextPart = FakeTextPart
    astrbot_message_module.UserMessageSegment = FakeMessageSegment
    astrbot_message_module.AssistantMessageSegment = FakeMessageSegment

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = astrbot_api_module
    sys.modules["astrbot.api.event"] = astrbot_event_module
    sys.modules["astrbot.api.provider"] = astrbot_provider_module
    sys.modules["astrbot.api.star"] = astrbot_star_module
    sys.modules["astrbot.core"] = astrbot_core_module
    sys.modules["astrbot.core.agent"] = astrbot_agent_module
    sys.modules["astrbot.core.agent.message"] = astrbot_message_module


install_astrbot_stubs()

from main import LLMRouterPlugin  # noqa: E402


class FakeLLMResponse:
    def __init__(self, completion_text: str) -> None:
        self.completion_text = completion_text


class FakeConversationManager:
    def __init__(self) -> None:
        self.saved_pairs: list[dict[str, Any]] = []

    async def get_curr_conversation_id(self, unified_origin: str) -> str:
        return "conversation-id"

    async def add_message_pair(self, **kwargs: Any) -> None:
        self.saved_pairs.append(kwargs)


class FakeContext:
    def __init__(
        self,
        provider_responses: dict[str, str],
        provider_errors: dict[str, Exception] | None = None,
    ) -> None:
        self.provider_responses = provider_responses
        self.provider_errors = provider_errors or {}
        self.llm_calls: list[dict[str, Any]] = []
        self.conversation_manager = FakeConversationManager()

    async def llm_generate(self, **kwargs: Any) -> FakeLLMResponse:
        self.llm_calls.append(kwargs)
        provider_id = str(kwargs["chat_provider_id"])
        if provider_id in self.provider_errors:
            raise self.provider_errors[provider_id]
        return FakeLLMResponse(self.provider_responses.get(provider_id, ""))


class FakeConfig(dict):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.save_count = 0

    def save_config(self) -> None:
        self.save_count += 1


class FakeEvent:
    def __init__(self, message_text: str = "") -> None:
        self.message_str = message_text
        self.message_obj = SimpleNamespace(group_id="20002", session_id="session-1")
        self.platform_meta = SimpleNamespace(name="test-platform")
        self.unified_msg_origin = "test:origin"
        self.sent_results: list[Any] = []
        self.stopped = False

    def get_sender_id(self) -> str:
        return "10001"

    def get_sender_name(self) -> str:
        return "Alice"

    def plain_result(self, response_text: str) -> dict[str, str]:
        return {"text": response_text}

    async def send(self, result: Any) -> None:
        self.sent_results.append(result)

    def stop_event(self) -> None:
        self.stopped = True


def make_provider_request(prompt: str) -> SimpleNamespace:
    return SimpleNamespace(
        prompt=prompt,
        contexts=[{"role": "user", "content": "previous question"}],
        system_prompt="system prompt",
        image_urls=["image-url"],
        audio_urls=["audio-path"],
        extra_user_content_parts=[{"type": "text", "text": "dynamic context"}],
        tool_calls_result=None,
    )


def make_route_entry(
    *,
    rule_keywords: list[str],
    content_types: list[str],
    route_provider: str = "route-provider",
) -> dict[str, Any]:
    return {
        "__template_key": "route",
        "name": "math route",
        "enabled": True,
        "route_provider": route_provider,
        "content_types": content_types,
        "rule_keywords": rule_keywords,
        "whitelist": [],
        "blacklist": [],
    }


class PluginRoutingRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_migrates_and_saves_legacy_entries(self) -> None:
        context = FakeContext({})
        config = FakeConfig(
            routing_models=[
                {
                    "__template_key": "deepseek",
                    "name": "legacy route",
                    "api_base_url": "https://api.deepseek.com",
                    "api_keys": ["secret-key"],
                    "model": "deepseek-chat",
                    "content_types": ["数学问题"],
                }
            ]
        )
        plugin = LLMRouterPlugin(context, config)

        await plugin.initialize()

        self.assertEqual(config.save_count, 1)
        self.assertEqual(config["routing_models"][0]["__template_key"], "route")
        self.assertEqual(config["routing_models"][0]["route_provider"], "")
        self.assertNotIn("api_keys", config["routing_models"][0])

    async def test_rule_match_skips_classifier_and_calls_selected_provider(
        self,
    ) -> None:
        context = FakeContext(
            {
                "classifier-provider": '{"route_id":null,"matched_type":null}',
                "route-provider": "routed response",
            }
        )
        config = {
            "judgement_methods": ["规则匹配", "LLM判断"],
            "type_judgement_provider": "classifier-provider",
            "routing_models": [
                make_route_entry(
                    rule_keywords=["方程"],
                    content_types=["数学问题"],
                )
            ],
        }
        plugin = LLMRouterPlugin(context, config)
        event = FakeEvent()

        await plugin.route_llm_request(event, make_provider_request("解这个方程"))

        self.assertEqual(
            [call["chat_provider_id"] for call in context.llm_calls],
            ["route-provider"],
        )
        routed_call = context.llm_calls[0]
        self.assertEqual(routed_call["contexts"][0]["content"], "previous question")
        self.assertEqual(
            routed_call["extra_user_content_parts"][0]["text"], "dynamic context"
        )
        self.assertTrue(event.stopped)
        self.assertEqual(event.sent_results, [{"text": "routed response"}])
        self.assertEqual(len(context.conversation_manager.saved_pairs), 1)

    async def test_llm_classification_runs_after_rule_miss(self) -> None:
        context = FakeContext(
            {
                "classifier-provider": (
                    '{"route_id":"route_0","matched_type":"数学问题"}'
                ),
                "route-provider": "routed response",
            }
        )
        config = {
            "judgement_methods": ["规则匹配", "LLM判断"],
            "type_judgement_provider": "classifier-provider",
            "routing_models": [
                make_route_entry(
                    rule_keywords=["方程"],
                    content_types=["数学问题"],
                )
            ],
        }
        plugin = LLMRouterPlugin(context, config)
        event = FakeEvent()

        await plugin.route_llm_request(event, make_provider_request("证明勾股定理"))

        self.assertEqual(
            [call["chat_provider_id"] for call in context.llm_calls],
            ["classifier-provider", "route-provider"],
        )
        self.assertTrue(event.stopped)

    async def test_no_llm_match_keeps_original_astrbot_flow(self) -> None:
        context = FakeContext(
            {"classifier-provider": '{"route_id":null,"matched_type":null}'}
        )
        config = {
            "judgement_methods": ["LLM判断"],
            "type_judgement_provider": "classifier-provider",
            "routing_models": [
                make_route_entry(rule_keywords=[], content_types=["数学问题"])
            ],
        }
        plugin = LLMRouterPlugin(context, config)
        event = FakeEvent()

        await plugin.route_llm_request(event, make_provider_request("今天天气如何"))

        self.assertEqual(
            [call["chat_provider_id"] for call in context.llm_calls],
            ["classifier-provider"],
        )
        self.assertFalse(event.stopped)
        self.assertEqual(event.sent_results, [])

    async def test_route_provider_failure_keeps_original_astrbot_flow(self) -> None:
        context = FakeContext(
            {},
            provider_errors={"route-provider": RuntimeError("provider unavailable")},
        )
        config = {
            "judgement_methods": ["规则匹配"],
            "type_judgement_provider": "classifier-provider",
            "routing_models": [
                make_route_entry(
                    rule_keywords=["方程"],
                    content_types=["数学问题"],
                )
            ],
        }
        plugin = LLMRouterPlugin(context, config)
        event = FakeEvent()

        await plugin.route_llm_request(event, make_provider_request("解方程"))

        self.assertFalse(event.stopped)
        self.assertEqual(event.sent_results, [])

    async def test_entry_without_selected_provider_is_ignored(self) -> None:
        context = FakeContext({"route-provider": "should not be used"})
        config = {
            "judgement_methods": ["规则匹配"],
            "routing_models": [
                make_route_entry(
                    rule_keywords=["方程"],
                    content_types=["数学问题"],
                    route_provider="",
                )
            ],
        }
        plugin = LLMRouterPlugin(context, config)
        event = FakeEvent()

        await plugin.route_llm_request(event, make_provider_request("解方程"))

        self.assertEqual(context.llm_calls, [])
        self.assertFalse(event.stopped)


if __name__ == "__main__":
    unittest.main()
