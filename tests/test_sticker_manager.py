"""StickerManager 单元测试：目录结构、人格隔离、随机取图与旧目录回退。"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PLUGIN_ROOT.parent
for _p in (str(WORKSPACE_ROOT), str(PLUGIN_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from astrbot_plugin_sticker_reply.services.sticker import (  # noqa: E402
    STICKER_EXTENSIONS,
    StickerManager,
)


class StickerManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.base = Path(self.temp_dir)
        self.stickers_dir = self.base / "stickers"
        self.stickers_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def _make_file(path: Path, content: str = "dummy") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    # ── 基础行为 ───────────────────────────────────────────

    def test_root_dir_is_created(self):
        target = self.base / "new_root"
        self.assertFalse(target.exists())
        StickerManager(target)
        self.assertTrue(target.is_dir())

    def test_fallback_dir_is_never_created(self):
        missing = self.base / "legacy_stickers"
        StickerManager(self.stickers_dir, fallback_dir=missing)
        self.assertFalse(missing.exists())

    def test_get_categories_returns_empty_for_empty_dir(self):
        self.assertEqual(StickerManager(self.stickers_dir).get_categories(), [])

    def test_fallback_to_root_when_no_persona_subfolder(self):
        """没有专属子目录时，所有人格都回退到根目录的分类。"""
        self._make_file(self.stickers_dir / "happy" / "1.jpg")

        sticker_mgr = StickerManager(self.stickers_dir)
        self.assertIn("happy", sticker_mgr.get_categories(persona_id="default"))
        self.assertIn("happy", sticker_mgr.get_categories(persona_id="other_persona"))

    def test_persona_subfolder_isolation(self):
        """存在人格专属子目录时优先使用专属表情包。"""
        self._make_file(self.stickers_dir / "default" / "happy" / "normal.jpg")
        self._make_file(self.stickers_dir / "tsundere" / "angry" / "tsun.jpg")

        sticker_mgr = StickerManager(self.stickers_dir)

        self.assertEqual(sticker_mgr.get_categories(persona_id="tsundere"), ["angry"])
        self.assertEqual(sticker_mgr.get_categories(persona_id="default"), ["happy"])

    def test_custom_dir_name(self):
        """支持配置 sticker_dir_name 指向自定义目录。"""
        self._make_file(self.stickers_dir / "custom_pack" / "shy" / "shy.jpg")

        sticker_mgr = StickerManager(self.stickers_dir)
        self.assertEqual(
            sticker_mgr.get_categories(persona_id="maid", dir_name="custom_pack"),
            ["shy"],
        )

    # ── 取图 ───────────────────────────────────────────────

    def test_get_random_sticker_returns_absolute_path(self):
        target = self._make_file(self.stickers_dir / "开心" / "a.png")
        img = StickerManager(self.stickers_dir).get_random_sticker("开心")
        self.assertIsNotNone(img)
        self.assertTrue(img.is_absolute())
        self.assertEqual(img, target.resolve())

    def test_get_random_sticker_falls_back_to_default_dir(self):
        """人格目录下没有该分类时，回退到 default 目录取图。"""
        self._make_file(self.stickers_dir / "default" / "开心" / "a.png")
        self._make_file(self.stickers_dir / "neko" / "撒娇" / "b.png")

        sticker_mgr = StickerManager(self.stickers_dir)
        img = sticker_mgr.get_random_sticker("开心", persona_id="neko")
        self.assertIsNotNone(img)
        self.assertEqual(img.parent.name, "开心")

    def test_get_random_sticker_returns_none_for_unknown_category(self):
        self.assertIsNone(StickerManager(self.stickers_dir).get_random_sticker("不存在"))

    def test_unsupported_extensions_are_ignored(self):
        self._make_file(self.stickers_dir / "开心" / "note.txt")
        sticker_mgr = StickerManager(self.stickers_dir)
        self.assertIsNone(sticker_mgr.get_random_sticker("开心"))
        self.assertEqual(sticker_mgr.count_stickers("开心"), 0)

    def test_supported_extensions_are_recognized(self):
        for i, ext in enumerate(STICKER_EXTENSIONS):
            self._make_file(self.stickers_dir / "mix" / f"{i}{ext}")
        sticker_mgr = StickerManager(self.stickers_dir)
        self.assertEqual(sticker_mgr.count_stickers("mix"), len(STICKER_EXTENSIONS))
        self.assertIsNotNone(sticker_mgr.get_random_sticker("mix"))

    # ── 统计 ───────────────────────────────────────────────

    def test_describe_categories_reports_counts(self):
        self._make_file(self.stickers_dir / "b" / "1.jpg")
        self._make_file(self.stickers_dir / "a" / "1.jpg")
        self._make_file(self.stickers_dir / "a" / "2.png")

        entries = StickerManager(self.stickers_dir).describe_categories()
        self.assertEqual(entries, [("a", 2), ("b", 1)])

    # ── 旧插件目录回退 ─────────────────────────────────────

    def test_fallback_dir_used_when_primary_has_no_category(self):
        legacy = self.base / "astrbot_plugin_favorability" / "stickers"
        self._make_file(legacy / "开心" / "old.png")

        sticker_mgr = StickerManager(self.stickers_dir, fallback_dir=legacy)
        self.assertEqual(sticker_mgr.get_categories(), ["开心"])
        img = sticker_mgr.get_random_sticker("开心")
        self.assertIsNotNone(img)
        self.assertEqual(img.parent.parent.parent.name, "astrbot_plugin_favorability")

    def test_primary_dir_wins_over_fallback_dir(self):
        legacy = self.base / "astrbot_plugin_favorability" / "stickers"
        self._make_file(legacy / "旧分类" / "old.png")
        self._make_file(self.stickers_dir / "新分类" / "new.png")

        sticker_mgr = StickerManager(self.stickers_dir, fallback_dir=legacy)
        self.assertEqual(sticker_mgr.get_categories(), ["新分类"])

    def test_fallback_supports_persona_subfolders(self):
        legacy = self.base / "astrbot_plugin_favorability" / "stickers"
        self._make_file(legacy / "neko" / "撒娇" / "old.png")

        sticker_mgr = StickerManager(self.stickers_dir, fallback_dir=legacy)
        self.assertEqual(sticker_mgr.get_categories(persona_id="neko"), ["撒娇"])
        self.assertIsNotNone(
            sticker_mgr.get_random_sticker("撒娇", persona_id="neko")
        )

    def test_fallback_ignored_when_same_as_primary(self):
        self._make_file(self.stickers_dir / "开心" / "a.png")
        sticker_mgr = StickerManager(self.stickers_dir, fallback_dir=self.stickers_dir)
        self.assertIsNone(sticker_mgr._fallback)
        self.assertEqual(sticker_mgr.get_categories(), ["开心"])


if __name__ == "__main__":
    unittest.main()
