"""StickerPromptManager 与 STK 标签工具单元测试。"""

import json
import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PLUGIN_ROOT.parent
for _p in (str(WORKSPACE_ROOT), str(PLUGIN_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from astrbot_plugin_sticker_reply.services.prompt import (  # noqa: E402
    DEFAULT_STICKER_CONDITION,
    OLD_STICKER_CONDITION,
    RE_STK,
    STICKER_SYSTEM_PROMPT_TPL,
    StickerPromptManager,
    clean_sticker_tags,
    extract_sticker_categories,
    validate_stk_category,
)


class StickerTagTests(unittest.TestCase):
    def test_tag_variants_are_recognized(self):
        for tag, expected in (
            ("[STK:开心]", "开心"),
            ("[STK:happy]", "happy"),
            ("[stk:HAPPY]", "HAPPY"),
            ("[STK：撒娇]", "撒娇"),
            ("**[STK:angry]**", "angry"),
            ("【STK:傲娇】", "傲娇"),
            ("[STK:cry_1]", "cry_1"),
        ):
            m = RE_STK.search(f"回复正文\n{tag}")
            self.assertIsNotNone(m, tag)
            self.assertEqual(m.group(1).strip(), expected, tag)

    def test_invalid_categories_are_rejected(self):
        self.assertFalse(validate_stk_category(""))
        self.assertFalse(validate_stk_category("一" * 31))
        self.assertFalse(validate_stk_category("开心/难过"))
        self.assertFalse(validate_stk_category("../etc"))
        self.assertTrue(validate_stk_category("一" * 30))
        self.assertTrue(validate_stk_category("happy_1"))

    def test_extract_categories_dedupes_and_keeps_order(self):
        text = "[STK:开心] 你好 [STK:难过] 再见 [STK:开心]"
        self.assertEqual(extract_sticker_categories(text), ["开心", "难过"])

    def test_clean_removes_only_sticker_tags(self):
        text = "你好呀\n[FAV:+2]\n[STK:开心]\n[EVAL:有趣]\n[MUTE:60]"
        cleaned = clean_sticker_tags(text)
        self.assertEqual(cleaned, "你好呀\n[FAV:+2]\n[EVAL:有趣]\n[MUTE:60]")
        self.assertNotIn("STK", cleaned)

    def test_clean_collapses_extra_blank_lines(self):
        text = "第一行\n\n\n[STK:开心]\n\n第二行"
        self.assertEqual(clean_sticker_tags(text), "第一行\n第二行")

    def test_clean_handles_empty_text(self):
        self.assertEqual(clean_sticker_tags(""), "")
        self.assertEqual(clean_sticker_tags(None), None)


class StickerPromptTests(unittest.TestCase):
    def test_prompt_contains_condition_and_categories(self):
        prompt = StickerPromptManager.build_static_prompt(
            categories=["开心", "难过"],
            sticker_condition="仅在用户主动庆祝时发送",
            prompt_preset="custom",
        )
        self.assertIn("[STK:分类名]", prompt)
        self.assertIn("发送条件：仅在用户主动庆祝时发送", prompt)
        self.assertIn("可用分类：开心, 难过", prompt)

    def test_empty_condition_falls_back_to_default(self):
        prompt = StickerPromptManager.build_static_prompt(
            categories=["开心"], sticker_condition="", prompt_preset="custom"
        )
        self.assertIn(DEFAULT_STICKER_CONDITION, prompt)

    def test_presets_select_expected_condition(self):
        default_prompt = StickerPromptManager.build_static_prompt(
            categories=["开心"], prompt_preset="default"
        )
        old_prompt = StickerPromptManager.build_static_prompt(
            categories=["开心"], prompt_preset="old"
        )
        self.assertIn(DEFAULT_STICKER_CONDITION, default_prompt)
        self.assertIn(OLD_STICKER_CONDITION, old_prompt)
        self.assertNotIn(OLD_STICKER_CONDITION, default_prompt)

    def test_no_categories_means_no_prompt(self):
        """没有任何分类时不注入提示词，避免模型虚构分类。"""
        self.assertEqual(
            StickerPromptManager.build_static_prompt(categories=[], enabled=True), ""
        )
        self.assertEqual(
            StickerPromptManager.build_static_prompt(categories=None, enabled=True), ""
        )

    def test_disabled_returns_empty(self):
        self.assertEqual(
            StickerPromptManager.build_static_prompt(
                categories=["开心"], enabled=False
            ),
            "",
        )

    def test_custom_template_placeholders_are_replaced(self):
        prompt = StickerPromptManager.build_static_prompt(
            categories=["开心"],
            sticker_condition="只在庆祝时发送",
            prompt_preset="custom",
            sticker_prompt_core="自定义规则：{sticker_condition} | 分类：{categories}",
        )
        self.assertEqual(prompt, "自定义规则：只在庆祝时发送 | 分类：开心")

    def test_custom_template_without_placeholders_gets_appended(self):
        prompt = StickerPromptManager.build_static_prompt(
            categories=["开心"],
            sticker_condition="只在庆祝时发送",
            prompt_preset="custom",
            sticker_prompt_core="自定义规则",
        )
        self.assertIn("自定义规则", prompt)
        self.assertIn("当前发送条件：只在庆祝时发送", prompt)
        self.assertIn("可用分类：开心", prompt)

    def test_empty_custom_template_falls_back_to_builtin(self):
        prompt = StickerPromptManager.build_static_prompt(
            categories=["开心"], prompt_preset="custom", sticker_prompt_core="   "
        )
        self.assertIn(STICKER_SYSTEM_PROMPT_TPL.split("\n")[0], prompt)


class ConfigSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(
            (PLUGIN_ROOT / "_conf_schema.json").read_text(encoding="utf-8")
        )

    def test_groups_and_keys(self):
        expected_groups = {
            "feature_settings": [
                "enabled",
                "send_delay",
                "max_per_reply",
                "legacy_fallback",
                "sticker_root",
            ],
            "prompt_settings": [
                "prompt_preset",
                "sticker_condition",
                "sticker_prompt_core",
            ],
            "persona_settings": ["persona_overrides"],
        }
        for group, keys in expected_groups.items():
            self.assertEqual(self.schema[group]["type"], "object")
            self.assertEqual(list(self.schema[group]["items"]), keys)

    def test_prompt_items_are_gated_by_custom_preset(self):
        for key in ("sticker_condition", "sticker_prompt_core"):
            item = self.schema["prompt_settings"]["items"][key]
            self.assertEqual(item["type"], "text")
            self.assertTrue(item["default"])
            self.assertEqual(item["condition"], {"prompt_preset": "custom"})

    def test_prompt_preset_options(self):
        item = self.schema["prompt_settings"]["items"]["prompt_preset"]
        self.assertEqual(item["type"], "string")
        self.assertEqual(item["default"], "default")
        self.assertEqual(item["options"], ["default", "old", "custom"])

    def test_feature_defaults(self):
        items = self.schema["feature_settings"]["items"]
        self.assertTrue(items["enabled"]["default"])
        self.assertEqual(items["send_delay"]["type"], "float")
        self.assertEqual(items["send_delay"]["default"], 0.5)
        self.assertEqual(items["max_per_reply"]["type"], "int")
        self.assertEqual(items["max_per_reply"]["default"], 3)
        self.assertTrue(items["legacy_fallback"]["default"])
        self.assertEqual(items["sticker_root"]["default"], "")

    def test_persona_override_template(self):
        override = self.schema["persona_settings"]["items"]["persona_overrides"]
        self.assertEqual(override["type"], "template_list")
        template = override["templates"]["persona_override"]
        self.assertEqual(template["display_item"], "persona_id")
        self.assertEqual(
            list(template["items"]),
            [
                "persona_id",
                "enabled",
                "sticker_dir_name",
                "prompt_preset",
                "sticker_condition",
                "sticker_prompt_core",
            ],
        )
        self.assertEqual(template["items"]["persona_id"]["_special"], "select_persona")


if __name__ == "__main__":
    unittest.main()
