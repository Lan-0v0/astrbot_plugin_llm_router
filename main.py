from __future__ import annotations

import asyncio
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
    from .router_core import (
        LLM_JUDGEMENT_METHOD,
        RULE_MATCH_METHOD,
        IdentityContext,
        RouteEntry,
        RouteMatch,
        build_classifier_prompts,
        filter_eligible_routes,
        find_direct_route_match,
        find_rule_match,
        migrate_route_entry_mappings,
        parse_classification_route_id,
        parse_judgement_methods,
        parse_route_entries,
    )
except (
    ImportError
):  # pragma: no cover - AstrBot may add the plugin directory to sys.path.
    from router_core import (
        LLM_JUDGEMENT_METHOD,
        RULE_MATCH_METHOD,
        IdentityContext,
        RouteEntry,
        RouteMatch,
        build_classifier_prompts,
        filter_eligible_routes,
        find_direct_route_match,
        find_rule_match,
        migrate_route_entry_mappings,
        parse_classification_route_id,
        parse_judgement_methods,
        parse_route_entries,
    )


@register(
    "astrbot_plugin_llm_router",
    "Lan-0v0",
    "按规则或 LLM 类型判断将消息路由到指定模型，并支持白名单与黑名单。",
    "0.0.5",
)
class LLMRouterPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config

    async def initialize(self) -> None:
        migrated_entries, configuration_changed = migrate_route_entry_mappings(
            self.config.get("routing_models", [])
        )
        if configuration_changed:
            self.config["routing_models"] = migrated_entries
            save_config = getattr(self.config, "save_config", None)
            if callable(save_config):
                try:
                    save_config()
                except Exception as error:  # noqa: BLE001 - Migration is best-effort.
                    logger.warning(
                        "旧版路由条目已在内存中迁移，但保存配置失败。"
                        "错误类型：%s，错误：%s",
                        type(error).__name__,
                        error,
                    )
            logger.warning(
                "已将路由条目迁移至当前配置格式。"
                "若条目尚未选择 AstrBot 路由模型，请重新选择。"
            )
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
        direct_routing_enabled = bool(
            self.config.get("direct_route_without_match", True)
        )
        whitelist_direct_routing_enabled = direct_routing_enabled and bool(
            self.config.get("whitelist_direct_route", True)
        )
        if not judgement_methods and not direct_routing_enabled:
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

        if route_match is None and direct_routing_enabled:
            whitelist_is_bound = any(
                route_entry.whitelist for route_entry in eligible_routes
            )
            if whitelist_is_bound and whitelist_direct_routing_enabled:
                route_match = find_direct_route_match(
                    eligible_routes,
                    whitelist_only=True,
                )
            elif not whitelist_is_bound:
                route_match = find_direct_route_match(
                    eligible_routes,
                    whitelist_only=False,
                )

        if route_match is None:
            return

        routed_system_prompt = await self._resolve_route_system_prompt(
            route_match.route_entry,
            request.system_prompt,
        )
        try:
            routed_response = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=route_match.route_entry.provider_id,
                    prompt=str(request.prompt or message_text),
                    image_urls=list(request.image_urls or []),
                    audio_urls=list(request.audio_urls or []),
                    contexts=list(request.contexts or []),
                    system_prompt=routed_system_prompt,
                    extra_user_content_parts=list(
                        request.extra_user_content_parts or []
                    ),
                    tool_calls_result=request.tool_calls_result,
                ),
                timeout=90,
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

        response_text = str(getattr(routed_response, "completion_text", "")).strip()
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

        priority_groups: list[list[RouteEntry]] = []
        for route_entry in routes_with_types:
            if (
                not priority_groups
                or priority_groups[-1][0].priority != route_entry.priority
            ):
                priority_groups.append([])
            priority_groups[-1].append(route_entry)

        for priority_group in priority_groups:
            group_routes = tuple(priority_group)
            system_prompt, user_prompt = build_classifier_prompts(
                message_text,
                group_routes,
            )
            try:
                classifier_response = await asyncio.wait_for(
                    self.context.llm_generate(
                        chat_provider_id=classifier_provider_id,
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
                group_routes,
            )
            if selected_route_id is None:
                continue

            selected_route = next(
                (
                    route_entry
                    for route_entry in group_routes
                    if route_entry.route_id == selected_route_id
                ),
                None,
            )
            if selected_route is not None:
                return RouteMatch(
                    route_entry=selected_route,
                    judgement_method=LLM_JUDGEMENT_METHOD,
                    matched_value=selected_route_id,
                )
        return None

    async def _resolve_route_system_prompt(
        self,
        route_entry: RouteEntry,
        current_system_prompt: str | None,
    ) -> str | None:
        persona_id = route_entry.persona_id
        if not persona_id:
            return current_system_prompt

        try:
            persona_manager = self.context.persona_manager
            selected_persona: Any = None

            cached_persona_resolver = getattr(
                persona_manager,
                "get_persona_v3_by_id",
                None,
            )
            if callable(cached_persona_resolver):
                selected_persona = cached_persona_resolver(persona_id)

            if selected_persona is None:
                selected_persona = next(
                    (
                        persona
                        for persona in getattr(persona_manager, "personas_v3", [])
                        if str(persona.get("name", "")).strip() == persona_id
                    ),
                    None,
                )

            if selected_persona is None and persona_id.casefold() == "default":
                from astrbot.core.persona_mgr import DEFAULT_PERSONALITY

                selected_persona = DEFAULT_PERSONALITY

            if selected_persona is None:
                database_persona_getter = getattr(
                    persona_manager,
                    "get_persona",
                    None,
                )
                if callable(database_persona_getter):
                    selected_persona = await database_persona_getter(persona_id)

            persona_prompt = self._extract_persona_prompt(selected_persona)
        except Exception as error:  # noqa: BLE001 - Persona lookup is best-effort.
            logger.warning(
                "路由条目 '%s' 的人格 '%s' 读取失败，将沿用 AstrBot 当前人格。"
                "错误类型：%s，错误：%s",
                route_entry.name,
                persona_id,
                type(error).__name__,
                error,
            )
            return current_system_prompt

        if not persona_prompt:
            logger.warning(
                "路由条目 '%s' 选择的人格 '%s' 不存在或提示词为空，"
                "将沿用 AstrBot 当前人格。",
                route_entry.name,
                persona_id,
            )
            return current_system_prompt
        return persona_prompt

    @staticmethod
    def _extract_persona_prompt(persona: Any) -> str:
        if persona is None:
            return ""
        if isinstance(persona, dict):
            return str(persona.get("prompt", "")).strip()
        return str(getattr(persona, "system_prompt", "")).strip()

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
