"""
astrbot_plugin_sticker_reply — 表情包系统插件

从 astrbot_plugin_favorability 拆分出来的独立表情包功能：
LLM 在回复末尾输出 `[STK:分类名]`，插件移除标签并从本地表情包目录中
随机挑一张图片补发，实现「AI 用表情包回应」的效果。

架构说明：
  main.py          — 插件入口，注册命令，组装子模块
  services/        — 服务层：StickerManager（表情包目录），StickerPromptManager（提示词）
  llm/             — LLM 层：StickerHandler（请求注入 + 响应解析）
  commands/        — 指令层：StickerCommands（分类列表、随机发送）

数据目录（默认）：
  data/plugin_data/astrbot_plugin_sticker_reply/stickers/<分类名>/
  data/plugin_data/astrbot_plugin_sticker_reply/stickers/<人格名>/<分类名>/

兼容旧版：
  若新数据目录下没有任何分类，会自动回退读取旧插件的数据目录
  data/plugin_data/astrbot_plugin_favorability/stickers/（可用 legacy_fallback 关闭），
  因此升级拆分后无需移动已有表情包文件。
"""

from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api import AstrBotConfig, logger

from .services.sticker import StickerManager
from .services.prompt import (
    DEFAULT_STICKER_CONDITION,
    STICKER_PRESET_NAMES,
    STICKER_SYSTEM_PROMPT_TPL,
    StickerPromptManager,
)
from .llm.handler import StickerHandler
from .commands.user import StickerCommands

# 旧插件（表情包功能原属插件）的数据目录名，用于兼容回退
LEGACY_PLUGIN_NAME = "astrbot_plugin_favorability"


@register(
    "astrbot_plugin_sticker_reply",
    "Iris1598",
    "表情包系统：LLM 通过 [STK:分类名] 标签调用本地表情包，"
    "支持人格独立目录与分类随机发送",
    "v1.0.0",
)
class StickerPlugin(Star):
    """表情包系统主插件。"""

    _SETTING_GROUPS = {
        "enabled": "feature_settings",
        "send_delay": "feature_settings",
        "max_per_reply": "feature_settings",
        "legacy_fallback": "feature_settings",
        "sticker_root": "feature_settings",
        "prompt_preset": "prompt_settings",
        "sticker_condition": "prompt_settings",
        "sticker_prompt_core": "prompt_settings",
        "persona_overrides": "persona_settings",
    }

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._restore_empty_prompt_defaults()

        # ── 数据层 ──
        self.data_dir = StarTools.get_data_dir()
        sticker_root = self._resolve_sticker_root()
        legacy_dir = self._resolve_legacy_sticker_dir()
        self.stickers = StickerManager(sticker_root, fallback_dir=legacy_dir)
        logger.info(f"[sticker_reply] 表情包目录: {self.stickers.sticker_dir}")
        if legacy_dir is not None:
            logger.info(
                f"[sticker_reply] 已启用旧插件表情包目录回退: {legacy_dir}"
                "（新目录有分类时优先使用新目录）"
            )

        # ── 服务层（StickerPromptManager 为纯静态方法，无需实例化） ──
        self.prompt = StickerPromptManager  # 方便引用

        # ── LLM 层 ──
        self.llm_handler = StickerHandler(self)

        # ── 指令层 ──
        self.user_cmds = StickerCommands(self)

    # ── 路径解析 ───────────────────────────────────────────

    def _resolve_sticker_root(self) -> Path:
        """解析表情包根目录：配置了 sticker_root 时以其为准。"""
        configured = str(self._get_setting("sticker_root", "") or "").strip()
        if configured:
            root = Path(configured).expanduser()
            if not root.is_absolute():
                root = self.data_dir / root
            return root
        return self.data_dir / "stickers"

    def _resolve_legacy_sticker_dir(self) -> Path | None:
        """旧插件（astrbot_plugin_favorability）的表情包目录，不存在时返回 None。"""
        if not self.legacy_fallback:
            return None
        legacy = self.data_dir.parent / LEGACY_PLUGIN_NAME / "stickers"
        return legacy if legacy.is_dir() else None

    # ── 配置读写 ───────────────────────────────────────────

    def _get_setting(self, key: str, default=None):
        """读取分组配置，并兼容未分组的平铺配置。"""
        group_name = self._SETTING_GROUPS.get(key)
        if group_name:
            group = self.config.get(group_name)
            if isinstance(group, dict) and key in group:
                return group.get(key)
        return self.config.get(key, default)

    def _set_setting(self, key: str, value) -> None:
        group_name = self._SETTING_GROUPS.get(key)
        if not group_name:
            self.config[key] = value
            return
        group = self.config.get(group_name)
        if not isinstance(group, dict):
            group = {}
            self.config[group_name] = group
        group[key] = value

    def _restore_empty_prompt_defaults(self):
        """将留空的提示词配置恢复为内置默认值并持久化。"""
        restored = []
        prompt_defaults = {
            "sticker_condition": DEFAULT_STICKER_CONDITION,
            "sticker_prompt_core": STICKER_SYSTEM_PROMPT_TPL,
        }
        for key, default in prompt_defaults.items():
            value = self._get_setting(key, "")
            if not str(value or "").strip():
                self._set_setting(key, default)
                restored.append(key)

        if not restored:
            return

        save_config = getattr(self.config, "save_config", None)
        if callable(save_config):
            try:
                save_config()
            except Exception as e:
                logger.warning(f"[sticker_reply] 保存默认提示词配置失败: {e}")
        logger.info(f"[sticker_reply] 已恢复 {len(restored)} 项留空的默认提示词配置")

    # ── 配置属性 ───────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self._get_setting("enabled", True))

    @property
    def send_delay(self) -> float:
        try:
            delay = float(self._get_setting("send_delay", 0.5))
        except (TypeError, ValueError):
            delay = 0.5
        return max(0.0, delay)

    @property
    def max_per_reply(self) -> int:
        try:
            limit = int(self._get_setting("max_per_reply", 3))
        except (TypeError, ValueError):
            limit = 3
        return max(1, limit)

    @property
    def legacy_fallback(self) -> bool:
        return bool(self._get_setting("legacy_fallback", True))

    @property
    def prompt_preset(self) -> str:
        value = str(self._get_setting("prompt_preset", "default") or "").strip().lower()
        return value if value in STICKER_PRESET_NAMES else "default"

    @property
    def sticker_condition(self) -> str:
        return str(self._get_setting("sticker_condition", "") or "")

    @property
    def sticker_prompt_core(self) -> str:
        return str(self._get_setting("sticker_prompt_core", "") or "")

    # ── 人格配置 ───────────────────────────────────────────

    def get_persona_config(self, persona_id: str) -> "PersonaConfig":
        """获取指定人格的专属配置视图（未配置项自动回退全局默认配置）。"""
        return PersonaConfig(self, persona_id)

    async def resolve_persona_id(
        self, event: AstrMessageEvent, req: ProviderRequest = None
    ) -> str:
        """多层级智能解析当前会话生效的人格 ID / 名称，未识别时回退为 'default'。"""
        # 1. 优先尝试从 req.conversation 获取
        if req is not None:
            conv = getattr(req, "conversation", None)
            if conv:
                pid = getattr(conv, "persona_id", None)
                if pid and str(pid).strip() and str(pid).strip() != "[%None]":
                    return str(pid).strip()

        # 2. 尝试通过 AstrBot context.persona_manager 解析
        pm = getattr(self.context, "persona_manager", None)
        if pm and hasattr(pm, "resolve_selected_persona"):
            try:
                conv_pid = None
                if req is not None and getattr(req, "conversation", None):
                    conv_pid = getattr(req.conversation, "persona_id", None)
                elif hasattr(self.context, "conversation_manager"):
                    curr_cid = await self.context.conversation_manager.get_curr_conversation_id(
                        event.unified_msg_origin
                    )
                    if curr_cid:
                        conv = await self.context.conversation_manager.get_conversation(
                            event.unified_msg_origin, curr_cid
                        )
                        if conv:
                            conv_pid = getattr(conv, "persona_id", None)

                cfg = (
                    getattr(self.context, "get_config", lambda umo=None: {})(
                        umo=event.unified_msg_origin
                    )
                    or {}
                )
                res = await pm.resolve_selected_persona(
                    umo=event.unified_msg_origin,
                    conversation_persona_id=conv_pid,
                    platform_name=event.get_platform_name()
                    if hasattr(event, "get_platform_name")
                    else "",
                    provider_settings=cfg,
                )
                if res and res[0] and str(res[0]).strip() and str(res[0]).strip() != "[%None]":
                    return str(res[0]).strip()
            except Exception as e:
                logger.debug(f"[sticker_reply] 解析 persona 异常: {e}")

        # 3. 尝试通过 conversation_manager 获取当前 conversation 的 persona_id
        cm = getattr(self.context, "conversation_manager", None)
        if cm and hasattr(cm, "get_curr_conversation_id"):
            try:
                curr_cid = await cm.get_curr_conversation_id(event.unified_msg_origin)
                if curr_cid:
                    conv = await cm.get_conversation(
                        event.unified_msg_origin, curr_cid
                    )
                    if conv and getattr(conv, "persona_id", None):
                        pid = str(conv.persona_id).strip()
                        if pid and pid != "[%None]":
                            return pid
            except Exception as e:
                logger.debug(f"[sticker_reply] 从 conversation_manager 获取 persona 异常: {e}")

        return "default"

    # ── LLM 事件钩子 ───────────────────────────────────────

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        await self.llm_handler.on_llm_request(event, req)

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        await self.llm_handler.on_llm_response(event, resp)

    # ── 用户指令 ───────────────────────────────────────────

    @filter.command("表情包分类")
    async def cmd_categories(self, event: AstrMessageEvent):
        """查看当前人格可用的表情包分类与数量"""
        async for r in self.user_cmds.cmd_categories(event):
            yield r
        event.stop_event()

    @filter.command("随机表情包")
    async def cmd_random(self, event: AstrMessageEvent):
        """立即发送一张随机表情包，可附加分类名"""
        async for r in self.user_cmds.cmd_random(event):
            yield r
        event.stop_event()


class PersonaConfig:
    """针对特定人格的配置视图，支持独立覆盖与回退全局默认配置。"""

    def __init__(self, plugin: StickerPlugin, persona_id: str):
        self.plugin = plugin
        self.persona_id = (persona_id or "").strip() or "default"
        self.override = self._find_override()

    def _find_override(self) -> dict:
        overrides = self.plugin._get_setting("persona_overrides", [])
        if not isinstance(overrides, list):
            return {}
        for item in overrides:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("persona_id") or "").strip()
            if pid and pid == self.persona_id:
                return item
        return {}

    def get(self, key: str, default=None):
        if self.override and key in self.override:
            val = self.override[key]
            if isinstance(val, str):
                if val.strip():
                    return val
            elif val is not None:
                return val
        return self.plugin._get_setting(key, default)

    @property
    def enabled(self) -> bool:
        return bool(self.get("enabled", True))

    @property
    def sticker_dir_name(self) -> str:
        val = str(self.get("sticker_dir_name", "") or "").strip()
        return val or self.persona_id

    @property
    def prompt_preset(self) -> str:
        value = str(self.get("prompt_preset", "default") or "").strip().lower()
        return value if value in STICKER_PRESET_NAMES else "default"

    @property
    def sticker_condition(self) -> str:
        return str(self.get("sticker_condition", "") or "")

    @property
    def sticker_prompt_core(self) -> str:
        return str(self.get("sticker_prompt_core", "") or "")
