# FGOUID

FGO（Fate/Grand Order）查询插件，基于 [GsCore](https://github.com/Genshin-bots/gsuid_core) 框架，纯指令、无 AI。

## 命令

| 命令 | 说明 |
|---|---|
| `fgo从者 <名称>` | **从者卡图**（立绘 + 六维 + 宝具 + 技能数值）；无卡片数据/渲染失败时退回文字 |
| `fgo礼装 <名称>` | **礼装卡**（卡面 + 星级/COST + 未破/满破效果）；无卡面数据时退回文字 |
| `fgo活动 [关键词]` | 未来活动，无则最近活动 |
| `fgo卡池 [关键词]` | **卡池日历卡**（横幅 + 时间 + UP 从者）/ 按名称搜索 |
| `fgo今日老婆` | 今天的老婆（按 ID + 日期定种子，每天换人） |
| `fgo每日一抽` | 每天一抽（同一天结果固定），出货记进图鉴 |
| `fgo图鉴` | 收集进度：已收集多少从者、星级分布、最近几抽 |
| `fgo下载资源 [数量]` | 后台预热立绘/图标（默认 60 张，最多 200），减少首次出图等待 |
| `fgo设置` | 看当前配置（按群/按人） |
| `fgo设置出图 开/关` | 关掉后从者/礼装/卡池/老婆只发文字（省流量、怕刷屏的群用） |
| `fgo测试` | 链路自检 |
| `fgo帮助` | 帮助卡（图片，主题同 fgo-wiki card-render） |

趣味互动的「每日一抽 / 今日老婆」按「账号 + 日期」定种子：同一天重发不会刷新运气，
次日自动换。抽卡记录写在 `<gsuid_core>/data/FGOUID/play.db`，插件更新不会覆盖。

`fgo下载资源` 的进度记在 `data/FGOUID/prewarm.json`；素材缓存默认 300MB
（`FGOUID_ART_CACHE_MB` 可调），所以一次只推一批，避免刚下好的图又被 LRU 淘汰。

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
python tools/sync_gacha.py --wiki /path/to/fgo-wiki    # 回填卡池 UP/横幅、活动名/横幅
python tools/sync_ce.py --wiki /path/to/fgo-wiki       # 礼装卡面/未破满破效果/ATK·HP
python tools/sync_cards.py                            # 从者卡模型（复用 wiki 解析器）
python tools/sync_bondce.py                           # 羁绊礼装反查表
```

`sync_gacha.py` 只读 wiki 的 `raw/`（不碰 MD）：卡池 UP 从者、卡池横幅（jsdelivr 上的
`karl2829/fgo-images`）、活动正式名与横幅都从这里回填；wiki 里 UP 空着、活动名写成 ID
的条目会在这步补上。

- 数据修正不写回 fgo-wiki，统一放在 `overrides/`（别名）或后续的修正层里

## 帮助卡图片

`fgo帮助` 在**安装插件的机器上自己渲染**：HTML/CSS → Skia 位图（pytakumi），不启浏览器。
渲染一次后写入 `data/FGOUID/help_<hash>.png` 缓存（数据或模板变了 hash 才变），后续直接读盘。

三级降级，任何一层挂了都不至于没图：

```
服务器端渲染（pytakumi） → 仓库内预渲染 assets/help.png → 纯文字命令表
```

依赖在 `pyproject.toml` 里声明（`pytakumi==0.1.5`），GsCore 的 `AutoInstallDep`
（默认开启）会在加载插件时自动安装；没装成也只是降级，不影响其它命令。

实测（2 核 2G 阿里云，容器内存上限 900M）：

| 场景 | 耗时 | 进程峰值 | 容器内存 |
|---|---|---|---|
| 首次渲染 dpr=2 | 1.1 s | +82 MB | 452 MiB |
| 缓存命中 | ~5 ms | — | — |
| 并发 4 张 | 4.4 s | +250 MB | 577 MiB |

并发用 `core/render.py` 的 `Semaphore(2)` 卡住——8 张并发能把容器顶到 840 MiB+，
逼近 900 MiB 上限。

### 三层结构（为将来换渲染后端留路）

| 层 | 文件 | 职责 |
|---|---|---|
| 模型 | `core/help_card.py: help_model()` | 纯数据：文案、数字、区块结构 |
| HTML 投影 | `core/help_card.py: help_html()` | 模型 → HTML 片段，配 `templates/help_card.html` 外框 |
| 渲染 | `core/render.py` | pytakumi 封装：字体注入、图片内联、并发送流、裁边 |

要改渲染引擎（例如换成 PIL），只需再写一个 `help_pil(model)`，模型层不动。
`templates/help_card.html` 只保留外框与 CSS，正文区块全部由模型投影生成。

### 版式素材

- `templates/help_card.html`：沿用 fgo-wiki `card-render` 的暗色主题（DARK-CHALDEA FRAME）
- `assets/emblem.png`：从 fgo-wiki 素材库裁出的迦勒底徽记（去掉了下方文字），已随仓库提交
- `assets/help.png`：降级用的预渲染图，开发机生成：

```bash
uv venv .render-venv && uv pip install --python .render-venv/bin/python pytakumi==0.1.5 pillow
PYTHONDONTWRITEBYTECODE=1 .render-venv/bin/python tools/render_help.py   # → assets/help.png
# 该脚本直接调用 core/help_card.py，与运行时渲染同源；改文案后重跑一次即可
```

## 功能规划（四块）

| 块 | 状态 | 内容 |
|---|---|---|
| 公共信息 | ✅ 可用 | `fgo从者` `fgo礼装` `fgo活动` `fgo卡池` |
| 个人数据 | 🚧 施工中 | `fgo登录` `fgo我的` `fgo刷新`（需绑定账号，抓包链接 / 扫码） |
| 趣味互动 | ✅ 部分可用 | `fgo今日老婆` `fgo每日一抽` `fgo图鉴`；`fgo年终总结` 施工中（需绑定账号） |
| 设置 | 🚧 部分可用 | `fgo设置` `fgo设置出图` `fgo下载资源` ✅；语言 中/日 施工中 |

`fgo帮助` 的图就是按这四块排的，未开放项标「施工中」。

## 从者卡（带立绘）

`fgo从者 摩根` 在服务器上现场渲染一张完整卡（立绘 / 六维 / 宝具五档 / 技能十格），
不是纯文字也不是预生成图片。

```
fgo-wiki MD ──(tools/sync_cards.py，复用 wiki 的 parse_servant)──► servant_cards 表（zlib）
                                                                      │
card/templates + card/assets（随包 1MB） + Atlas 按需素材（缓存）◄──────┤
                                                                      ▼
                                                    core/card.py → core/render.py（pytakumi）
```

- **数据**：458 个国服从者，模型 JSON 平均 4.3KB，压缩后共 0.57MB（DB 1.6→2.4MB），同步耗时 8 秒
- **素材**：随包 111 个小图标（职阶/星级/徽标/指令卡，800KB）；立绘（~500KB）、羁绊礼装（~600KB）、
  技能图标（~20KB）按需从 Atlas 下载，缓存在 `data/FGOUID/art/`，默认 300MB 上限 + LRU 淘汰
- **缓存**：渲染结果存 `data/FGOUID/cards/<id>_<hash>.png`，同一从者第二次是读盘
- **实测**（2C2G）：首次查询 ~6s（含立绘下载 4s）；缓存命中 2.3s；单张 1400KB / 2200×5516

> 开发期 `tools/sync_cards.py` 直接 import `fgo-wiki/card-render/build_data.py` 的 `parse_servant()`，
> 也就是「出图脚本先写在 wiki」的那一份；插件定型后把解析器一起拷进来，改成包内相对导入即可。

## 结构

```
FGOUID/
├── __init__.py            # 命令入口（GsCore SV）
├── core/db.py             # 只读查询层
├── core/render.py         # 服务器端 pytakumi 渲染（并发/字体/裁边）
├── core/help_card.py      # 帮助卡模型 → HTML 投影 + 缓存
├── core/card.py           # 从者卡：模型 → 素材 → 渲染 → 缓存
├── core/gacha_card.py     # 卡池日历卡（列表卡）：行模型 → HTML → 渲染 → 缓存
├── core/ce_card.py        # 礼装卡：craft_essences + ce_details → HTML → 渲染 → 缓存
├── core/settings.py       # 按群/按人的偏好（出图开关、语言），JSON 落 data/FGOUID
├── core/store.py          # 运行时可写目录
├── card/                  # 从 fgo-wiki/card-render 搬来的渲染实现
│   ├── build.py           #   数据模型 → HTML（模板填充）
│   ├── fetch.py           #   立绘/羁绊礼装/技能图标按需下载 + 缓存
│   ├── bondce.json        #   羁绊加成礼装反查（由 wiki 固化，107KB）
│   ├── cardkit/           #   pytakumi 渲染内核 + 调色板 + 羁绊礼装匹配
│   ├── templates/         #   servant_card_data.html
│   └── assets/            #   随包小素材（800KB）
├── data/fgo.db            # 索引快照
├── data/meta.json         # 来源版本
├── overrides/aliases.json # 别名覆盖
├── assets/help.png        # 降级用预渲染图
├── assets/emblem.png      # 迦勒底徽记
├── templates/help_card.html   # 帮助卡外框 + CSS，正文由模型投影
├── templates/list_card.html   # 列表卡外框 + CSS（卡池/活动共用）
├── templates/ce_card.html     # 礼装卡版式（左卡面右信息）
└── tools/
    ├── sync_from_wiki.py  # wiki → db
    └── render_help.py     # 生成降级用 assets/help.png（仅开发机）
```

## License

代码 MIT；数据遵循上游 CC BY-NC-SA 4.0。
