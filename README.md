# astrbot_plugin_sticker_reply

AstrBot 表情包系统插件：让 AI 在回复时用本地表情包回应你。

插件把「可用分类 + 发送条件」注入给模型，模型在需要时于回复末尾输出 `[STK:分类名]`，插件解析标签、从对应分类中随机挑一张图片补发，并把标签从正文中移除。本插件由 [astrbot_plugin_favorability](https://github.com/iris1598/astrbot_plugin_favorability) 的表情包功能拆分而来，可以单独安装、单独开关。

## 功能特性

- **LLM 标签驱动**：模型通过 `[STK:分类名]` 选择表情包，支持 `[STK:x]`、`**[STK:x]**`、`【STK:x】` 等书写变体
- **分类随机发送**：同一分类下随机挑图，避免每次都是同一张
- **人格独立目录**：每个 AI 人格可使用 `stickers/<人格名>/<分类名>/` 下的专属表情包
- **提示词可配置**：`default` / `old` / `custom` 三套预设，自定义模板支持 `{sticker_condition}`、`{categories}` 占位符
- **自动清洗标签**：即使关闭表情包开关，模型回复中残留的 `[STK:]` 标签也会被清理，不会泄漏给用户
- **旧插件兼容**：默认回退读取 `astrbot_plugin_favorability` 的表情包目录，升级拆分无需搬文件
- **与其它插件解耦**：只处理 STK 标签，不影响好感度插件的 `[FAV:]`/`[EVAL:]`/`[REL:]`/`[MUTE:]` 标签，两个插件同时启用时执行顺序无关

## 安装

通过 AstrBot 插件市场安装，或将本仓库克隆到 AstrBot 的插件目录：

```bash
cd AstrBot/data/plugins
git clone https://github.com/iris1598/astrbot_plugin_sticker_reply.git
```

本插件只依赖 AstrBot 本体与 Python 标准库，无需安装额外依赖。完成后重启 AstrBot，并在 WebUI 中启用插件。

## 表情包目录

把图片按分类放进目录即可（默认位置）：

```text
data/plugin_data/astrbot_plugin_sticker_reply/stickers/
    ├── 开心/
    │     ├── 1.jpg
    │     └── 2.png
    ├── 难过/
    └── neko/          # 人格 neko 的专属目录
          └── 撒娇/
```

- 支持 `jpg`、`png`、`gif`、`webp`
- 放好图片立即生效，无需重载插件
- 没有建立人格专属目录时，所有人格共用 `stickers/` 根目录（或 `stickers/default/`）
- 人格专属目录存在时优先使用，缺失的分类再回退默认目录

## 指令

| 指令 | 说明 |
|---|---|
| `/表情包分类` | 查看当前人格可用的表情包分类与图片数量 |
| `/随机表情包 [分类]` | 立即发送一张随机表情包，用于验证目录配置 |

## WebUI 配置

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `true` | 表情包系统开关 |
| `send_delay` | `0.5` | 发送表情包前等待的秒数，避免抢在文字回复之前 |
| `max_per_reply` | `3` | 单条回复最多发送数量，超出的标签会被忽略 |
| `legacy_fallback` | `true` | 新目录没有分类时，回退读取旧插件 `astrbot_plugin_favorability/stickers/` |
| `sticker_root` | 空 | 自定义表情包根目录（绝对路径或相对插件数据目录），留空使用默认目录 |
| `prompt_preset` | `default` | 提示词预设：`default`、`old` 或 `custom` |
| `sticker_condition` | 仅在合适时发送… | 自定义发送条件（`custom` 预设下显示） |
| `sticker_prompt_core` | 内置默认值 | 自定义提示词模板，支持 `{sticker_condition}`、`{categories}` |
| `persona_overrides` | 空列表 | 人格独立配置：专属开关、子目录名、发送条件与提示词 |

## 从好感度插件迁移

表情包功能原先内置于 `astrbot_plugin_favorability`（v3.0.x 及更早）。升级到 `astrbot_plugin_favorability` v3.1.0 后：

1. 安装并启用本插件；
2. 保持 `legacy_fallback` 开启即可直接沿用旧目录 `data/plugin_data/astrbot_plugin_favorability/stickers/`；
3. 想彻底迁移时，把该目录下的分类文件夹复制到 `data/plugin_data/astrbot_plugin_sticker_reply/stickers/`（人格子目录同样复制），确认新目录出现分类后即可关闭 `legacy_fallback`。

旧配置项与新配置的对应关系：

| 旧插件配置 | 本插件配置 |
|---|---|
| `sticker_enabled` | `enabled` |
| `sticker_condition` | `sticker_condition` |
| 人格配置 `sticker_dir_name` | 人格配置 `sticker_dir_name` |

## 工作流程

1. **请求阶段**：插件解析当前会话人格，读取该人格可用分类，把表情包机制规则追加到 `system_prompt`（分类为空时不注入，避免模型虚构分类）
2. **响应阶段**：插件先从正文中移除所有 `[STK:]` 标签，再按分类随机取图；延迟 `send_delay` 秒后通过 `context.send_message()` 逐张补发
3. **失败降级**：分类不存在或目录为空时只记录日志，不影响正常文字回复

## 项目结构

```text
astrbot_plugin_sticker_reply/
├── commands/user.py      # /表情包分类、/随机表情包
├── llm/handler.py        # 请求注入与响应解析
├── services/prompt.py    # STK 标签正则、校验与提示词组装
├── services/sticker.py   # 表情包目录管理（分类、人格隔离、随机取图）
├── tests/                # 单元测试（不依赖 AstrBot 本体）
├── _conf_schema.json     # WebUI 配置定义
├── main.py               # 插件入口
└── metadata.yaml         # AstrBot 插件元数据
```

## 测试

```bash
python -m unittest discover -s tests -t tests
```

## 依赖

- AstrBot（`on_llm_request` / `on_llm_response` 钩子）

## 版本历史

- **v1.0.0**：从 `astrbot_plugin_favorability` 拆分出的首个独立版本，新增 `/表情包分类`、`/随机表情包` 指令、发送数量上限与旧插件目录回退

## 致谢

表情包功能与 `[STK:分类名]` 标签协议来自 `astrbot_plugin_favorability`，本插件在其基础上拆分独立并增强。
