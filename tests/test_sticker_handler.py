"""StickerHandler 单元测试：提示词注入、标签清理与表情包发送。

测试通过最小 astrbot 桩运行，不依赖 AstrBot 本体。
"""

import asyncio
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PLUGIN_ROOT.parent
for _p in (str(WORKSPACE_ROOT), str(PLUGIN_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── 最小 astrbot 桩（必须在导入插件模块之前安装） ──────────


class _Logger:
    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


class MessageChain:
    """仅记录被发送的图片路径。"""

    def __init__(self):
        self.images = []

    def file_image(self, path):
        self.images.append(path)
        return self


class LLMResponse:
    def __init__(self, completion_text=""):
        self.completion_text = completion_text


class ProviderRequest:
    def __init__(self, system_prompt=""):
        self.system_prompt = system_prompt


def _install_astrbot_stub():
    if "astrbot.api" in sys.modules:
        return
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = _Logger()
    event_mod = types.ModuleType("astrbot.api.event")
    event_mod.AstrMessageEvent = object
    event_mod.MessageChain = MessageChain
    provider_mod = types.ModuleType("astrbot.api.provider")
    provider_mod.LLMResponse = LLMResponse
    provider_mod.ProviderRequest = ProviderRequest
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api
    sys.modules["astrbot.api.event"] = event_mod
    sys.modules["astrbot.api.provider"] = provider_mod


_install_astrbot_stub()

from astrbot_plugin_sticker_reply.llm.handler import (  # noqa: E402
    StickerHandler,
)
from astrbot_plugin_sticker_reply.services.sticker import (  # noqa: E402
    StickerManager,
)


# ── 测试替身 ──────────────────────────────────────────────


class FakeContext:
    def __init__(self):
        self.sent = []

    async def send_message(self, umo, chain):
        self.sent.append((umo, chain))


class FakePersonaConfig:
    def __init__(
        self,
        enabled=True,
        sticker_dir_name="default",
        sticker_condition="",
        prompt_preset="default",
        sticker_prompt_core="",
    ):
        self.enabled = enabled
        self.sticker_dir_name = sticker_dir_name
        self.sticker_condition = sticker_condition
        self.prompt_preset = prompt_preset
        self.sticker_prompt_core = sticker_prompt_core


class FakePlugin:
    def __init__(
        self,
        sticker_root,
        persona_config=None,
        max_per_reply=3,
        send_delay=0,
        persona_id="default",
    ):
        self.stickers = StickerManager(sticker_root)
        self.context = FakeContext()
        self.max_per_reply = max_per_reply
        self.send_delay = send_delay
        self._persona_config = persona_config or FakePersonaConfig()
        self._persona_id = persona_id

    def get_persona_config(self, persona_id):
        return self._persona_config

    async def resolve_persona_id(self, event, req=None):
        return self._persona_id


class StickerHandlerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.root = Path(self.temp_dir) / "stickers"
        self.root.mkdir(parents=True)
        (self.root / "开心").mkdir()
        (self.root / "开心" / "a.png").write_text("dummy", encoding="utf-8")
        (self.root / "难过").mkdir()
        (self.root / "难过" / "b.png").write_text("dummy", encoding="utf-8")
        self.event = SimpleNamespace(unified_msg_origin="test:FriendMessage:1")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ── on_llm_request ─────────────────────────────────────

    def test_request_injects_prompt_with_categories(self):
        plug = FakePlugin(self.root)
        handler = StickerHandler(plug)
        req = ProviderRequest(system_prompt="BASE_PROMPT")

        asyncio.run(handler.on_llm_request(self.event, req))

        self.assertTrue(req.system_prompt.startswith("BASE_PROMPT"))
        self.assertIn("表情包机制", req.system_prompt)
        self.assertIn("可用分类：开心, 难过", req.system_prompt)
        self.assertIn("[STK:分类名]", req.system_prompt)

    def test_request_skips_when_disabled(self):
        plug = FakePlugin(self.root, persona_config=FakePersonaConfig(enabled=False))
        handler = StickerHandler(plug)
        req = ProviderRequest(system_prompt="BASE_PROMPT")

        asyncio.run(handler.on_llm_request(self.event, req))

        self.assertEqual(req.system_prompt, "BASE_PROMPT")

    def test_request_skips_when_no_categories(self):
        plug = FakePlugin(Path(self.temp_dir) / "empty")
        handler = StickerHandler(plug)
        req = ProviderRequest(system_prompt="BASE_PROMPT")

        asyncio.run(handler.on_llm_request(self.event, req))

        self.assertEqual(req.system_prompt, "BASE_PROMPT")

    # ── on_llm_response ────────────────────────────────────

    def _run_response(self, handler, resp):
        """执行 on_llm_response 并等待它调度的发送任务。"""
        created = []
        with mock.patch(
            "asyncio.create_task", side_effect=lambda coro: created.append(coro)
        ):
            asyncio.run(handler.on_llm_response(self.event, resp))

        async def _drain():
            for coro in created:
                await coro

        asyncio.run(_drain())
        return created

    def test_response_strips_tag_and_sends_sticker(self):
        plug = FakePlugin(self.root)
        handler = StickerHandler(plug)
        resp = LLMResponse("今天也要开心哦！\n[STK:开心]")

        created = self._run_response(handler, resp)

        self.assertEqual(resp.completion_text, "今天也要开心哦！")
        self.assertEqual(len(created), 1)
        self.assertEqual(len(plug.context.sent), 1)
        _, chain = plug.context.sent[0]
        self.assertEqual(len(chain.images), 1)
        self.assertTrue(chain.images[0].endswith("a.png"))

    def test_response_keeps_other_plugins_tags(self):
        plug = FakePlugin(self.root)
        handler = StickerHandler(plug)
        resp = LLMResponse("回复\n[FAV:+2]\n[STK:开心]\n[EVAL:有趣]")

        self._run_response(handler, resp)

        self.assertEqual(resp.completion_text, "回复\n[FAV:+2]\n[EVAL:有趣]")

    def test_response_without_tag_does_nothing(self):
        plug = FakePlugin(self.root)
        handler = StickerHandler(plug)
        resp = LLMResponse("普通回复，没有标签")

        created = self._run_response(handler, resp)

        self.assertEqual(created, [])
        self.assertEqual(plug.context.sent, [])
        self.assertEqual(resp.completion_text, "普通回复，没有标签")

    def test_response_strips_tag_but_does_not_send_when_disabled(self):
        plug = FakePlugin(self.root, persona_config=FakePersonaConfig(enabled=False))
        handler = StickerHandler(plug)
        resp = LLMResponse("回复\n[STK:开心]")

        created = self._run_response(handler, resp)

        self.assertEqual(created, [])
        self.assertEqual(resp.completion_text, "回复")
        self.assertEqual(plug.context.sent, [])

    def test_response_respects_max_per_reply(self):
        plug = FakePlugin(self.root, max_per_reply=1)
        handler = StickerHandler(plug)
        resp = LLMResponse("回复\n[STK:开心]\n[STK:难过]")

        self._run_response(handler, resp)

        self.assertEqual(len(plug.context.sent), 1)

    def test_response_dedupes_repeated_category(self):
        plug = FakePlugin(self.root)
        handler = StickerHandler(plug)
        resp = LLMResponse("回复\n[STK:开心]\n[STK:开心]")

        self._run_response(handler, resp)

        self.assertEqual(len(plug.context.sent), 1)

    def test_response_ignores_missing_category_silently(self):
        plug = FakePlugin(self.root)
        handler = StickerHandler(plug)
        resp = LLMResponse("回复\n[STK:不存在的分类]")

        self._run_response(handler, resp)

        self.assertEqual(resp.completion_text, "回复")
        self.assertEqual(plug.context.sent, [])

    def test_response_uses_persona_subdirectory(self):
        (self.root / "neko" / "撒娇").mkdir(parents=True)
        (self.root / "neko" / "撒娇" / "neko.png").write_text("dummy", encoding="utf-8")

        plug = FakePlugin(
            self.root,
            persona_config=FakePersonaConfig(sticker_dir_name="neko"),
            persona_id="neko",
        )
        handler = StickerHandler(plug)
        resp = LLMResponse("回复\n[STK:撒娇]")

        self._run_response(handler, resp)

        _, chain = plug.context.sent[0]
        self.assertTrue(chain.images[0].endswith("neko.png"))

    def test_send_delay_is_applied(self):
        plug = FakePlugin(self.root, send_delay=0.01)
        handler = StickerHandler(plug)

        async def _run():
            with mock.patch("asyncio.sleep", new=mock.AsyncMock()) as sleeper:
                await handler._send_stickers(self.event, plug, ["开心"])
                sleeper.assert_awaited_once_with(0.01)

        asyncio.run(_run())
        self.assertEqual(len(plug.context.sent), 1)


if __name__ == "__main__":
    unittest.main()
