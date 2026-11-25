# FGOUID

FGO（Fate/Grand Order）查询插件，基于 [GsCore](https://github.com/Genshin-bots/gsuid_core) 框架，纯指令、无 AI。

## 命令

| 命令 | 说明 |
|---|---|
| `fgo从者 <名称>` | 从者信息（属性/阵营/攻防/特性/卡池），支持中文名、日文名、别名 |
| `fgo礼装 <名称>` | 概念礼装（稀有度/COST/类型/效果） |
| `fgo活动 [关键词]` | 未来活动，无则最近活动 |
| `fgo卡池 [关键词]` | 近期卡池日历 / 按名称搜索 |
| `fgo测试` | 链路自检 |
| `fgo帮助` | 帮助卡（图片，主题同 fgo-wiki card-render） |

## 安装

把本仓库 clone 到 GsCore 的插件目录，然后重启 core：

```bash
cd <gsuid_core>/gsuid_core/plugins
git clone <本仓库地址> FGOUID
# 重启 gsuid_core
```

插件自带 `data/fgo.db`，**运行时不需要 fgo-wiki**。

## 数据

- 数据来源：Atlas Academy API、Mooncell，经 [fgo-wiki](https://github.com/karl2829/fgo-wiki) 整理（CC BY-NC-SA 4.0）
- 本仓库的 `data/fgo.db` 是从 fgo-wiki 生成的**自包含快照**，`data/meta.json` 记录来源 commit 与构建时间
- 刷新数据（开发/维护）：

```bash
python tools/sync_from_wiki.py --wiki /path/to/fgo-wiki
python tools/sync_from_wiki.py --wiki /path/to/fgo-wiki --freeze   # 发布快照
```

- 数据修正不写回 fgo-wiki，统一放在 `overrides/`（别名）或后续的修正层里

## 帮助卡图片

`fgo帮助` 发送的是一张预渲染 PNG（`assets/help.png`），**运行时不需要 pytakumi**：
图在开发机生成好随仓库分发，服务器只做 base64 发送。

改版式或数据后重新生成：

```bash
# 一次性：建渲染环境（pytakumi 0.1.5）
uv venv .render-venv && uv pip install --python .render-venv/bin/python pytakumi==0.1.5 pillow

.render-venv/bin/python tools/render_help.py           # → assets/help.png（2200px 宽，约 400 KB）
.render-venv/bin/python tools/render_help.py --dpr 1   # 预览用低清
```

- 版式：`templates/help_card.html`，沿用 fgo-wiki `card-render` 的暗色主题（DARK-CHALDEA FRAME）
  与调色板，金框 / 四角 / 页脚与从者卡一致
- 图里的数量、别名条数、wiki commit 从 `data/meta.json` 与 `data/fgo.db` **现读**，
  数据刷新后重跑一次即可，不会和库里的数字对不上
- `assets/emblem.png` 是从 fgo-wiki 素材库裁出的迦勒底徽记（去掉了下方文字），
  已随仓库提交，脱离 wiki 后仍可单独重建

## 结构

```
FGOUID/
├── __init__.py            # 命令入口（GsCore SV）
├── core/db.py             # 只读查询层
├── data/fgo.db            # 索引快照
├── data/meta.json         # 来源版本
├── overrides/aliases.json # 别名覆盖
├── assets/help.png        # fgo帮助 的卡片图（预渲染）
├── assets/emblem.png      # 迦勒底徽记
├── templates/help_card.html
└── tools/
    ├── sync_from_wiki.py  # wiki → db
    └── render_help.py     # 帮助卡渲染（仅开发机）
```

## License

代码 MIT；数据遵循上游 CC BY-NC-SA 4.0。
