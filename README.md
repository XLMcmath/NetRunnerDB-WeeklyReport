# NetrunnerDB 每周牌组摘要

每周自动抓取 [netrunnerdb.com](https://netrunnerdb.com) 的官方精选与热门牌组，
生成一份**双击即可查看**的网页摘要（离线可读，含卡表与身份卡图）。

## 看哪里

| 文件 | 说明 |
| --- | --- |
| [`index.html`](index.html) | 存档目录，列出所有期数，点进去看某周 |
| `2026-W43/index.html` | **本期主视图**：统计概览 + 三个榜单 + 可展开的完整卡表 |
| `2026-W43/decks.md` | Markdown 版，方便贴到聊天/笔记 |
| `2026-W43/decklists/*.txt` | 单副牌组的纯文本卡表，可导入 jnet |
| `2026-W43/decks.json` | 结构化数据，方便自己再加工（画趋势图等） |
| `nrdb_weekly.py` | 抓取 + 生成脚本 |
| `card_names_zh.xlsx` | 卡牌中文名对照表（可选，填了才显示中文） |
| `run_weekly.ps1` | 运行入口（`-IfDue` / `-Force`） |
| `update_now.bat` | 双击立即更新 |

## 内容结构

1. **官方每周精选** — netrunnerdb.com/en/decklists/dotw 最近几期的官方推荐
2. **本周热门 Top 12** — 最近 7 天新建的牌组，按热度分排序
   （热度 = 赞×3 + 藏×2 + 评×1）
3. **官方人气榜** — netrunnerdb.com 自带的 Popular 排序（偏近期热度，和下面的算法不同）
4. **本周概览** — 新牌组数量、社区互动量、派系分布、热门特性（ID）Top 8

顶部的筛选条可以只看 **公司 / 潜袭者**，以及 **标准 / 新启**；选中状态写进 URL hash，可以直接把链接发给别人。
赛制是推断出来的（NRDB 不记录牌组赛制）：标题/简介里写了 startup → `新启`；
整副牌只用到新启卡池（System Gateway / Elevation / Vantage Point）→ `新启?`；有池外卡 → 标准。

**点区块标题即可收起/展开**（标题右侧小三角），状态记在浏览器里，下次打开还是上次的样子；
顶部「全部收起」一键折叠全部区块。

每副牌组：

- 右上角 `影响力 X/Y`：只累加**外派系**卡的影响力（含带影响力的中立卡，如 Baba Yaga 2）；
  超过上限时数字变橙色——这多半是特殊赛制/非常规牌组，不是算错了
- 卡表按 `数量 · 费用 · 卡名 · 影响力` 排列，费用在卡名**前面**（和实体牌左上角一致），
  只有外派系卡才标影响力徽章
- 左下角 **「复制链接」** 一键复制 NRDB 地址，粘到 jnet 的 Import 里即可导入
- **鼠标悬停卡名**会弹出中文卡图（社群 Sneakdoor Beta 的简中卡图；取不到时自动回退 NRDB 英文图），
  触屏设备点一下卡名也能看，点别处或按 Esc 关闭
- `纯文本牌表` 是 **jnet 能直接解析的格式**（`;; identity-code:` + `Nx 卡名`，不带编号后缀）

## 卡牌中文名（可选）

卡名默认显示英文。想显示中文，只要在同一目录放一份 `card_names_zh.xlsx`。
**现在这张表已经内置好了：2460 张卡里 2432 张有中文名**，你直接跑就有中文：

| code | name_en | name_zh | type | faction | side | decks | note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 30012 | Sure Gamble | 胜券在握 | event | neutral-runner | runner | 8 | Chinese_Tools / zhCN |

译名不是手打的，来自两个社区数据源（按英文名或卡号匹配，`note` 列标了来源）：

| 来源 | 内容 |
| --- | --- |
| [isNovel/NetrunnerDB_Chinese_Tools](https://github.com/isNovel/NetrunnerDB_Chinese_Tools) | 同一个作者的「NetrunnerDB 简中工具」扩展，内含 879 条译名（身份牌尤其全） |
| [Sneakdoor-BETA/netrunner-card-text-zhCN](https://github.com/Sneakdoor-BETA/netrunner-card-text-zhCN) | 《矩阵潜袭》卡牌中文文本数据，2000+ 张 |

- 想重新拉一遍/补新系列：`python nrdb_weekly.py --import-names`
  （**只填 `name_zh` 为空的行**，你手改过的内容不会被覆盖）
- **只填 `name_zh` 列**。`code`、`name_en` 别改，`type`/`faction`/`decks`/`note`
  是给你参考的（`decks` = 本周有几副牌组用了它，表格按它从大到小排）。
- 也可以只写 `name_en` + `name_zh`（`code` 留空），程序按英文名兜底匹配——
  这样同一张卡的不同重印版本也能一起翻到（英文名匹配忽略大小写、重音符、
  中英文引号和多余空格）。
- 用 Excel 直接改、直接保存即可，不必转 CSV。也支持 `.csv`
  （UTF-8 带/不带 BOM 都行，GBK 也认），列名认 `code` / `name_en` / `name_zh`
  以及“编号 / 英文名 / 中文名”这类写法。
- 每周补新卡：`python nrdb_weekly.py --harvest`，会把本周新出现的卡追加进表里，
  **已填的中文名不会被覆盖**。
- 用别的表：`python nrdb_weekly.py --names D:\somewhere\my_names.xlsx`。
- 效果：页面显示「中文名 + 英文原名（斜体小字）」；`decklists/*.txt` 保持英文，
  因为 jnet 靠英文名导入。

还剩 28 张没有译名，都是 Terminal Directive 战役卡
（`Evidence Collection 2`、`Machicolation A/B`、`Lt. Todachine` 这类变体），
`note` 列标着“待译”，需要的话自己补上即可。

实现原理和那个浏览器插件一样：卡牌始终以 `code` 为键（插件用页面里的
`NRDB.data.cards`，这里用 `/api/2.0/public/cards`），只在渲染时替换显示文字，
所以译名表加错了行也不会串卡。

## 每周自动更新

当前环境没有管理员权限，`schtasks` / `Register-ScheduledTask` 都会被拒绝，
所以用的是**开机自检**方案（已装好，无需再配置）：

| 位置 | 作用 |
| --- | --- |
| `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\NetrunnerDB Weekly Digest.vbs` | 登录时静默调用下面这行 |
| `run_weekly.ps1 -IfDue` | 检查最新一期是否已超过 ~6.5 天，是才跑；否则直接退出 |
| `run_weekly.ps1 -Force` | 无视新鲜度，立刻重跑 |
| `update_now.bat` | 双击立即更新并打开摘要 |

也就是说：每周第一次登录/开机时自动补齐当周摘要；同一周内再登录不会重复抓取。
日志在 `logs/runner.log`（每次运行一行）和 `logs/run_*.log`（保留 90 天）。

想改成固定时间（比如每周一 09:00），用**管理员** PowerShell 跑一次：

```powershell
$s = "C:\Users\Administrator\Documents\deepseek-harness\default-workspace\netrunnerdb-weekly\run_weekly.ps1"
Register-ScheduledTask -TaskName "NetrunnerDB Weekly Digest" `
  -Action (New-ScheduledTaskAction -Execute "powershell.exe" `
          -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$s`" -Force") `
  -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 9am) `
  -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable) -Force
```

装好计划任务后，记得删掉 Startup 里的 `NetrunnerDB Weekly Digest.vbs`，避免两套都跑。

关闭自动更新：删除 Startup 里那个 `.vbs` 即可。

## 手动运行

```powershell
# 最近 7 天（默认）
python nrdb_weekly.py

# 换窗口 / 收录数量
python nrdb_weekly.py --days 14 --top-hot 20 --top-dotw 8

# 不下载卡图、只看数据不写文件
python nrdb_weekly.py --no-images
python nrdb_weekly.py --dry-run
```

需要 Python 3.9+ 和 `lxml`（DSH 自带运行时已满足）。

## 备注

- 站点结构若改版，`parse_listing()` 里的 XPath 可能需要跟着调。
- 请求间隔 0.35s、失败重试 3 次，避免给站点添麻烦，请勿把 `--days` 调得过大。
- 卡牌与牌组内容版权归 Null Signal Games / FFG 及各作者所有，本工具仅做个人查阅用聚合。
