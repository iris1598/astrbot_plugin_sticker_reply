"""
表情包提示词与标签匹配模块 - StickerPromptManager

职责：
1. 规范化表情包标签格式，确保 LLM 理解 [STK:分类名] 的用法
2. 提供标签正则匹配、合法性校验与文本清理工具
3. 组装注入到 system_prompt 的表情包机制规则（含当前可用分类）

标签格式规范：
  [STK:分类名] — 表情包，分类名限 30 字以内，仅含中文/英文/数字/下划线，
                 与回复正文末尾同行输出；插件会移除标签并补发对应图片。
"""

import re
from typing import Optional

# 增强版 STK：分类名仅含中文/英文/数字/下划线，限 30 字符
# 匹配 [STK:angry] [STK:开心] **[STK:xxx]** 【STK:xxx】 等
RE_STK = re.compile(
    r"\*{0,2}[\[【]STK\s*[:：]\s*([\w\u4e00-\u9fff]{1,30}?)[\]】]\*{0,2}",
    re.IGNORECASE,
)

# ── 默认提示词 ────────────────────────────────────────────

DEFAULT_STICKER_CONDITION = (
    "仅当表情包能够自然表达当前情绪、语气或场景时发送；普通回复、信息性回复或没有合适分类时不要发送。"
)
OLD_STICKER_CONDITION = "根据当前情绪选择合适的分类发送；如果不确定用哪个分类，可以不发送。"

# 表情包机制提示词模板（支持 {sticker_condition} 与 {categories} 占位符）
STICKER_SYSTEM_PROMPT_TPL = """--- 表情包机制 ---
1. 发送条件：{sticker_condition}
2. 发送格式：将 `[STK:分类名]` 放在回复正文末尾。
3. 可用分类：{categories}
4. 如果没有合适分类或无法确定分类，可以不发送；不要虚构不存在的分类。"""

STICKER_PROMPT_DEFAULTS = {
    "sticker_condition": DEFAULT_STICKER_CONDITION,
    "sticker_prompt_core": STICKER_SYSTEM_PROMPT_TPL,
}

STICKER_PRESET_NAMES = ("default", "old", "custom")

# 保留旧常量名，兼容已有引用
STICKER_CONDITION_DEFAULTS = STICKER_PROMPT_DEFAULTS


# ── 标签校验与清理 ────────────────────────────────────────


def validate_stk_category(category: str) -> bool:
    """验证 STK 分类名是否合法（非空、不超过 30 字、仅中英文数字下划线）。"""
    return (
        bool(category)
        and len(category) <= 30
        and bool(re.match(r"^[\w\u4e00-\u9fff]+$", category))
    )


def extract_sticker_categories(text: str) -> list[str]:
    """提取文本中所有合法的 STK 分类名（去重并保持出现顺序）。"""
    if not text:
        return []
    categories = []
    for raw in RE_STK.findall(text):
        name = (raw or "").strip()
        if name and validate_stk_category(name) and name not in categories:
            categories.append(name)
    return categories


def clean_sticker_tags(text: str) -> str:
    """从文本中彻底移除所有 STK 标签，并清理多余空行。

    只处理表情包标签，不会影响其它插件（如好感度）的标签。
    """
    if not text:
        return text
    text = RE_STK.sub("", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


# ── 提示词组装 ────────────────────────────────────────────


class StickerPromptManager:
    """表情包提示词管理器（纯静态方法）。"""

    @staticmethod
    def resolve_condition(prompt_preset: str = "custom", sticker_condition: str = "") -> str:
        """按预设解析表情包发送条件。"""
        preset = (prompt_preset or "custom").strip().lower()
        if preset == "default":
            return DEFAULT_STICKER_CONDITION
        if preset == "old":
            return OLD_STICKER_CONDITION
        return (sticker_condition or "").strip() or DEFAULT_STICKER_CONDITION

    @staticmethod
    def build_static_prompt(
        categories: Optional[list[str]] = None,
        sticker_condition: str = "",
        prompt_preset: str = "custom",
        sticker_prompt_core: str = "",
        enabled: bool = True,
    ) -> str:
        """构建表情包静态规则文本（追加到 system_prompt）。

        Args:
            categories: 当前人格可用的表情包分类名列表。
            sticker_condition: 自定义发送条件（preset 为 custom 时生效）。
            prompt_preset: default / old / custom。
            sticker_prompt_core: 自定义提示词模板，支持 {sticker_condition}、
                {categories} 占位符；留空时使用内置模板。
            enabled: 表情包系统开关；关闭时返回空字符串。

        Returns:
            追加到 system_prompt 的文本；无分类时返回空字符串，避免模型
            在没有任何图片可发的情况下虚构分类。
        """
        if not enabled:
            return ""

        categories = [c for c in (categories or []) if c]
        if not categories:
            return ""

        preset = (prompt_preset or "custom").strip().lower()
        if preset == "default":
            template = STICKER_SYSTEM_PROMPT_TPL
        else:
            template = (sticker_prompt_core or "").strip() or STICKER_SYSTEM_PROMPT_TPL

        condition = StickerPromptManager.resolve_condition(
            prompt_preset, sticker_condition
        )
        cat_str = ", ".join(categories)

        if "{sticker_condition}" in template:
            template = template.replace("{sticker_condition}", condition)
        else:
            template = f"{template}\n当前发送条件：{condition}"

        if "{categories}" in template:
            template = template.replace("{categories}", cat_str)
        else:
            template = f"{template}\n可用分类：{cat_str}"

        return template
