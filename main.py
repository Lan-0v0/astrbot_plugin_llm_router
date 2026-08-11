from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.message import (
    AssistantMessageSegment,
    TextPart,
    UserMessageSegment,
)

try:
    from .api_clients import RoutedModelClient
    from .router_core import (
        LLM_JUDGEMENT_METHOD,
        RULE_MATCH_METHOD,
        GenerationInput,
        IdentityContext,
        RouteEntry,
        RouteMatch,
        build_classifier_prompts,
        filter_eligible_routes,
        find_rule_match,
        parse_classification_route_id,
        parse_judgement_methods,
        parse_route_entries,
    )
except (
    ImportError
):  # pragma: no cover - AstrBot may add the plugin directory to sys.path.
    from api_clients import RoutedModelClient
    from router_core import (
        LLM_JUDGEMENT_METHOD,
        RULE_MATCH_METHOD,
        GenerationInput,
        IdentityContext,
        RouteEntry,
        RouteMatch,
        build_classifier_prompts,
        filter_eligible_routes,
        find_rule_match,
        parse_classification_route_id,
        parse_judgement_methods,
        parse_route_entries,
    )


@register(
    "astrbot_plugin_llm_router",
    "Lan-0v0",
    "按规则或 LLM 类型判断将消息路由到指定模型，并支持白名单与黑名单。",
    "0.0.1",
)
class LLMRouterPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._model_client = RoutedModelClient()

    async def initialize(self) -> None:
        logger.info("LLM Router 插件已加载。")

    @filter.on_llm_request()
    async def route_llm_request(
        self,
        event: AstrMessageEvent,
        request: ProviderRequest,
    ) -> None:
        message_text = self._get_message_text(event, request)
        if not message_text:
            return

        judgement_methods = parse_judgement_methods(
            self.config.get("judgement_methods")
        )
        if not judgement_methods:
            return

        route_entries = parse_route_entries(self.config.get("routing_models", []))
        identity_context = self._build_identity_context(event)
        eligible_routes = filter_eligible_routes(route_entries, identity_context)
        if not eligible_routes:
            return

        route_match: RouteMatch | None = None
        if RULE_MATCH_METHOD in judgement_methods:
            route_match = find_rule_match(message_text, eligible_routes)

        if route_match is None and LLM_JUDGEMENT_METHOD in judgement_methods:
            route_match = await self._find_llm_match(message_text, eligible_routes)

        if route_match is None:
            return

        generation_input = self._build_generation_input(request, message_text)
        try:
            response_text = await self._model_client.generate(
                route_match.route_entry,
                generation_input,
            )
        except Exception as error:  # noqa: BLE001 - Fail open to AstrBot's original model.
            logger.warning(
                "路由模型 '%s' 请求失败，将继续使用 AstrBot 原模型。"
                "错误类型：%s，错误：%s",
                route_match.route_entry.name,
                type(error).__name__,
                error,
            )
            return

        response_text = response_text.strip()
        if not response_text:
            logger.warning(
                "路由模型 '%s' 返回空内容，将继续使用 AstrBot 原模型。",
                route_match.route_entry.name,
            )
            return

        try:
            await event.send(event.plain_result(response_text))
        except Exception as error:  # noqa: BLE001 - A send failure must fail open.
            logger.warning(
                "路由结果发送失败，将继续使用 AstrBot 原模型。错误类型：%s，错误：%s",
                type(error).__name__,
                error,
            )
            return

        event.stop_event()
        await self._persist_conversation_pair(event, message_text, response_text)
        logger.info(
            "消息已路由至 '%s'，判断方式=%s，命中项=%s。",
            route_match.route_entry.name,
            route_match.judgement_method,
            route_match.matched_value,
        )

    async def _find_llm_match(
        self,
        message_text: str,
        eligible_routes: tuple[RouteEntry, ...],
    ) -> RouteMatch | None:
        routes_with_types = tuple(
            route_entry for route_entry in eligible_routes if route_entry.content_types
        )
        if not routes_with_types:
            return None

        classifier_provider_id = str(
            self.config.get("type_judgement_provider", "")
        ).strip()
        if not classifier_provider_id:
            logger.warning("已启用 LLM 判断，但尚未选择类型判断 LLM。")
            return None

        classifier_provider = self.context.get_provider_by_id(classifier_provider_id)
        if classifier_provider is None or not hasattr(classifier_provider, "text_chat"):
            logger.warning(
                "找不到可用的类型判断 LLM 提供商 '%s'。",
                classifier_provider_id,
            )
            return None

        system_prompt, user_prompt = build_classifier_prompts(
            message_text,
            routes_with_types,
        )
        try:
            classifier_response = await asyncio.wait_for(
                classifier_provider.text_chat(
                    prompt=user_prompt,
                    contexts=[],
                    system_prompt=system_prompt,
                ),
                timeout=45,
            )
        except Exception as error:  # noqa: BLE001 - Provider adapters expose varied errors.
            logger.warning(
                "类型判断 LLM 调用失败，将继续使用 AstrBot 原模型。"
                "错误类型：%s，错误：%s",
                type(error).__name__,
                error,
            )
            return None

        classifier_response_text = str(
            getattr(classifier_response, "completion_text", "")
        )
        selected_route_id = parse_classification_route_id(
            classifier_response_text,
            routes_with_types,
        )
        if selected_route_id is None:
            return None

        selected_route = next(
            (
                route_entry
                for route_entry in routes_with_types
                if route_entry.route_id == selected_route_id
            ),
            None,
        )
        if selected_route is None:
            return None
        return RouteMatch(
            route_entry=selected_route,
            judgement_method=LLM_JUDGEMENT_METHOD,
            matched_value=selected_route_id,
        )

    @staticmethod
    def _get_message_text(event: AstrMessageEvent, request: ProviderRequest) -> str:
        request_prompt = getattr(request, "prompt", None)
        if request_prompt is not None and str(request_prompt).strip():
            return str(request_prompt).strip()
        return str(getattr(event, "message_str", "")).strip()

    @staticmethod
    def _build_identity_context(event: AstrMessageEvent) -> IdentityContext:
        message_object = getattr(event, "message_obj", None)
        platform_metadata = getattr(event, "platform_meta", None)
        return IdentityContext(
            user_id=LLMRouterPlugin._safe_event_call(event, "get_sender_id"),
            group_id=str(getattr(message_object, "group_id", "") or ""),
            session_id=str(getattr(message_object, "session_id", "") or ""),
            unified_origin=str(getattr(event, "unified_msg_origin", "") or ""),
            sender_name=LLMRouterPlugin._safe_event_call(event, "get_sender_name"),
            platform_id=str(getattr(platform_metadata, "name", "") or ""),
        )

    @staticmethod
    def _safe_event_call(event: AstrMessageEvent, method_name: str) -> str:
        method = getattr(event, method_name, None)
        if not callable(method):
            return ""
        try:
            return str(method() or "")
        except Exception:  # noqa: BLE001 - Platform adapters may raise arbitrary errors.
            return ""

    @staticmethod
    def _build_generation_input(
        request: ProviderRequest,
        fallback_message_text: str,
    ) -> GenerationInput:
        raw_contexts = getattr(request, "contexts", []) or []
        contexts = tuple(
            dict(raw_context)
            for raw_context in raw_contexts
            if isinstance(raw_context, Mapping)
        )
        extra_user_texts = tuple(
            extracted_text
            for raw_content_part in getattr(request, "extra_user_content_parts", [])
            or []
            if (
                extracted_text := LLMRouterPlugin._extract_content_part_text(
                    raw_content_part
                )
            )
        )
        return GenerationInput(
            prompt=str(getattr(request, "prompt", None) or fallback_message_text),
            system_prompt=str(getattr(request, "system_prompt", "") or ""),
            contexts=contexts,
            image_urls=tuple(
                str(item) for item in getattr(request, "image_urls", []) or []
            ),
            audio_urls=tuple(
                str(item) for item in getattr(request, "audio_urls", []) or []
            ),
            extra_user_texts=extra_user_texts,
        )

    @staticmethod
    def _extract_content_part_text(content_part: Any) -> str:
        if isinstance(content_part, Mapping):
            return str(content_part.get("text", "") or "").strip()
        return str(getattr(content_part, "text", "") or "").strip()

    async def _persist_conversation_pair(
        self,
        event: AstrMessageEvent,
        user_text: str,
        assistant_text: str,
    ) -> None:
        try:
            conversation_manager = self.context.conversation_manager
            conversation_id = await conversation_manager.get_curr_conversation_id(
                event.unified_msg_origin
            )
            if not conversation_id:
                return
            await conversation_manager.add_message_pair(
                cid=conversation_id,
                user_message=UserMessageSegment(content=[TextPart(text=user_text)]),
                assistant_message=AssistantMessageSegment(
                    content=[TextPart(text=assistant_text)]
                ),
            )
        except Exception as error:  # noqa: BLE001 - History persistence is best-effort.
            logger.warning(
                "路由回复已发送，但写入 AstrBot 会话历史失败。错误类型：%s，错误：%s",
                type(error).__name__,
                error,
            )

    async def terminate(self) -> None:
        await self._model_client.close()
