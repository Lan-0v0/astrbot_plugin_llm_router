import json
import unittest

from router_core import (
    LLM_JUDGEMENT_METHOD,
    RULE_MATCH_METHOD,
    IdentityContext,
    build_classifier_prompts,
    filter_eligible_routes,
    find_rule_match,
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
) -> dict:
    return {
        "__template_key": "openai_compatible",
        "name": name,
        "enabled": True,
        "api_base_url": "https://example.com/v1",
        "model": "example-model",
        "api_keys": ["test-key"],
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


class RouteParsingTests(unittest.TestCase):
    def test_provider_defaults_are_applied(self) -> None:
        route_entries = parse_route_entries(
            [
                {
                    "__template_key": "deepseek",
                    "name": "default deepseek",
                    "enabled": True,
                }
            ]
        )

        self.assertEqual(route_entries[0].api_base_url, "https://api.deepseek.com")
        self.assertEqual(route_entries[0].model_name, "deepseek-chat")

    def test_disabled_route_is_not_eligible(self) -> None:
        raw_entry = make_route_entry("disabled")
        raw_entry["enabled"] = False
        route_entries = parse_route_entries([raw_entry])

        eligible_routes = filter_eligible_routes(route_entries, IdentityContext())

        self.assertEqual(eligible_routes, ())


if __name__ == "__main__":
    unittest.main()
