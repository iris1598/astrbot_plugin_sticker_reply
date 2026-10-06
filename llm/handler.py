"""
LLM 请求/响应处理模块 - StickerHandler

职责：
1. on_llm_request：向 LLM 注入表情包机制规则与当前人格可用分类（静态 → system_prompt）
2. on_llm_response：解析回复中的 [STK:分类名] 标签，移除标签并异步补发对应表情包图片

设计说明：
  - 只处理 STK 标签，不会触碰好感度插件的 FAV/EVAL/REL/MUTE 标签，因此与
    astrbot_plugin_favorability 同时启用时互不干扰（两个钩子的执行顺序无关）。
  - 无论表情包开关是否开启，都会先把 STK 标签从正文中移除，避免内部标签泄漏给用户。
"""

import asyncio

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.provider import LLMResponse, ProviderRequest

from ..services.prompt import (
    RE_STK,
    StickerPromptManager,
    clean_sticker_tags,
    extract_sticker_categories,
)


class StickerHandler:
    """封装表情包提示词注入和响应解析逻辑。"""

    def __init__(self, plugin_instance):
        # 以弱引用方式持有插件实例，避免循环引用
        self._plugin = plugin_instance

    @property
    def plugin(self):
        return self._plugin

    # ── on_llm_request ─────────────────────────────────────

    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """向 LLM 注入表情包机制规则与可用分类。"""
        plug = self.plugin
        persona_id = await plug.resolve_persona_id(event, req)
        pconf = plug.get_persona_config(persona_id)

        if not pconf.enabled:
            return

        categories = plug.stickers.get_categories(
            persona_id=persona_id, dir_name=pconf.sticker_dir_name
        )
        if not categories:
            logger.debug(
                f"[sticker_reply][{persona_id}] 表情包目录下没有可用分类，跳过提示词注入"
            )
            return

        static_prompt = StickerPromptManager.build_static_prompt(
            categories=categories,
            sticker_condition=pconf.sticker_condition,
            prompt_preset=pconf.prompt_preset,
            sticker_prompt_core=pconf.sticker_prompt_core,
            enabled=True,
        )
        if static_prompt:
            req.system_prompt = (req.system_prompt or "") + static_prompt

    # ── on_llm_response ────────────────────────────────────

    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        """解析 LLM 响应中的表情包标签，移除标签并异步补发图片。"""
        if not resp.completion_text:
            return

        original = resp.completion_text
        has_tag = bool(RE_STK.search(original))

        # 1. 先移除标签：即使表情包功能被关闭，也不让内部标签泄漏给用户
        cleaned = clean_sticker_tags(original)
        if cleaned != original:
            resp.completion_text = cleaned

        if not has_tag:
            return

        plug = self.plugin
        persona_id = await plug.resolve_persona_id(event)
        pconf = plug.get_persona_config(persona_id)
        if not pconf.enabled:
            logger.debug(
                f"[sticker_reply][{persona_id}] 表情包系统已停用，仅移除标签不发送图片"
            )
            return

        categories = extract_sticker_categories(original)
        if not categories:
            logger.warning("[sticker_reply] STK 标签中的分类名非法，已忽略")
            return

        max_per_reply = max(1, int(plug.max_per_reply))
        if len(categories) > max_per_reply:
            logger.info(
                f"[sticker_reply] 单条回复请求了 {len(categories)} 个表情包，"
                f"按上限截断为 {max_per_reply} 个"
            )
            categories = categories[:max_per_reply]

        asyncio.create_task(
            self._send_stickers(
                event,
                plug,
                categories,
                persona_id=persona_id,
                sticker_dir_name=pconf.sticker_dir_name,
            )
        )

    # ── 异步辅助：发送表情包 ───────────────────────────────

    async def _send_stickers(
        self,
        event: AstrMessageEvent,
        plug,
        categories: list[str],
        persona_id: str = "default",
        sticker_dir_name: str | None = None,
    ):
        """延迟发送表情包，避免与主回复争抢消息顺序。"""
        delay = plug.send_delay
        if delay > 0:
            await asyncio.sleep(delay)

        umo = event.unified_msg_origin
        for cat in categories:
            img_path = plug.stickers.get_random_sticker(
                cat, persona_id=persona_id, dir_name=sticker_dir_name
            )
            if not img_path:
                logger.warning(
                    f"[sticker_reply][{persona_id}] 分类「{cat}」下没有可用表情包"
                )
                continue
            try:
                mc = MessageChain().file_image(str(img_path))
                await plug.context.send_message(umo, mc)
            except Exception as e:
                logger.error(f"[sticker_reply] 表情包发送失败: {e}")
