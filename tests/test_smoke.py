import json
import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PluginSmokeTests(unittest.TestCase):
    def test_configuration_schema_is_valid_and_contains_all_route_templates(
        self,
    ) -> None:
        schema_path = PROJECT_ROOT / "_conf_schema.json"

        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(
            schema["judgement_methods"]["default"],
            ["规则匹配", "LLM判断"],
        )
        self.assertEqual(
            set(schema["routing_models"]["templates"]),
            {"openai_compatible", "gemini", "deepseek", "zhipu"},
        )
        for route_template in schema["routing_models"]["templates"].values():
            template_items = route_template["items"]
            self.assertIn("model", template_items)
            self.assertIn("content_types", template_items)
            self.assertIn("rule_keywords", template_items)
            self.assertIn("whitelist", template_items)
            self.assertIn("blacklist", template_items)

    def test_required_plugin_files_exist(self) -> None:
        required_files = {
            ".gitattributes",
            ".github/workflows/ci.yml",
            ".github/workflows/release.yml",
            "main.py",
            "router_core.py",
            "api_clients.py",
            "metadata.yaml",
            "_conf_schema.json",
            "requirements.txt",
            "README.md",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "LICENSE",
        }

        missing_files = [
            file_name
            for file_name in required_files
            if not (PROJECT_ROOT / file_name).is_file()
        ]

        self.assertEqual(missing_files, [])

    def test_release_version_is_consistent(self) -> None:
        metadata_text = (PROJECT_ROOT / "metadata.yaml").read_text(encoding="utf-8")
        main_text = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        changelog_text = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        metadata_version_match = re.search(
            r"^version:\s*(v\d+\.\d+\.\d+)\s*$",
            metadata_text,
            flags=re.MULTILINE,
        )

        self.assertIsNotNone(metadata_version_match)
        assert metadata_version_match is not None
        self.assertEqual(metadata_version_match.group(1), "v0.0.1")
        self.assertIn('"0.0.1",', main_text)
        self.assertIn("## [v0.0.1]", changelog_text)

    def test_metadata_contains_public_repository_information(self) -> None:
        metadata_text = (PROJECT_ROOT / "metadata.yaml").read_text(encoding="utf-8")

        self.assertIn("author: Lan-0v0", metadata_text)
        self.assertIn(
            "repo: https://github.com/Lan-0v0/astrbot_plugin_llm_router",
            metadata_text,
        )


if __name__ == "__main__":
    unittest.main()
