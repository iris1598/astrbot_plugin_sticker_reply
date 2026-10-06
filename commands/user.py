"""
用户指令模块 - StickerCommands

提供表情包相关命令：
  - /表情包分类        — 查看当前人格可用的表情包分类与数量
  - /随机表情包 [分类] — 立即发送一张随机表情包（用于验证目录配置）
"""

import random

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent


class StickerCommands:
    """用户指令集合，通过插件主类绑定。"""

    def __init__(self, plugin_instance):
        self._plugin = plugin_instance

    @property
    def plugin(self):
        return self._plugin

    # ── /表情包分类 ────────────────────────────────────────

    async def cmd_categories(self, event: AstrMessageEvent):
        """列出当前人格可用的表情包分类。"""
        plug = self.plugin
        persona_id = await plug.resolve_persona_id(event)
        pconf = plug.get_persona_config(persona_id)

        if not pconf.enabled:
            yield event.plain_result("⚠️ 表情包系统未启用。")
            return

        entries = plug.stickers.describe_categories(
            persona_id=persona_id, dir_name=pconf.sticker_dir_name
        )
        if not entries:
            yield event.plain_result(
                "📭 还没有可用的表情包分类。\n"
                f"把图片放进目录：{plug.stickers.sticker_dir}\\<分类名>\\\n"
                "（支持 jpg / png / gif / webp，无需重载插件）"
            )
            return

        total = sum(count for _, count in entries)
        lines = [f"🧩 可用表情包分类：{len(entries)} 类，共 {total} 张"]
        lines.extend(f"• {name}（{count} 张）" for name, count in entries)
        lines.append("模型会用 [STK:分类名] 标签调用这些分类。")
        yield event.plain_result("\n".join(lines))

    # ── /随机表情包 [分类] ─────────────────────────────────

    async def cmd_random(self, event: AstrMessageEvent):
        """立即发送一张随机表情包；带分类名时只在该分类中挑选。"""
        plug = self.plugin
        persona_id = await plug.resolve_persona_id(event)
        pconf = plug.get_persona_config(persona_id)

        if not pconf.enabled:
            yield event.plain_result("⚠️ 表情包系统未启用。")
            return

        parts = (event.message_str or "").split()
        category = parts[1].strip() if len(parts) >= 2 else ""

        categories = plug.stickers.get_categories(
            persona_id=persona_id, dir_name=pconf.sticker_dir_name
        )
        if not categories:
            yield event.plain_result("📭 还没有可用的表情包分类，请先往表情包目录里放图片。")
            return

        if category and category not in categories:
            yield event.plain_result(
                f"❌ 没有「{category}」这个分类。\n"
                f"可用分类：{', '.join(categories)}"
            )
            return

        if not category:
            category = random.choice(categories)

        img_path = plug.stickers.get_random_sticker(
            category, persona_id=persona_id, dir_name=pconf.sticker_dir_name
        )
        if not img_path:
            yield event.plain_result(f"❌ 分类「{category}」下没有可用图片。")
            return

        logger.info(f"[sticker_reply][{persona_id}] 手动发送表情包: {img_path}")
        yield event.chain_result([Comp.Image.fromFileSystem(str(img_path))])
