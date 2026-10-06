"""
表情包管理模块 - StickerManager

管理本地表情包目录，支持按分类随机选取图片。

目录结构示例：
  stickers/
    ├── default/           (默认/通用人格表情包，或直接放在 stickers/ 根目录)
    │     └── 开心/
    └── neko/              (人格 neko 的独立表情包目录)
          ├── 撒娇/
          └── 傲娇/

另外支持一个可选的 fallback 目录：当主目录下找不到分类时，自动回退到
fallback 目录查找（用于兼容旧插件 astrbot_plugin_favorability 的表情包目录）。
"""

import random
from pathlib import Path
from typing import Optional

# 支持的表情包文件扩展名
STICKER_EXTENSIONS = (".jpg", ".png", ".gif", ".webp")


class StickerManager:
    """管理本地表情包目录，按人格子目录与分类文件夹组织。"""

    def __init__(
        self,
        sticker_dir: Path,
        fallback_dir: Optional[Path] = None,
        create: bool = True,
    ):
        self.sticker_dir = Path(sticker_dir)
        if create:
            self.sticker_dir.mkdir(parents=True, exist_ok=True)

        # 回退目录只读使用，绝不主动创建，避免凭空生成旧插件的数据目录
        fallback = Path(fallback_dir) if fallback_dir else None
        if fallback is not None and fallback != self.sticker_dir:
            self._fallback: Optional[StickerManager] = StickerManager(
                fallback, create=False
            )
        else:
            self._fallback = None

    # ── 路径解析 ───────────────────────────────────────────

    def resolve_persona_dir(
        self, persona_id: str = "default", dir_name: Optional[str] = None
    ) -> Path:
        """解析人格对应的表情包子目录路径。"""
        sub_name = (dir_name or "").strip() or (persona_id or "").strip() or "default"
        if sub_name == "default":
            # 如果存在 stickers/default/ 优先使用，否则使用 stickers/ 根目录
            default_sub = self.sticker_dir / "default"
            if default_sub.exists() and default_sub.is_dir():
                return default_sub
            return self.sticker_dir
        return self.sticker_dir / sub_name

    def resolve_category_dir(
        self, category: str, persona_id: str = "default", dir_name: Optional[str] = None
    ) -> Path:
        """返回分类目录路径（优先人格专属目录，其次默认目录，最后回退目录）。"""
        p_dir = self.resolve_persona_dir(persona_id, dir_name)
        cat_path = p_dir / category
        if self._has_files(cat_path):
            return cat_path

        default_dir = self.resolve_persona_dir("default")
        if default_dir != p_dir:
            default_cat = default_dir / category
            if self._has_files(default_cat):
                return default_cat

        if self._fallback is not None:
            return self._fallback.resolve_category_dir(category, persona_id, dir_name)

        return cat_path

    # ── 查询接口 ───────────────────────────────────────────

    def get_categories(
        self, persona_id: str = "default", dir_name: Optional[str] = None
    ) -> list[str]:
        """返回指定人格所有分类名（子目录名），不存在时回退到默认表情包目录。"""
        cats = self._get_categories_local(persona_id, dir_name)
        if cats:
            return cats
        if self._fallback is not None:
            return self._fallback._get_categories_local(persona_id, dir_name)
        return []

    def count_stickers(
        self, category: str, persona_id: str = "default", dir_name: Optional[str] = None
    ) -> int:
        """统计某分类下可用的图片数量。"""
        return len(self._list_files(self.resolve_category_dir(category, persona_id, dir_name)))

    def describe_categories(
        self, persona_id: str = "default", dir_name: Optional[str] = None
    ) -> list[tuple[str, int]]:
        """返回 [(分类名, 图片数量), ...]，按分类名排序。"""
        return [
            (name, self.count_stickers(name, persona_id, dir_name))
            for name in self.get_categories(persona_id, dir_name)
        ]

    def get_random_sticker(
        self,
        category: str,
        persona_id: str = "default",
        dir_name: Optional[str] = None,
    ) -> Optional[Path]:
        """从指定分类随机返回一张表情包的绝对路径。

        优先从人格专属目录读取，为空或不存在时回退默认目录，最后回退到
        fallback 目录（旧插件数据目录）。
        """
        # 1. 优先从人格专属目录查找
        p_dir = self.resolve_persona_dir(persona_id, dir_name)
        cat_path = p_dir / category
        files = self._list_files(cat_path)
        if files:
            return random.choice(files).resolve()

        # 2. 回退到默认目录查找
        default_dir = self.resolve_persona_dir("default")
        if default_dir != p_dir:
            files = self._list_files(default_dir / category)
            if files:
                return random.choice(files).resolve()

        # 3. 回退到 fallback 目录（旧插件数据目录）
        if self._fallback is not None:
            return self._fallback.get_random_sticker(
                category, persona_id=persona_id, dir_name=dir_name
            )

        return None

    # ── 内部工具 ───────────────────────────────────────────

    def _get_categories_local(
        self, persona_id: str = "default", dir_name: Optional[str] = None
    ) -> list[str]:
        """仅在本目录内查找分类，不回退 fallback。"""
        p_dir = self.resolve_persona_dir(persona_id, dir_name)
        if p_dir.exists() and p_dir.is_dir():
            cats = [d.name for d in p_dir.iterdir() if d.is_dir()]
            if cats:
                return sorted(cats)

        # 回退检查默认目录
        default_dir = self.resolve_persona_dir("default")
        if default_dir.exists() and default_dir.is_dir() and default_dir != p_dir:
            return sorted([d.name for d in default_dir.iterdir() if d.is_dir()])

        return []

    @staticmethod
    def _list_files(cat_path: Path) -> list[Path]:
        """列出分类目录下的所有表情包文件。"""
        if not cat_path.exists() or not cat_path.is_dir():
            return []
        return [
            f
            for f in cat_path.iterdir()
            if f.is_file() and f.suffix.lower() in STICKER_EXTENSIONS
        ]

    @staticmethod
    def _has_files(cat_path: Path) -> bool:
        return bool(StickerManager._list_files(cat_path))
