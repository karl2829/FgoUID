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
| `fgo帮助` | 命令列表 |

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

## 结构

```
FGOUID/
├── __init__.py            # 命令入口（GsCore SV）
├── core/db.py             # 只读查询层
├── data/fgo.db            # 索引快照
├── data/meta.json         # 来源版本
├── overrides/aliases.json # 别名覆盖
└── tools/sync_from_wiki.py
```

## License

代码 MIT；数据遵循上游 CC BY-NC-SA 4.0。
