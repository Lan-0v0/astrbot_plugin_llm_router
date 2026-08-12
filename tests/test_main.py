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
    def on_waiting_llm_request(self):
        def decorator(handler):
            return handler

        return decorator

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


def install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    astrbot_api_module = types.ModuleType("astrbot.api")
    astrbot_event_module = types.ModuleType("astrbot.api.event")
    astrbot_provider_module = types.ModuleType("astrbot.api.provider")
    astrbot_star_module = types.ModuleType("astrbot.api.star")
    astrbot_core_module = types.ModuleType("astrbot.core")
    astrbot_persona_module = types.ModuleType("astrbot.core.persona_mgr")

    astrbot_api_module.AstrBotConfig = dict
    astrbot_api_module.logger = FakeLogger()
    astrbot_event_module.AstrMessageEvent = object
    astrbot_event_module.filter = FakeFilter()
    astrbot_provider_module.ProviderRequest = object
    astrbot_star_module.Context = object
    astrbot_star_module.Star = FakeStar
    astrbot_star_module.register = fake_register
    astrbot_persona_module.DEFAULT_PERSONALITY = {
        "name": "default",
        "prompt": "You are a helpful and friendly assistant.",
    }

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = astrbot_api_module
    sys.modules["astrbot.api.event"] = astrbot_event_module
    sys.modules["astrbot.api.provider"] = astrbot_provider_module
    sys.modules["astrbot.api.star"] = astrbot_star_module
    sys.modules["astrbot.core"] = astrbot_core_module
    sys.modules["astrbot.core.persona_mgr"] = astrbot_persona_module


install_astrbot_stubs()

from main import (  # noqa: E402
    ROUTE_MATCH_EXTRA_KEY,
    SELECTED_PROVIDER_EXTRA_KEY,
    LLMRouterPlugin,
)
from router_core import RouteMatch, parse_route_entries  # noqa: E402


class FakeLLMResponse:
    def __init__(self, completion_text: str) -> None:
        self.completion_text = completion_text


class FakeProvider:
    def __init__(
        self,
        provider_id: str,
        modalities: list[str] | None,
        model_metadata_inputs: list[str] | None = None,
    ) -> None:
        self.provider_config = {
            "id": provider_id,
            "modalities": modalities,
        }
        if model_metadata_inputs is not None:
            self.provider_config["model_metadata"] = {
                "modalities": {"input": model_metadata_inputs}
            }


class FakePersonaManager:
    def __init__(self, persona_prompts: dict[str, str] | None = None) -> None:
        available_persona_prompts = {
            "default": "You are a helpful and friendly assistant.",
        }
        available_persona_prompts.update(persona_prompts or {})
        self.personas_v3 = [
            {"name": persona_id, "prompt": persona_prompt}
            for persona_id, persona_prompt in available_persona_prompts.items()
        ]

    def get_persona_v3_by_id(self, persona_id: str) -> dict[str, str] | None:
        return next(
            (persona for persona in self.personas_v3 if persona["name"] == persona_id),
            None,
        )


class FakeContext:
    def __init__(
        self,
        *,
        provider_responses: dict[str, str | list[str]] | None = None,
        provider_errors: dict[str, Exception] | None = None,
        provider_modalities: dict[str, list[str] | None] | None = None,
        provider_metadata_modalities: dict[str, list[str]] | None = None,
        persona_prompts: dict[str, str] | None = None,
    ) -> None:
        self.provider_responses = provider_responses or {}
        self.provider_errors = provider_errors or {}
        self.llm_calls: list[dict[str, Any]] = []
        self.persona_manager = FakePersonaManager(persona_prompts)
        metadata_modalities = provider_metadata_modalities or {}
        self.providers = {
            provider_id: FakeProvider(
                provider_id,
                modalities,
                metadata_modalities.get(provider_id),
            )
            for provider_id, modalities in (provider_modalities or {}).items()
        }

    def get_provider_by_id(self, provider_id: str) -> FakeProvider | None:
        return self.providers.get(provider_id)

    async def llm_generate(self, **kwargs: Any) -> FakeLLMResponse:
        self.llm_calls.append(kwargs)
        provider_id = str(kwargs["chat_provider_id"])
        if provider_id in self.provider_errors:
            raise self.provider_errors[provider_id]
        configured_response = self.provider_responses.get(provider_id, "")
        if isinstance(configured_response, list):
            response_text = configured_response.pop(0) if configured_response else ""
        else:
            response_text = configured_response
        return FakeLLMResponse(response_text)


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
        self.extras: dict[str, Any] = {}
        self.sent_results: list[Any] = []
        self.stopped = False

    def get_sender_id(self) -> str:
        return "10001"

    def get_sender_name(self) -> str:
        return "Alice"

    def set_extra(self, key: str, value: Any) -> None:
        self.extras[key] = value

    def get_extra(self, key: str) -> Any:
        return self.extras.get(key)

    async def send(self, result: Any) -> None:
        self.sent_results.append(result)

    def stop_event(self) -> None:
        self.stopped = True


def make_provider_request(
    *,
    system_prompt: str = "current system prompt",
    contexts: list[Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        prompt="current prompt",
        contexts=contexts or [],
        system_prompt=system_prompt,
        image_urls=["current-image"],
        audio_urls=["current-audio"],
        extra_user_content_parts=[{"type": "text", "text": "dynamic context"}],
        func_tool=object(),
        tool_calls_result=None,
    )


def make_route_entry(
    *,
    rule_keywords: list[str],
    content_types: list[str],
    route_provider: str = "route-provider",
    route_persona: str = "",
    priority: int = 100,
    whitelist: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "__template_key": "route",
        "name": "math route",
        "enabled": True,
        "route_provider": route_provider,
        "route_persona": route_persona,
        "priority": priority,
        "content_types": content_types,
        "rule_keywords": rule_keywords,
        "whitelist": whitelist or [],
        "blacklist": [],
    }


class ProviderSelectionRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_migrates_and_saves_legacy_entries(self) -> None:
        context = FakeContext()
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
        self.assertEqual(config["routing_models"][0]["route_persona"], "")
        self.assertNotIn("api_keys", config["routing_models"][0])

    async def test_rule_match_only_selects_provider_for_astrbot(self) -> None:
        context = FakeContext(
            provider_modalities={"route-provider": ["text"]},
        )
        config = {
            "judgement_methods": ["规则匹配"],
            "routing_models": [
                make_route_entry(rule_keywords=["方程"], content_types=[])
            ],
        }
        plugin = LLMRouterPlugin(context, config)
        event = FakeEvent("解这个方程")

        await plugin.select_route_provider(event)

        self.assertEqual(event.get_extra(SELECTED_PROVIDER_EXTRA_KEY), "route-provider")
        self.assertIsInstance(event.get_extra(ROUTE_MATCH_EXTRA_KEY), RouteMatch)
        self.assertEqual(context.llm_calls, [])
        self.assertEqual(event.sent_results, [])
        self.assertFalse(event.stopped)

    async def test_llm_classification_selects_provider_without_generating_reply(
        self,
    ) -> None:
        context = FakeContext(
            provider_responses={
                "classifier-provider": (
                    '{"route_id":"route_0","matched_type":"数学问题"}'
                )
            },
            provider_modalities={
                "classifier-provider": ["text"],
                "route-provider": ["text"],
            },
        )
        config = {
            "judgement_methods": ["LLM判断"],
            "type_judgement_provider": "classifier-provider",
            "routing_models": [
                make_route_entry(rule_keywords=[], content_types=["数学问题"])
            ],
        }
        plugin = LLMRouterPlugin(context, config)
        event = FakeEvent("证明勾股定理")

        await plugin.select_route_provider(event)

        self.assertEqual(
            [call["chat_provider_id"] for call in context.llm_calls],
            ["classifier-provider"],
        )
        self.assertEqual(event.get_extra(SELECTED_PROVIDER_EXTRA_KEY), "route-provider")
        self.assertEqual(event.sent_results, [])
        self.assertFalse(event.stopped)

    async def test_direct_route_handles_media_only_message(self) -> None:
        context = FakeContext(provider_modalities={"route-provider": ["text"]})
        config = {
            "judgement_methods": [],
            "routing_models": [make_route_entry(rule_keywords=[], content_types=[])],
        }
        plugin = LLMRouterPlugin(context, config)
        event = FakeEvent("")

        await plugin.select_route_provider(event)

        self.assertEqual(event.get_extra(SELECTED_PROVIDER_EXTRA_KEY), "route-provider")

    async def test_whitelist_binding_still_excludes_public_route(self) -> None:
        context = FakeContext(
            provider_modalities={
                "public-provider": ["text"],
                "bound-provider": ["text"],
            }
        )
        config = {
            "judgement_methods": [],
            "routing_models": [
                make_route_entry(
                    rule_keywords=[],
                    content_types=[],
                    route_provider="public-provider",
                    priority=100,
                ),
                make_route_entry(
                    rule_keywords=[],
                    content_types=[],
                    route_provider="bound-provider",
                    priority=10,
                    whitelist=["user:10001"],
                ),
            ],
        }
        plugin = LLMRouterPlugin(context, config)
        event = FakeEvent("任意消息")

        await plugin.select_route_provider(event)

        self.assertEqual(event.get_extra(SELECTED_PROVIDER_EXTRA_KEY), "bound-provider")

    async def test_master_direct_switch_disables_saved_whitelist_switch(self) -> None:
        context = FakeContext(provider_modalities={"bound-provider": ["text"]})
        config = {
            "judgement_methods": [],
            "direct_route_without_match": False,
            "whitelist_direct_route": True,
            "routing_models": [
                make_route_entry(
                    rule_keywords=[],
                    content_types=[],
                    route_provider="bound-provider",
                    whitelist=["user:10001"],
                )
            ],
        }
        plugin = LLMRouterPlugin(context, config)
        event = FakeEvent("任意消息")

        await plugin.select_route_provider(event)

        self.assertIsNone(event.get_extra(SELECTED_PROVIDER_EXTRA_KEY))

    async def test_missing_route_provider_keeps_astrbot_original_provider(self) -> None:
        context = FakeContext()
        config = {
            "judgement_methods": ["规则匹配"],
            "routing_models": [
                make_route_entry(rule_keywords=["方程"], content_types=[])
            ],
        }
        plugin = LLMRouterPlugin(context, config)
        event = FakeEvent("解方程")

        await plugin.select_route_provider(event)

        self.assertIsNone(event.get_extra(SELECTED_PROVIDER_EXTRA_KEY))
        self.assertIsNone(event.get_extra(ROUTE_MATCH_EXTRA_KEY))


class RequestHandoffRegressionTests(unittest.IsolatedAsyncioTestCase):
    def make_route_match(
        self,
        *,
        route_provider: str = "route-provider",
        route_persona: str = "",
    ) -> RouteMatch:
        route_entry = parse_route_entries(
            [
                make_route_entry(
                    rule_keywords=[],
                    content_types=[],
                    route_provider=route_provider,
                    route_persona=route_persona,
                )
            ]
        )[0]
        return RouteMatch(
            route_entry=route_entry,
            judgement_method="direct",
            matched_value="无需匹配/判断",
        )

    async def test_unrouted_request_is_not_modified(self) -> None:
        context = FakeContext(provider_modalities={"route-provider": ["text"]})
        plugin = LLMRouterPlugin(context, {})
        event = FakeEvent("message")
        original_contexts = [{"role": "user", "content": "history"}]
        request = make_provider_request(contexts=original_contexts)

        await plugin.apply_route_request(event, request)

        self.assertEqual(request.system_prompt, "current system prompt")
        self.assertEqual(request.contexts, original_contexts)

    async def test_route_persona_overrides_only_system_prompt(self) -> None:
        context = FakeContext(
            provider_modalities={"route-provider": ["text"]},
            persona_prompts={"math-expert": "You are a precise math expert."},
        )
        plugin = LLMRouterPlugin(context, {})
        event = FakeEvent("message")
        event.set_extra(
            ROUTE_MATCH_EXTRA_KEY,
            self.make_route_match(route_persona="math-expert"),
        )
        request = make_provider_request()
        original_tools = request.func_tool
        original_images = list(request.image_urls)
        original_audio = list(request.audio_urls)
        original_extra_parts = list(request.extra_user_content_parts)

        await plugin.apply_route_request(event, request)

        self.assertEqual(request.system_prompt, "You are a precise math expert.")
        self.assertIs(request.func_tool, original_tools)
        self.assertEqual(request.image_urls, original_images)
        self.assertEqual(request.audio_urls, original_audio)
        self.assertEqual(request.extra_user_content_parts, original_extra_parts)

    async def test_text_provider_removes_historical_image_blocks_only(self) -> None:
        context = FakeContext(provider_modalities={"route-provider": ["text"]})
        plugin = LLMRouterPlugin(context, {})
        event = FakeEvent("message")
        event.set_extra(ROUTE_MATCH_EXTRA_KEY, self.make_route_match())
        original_contexts = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "keep this text"},
                    {"type": "image_url", "image_url": {"url": "old-image"}},
                ],
            },
            {
                "role": "assistant",
                "content": "<image_caption>existing description</image_caption>",
            },
        ]
        request = make_provider_request(contexts=original_contexts)

        await plugin.apply_route_request(event, request)

        self.assertEqual(
            request.contexts[0]["content"],
            [{"type": "text", "text": "keep this text"}],
        )
        self.assertEqual(
            request.contexts[1]["content"],
            "<image_caption>existing description</image_caption>",
        )
        self.assertEqual(
            original_contexts[0]["content"][1]["type"],
            "image_url",
        )

    async def test_image_capable_provider_preserves_historical_images(self) -> None:
        context = FakeContext(provider_modalities={"route-provider": ["text", "image"]})
        plugin = LLMRouterPlugin(context, {})
        event = FakeEvent("message")
        event.set_extra(ROUTE_MATCH_EXTRA_KEY, self.make_route_match())
        contexts = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {"type": "image_url", "image_url": {"url": "old-image"}},
                ],
            }
        ]
        request = make_provider_request(contexts=contexts)

        await plugin.apply_route_request(event, request)

        self.assertEqual(len(request.contexts[0]["content"]), 2)

    async def test_model_metadata_can_declare_historical_image_support(self) -> None:
        context = FakeContext(
            provider_modalities={"route-provider": []},
            provider_metadata_modalities={
                "route-provider": ["text", "image"],
            },
        )
        plugin = LLMRouterPlugin(context, {})
        event = FakeEvent("message")
        event.set_extra(ROUTE_MATCH_EXTRA_KEY, self.make_route_match())
        contexts = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {"type": "image_url", "image_url": {"url": "old-image"}},
                ],
            }
        ]
        request = make_provider_request(contexts=contexts)

        await plugin.apply_route_request(event, request)

        self.assertEqual(len(request.contexts[0]["content"]), 2)

    async def test_unconfigured_modalities_preserve_context_for_astrbot(self) -> None:
        context = FakeContext(provider_modalities={"route-provider": []})
        plugin = LLMRouterPlugin(context, {})
        event = FakeEvent("message")
        event.set_extra(ROUTE_MATCH_EXTRA_KEY, self.make_route_match())
        contexts = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {"type": "image_url", "image_url": {"url": "old-image"}},
                ],
            }
        ]
        request = make_provider_request(contexts=contexts)

        await plugin.apply_route_request(event, request)

        self.assertEqual(len(request.contexts[0]["content"]), 2)


if __name__ == "__main__":
    unittest.main()
