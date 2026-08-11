import json
import unittest

from router_core import (
    LLM_JUDGEMENT_METHOD,
    RULE_MATCH_METHOD,
    IdentityContext,
    build_classifier_prompts,
    filter_eligible_routes,
    find_rule_match,
    migrate_route_entry_mappings,
    normalize_priority,
    parse_classification_route_id,
    parse_judgement_methods,
    parse_route_entries,
)


def make_route_entry(
    name: str,
    *,
    content_types: list[str] | None = None,
    rule_keywords: list[str] | None = None,
    whitelist: list[str] | None = None,
    blacklist: list[str] | None = None,
    route_provider: str = "selected-provider",
    route_persona: str = "",
    priority: int = 100,
) -> dict:
    return {
        "__template_key": "route",
        "name": name,
        "enabled": True,
        "route_provider": route_provider,
        "route_persona": route_persona,
        "priority": priority,
        "content_types": content_types or [],
        "rule_keywords": rule_keywords or [],
        "whitelist": whitelist or [],
        "blacklist": blacklist or [],
    }


class JudgementMethodTests(unittest.TestCase):
    def test_empty_configuration_enables_both_methods(self) -> None:
        self.assertEqual(
            parse_judgement_methods(None),
            frozenset({RULE_MATCH_METHOD, LLM_JUDGEMENT_METHOD}),
        )

    def test_chinese_checkbox_values_are_parsed(self) -> None:
        self.assertEqual(
            parse_judgement_methods(["规则匹配", "LLM判断"]),
            frozenset({RULE_MATCH_METHOD, LLM_JUDGEMENT_METHOD}),
        )

    def test_unchecking_every_method_disables_routing(self) -> None:
        self.assertEqual(parse_judgement_methods([]), frozenset())


class RuleRoutingTests(unittest.TestCase):
    def test_higher_priority_rule_match_wins_even_when_listed_later(self) -> None:
        route_entries = parse_route_entries(
            [
                make_route_entry("lower", rule_keywords=["方程"], priority=10),
                make_route_entry("higher", rule_keywords=["方程"], priority=90),
            ]
        )
        eligible_routes = filter_eligible_routes(route_entries, IdentityContext())

        route_match = find_rule_match("请帮我解这个方程", eligible_routes)

        self.assertIsNotNone(route_match)
        assert route_match is not None
        self.assertEqual(route_match.route_entry.name, "higher")

    def test_first_matching_route_wins(self) -> None:
        route_entries = parse_route_entries(
            [
                make_route_entry("first", rule_keywords=["方程"]),
                make_route_entry("second", rule_keywords=["方程"]),
            ]
        )

        route_match = find_rule_match("请帮我解这个方程", route_entries)

        self.assertIsNotNone(route_match)
        assert route_match is not None
        self.assertEqual(route_match.route_entry.name, "first")
        self.assertEqual(route_match.matched_value, "方程")

    def test_english_rule_matching_is_case_insensitive(self) -> None:
        route_entries = parse_route_entries(
            [make_route_entry("greeting", rule_keywords=["Hello"])]
        )

        route_match = find_rule_match("HELLO there", route_entries)

        self.assertIsNotNone(route_match)


class AccessListTests(unittest.TestCase):
    def test_blacklist_overrides_whitelist(self) -> None:
        route_entries = parse_route_entries(
            [
                make_route_entry(
                    "restricted",
                    whitelist=["user:10001"],
                    blacklist=["10001"],
                )
            ]
        )
        identity_context = IdentityContext(user_id="10001")

        eligible_routes = filter_eligible_routes(route_entries, identity_context)

        self.assertEqual(eligible_routes, ())

    def test_nonempty_whitelist_requires_a_match(self) -> None:
        route_entries = parse_route_entries(
            [make_route_entry("group-only", whitelist=["group:20002"])]
        )

        denied_routes = filter_eligible_routes(
            route_entries,
            IdentityContext(user_id="10001", group_id="30003"),
        )
        allowed_routes = filter_eligible_routes(
            route_entries,
            IdentityContext(user_id="10001", group_id="20002"),
        )

        self.assertEqual(denied_routes, ())
        self.assertEqual(len(allowed_routes), 1)

    def test_whitelist_match_binds_user_and_excludes_public_routes(self) -> None:
        route_entries = parse_route_entries(
            [
                make_route_entry("public", priority=100),
                make_route_entry(
                    "bound",
                    whitelist=["user:10001"],
                    priority=10,
                ),
            ]
        )

        eligible_routes = filter_eligible_routes(
            route_entries,
            IdentityContext(user_id="10001"),
        )

        self.assertEqual([route.name for route in eligible_routes], ["bound"])

    def test_multiple_matching_whitelists_are_sorted_by_priority(self) -> None:
        route_entries = parse_route_entries(
            [
                make_route_entry(
                    "lower",
                    whitelist=["user:10001"],
                    priority=20,
                ),
                make_route_entry(
                    "higher",
                    whitelist=["user:10001"],
                    priority=80,
                ),
            ]
        )

        eligible_routes = filter_eligible_routes(
            route_entries,
            IdentityContext(user_id="10001"),
        )

        self.assertEqual(
            [route.name for route in eligible_routes],
            ["higher", "lower"],
        )

    def test_equal_priorities_preserve_panel_order(self) -> None:
        route_entries = parse_route_entries(
            [
                make_route_entry("first", priority=50),
                make_route_entry("second", priority=50),
            ]
        )

        eligible_routes = filter_eligible_routes(route_entries, IdentityContext())

        self.assertEqual(
            [route.name for route in eligible_routes],
            ["first", "second"],
        )

    def test_name_matching_requires_explicit_prefix(self) -> None:
        route_entries = parse_route_entries(
            [make_route_entry("named", whitelist=["name:Alice"])]
        )

        eligible_routes = filter_eligible_routes(
            route_entries,
            IdentityContext(sender_name="alice"),
        )

        self.assertEqual(len(eligible_routes), 1)


class LLMClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.route_entries = parse_route_entries(
            [
                make_route_entry("math", content_types=["数学问题", "方程"]),
                make_route_entry("history", content_types=["历史问题"]),
            ]
        )

    def test_json_response_selects_valid_route(self) -> None:
        response_text = '```json\n{"route_id":"route_1","matched_type":"历史问题"}\n```'

        selected_route_id = parse_classification_route_id(
            response_text,
            self.route_entries,
        )

        self.assertEqual(selected_route_id, "route_1")

    def test_null_response_keeps_astrbot_original_model(self) -> None:
        selected_route_id = parse_classification_route_id(
            '{"route_id":null,"matched_type":null}',
            self.route_entries,
        )

        self.assertIsNone(selected_route_id)

    def test_unknown_route_is_rejected(self) -> None:
        selected_route_id = parse_classification_route_id(
            '{"route_id":"route_999","matched_type":"数学问题"}',
            self.route_entries,
        )

        self.assertIsNone(selected_route_id)

    def test_classifier_prompt_contains_structured_catalog_and_message(self) -> None:
        system_prompt, user_prompt = build_classifier_prompts(
            "三国时期发生了什么？",
            self.route_entries,
        )
        parsed_user_prompt = json.loads(user_prompt)

        self.assertIn("只输出一个紧凑 JSON", system_prompt)
        self.assertEqual(parsed_user_prompt["message"], "三国时期发生了什么？")
        self.assertEqual(
            parsed_user_prompt["candidate_routes"][1]["types"],
            ["历史问题"],
        )
        self.assertEqual(parsed_user_prompt["candidate_routes"][0]["priority"], 100)
        self.assertIn("priority 数值最大的候选", system_prompt)


class RouteParsingTests(unittest.TestCase):
    def test_priority_is_clamped_to_supported_range(self) -> None:
        self.assertEqual(normalize_priority(101), 100)
        self.assertEqual(normalize_priority(-1), 0)
        self.assertEqual(normalize_priority("75"), 75)
        self.assertEqual(normalize_priority("invalid"), 100)

    def test_migration_normalizes_existing_priority(self) -> None:
        current_entry = make_route_entry("invalid priority")
        current_entry["priority"] = 999

        migrated_entries, configuration_changed = migrate_route_entry_mappings(
            [current_entry]
        )

        self.assertTrue(configuration_changed)
        self.assertEqual(migrated_entries[0]["priority"], 100)

    def test_migration_adds_persona_default_to_existing_route(self) -> None:
        current_entry = make_route_entry("v0.0.2 route")
        del current_entry["route_persona"]

        migrated_entries, configuration_changed = migrate_route_entry_mappings(
            [current_entry]
        )

        self.assertTrue(configuration_changed)
        self.assertEqual(migrated_entries[0]["route_persona"], "")

    def test_legacy_route_migration_removes_credentials(self) -> None:
        migrated_entries, configuration_changed = migrate_route_entry_mappings(
            [
                {
                    "__template_key": "deepseek",
                    "name": "legacy route",
                    "enabled": True,
                    "api_base_url": "https://api.deepseek.com",
                    "api_keys": ["secret-key"],
                    "model": "deepseek-chat",
                    "content_types": ["数学问题"],
                    "rule_keywords": ["方程"],
                }
            ]
        )

        self.assertTrue(configuration_changed)
        self.assertEqual(migrated_entries[0]["__template_key"], "route")
        self.assertEqual(migrated_entries[0]["route_provider"], "")
        self.assertEqual(migrated_entries[0]["route_persona"], "")
        self.assertEqual(migrated_entries[0]["priority"], 100)
        self.assertNotIn("api_base_url", migrated_entries[0])
        self.assertNotIn("api_keys", migrated_entries[0])
        self.assertNotIn("model", migrated_entries[0])

    def test_current_route_migration_is_idempotent(self) -> None:
        current_entry = make_route_entry("current")

        migrated_entries, configuration_changed = migrate_route_entry_mappings(
            [current_entry]
        )

        self.assertFalse(configuration_changed)
        self.assertEqual(migrated_entries, [current_entry])

    def test_selected_astrbot_provider_is_parsed(self) -> None:
        route_entries = parse_route_entries([make_route_entry("selected")])

        self.assertEqual(route_entries[0].provider_id, "selected-provider")

    def test_selected_astrbot_persona_is_parsed(self) -> None:
        route_entries = parse_route_entries(
            [make_route_entry("selected", route_persona="math-expert")]
        )

        self.assertEqual(route_entries[0].persona_id, "math-expert")

    def test_route_without_selected_provider_is_not_eligible(self) -> None:
        route_entries = parse_route_entries(
            [make_route_entry("missing provider", route_provider="")]
        )

        eligible_routes = filter_eligible_routes(route_entries, IdentityContext())

        self.assertEqual(eligible_routes, ())

    def test_disabled_route_is_not_eligible(self) -> None:
        raw_entry = make_route_entry("disabled")
        raw_entry["enabled"] = False
        route_entries = parse_route_entries([raw_entry])

        eligible_routes = filter_eligible_routes(route_entries, IdentityContext())

        self.assertEqual(eligible_routes, ())


if __name__ == "__main__":
    unittest.main()
