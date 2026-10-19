#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NetrunnerDB 每周牌组摘要生成器
==============================

从 netrunnerdb.com 抓取三类内容，生成一份可直接双击打开的 HTML 摘要：

1. 官方「每周牌组」  /en/decklists/dotw       (Decklists of the Week)
2. 本周热门          /en/decklists/recent    (最近 N 天 + 点赞/收藏/评论热度排序)
3. 官方人气榜        /en/decklists           (站点自带 Popular 排序, 偏近期)

每次都输出到  <脚本目录>/<年-周>/  目录：
    index.html      主视图（离线可看，含本地缓存的牌组身份卡图）
    decks.md        Markdown 版（可直接贴到聊天/笔记）
    decks.json      结构化数据（便于二次处理、画趋势图）
    decklists/*.txt  NetrunnerDB 纯文本牌表（可导入 jnet）
并刷新 <脚本目录>/index.html 作为所有期数的存档目录。

用法:
    python nrdb_weekly.py                # 抓最近 7 天
    python nrdb_weekly.py --days 14      # 抓最近 14 天
    python nrdb_weekly.py --no-images    # 不下载卡图
    python nrdb_weekly.py --dry-run      # 只抓数据，不写文件

只依赖标准库 + lxml。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape as _escape
from pathlib import Path

import lxml.html


def esc(value) -> str:
    """HTML 转义（容忍非字符串输入）。"""
    return _escape(str(value), quote=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
SITE = "https://netrunnerdb.com"
API = SITE + "/api/2.0/public"

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"

SLEEP = 0.35  # 请求间隔，避免给站点添压力


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, flush=True)


def _request(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    return urllib.request.urlopen(req, timeout=timeout).read()


def fetch(url: str, retries: int = 3, timeout: int = 60) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            data = _request(url, timeout=timeout)
            time.sleep(SLEEP)
            return data
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            raise
        except Exception as e:  # noqa: BLE001 - 网络抖动统一重试
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"请求失败: {url} ({last})")


def fetch_text(url: str) -> str:
    return fetch(url).decode("utf-8", "replace")


def fetch_json(url: str):
    return json.loads(fetch(url).decode("utf-8"))


def cached_json(url: str, name: str, max_age_days: float):
    """带本地缓存的 JSON 下载（卡牌库不常变）。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if path.exists():
        age = (time.time() - path.stat().st_mtime) / 86400
        if age < max_age_days:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - 缓存损坏则重新下载
                pass
    data = fetch_json(url)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# --------------------------------------------------------------------------
# 站点元数据
# --------------------------------------------------------------------------

FACTION_META = {
    "anarch": ("Anarch", "runner", "#e08b0c"),
    "criminal": ("Criminal", "runner", "#3b82f6"),
    "shaper": ("Shaper", "runner", "#22a05a"),
    "neutral-runner": ("Neutral", "runner", "#7c8aa0"),
    "neutral": ("Neutral", "neutral", "#7c8aa0"),
    "apex": ("Apex", "runner", "#8b7ba8"),
    "adam": ("Adam", "runner", "#6f8faf"),
    "sunny-lebeau": ("Sunny Lebeau", "runner", "#d98f4a"),
    "haas-bioroid": ("Haas-Bioroid", "corp", "#8b5cf6"),
    "jinteki": ("Jinteki", "corp", "#e5484d"),
    "nbn": ("NBN", "corp", "#eab308"),
    "weyland-consortium": ("Weyland", "corp", "#0e9f8a"),
    "neutral-corp": ("Neutral", "corp", "#7c8aa0"),
}

TYPE_ORDER = {
    "corp": ["identity", "agenda", "asset", "upgrade", "operation", "ice"],
    "runner": ["identity", "event", "hardware", "program", "resource"],
}

TYPE_LABEL = {
    "identity": ("身份", "Identity"),
    "event": ("事件", "Event"),
    "hardware": ("硬件", "Hardware"),
    "program": ("程序", "Program"),
    "resource": ("资源", "Resource"),
    "agenda": ("议案", "Agenda"),
    "asset": ("资产", "Asset"),
    "upgrade": ("升级", "Upgrade"),
    "operation": ("事务", "Operation"),
    "ice": ("防火墙", "ICE"),
    "other": ("其他", "Other"),
}

# 双方阵营的中文叫法（潜袭者=Runner，公司=Corp）
SIDE_LABEL = {"runner": "潜袭者", "corp": "公司"}


def faction_display(code: str, side: str = ""):
    if code in FACTION_META:
        return FACTION_META[code]
    label = " ".join(w.capitalize() for w in (code or "").replace("-", " ").split()) or "Unknown"
    return (label, side or "neutral", "#7c8aa0")


# --------------------------------------------------------------------------
# 列表页解析
# --------------------------------------------------------------------------

UUID_RE = re.compile(r"/decklist/([0-9a-fA-F-]{36})/")


def parse_listing(html: str) -> list[dict]:
    """解析 /en/decklists、/recent、/dotw、/popular 的列表行。"""
    doc = lxml.html.fromstring(html)
    rows = []
    for entry in doc.xpath('//div[@class="media"]'):
        links = entry.xpath('.//div[contains(@class,"h4")]//a[starts-with(@href,"/en/decklist/")]')
        if not links:
            continue
        try:
            link = links[0]
            href = link.get("href") or ""
            m = UUID_RE.search(href)
            if not m:
                continue
            uuid = m.group(1)

            img = entry.xpath('.//img[contains(@class,"card-image")]')
            img_src = (img[0].get("data-src") or img[0].get("src") or "") if img else ""
            identity_title = norm_ws(img[0].get("alt")) if img else ""
            identity_code = ""
            mc = re.search(r"/(\d{5})\.jpg", img_src)
            if mc:
                identity_code = mc.group(1)

            social_div = entry.xpath('.//div[contains(@class,"social")]')
            counts = []
            if social_div:
                counts = [int(x) for x in re.findall(r"\d+", social_div[0].text_content())]
            votes, favs, comments = (counts + [0, 0, 0])[:3]

            prof = entry.xpath('.//a[starts-with(@href,"/en/profile/")]')
            author = norm_ws(prof[0].text_content()) if prof else ""
            author_url = SITE + prof[0].get("href") if prof else ""

            rep = ""
            reps = entry.xpath('.//small[contains(@class,"reputation")]')
            if reps:
                rep = norm_ws(reps[0].text_content())

            def pick(cls: str) -> str:
                nodes = entry.xpath(f'.//span[contains(@class,"{cls}")]')
                return norm_ws(nodes[0].text_content()) if nodes else ""

            times = entry.xpath(".//time")
            dt = parse_dt(times[0].get("datetime")) if times else None

            rows.append(
                {
                    "uuid": uuid,
                    "url": SITE + href,
                    "title": norm_ws(link.text_content()),
                    "identity_title": identity_title,
                    "identity_code": identity_code,
                    "author": author,
                    "author_url": author_url,
                    "reputation": rep,
                    "votes": votes,
                    "favorites": favs,
                    "comments": comments,
                    "faction": "",
                    "side": "",
                    "event": pick("text-success"),
                    "rotation": pick("text-info"),
                    "date": dt.isoformat() if dt else "",
                }
            )
        except Exception:  # noqa: BLE001 - 单行解析失败不影响整页
            continue
    return rows


def hot_score(deck: dict) -> int:
    """热度分：点赞权重最高，其次收藏，再次评论。"""
    return deck["votes"] * 3 + deck["favorites"] * 2 + deck["comments"] * 1


# --------------------------------------------------------------------------
# 抓取
# --------------------------------------------------------------------------

def scan_recent(days: int, max_pages: int = 14) -> tuple[list[dict], int]:
    """翻 /recent 直到越过时间窗口，返回窗口内全部牌组与扫描总数。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    collected, scanned = [], 0
    for page in range(1, max_pages + 1):
        url = f"{SITE}/en/decklists/recent" if page == 1 else f"{SITE}/en/decklists/recent/{page}"
        rows = parse_listing(fetch_text(url))
        if not rows:
            break
        scanned += len(rows)
        older = 0
        for row in rows:
            dt = parse_dt(row["date"])
            if dt and dt >= cutoff:
                collected.append(row)
            else:
                older += 1
        log(f"  recent 第 {page} 页: {len(rows)} 条，窗口内累计 {len(collected)}")
        if older == len(rows):
            break
    return collected, scanned


def fetch_dotw(limit: int) -> list[dict]:
    rows = parse_listing(fetch_text(f"{SITE}/en/decklists/dotw"))
    return rows[:limit]


def fetch_popular(limit: int) -> list[dict]:
    rows = parse_listing(fetch_text(f"{SITE}/en/decklists"))
    return rows[:limit]


def load_cards() -> tuple[dict, dict]:
    """牌张元数据（标题/类型/阵营），本地缓存 30 天。返回 (按编号, 按标题)。"""
    data = cached_json(f"{API}/cards", "cards.json", max_age_days=30)
    by_code, by_title = {}, {}
    for card in data.get("data", []):
        meta = {
            "code": card["code"],
            "title": card.get("title", ""),
            "type": card.get("type_code", ""),
            "faction": card.get("faction_code", ""),
            "side": card.get("side_code", ""),
            "cost": card.get("cost"),
            "faction_cost": card.get("faction_cost"),
            "agenda_points": card.get("agenda_points"),
            # 特性牌才有：影响力上限、牌组张数下限
            "influence_limit": card.get("influence_limit"),
            "minimum_deck_size": card.get("minimum_deck_size"),
        }
        by_code[meta["code"]] = meta
        by_title.setdefault(meta["title"].lower(), meta)
    return by_code, by_title


def resolve_identities(rows: list[dict], by_code: dict, by_title: dict) -> list[dict]:
    """列表页只给了身份名/图号，用卡库补全阵营与阵营侧。"""
    for row in rows:
        meta = by_code.get(row.get("identity_code", "")) or by_title.get(
            (row.get("identity_title") or "").lower()
        )
        if meta:
            row["faction"] = meta["faction"]
            row["side"] = meta["side"]
            if meta["title"]:
                row["identity_title"] = meta["title"]
    return rows


# --------------------------------------------------------------------------
# 中文译名表
# --------------------------------------------------------------------------
# 支持 Excel（.xlsx，推荐：直接用 Excel 填，不必转 CSV）与 .csv。
# 只需两列有效内容：卡牌编号 code + 中文名 name_zh；name_en 用来核对。
# 也允许只写英文名（name_en）+ 中文名，程序按英文名兜底匹配。

COL_ALIASES = {
    "code": {"code", "card_code", "cardcode", "card", "number", "编号", "卡号", "卡牌编号"},
    "en": {"name_en", "en", "english", "english_name", "name", "英文", "英文名", "原名"},
    "zh": {"name_zh", "zh", "cn", "chinese", "chinese_name", "中文", "中文名", "译名", "翻译"},
    "note": {"note", "备注", "来源", "source"},
}


def _norm_name(value: str) -> str:
    """英文名归一化：忽略大小写、重音符、弯引号、多余空格，方便手填的表格对上。"""
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    for a, b in (("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'"), ("–", "-"), ("—", "-")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


def _norm_header(value) -> str:
    return re.sub(r"[\s_\-]+", "", str(value or "").strip().lower())


def _header_role(value) -> str | None:
    v = _norm_header(value)
    for role, aliases in COL_ALIASES.items():
        if v in {_norm_header(a) for a in aliases}:
            return role
    return None


def _rows_from_xlsx(path: Path) -> list[list]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _rows_from_csv(path: Path) -> list[list]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    return [row for row in csv.reader(io.StringIO(text))]


def load_name_table(path: Path) -> tuple[dict, dict, dict]:
    """读译名表，返回 (code→中文, 英文名小写→中文, 统计信息)。"""
    by_code: dict[str, str] = {}
    by_title: dict[str, str] = {}
    info = {"path": str(path), "rows": 0, "used": 0}

    if not path or not Path(path).exists():
        return by_code, by_title, info

    path = Path(path)
    rows = _rows_from_xlsx(path) if path.suffix.lower() in (".xlsx", ".xlsm") else _rows_from_csv(path)

    header_idx, roles = None, {}
    for idx, row in enumerate(rows[:10]):
        found = {}
        for col, cell in enumerate(row):
            role = _header_role(cell)
            if role and role not in found:
                found[role] = col
        if "zh" in found and ("code" in found or "en" in found):
            header_idx, roles = idx, found
            break
    if header_idx is None:
        return by_code, by_title, info

    for row in rows[header_idx + 1:]:
        def cell(role):
            col = roles.get(role)
            if col is None or col >= len(row):
                return ""
            return str(row[col] or "").strip()

        zh = cell("zh")
        if not zh:
            continue
        info["rows"] += 1
        code = cell("code")
        en = cell("en")
        if code:
            by_code[code] = zh
        if en:
            by_title[_norm_name(en)] = zh
        info["used"] += 1

    return by_code, by_title, info


def pick_name_table(explicit: str | None) -> Path | None:
    """--names 优先（相对路径先按当前目录、再按脚本目录找）；否则自动找默认文件名。"""
    if explicit:
        p = Path(explicit)
        if p.is_absolute():
            return p
        for base in (Path.cwd(), HERE):
            cand = base / p
            if cand.exists():
                return cand
        return Path.cwd() / p
    for name in ("card_names_zh.xlsx", "card_names_zh.csv"):
        p = HERE / name
        if p.exists():
            return p
    return None


def translate(code: str, en: str, names) -> str:
    by_code, by_title = names
    return by_code.get(code or "") or by_title.get(_norm_name(en), "")


def read_name_sheet(path: Path) -> list[dict]:
    """把译名表读成 [{code, en, zh}]，用于 --harvest 时保留已翻译的行。"""
    if not path or not Path(path).exists():
        return []
    path = Path(path)
    rows = _rows_from_xlsx(path) if path.suffix.lower() in (".xlsx", ".xlsm") else _rows_from_csv(path)
    header_idx, roles = None, {}
    for idx, row in enumerate(rows[:10]):
        found = {}
        for col, cell in enumerate(row):
            role = _header_role(cell)
            if role and role not in found:
                found[role] = col
        if "zh" in found and ("code" in found or "en" in found):
            header_idx, roles = idx, found
            break
    if header_idx is None:
        return []
    out = []
    for row in rows[header_idx + 1:]:
        def cell(role):
            col = roles.get(role)
            if col is None or col >= len(row):
                return ""
            return str(row[col] or "").strip()
        if cell("code") or cell("en"):
            out.append({"code": cell("code"), "en": cell("en"), "zh": cell("zh"), "note": cell("note")})
    return out


def write_name_sheet(path: Path, records: dict) -> dict:
    """把 {code: 记录} 写成译名表（xlsx 优先，含填写说明页）。"""
    order_side = {"runner": 0, "corp": 1}
    order_type = {t: i for i, t in enumerate(
        ["identity", "event", "hardware", "program", "resource", "agenda", "asset", "upgrade", "operation", "ice"])}
    rows = sorted(
        records.values(),
        key=lambda r: (-(int(r.get("decks") or 0)), order_side.get(r.get("side", ""), 2),
                       order_type.get(r.get("type", ""), 9), (r.get("en") or "").lower()),
    )

    header = ["code", "name_en", "name_zh", "type", "faction", "side", "decks", "note"]
    table = [header] + [[r.get("code", ""), r.get("en", ""), r.get("zh", ""), r.get("type", ""),
                         r.get("faction", ""), r.get("side", ""), r.get("decks", ""), r.get("note", "")]
                        for r in rows]

    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = "card_names_zh"
        for row in table:
            ws.append(row)
        head_fill = PatternFill("solid", fgColor="1F3864")
        for col in range(1, len(header) + 1):
            c = ws.cell(row=1, column=col)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = head_fill
            c.alignment = Alignment(vertical="center")
        widths = [10, 42, 32, 12, 16, 9, 8, 24]
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(header))}{ws.max_row}"

        tips = wb.create_sheet("填写说明")
        for line in [
            ["卡牌中文名对照表 · 使用说明"],
            [""],
            ["1. 只填 name_zh 列（中文名）。code、name_en 不要改，其他列是参考信息。"],
            ["2. 也可以只写 name_en + name_zh，把 code 留空；程序会按英文名兜底匹配，"],
            ["   这样同一张卡的重印版本（编号不同、英文名相同）也能一起翻到。"],
            ["3. decks 列 = 本周有几副牌组用了这张卡，表格按它从大到小排，先改高频的更划算。"],
            ["4. 改完保存（.xlsx 直接存，不用转 CSV），然后重新运行 nrdb_weekly.py"],
            ["   或双击 update_now.bat，页面就会显示「中文名 + 英文原名」。"],
            ["5. 补新卡：python nrdb_weekly.py --harvest"],
            ["   把本周新出现的卡追加进来，已填的中文名不会被覆盖。"],
            ["6. 重新导入社区译名：python nrdb_weekly.py --import-names"],
            ["   只填 name_zh 为空的行，你手改过的内容不会被覆盖。"],
            ["7. 也可以另存成 CSV（UTF-8 或 GBK 都认，列名 code/name_en/name_zh）。"],
            ["8. 不想显示中文：清空 name_zh 列，或删掉本文件即可。"],
            [""],
            ["note 列含义：Chinese_Tools / zhCN = 自动导入的社区译名；空 = 手填或本周采集。"],
            ["待译 = 社区数据里也没有，需要人工补。"],
            [""],
            ["英文名匹配容忍大小写、重音符、中英文引号与空格差异。"],
            ["注意：decklists/*.txt 始终保留英文名，因为 jnet 靠英文名导入。"],
        ]:
            tips.append(line)
        tips.column_dimensions["A"].width = 78
        for cell in tips["A"]:
            cell.alignment = Alignment(vertical="center", wrap_text=False)
        tips["A1"].font = Font(bold=True, size=13)
        wb.save(path)
    else:
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            csv.writer(fh).writerows(table)

    total = len(rows)
    done = sum(1 for r in rows if r.get("zh"))
    return {"path": str(path), "total": total, "translated": done, "missing": total - done}


def _prev_records(existing: list[dict]) -> dict[str, dict]:
    """把已有表读成 {code: 记录}，用来保留用户已填内容。"""
    out = {}
    for row in existing:
        key = row["code"] or ("en:" + row["en"].lower())
        out[key] = {"code": row["code"], "en": row["en"], "zh": row["zh"],
                    "type": "", "faction": "", "side": "", "decks": "",
                    "note": row.get("note", "")}
    return out


def _deck_card_counts(decks: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for deck in decks:
        for group in deck["groups"]:
            for item in group["items"]:
                counts[item["code"]] = counts.get(item["code"], 0) + 1
        if deck.get("identity_code"):
            counts[deck["identity_code"]] = counts.get(deck["identity_code"], 0) + 1
    return counts


def harvest_records(decks: list[dict], cards: dict, existing: list[dict]) -> dict:
    """本周出现的卡牌 → 记录（保留已有中文名）。"""
    records = _prev_records(existing)
    for code, n in _deck_card_counts(decks).items():
        meta = cards.get(code, {})
        en = meta.get("title", "")
        key = code or ("en:" + en.lower())
        rec = records.setdefault(key, {"code": code, "en": en, "zh": "", "type": "",
                                       "faction": "", "side": "", "decks": "", "note": ""})
        rec["en"] = rec.get("en") or en
        rec["type"] = meta.get("type", "")
        rec["faction"] = faction_display(meta.get("faction", ""), meta.get("side", ""))[0]
        rec["side"] = meta.get("side", "")
        rec["decks"] = str(n)
    return records


# ---- 社区译名数据（两个来源，均按英文名匹配，不依赖编号） ----

COMMUNITY_SOURCES = [
    ("Chinese_Tools",
     "https://raw.githubusercontent.com/isNovel/NetrunnerDB_Chinese_Tools/HEAD/NETRUNNERTOOLS/translation.json"),
    ("zhCN",
     "https://raw.githubusercontent.com/Sneakdoor-BETA/netrunner-card-text-zhCN/HEAD/data/json/cards.json"),
]


def _slug_variants(title: str) -> list[str]:
    """同一张卡可能被写成「O₂ Shortage」「O2 Shortage」「O Shortage」，多给几个候选。"""
    out = []
    for base in (title, _straight_quotes(title)):
        normalized = unicodedata.normalize("NFKD", base)
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))
        for form in (normalized, base):  # base 保留 ₂ 之类，交给正则当分隔符
            for amp in ("and", ""):
                s = form.replace("&", f" {amp} " if amp else " ")
                for apos in ("", "_"):
                    x = re.sub(r"[^a-zA-Z0-9]+", "_", s.replace("'", apos)).strip("_").lower()
                    if x:
                        out.append(x)
    return out


def _straight_quotes(s: str) -> str:
    for a, b in (("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'"), ("–", "-"), ("—", "-")):
        s = s.replace(a, b)
    return s


def load_community_names() -> tuple[dict, dict]:
    """返回 (英文名小写 → 中文, slug → 中文)。缓存 7 天。"""
    by_title, by_slug = {}, {}
    for label, url in COMMUNITY_SOURCES:
        try:
            data = cached_json(url, f"community_{label}.json", max_age_days=7)
        except Exception as e:  # noqa: BLE001 - 源不可达时降级
            log(f"   ! 社区数据 {label} 拉取失败: {e}")
            continue
        if isinstance(data, dict):                      # translation.json: title -> zh
            for k, v in data.items():
                if isinstance(v, str) and v.strip():
                    by_title.setdefault(k.lower(), v.strip())
                    by_title.setdefault(_straight_quotes(k).lower(), v.strip())
                    for s in _slug_variants(k):
                        by_slug.setdefault(s, v.strip())
        else:                                            # cards.json: [{id, name}]
            for card in data:
                name = (card.get("name") or "").strip()
                if name and card.get("id"):
                    by_slug.setdefault(card["id"], name)
    return by_title, by_slug


def community_lookup(title: str, by_title: dict, by_slug: dict) -> str:
    for key in (title, _straight_quotes(title)):
        hit = by_title.get(key.lower())
        if hit:
            return hit
    for slug in _slug_variants(title):
        hit = by_slug.get(slug)
        if hit:
            return hit
    return ""


def import_records(cards: dict, existing: list[dict]) -> dict:
    """用社区译名补全整张表：已有中文名的行不动，只填空行。"""
    records = _prev_records(existing)
    by_title, by_slug = load_community_names()
    filled = 0
    for code, meta in cards.items():
        en = meta.get("title", "")
        key = code or ("en:" + en.lower())
        rec = records.setdefault(key, {"code": code, "en": en, "zh": "", "type": "",
                                       "faction": "", "side": "", "decks": "", "note": ""})
        rec["en"] = rec.get("en") or en
        rec["type"] = meta.get("type", "") or rec.get("type", "")
        rec["faction"] = faction_display(meta.get("faction", ""), meta.get("side", ""))[0]
        rec["side"] = meta.get("side", "") or rec.get("side", "")
        if not rec.get("zh"):
            zh = community_lookup(en, by_title, by_slug)
            if zh:
                rec["zh"] = zh
                rec["note"] = "Chinese_Tools / zhCN"
                filled += 1
            else:
                rec["note"] = "待译"
        elif not rec.get("note"):
            rec["note"] = ""
    log(f"   社区译名补全 {filled} 张")
    return records



def fetch_deck(uuid: str) -> dict | None:
    try:
        payload = fetch_json(f"{API}/decklist/{uuid}")
        return payload["data"][0]
    except Exception as e:  # noqa: BLE001
        log(f"  ! 牌组 {uuid} 抓取失败: {e}")
        return None


# --------------------------------------------------------------------------
# 牌组详情整理
# --------------------------------------------------------------------------

def build_deck(deck: dict, raw: dict, cards: dict, names=({}, {})) -> dict:
    """把 API 详情整理成模板需要的结构。names = (code→中文, 英文名→中文)。"""
    slots = raw.get("cards") or {}
    identity_code, identity_name, identity_faction = "", "", ""
    grouped: dict[str, list] = {}

    for code, qty in slots.items():
        meta = cards.get(code, {})
        ctype = meta.get("type") or "other"
        if ctype == "identity":
            identity_code = code
            identity_name = meta.get("title", "")
            identity_faction = meta.get("faction", "")
            continue
        item = {
            "code": code,
            "title": meta.get("title", f"[{code}]"),
            "title_zh": translate(code, meta.get("title", ""), names),
            "cost": meta.get("cost"),
            "faction": meta.get("faction", ""),
            "faction_cost": meta.get("faction_cost"),
            "qty": int(qty),
        }
        grouped.setdefault(ctype, []).append(item)

    ident_meta = cards.get(identity_code, {})
    faction_code = ident_meta.get("faction") or deck.get("faction", "")
    side = ident_meta.get("side") or deck.get("side") or ""
    if side not in ("corp", "runner"):
        side = "corp" if faction_code in ("haas-bioroid", "jinteki", "nbn", "weyland-consortium") else "runner"

    order = TYPE_ORDER.get(side, TYPE_ORDER["runner"])
    for extra in sorted(grouped):
        if extra not in order:
            order.append(extra)

    groups = []
    for ctype in order:
        items = grouped.get(ctype)
        if not items:
            continue
        items.sort(key=lambda x: (x["title"].lower()))
        zh, en = TYPE_LABEL.get(ctype, TYPE_LABEL["other"])
        groups.append({"type": ctype, "label_zh": zh, "label_en": en, "items": items,
                       "count": sum(i["qty"] for i in items)})

    n_cards = sum(i["qty"] for g in groups for i in g["items"])
    agenda_pts = sum(
        int(i["qty"]) * int(cards.get(i["code"], {}).get("agenda_points") or 0)
        for g in groups if g["type"] == "agenda" for i in g["items"]
    )

    # 影响力：只跳过「与本特性同派系」的卡；中立卡也可能带影响力成本（如 Baba Yaga 2）
    influence = 0
    for group in groups:
        for item in group["items"]:
            if item["faction"] and item["faction"] == faction_code:
                continue
            influence += int(item["qty"]) * int(item["faction_cost"] or 0)
            # 外派系卡标出自身影响力，方便逐张核对
            if (item["faction_cost"] or 0) > 0:
                item["inf"] = int(item["faction_cost"])

    fname, _, color = faction_display(faction_code, side)
    ident_en = identity_name or deck.get("identity_title", "")
    return {
        **deck,
        "identity_code": identity_code or deck.get("identity_code", ""),
        "identity_title": ident_en,
        "identity_zh": translate(identity_code, ident_en, names),
        "faction_name": fname,
        "faction_color": color,
        "side": side,
        "n_cards": n_cards,
        "agenda_points": agenda_pts,
        "influence": influence,
        "influence_limit": ident_meta.get("influence_limit"),
        "min_deck_size": ident_meta.get("minimum_deck_size"),
        "score": hot_score(deck),
        "groups": groups,
        # 作者写的 deck 说明不转载（体积大、版权归作者），需要时去 NetrunnerDB 看
        "api_votes": raw.get("votes_count"),
        "api_favorites": raw.get("favorites_count"),
        "api_comments": raw.get("comments_count"),
    }


def decklist_txt(deck: dict) -> str:
    """jnet 可直接粘贴导入的牌表格式。

    jnet 的解析规则（deckbuilder.cljs）：
      · 每张卡：`<数量>x <英文卡名>`，卡名后面不能再跟任何东西（(12345) 会被当成卡名的一部分）
      · 特性：`;; identity-code: <编号>` 或 `;; identity: <英文名>`
      · 其它元信息：`;; title:` / `;; notes:`
    所以这里不写编号，编号在 decks.json 里。
    """
    lines = [
        f';; title: {deck["title"]}',
        f';; identity-code: {deck["identity_code"]}',
    ]
    if deck.get("url"):
        lines.append(f';; notes: {deck["url"]}')
    lines.append("")
    for group in deck["groups"]:
        lines.append(f'{group["label_en"]} ({group["count"]})')
        for item in group["items"]:
            lines.append(f'{item["qty"]}x {item["title"]}')
        lines.append("")
    return "\n".join(lines)


def decklist_md(deck: dict) -> str:
    out = []
    out.append(f'### {deck["title"]}')
    ident = deck.get("identity_title", "")
    if deck.get("identity_zh"):
        ident = f'{deck["identity_zh"]}（{ident}）'
    meta = [f"**{ident}**"]
    if deck.get("author"):
        meta.append(f'作者 [{deck["author"]}]({deck["author_url"]})')
    if deck.get("event"):
        meta.append(deck["event"])
    meta.append(f'{deck.get("n_cards", 0)} 张')
    if deck.get("agenda_points"):
        meta.append(f'{deck["agenda_points"]} 议案分数')
    meta.append(f'♥{deck["votes"]} ★{deck["favorites"]} 💬{deck["comments"]}')
    if deck.get("date"):
        meta.append(deck["date"][:10])
    out.append(" · ".join(meta))
    out.append("")
    out.append(f'[在 NetrunnerDB 打开]({deck["url"]})')
    out.append("")
    for group in deck["groups"]:
        out.append(f'**{group["label_zh"]} / {group["label_en"]} ({group["count"]})**')
        out.append("")
        out.append(", ".join(
            f'{i["qty"]}× {(i.get("title_zh") or i["title"])}' for i in group["items"]
        ))
        out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------
# 统计
# --------------------------------------------------------------------------

def compute_stats(window: list[dict], names=({}, {})) -> dict:
    factions: dict[str, int] = {}
    identities: dict[str, int] = {}
    sides = {"runner": 0, "corp": 0}
    votes = favs = comments = 0

    for deck in window:
        code = deck.get("faction") or ""
        name, side, _ = faction_display(code, deck.get("side", ""))
        factions[name] = factions.get(name, 0) + 1
        if side in sides:
            sides[side] += 1
        ident_en = deck.get("identity_title") or "Unknown"
        ident = translate(deck.get("identity_code", ""), ident_en, names) or ident_en
        identities[ident] = identities.get(ident, 0) + 1
        votes += deck.get("votes", 0)
        favs += deck.get("favorites", 0)
        comments += deck.get("comments", 0)

    top_ids = sorted(identities.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    return {
        "total": len(window),
        "factions": sorted(factions.items(), key=lambda kv: -kv[1]),
        "identities": top_ids,
        "sides": sides,
        "votes": votes,
        "favorites": favs,
        "comments": comments,
        "unique_identities": len(identities),
    }


# --------------------------------------------------------------------------
# 图片
# --------------------------------------------------------------------------

def download_identity_images(deck_codes: list[str], img_dir: Path) -> set[str]:
    """下载身份卡小图，返回本地可用的 code 集合。"""
    img_dir.mkdir(parents=True, exist_ok=True)
    ok = set()
    for code in sorted({c for c in deck_codes if c}):
        target = img_dir / f"{code}.jpg"
        if target.exists() and target.stat().st_size > 0:
            ok.add(code)
            continue
        for size in ("small", "tiny"):
            try:
                data = fetch(f"https://card-images.netrunnerdb.com/v2/{size}/{code}.jpg",
                             retries=2, timeout=45)
                if len(data) > 500:
                    target.write_bytes(data)
                    ok.add(code)
                    break
            except Exception:  # noqa: BLE001
                continue
    return ok


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

CSS = """
:root{
  --bg:#0d1117; --bg2:#131a24; --card:#161e2b; --line:#233042;
  --txt:#e6edf3; --muted:#8b9bb0; --dim:#5f7085;
  --accent:#4cc38a; --accent2:#58a6ff; --warn:#f0a83c;
  --radius:14px;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:
    radial-gradient(1100px 500px at 12% -10%, #16304a 0%, transparent 60%),
    radial-gradient(900px 420px at 88% 0%, #1c3a2e 0%, transparent 55%),
    var(--bg);
  color:var(--txt);
  font:15px/1.62 "Noto Sans SC","Microsoft YaHei","PingFang SC",-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;
}
a{color:inherit;text-decoration:none}
.wrap{max-width:1180px;margin:0 auto;padding:0 22px 64px}
code,.mono{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace}

/* ---------- hero ---------- */
.hero{padding:46px 0 26px;border-bottom:1px solid var(--line);margin-bottom:30px}
.kicker{display:inline-flex;align-items:center;gap:8px;font-size:12.5px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--accent);font-weight:600}
.kicker .dot{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent)}
h1{font-size:42px;line-height:1.12;margin:14px 0 10px;letter-spacing:-.02em;font-weight:800}
h1 .light{font-weight:300;color:var(--muted)}
.hero p{margin:0;color:var(--muted);font-size:15.5px}
.hero-tags{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
.htag{font-size:12.5px;color:var(--muted);border:1px solid var(--line);border-radius:999px;
  padding:4px 11px;background:#ffffff05}
.htag b{color:var(--txt);font-weight:600}
.jump{display:flex;flex-wrap:wrap;gap:9px;margin-top:16px}
.jumpitem{font-size:13px;border:1px solid #2c3f56;border-radius:9px;padding:6px 12px;
  background:#ffffff07;color:#c9d5e3;transition:border-color .15s,background .15s}
.jumpitem:hover{border-color:var(--accent);background:#4cc38a14;color:#fff}
.jumpitem b{color:var(--accent);font-weight:700;margin-left:3px}
.jumpitem.toggleall{font:inherit;font-size:12.6px;font-family:inherit;cursor:pointer;
  background:#ffffff07;color:var(--muted)}
.jumpitem.toggleall:hover{color:#fff}

/* ---------- stat grid ---------- */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:0 0 26px}
.stat{background:linear-gradient(180deg,#ffffff08,#ffffff02);border:1px solid var(--line);
  border-radius:var(--radius);padding:16px 18px}
.stat .k{font-size:12.5px;color:var(--dim);letter-spacing:.06em}
.stat .v{font-size:29px;font-weight:750;letter-spacing:-.02em;margin-top:2px}
.stat .v small{font-size:13px;font-weight:500;color:var(--muted);margin-left:5px}

/* ---------- panels ---------- */
.panels{display:grid;grid-template-columns:1.15fr .85fr;gap:16px;margin-bottom:36px}
.panel{background:var(--bg2);border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px}
.panel h3{margin:0 0 14px;font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);font-weight:700}
.bar{margin-bottom:9px}
.bar .lab{display:flex;justify-content:space-between;font-size:13.5px;margin-bottom:4px}
.bar .lab span:last-child{color:var(--muted);font-variant-numeric:tabular-nums}
.bar .track{height:7px;border-radius:4px;background:#ffffff0d;overflow:hidden}
.bar .fill{height:100%;border-radius:4px;background:var(--accent);transition:width .3s}
.idlist{display:flex;flex-direction:column;gap:7px}
.idrow{display:flex;align-items:center;gap:10px;font-size:13.8px}
.idrow .n{color:var(--dim);width:18px;text-align:right;font-variant-numeric:tabular-nums}
.idrow .t{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.idrow .c{color:var(--muted);font-variant-numeric:tabular-nums}

/* ---------- section ---------- */
section{margin-bottom:46px}
.sec-head{display:flex;align-items:baseline;gap:12px;border-bottom:1px solid var(--line);
  padding-bottom:10px;margin-bottom:18px;cursor:pointer;user-select:none}
.sec-head:hover h2{color:#fff}
.sec-head:focus-visible{outline:2px solid var(--accent2);outline-offset:3px;border-radius:4px}
.sec-head h2{font-size:21px;margin:0;font-weight:750;letter-spacing:-.01em}
.sec-head .num{font-size:13px;color:var(--accent);font-weight:700;letter-spacing:.1em}
.sec-head .hint{margin-left:auto;font-size:12.5px;color:var(--dim)}
.sec-head .caret{font-size:12px;color:var(--dim);margin-left:10px;transition:transform .18s}
.sec-head[aria-expanded="false"] .caret{transform:rotate(-90deg)}
.sec.is-collapsed .sec-body{display:none}

/* ---------- deck card ---------- */
.deck{background:linear-gradient(180deg,#ffffff07,#ffffff02);border:1px solid var(--line);
  border-left:3px solid var(--fc,#4cc38a);border-radius:var(--radius);padding:16px 18px;margin-bottom:14px}
.deck-top{display:flex;gap:16px;align-items:flex-start}
.idimg{width:66px;height:92px;border-radius:8px;object-fit:cover;flex:none;
  background:#0b1017;border:1px solid #ffffff14;box-shadow:0 6px 18px #0006}
.idimg.empty{display:flex;align-items:center;justify-content:center;color:var(--dim);font-size:10px}
.dmain{flex:1;min-width:0}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
.tag{font-size:11.5px;padding:2.5px 8px;border-radius:6px;background:#ffffff0d;color:var(--muted);
  border:1px solid #ffffff10;white-space:nowrap}
.tag.hot{background:#f0a83c1f;color:#f0a83c;border-color:#f0a83c40}
.tag.dotw{background:#4cc38a1f;color:var(--accent);border-color:#4cc38a40}
.tag.alltime{background:#58a6ff1f;color:var(--accent2);border-color:#58a6ff40}
.tag.rank{background:#ffffff12;color:#e6edf3;border-color:#ffffff26;font-weight:700;
  font-variant-numeric:tabular-nums;min-width:28px;text-align:center}
.tchips{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
.tchip{font-size:11.5px;color:var(--dim);border:1px solid #ffffff12;border-radius:5px;
  padding:1.5px 7px;background:#ffffff05}
.tchip b{color:#9fb0c6;font-weight:600}
.deck h4{margin:0 0 4px;font-size:17.5px;font-weight:700;line-height:1.35;letter-spacing:-.01em}
.deck h4 a:hover{color:var(--accent2)}
.idname{font-size:13.5px;color:var(--muted);margin-bottom:8px}
.idname b{color:#c9d5e3;font-weight:600}
.idname .ce{font-size:12.2px;color:var(--dim);font-style:italic;margin-left:6px}
.meta{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--dim)}
.meta b{color:var(--muted);font-weight:600}
.meta .social{color:#c9d5e3;font-variant-numeric:tabular-nums}
.right{flex:none;text-align:right;display:flex;flex-direction:column;gap:4px;align-items:flex-end}
.score{font-size:23px;font-weight:800;letter-spacing:-.02em;line-height:1}
.score small{display:block;font-size:10.5px;color:var(--dim);font-weight:600;letter-spacing:.08em;margin-top:2px}
.size{font-size:12px;color:var(--muted)}
.inftotal{border-bottom:1px dotted #5f708566}
.inftotal.over{color:var(--warn);border-bottom-color:#f0a83c66}

details{margin-top:12px;border-top:1px dashed #ffffff14;padding-top:10px}
summary{cursor:pointer;font-size:13px;color:var(--muted);list-style:none;user-select:none;display:inline-flex;
  align-items:center;gap:7px}
summary::-webkit-details-marker{display:none}
summary:before{content:"▸";color:var(--accent);transition:transform .15s}
details[open] summary:before{transform:rotate(90deg)}
summary:hover{color:var(--txt)}
.lists{display:grid;grid-template-columns:repeat(auto-fill,minmax(232px,1fr));gap:6px 22px;margin-top:14px}
.gtype{break-inside:avoid}
.gtype h5{margin:0 0 5px;font-size:11.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);
  font-weight:700;border-bottom:1px solid #ffffff0d;padding-bottom:4px}
.gtype h5 em{font-style:normal;color:var(--dim);font-weight:500;letter-spacing:0}
.gtype ul{margin:0;padding:0;list-style:none}
.gtype li{display:flex;gap:7px;font-size:13.2px;line-height:1.72;color:#c9d5e3}
.gtype li .q{color:var(--accent);font-weight:700;font-variant-numeric:tabular-nums;min-width:16px}
.gtype li .nm{flex:1;min-width:0}
.gtype li .cz{color:#dbe4ee}
.gtype li .cn{color:#c9d5e3}
.gtype li .ce{font-size:11.2px;color:var(--dim);font-style:italic}
.gtype li .cost{color:var(--dim);font-size:11.5px;font-variant-numeric:tabular-nums;flex:none;
  width:17px;text-align:right}
.gtype li .cost.blank{visibility:hidden}
.gtype li .inf{flex:none;font-size:10.8px;line-height:1.5;color:#f0a83c;background:#f0a83c14;
  border:1px solid #f0a83c55;border-radius:4px;padding:0 4px;font-variant-numeric:tabular-nums}
.gtype li.off .q{color:var(--warn)}
.deckfoot{margin-top:10px;display:flex;align-items:center;gap:14px;font-size:12.3px}
.deckfoot a{color:var(--accent2);opacity:.85}
.deckfoot a:hover{opacity:1;text-decoration:underline}
.copybtn{font:inherit;font-size:12.2px;line-height:1.5;color:#9ecbff;cursor:pointer;
  background:#58a6ff14;border:1px solid #58a6ff38;border-radius:6px;padding:2px 10px;
  display:inline-flex;align-items:center;gap:5px;transition:background .15s,border-color .15s,color .15s}
.copybtn:hover{background:#58a6ff24;border-color:#58a6ff70;color:#cfe4ff}
.copybtn:active{transform:translateY(1px)}
.copybtn.copied{color:#8fe0b4;background:#4cc38a1f;border-color:#4cc38a66}
.copybtn svg{width:12px;height:12px;flex:none}

/* ---------- archive ---------- */
.arc{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:14px}
.arc a.item{display:block;background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:15px 17px;transition:border-color .15s,transform .15s}
.arc a.item:hover{border-color:#3d5a7a;transform:translateY(-2px)}
.arc .week{font-size:16.5px;font-weight:700;letter-spacing:-.01em}
.arc .sub{font-size:12.5px;color:var(--dim);margin-top:3px}
.arc .latest{color:var(--accent);font-size:11.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase}

footer{border-top:1px solid var(--line);margin-top:20px;padding-top:22px;color:var(--dim);font-size:12.5px;line-height:1.9}
footer a{color:var(--muted);text-decoration:underline;text-underline-offset:3px}
@media (max-width:900px){
  .stats{grid-template-columns:repeat(2,1fr)}
  .panels{grid-template-columns:1fr}
  h1{font-size:32px}
  .lists{grid-template-columns:1fr}
}
@media print{
  body{background:#fff;color:#111}
  .deck,.panel,.stat{background:#fff;border-color:#ddd;break-inside:avoid}
  details{open:true}
  .gtype li{color:#222}
}
"""

FACTION_ORDER = ["Anarch", "Criminal", "Shaper", "Haas-Bioroid", "Jinteki", "NBN", "Weyland", "Neutral", "Unknown"]

# 区块折叠（点标题收起 / 展开，状态记在 localStorage）
JS_COLLAPSE = r"""
(function () {
  var KEY = "nrdb-collapsed-v1";

  function sections() {
    return Array.prototype.slice.call(document.querySelectorAll(".sec"));
  }

  function apply(sec, collapsed) {
    sec.classList.toggle("is-collapsed", collapsed);
    var head = sec.querySelector(".sec-head");
    if (head) head.setAttribute("aria-expanded", collapsed ? "false" : "true");
  }

  function readState() {
    try { return JSON.parse(localStorage.getItem(KEY) || "[]") || []; }
    catch (e) { return []; }
  }

  function saveState() {
    var ids = sections()
      .filter(function (s) { return s.classList.contains("is-collapsed"); })
      .map(function (s) { return s.id; });
    try { localStorage.setItem(KEY, JSON.stringify(ids)); } catch (e) {}
    updateToggleLabel();
  }

  function updateToggleLabel() {
    var btn = document.querySelector(".toggleall");
    if (!btn) return;
    var anyOpen = sections().some(function (s) { return !s.classList.contains("is-collapsed"); });
    btn.textContent = anyOpen ? "全部收起" : "全部展开";
    btn.setAttribute("data-all", anyOpen ? "collapse" : "expand");
  }

  function init() {
    var collapsed = readState();
    sections().forEach(function (s) {
      if (collapsed.indexOf(s.id) >= 0) apply(s, true);
    });
    updateToggleLabel();
  }

  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (t.closest && t.closest("a")) return;

    var btn = t.closest && t.closest(".toggleall");
    if (btn) {
      var anyOpen = sections().some(function (s) { return !s.classList.contains("is-collapsed"); });
      sections().forEach(function (s) { apply(s, anyOpen); });
      saveState();
      return;
    }

    var head = t.closest && t.closest(".sec-head");
    if (head) {
      var sec = head.parentElement;
      apply(sec, !sec.classList.contains("is-collapsed"));
      saveState();
    }
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    var head = ev.target.closest && ev.target.closest(".sec-head");
    if (!head) return;
    ev.preventDefault();
    head.click();
  });

  init();
})();
"""


def render_bar(label: str, count: int, total: int, color: str) -> str:
    pct = (count / total * 100) if total else 0
    return (
        f'<div class="bar"><div class="lab"><span>{esc(label)}</span>'
        f'<span>{count} · {pct:.0f}%</span></div>'
        f'<div class="track"><div class="fill" style="width:{pct:.1f}%;background:{color}"></div></div></div>'
    )


def name_html(en: str, zh: str = "") -> str:
    """卡牌名：有中文就中英并列，没中文只显示英文（保持正常字号）。"""
    if zh:
        inner = f'<span class="cz">{esc(zh)}</span> <span class="ce">{esc(en)}</span>'
    else:
        inner = f'<span class="cn">{esc(en)}</span>'
    return f'<span class="nm">{inner}</span>'


def render_deck(deck: dict, badge: str, imgs: set[str], rank: int | None = None) -> str:
    tags = []
    if rank:
        tags.append(f'<span class="tag rank">#{rank}</span>')
    tags.append(f'<span class="tag {badge[0]}">{esc(badge[1])}</span>')
    if deck.get("faction_name"):
        tags.append(f'<span class="tag">{esc(deck["faction_name"])}</span>')
    if deck.get("rotation"):
        tags.append(f'<span class="tag">{esc(deck["rotation"])}</span>')

    code = deck.get("identity_code", "")
    if code and code in imgs:
        img = f'<img class="idimg" src="img/{code}.jpg" alt="{esc(deck["identity_title"])}" loading="lazy">'
    else:
        img = '<div class="idimg empty">NO IMG</div>'

    meta = []
    if deck.get("author"):
        meta.append(f'<span>作者 <b>{esc(deck["author"])}</b>'
                    + (f' · {esc(deck["reputation"])} rep' if deck.get("reputation") else "")
                    + "</span>")
    meta.append(
        f'<span class="social"><b>{deck["votes"]}</b> 赞 &nbsp;'
        f'<b>{deck["favorites"]}</b> 藏 &nbsp;<b>{deck["comments"]}</b> 评</span>'
    )
    if deck.get("date"):
        meta.append(f'<span>{esc(deck["date"][:10])}</span>')
    if deck.get("event"):
        meta.append(f'<span>{esc(deck["event"])}</span>')

    chips = "".join(
        f'<span class="tchip">{esc(g["label_zh"])} <b>{g["count"]}</b></span>'
        for g in deck.get("groups", [])
    )

    groups_html = []
    for group in deck.get("groups", []):
        items = "".join(
            f'<li><span class="q">{i["qty"]}×</span>'
            + (
                f'<span class="cost" title="费用">{esc(str(i["cost"]))}</span>'
                if i.get("cost") is not None else '<span class="cost blank"></span>'
            )
            + name_html(i["title"], i.get("title_zh", ""))
            + (f'<span class="inf" title="影响力消耗">{i["inf"]}</span>' if i.get("inf") else "")
            + "</li>"
            for i in group["items"]
        )
        groups_html.append(
            f'<div class="gtype"><h5>{esc(group["label_en"])} '
            f'<em>· {esc(group["label_zh"])} {group["count"]}</em></h5><ul>{items}</ul></div>'
        )

    size_bits = [f'{deck.get("n_cards", 0)} 张']
    inf_total = deck.get("influence", 0)
    inf_limit = deck.get("influence_limit")
    over = bool(inf_limit) and inf_total > inf_limit
    if inf_limit:
        size_bits.append(f'<span class="inftotal{" over" if over else ""}" '
                         f'title="影响力 = 外派系卡的影响力之和（含带影响力的中立卡）">'
                         f'影响力 {inf_total}/{inf_limit}</span>')
    else:
        size_bits.append(f'<span class="inftotal">影响力 {inf_total}</span>')
    if deck.get("agenda_points"):
        size_bits.append(f'{deck["agenda_points"]} 议案分数')

    ident_en = deck.get("identity_title", "")
    ident_zh = deck.get("identity_zh", "")
    if ident_zh:
        ident_html = f'<b>{esc(ident_zh)}</b><span class="ce">{esc(ident_en)}</span>'
    else:
        ident_html = f"<b>{esc(ident_en)}</b>"

    return f"""
<article class="deck" style="--fc:{deck.get('faction_color', '#4cc38a')}">
  <div class="deck-top">
    {img}
    <div class="dmain">
      <div class="tags">{''.join(tags)}</div>
      <h4><a href="{esc(deck['url'])}" target="_blank" rel="noopener">{esc(deck['title'])}</a></h4>
      <div class="idname">{ident_html}</div>
      <div class="meta">{''.join(meta)}</div>
      <div class="tchips">{chips}</div>
    </div>
    <div class="right">
      <div class="score" title="热度 = 赞×3 + 藏×2 + 评×1">{deck.get('score', 0)}<small>热度</small></div>
      <div class="size">{' · '.join(size_bits)}</div>
    </div>
  </div>
  <details>
    <summary>展开完整牌表 · {deck.get('n_cards', 0)} 张</summary>
    <div class="lists">{''.join(groups_html)}</div>
  </details>
  <div class="deckfoot">
    <button type="button" class="copybtn" data-url="{esc(deck['url'])}"
            title="复制 NetrunnerDB 牌组链接，粘到 jnet 的 Import 里即可导入">
      <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M4 2a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V2zm2 0v8h6V2H6z"/><path d="M2 5a2 2 0 0 1 2-2v1.5A.5.5 0 0 0 3.5 5v8a.5.5 0 0 0 .5.5h6a.5.5 0 0 0 .5-.5H12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5z"/></svg>
      <span class="copybtn-label">复制链接</span>
    </button>
    <a href="decklists/{esc(deck['uuid'])}.txt">纯文本牌表</a>
    <a href="{esc(deck['url'])}" target="_blank" rel="noopener">NetrunnerDB 页面 ↗</a>
  </div>
</article>"""


def render_section(num: str, title: str, hint: str, decks: list[dict], badge: str,
                   imgs: set[str], ranked: bool = False) -> str:
    body = "".join(
        render_deck(d, badge, imgs, rank=(i + 1) if ranked else None)
        for i, d in enumerate(decks)
    ) or '<p class="meta">本期没有符合条件的牌组。</p>'
    sec_id = f"s{num}"
    return f"""
<section class="sec" id="{sec_id}">
  <div class="sec-head" role="button" tabindex="0" aria-expanded="true" aria-controls="body-{sec_id}"
       data-sec="{sec_id}">
    <span class="num">{num}</span><h2>{esc(title)}</h2>
    <span class="hint">{esc(hint)}</span><span class="caret" aria-hidden="true">▾</span>
  </div>
  <div class="sec-body" id="body-{sec_id}">{body}</div>
</section>"""


def render_week_html(issue: dict, decks_sections: list, stats: dict, imgs: set[str]) -> str:
    total = stats["total"] or 1
    faction_bars = "".join(
        render_bar(name, count, total, dict((f[0], f[2]) for f in FACTION_META.values()).get(name, "#4cc38a"))
        for name, count in sorted(stats["factions"], key=lambda kv: (-kv[1], kv[0]))
    )
    id_rows = "".join(
        f'<div class="idrow"><span class="n">{i + 1}</span><span class="t">{esc(name)}</span>'
        f'<span class="c">{count}</span></div>'
        for i, (name, count) in enumerate(stats["identities"])
    ) or '<p class="meta">—</p>'

    sections, jumps = [], []
    for idx, (num, title, hint, decks, badge) in enumerate(decks_sections, start=1):
        if not decks:
            continue
        sections.append(render_section(str(idx), title, hint, decks, badge, imgs, ranked=idx >= 2))
        jumps.append(f'<a class="jumpitem" href="#s{idx}">{esc(title)} <b>{len(decks)}</b></a>')

    side_bits = f'{SIDE_LABEL["runner"]} {stats["sides"]["runner"]} · {SIDE_LABEL["corp"]} {stats["sides"]["corp"]}'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NetrunnerDB 每周牌组摘要 · {esc(issue['week_id'])}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<header class="hero">
  <div class="kicker"><span class="dot"></span>NetrunnerDB · Weekly Meta Digest</div>
  <h1>每周牌组摘要 <span class="light">/ {esc(issue['year'])} 年第 {issue['week_no']} 周</span></h1>
  <p>{esc(issue['window_text'])} · 共追踪 <b>{stats['total']}</b> 副本周新牌组</p>
  <div class="hero-tags">
    <span class="htag">数据来源 <b>netrunnerdb.com</b></span>
    <span class="htag">生成时间 <b>{esc(issue['generated_text'])}</b></span>
    <span class="htag">统计窗口 <b>{issue['days']} 天</b></span>
    <span class="htag">阵营 <b>{side_bits}</b></span>
  </div>
  <nav class="jump">
    <a class="jumpitem" href="#s0">概览 <b>{stats['total']}</b></a>
    {''.join(jumps)}
    <button type="button" class="jumpitem toggleall" data-all="collapse">全部收起</button>
  </nav>
</header>

<section class="sec" id="s0">
  <div class="sec-head" role="button" tabindex="0" aria-expanded="true" aria-controls="body-s0"
       data-sec="s0">
    <span class="num">◆</span><h2>本周概览</h2>
    <span class="hint">派系分布 · 特性（ID）Top 8</span><span class="caret" aria-hidden="true">▾</span>
  </div>
  <div class="sec-body" id="body-s0">
    <div class="stats">
      <div class="stat"><div class="k">本周新牌组</div><div class="v">{stats['total']}<small>副</small></div></div>
      <div class="stat"><div class="k">社区互动</div><div class="v">{stats['votes'] + stats['favorites'] + stats['comments']}<small>次</small></div></div>
      <div class="stat"><div class="k">出现特性</div><div class="v">{stats['unique_identities']}<small>种</small></div></div>
      <div class="stat"><div class="k">本页收录</div><div class="v">{sum(len(s[3]) for s in decks_sections)}<small>副完整牌表</small></div></div>
    </div>

    <div class="panels">
      <div class="panel">
        <h3>派系分布 · 本周新牌组</h3>
        {faction_bars}
      </div>
      <div class="panel">
        <h3>热门特性（ID）Top 8 · 本周新牌组中出现次数</h3>
        <div class="idlist">{id_rows}</div>
      </div>
    </div>
  </div>
</section>

{''.join(sections)}

<footer>
  <b>说明</b>：热度 = 点赞×3 + 收藏×2 + 评论×1，数据取自 NetrunnerDB 列表页；
  「本周热门」先按时间窗口筛选新牌组，再按热度排序；「官方人气榜」是站点自带的
  Popular 排序（偏近期热度，与本页算法不同）。牌表通过公开 API
  <code>/api/2.0/public/decklist/&lt;uuid&gt;</code> 获取。<br>
  卡牌中文名来自同目录的 <code>card_names_zh.xlsx</code>（可选，未填写的显示英文原名）。<br>
  本站与 Fantasy Flight Games / Null Signal Games 无关联，卡牌文字版权归其所有。
  牌组内容版权归各作者所有。<br>
  生成脚本：<code>nrdb_weekly.py</code> · 上一期见 <a href="../index.html">存档目录</a>。
</footer>

</div>

<script>
(function () {{
  function copyText(text) {{
    if (navigator.clipboard && window.isSecureContext) {{
      return navigator.clipboard.writeText(text);
    }}
    return new Promise(function (resolve, reject) {{
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-1000px";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {{ document.execCommand("copy"); resolve(); }}
      catch (e) {{ reject(e); }}
      finally {{ document.body.removeChild(ta); }}
    }});
  }}

  document.addEventListener("click", function (ev) {{
    var btn = ev.target && ev.target.closest ? ev.target.closest(".copybtn") : null;
    if (!btn) return;
    ev.preventDefault();
    var label = btn.querySelector(".copybtn-label");
    var text = btn.getAttribute("data-url") || "";
    copyText(text).then(function () {{
      label.textContent = "已复制 ✓";
      btn.classList.add("copied");
      clearTimeout(btn._timer);
      btn._timer = setTimeout(function () {{
        label.textContent = "复制链接";
        btn.classList.remove("copied");
      }}, 1500);
    }}).catch(function () {{
      label.textContent = "复制失败，请手动复制";
      setTimeout(function () {{ label.textContent = "复制链接"; }}, 2200);
    }});
  }});
}})();
</script>
<script>{JS_COLLAPSE}</script>
</body>
</html>
"""


def render_archive_html(issues: list[dict]) -> str:
    cards = []
    for issue in issues:
        latest = ' <span class="latest">最新</span>' if issue is issues[0] else ""
        cards.append(
            f'<a class="item" href="{esc(issue["dir"])}/index.html">'
            f'<div class="week">{esc(issue["week_id"])}{latest}</div>'
            f'<div class="sub">{esc(issue.get("window_text", ""))}</div>'
            f'<div class="sub">{issue.get("total", 0)} 副牌组 · {issue.get("decks_shown", 0)} 副完整牌表</div>'
            f"</a>"
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NetrunnerDB 每周牌组摘要 · 存档</title><style>{CSS}</style></head>
<body><div class="wrap">
<header class="hero">
  <div class="kicker"><span class="dot"></span>NetrunnerDB · Weekly Meta Digest</div>
  <h1>每周牌组摘要 <span class="light">/ 存档</span></h1>
  <p>共 {len(issues)} 期 · 每周自动抓取一次 netrunnerdb.com 的热门与精选牌组</p>
</header>
<section>
  <div class="sec-head"><h2>全部期数</h2><span class="hint">点击进入某一期</span></div>
  <div class="arc">{''.join(cards) or '<p class="meta">还没有任何一期，先运行 nrdb_weekly.py。</p>'}</div>
</section>
<footer>数据来源 <a href="https://netrunnerdb.com/en/decklists/dotw">netrunnerdb.com</a> ·
与 FFG / Null Signal Games 无关联。</footer>
</div></body></html>
"""


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="抓取 NetrunnerDB 每周热门牌组并生成 HTML 摘要")
    ap.add_argument("--days", type=int, default=7, help="统计窗口天数（默认 7）")
    ap.add_argument("--top-hot", type=int, default=12, help="本周热门收录数量（默认 12）")
    ap.add_argument("--top-dotw", type=int, default=6, help="官方周精选收录数量（默认 6）")
    ap.add_argument("--top-alltime", type=int, default=5, help="官方人气榜收录数量（默认 5）")
    ap.add_argument("--no-images", action="store_true", help="不下载身份卡图")
    ap.add_argument("--dry-run", action="store_true", help="只抓取与统计，不写文件")
    ap.add_argument("--names", default=None,
                    help="中文译名表路径（.xlsx 或 .csv），默认自动找 card_names_zh.xlsx / .csv")
    ap.add_argument("--harvest", action="store_true",
                    help="生成本周出现的卡牌清单工作表（保留已填的中文名），便于继续翻译")
    ap.add_argument("--import-names", action="store_true",
                    help="从社区译名数据（NetrunnerDB_Chinese_Tools / zhCN）补全整张表，只填空行")
    ap.add_argument("--out", default=str(HERE), help="输出根目录（默认脚本所在目录）")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = Path(args.out).resolve()
    now = datetime.now().astimezone()
    iso = now.isocalendar()
    week_id = f"{iso.year}-W{iso.week:02d}"
    week_dir = root / week_id
    start = now - timedelta(days=args.days)

    log(f"== NetrunnerDB 每周牌组摘要 · {week_id} ==")
    log(f"   窗口: {start:%Y-%m-%d} → {now:%Y-%m-%d}")

    log("[1/5] 载入牌张库（用于识别身份阵营）…")
    cards, cards_by_title = load_cards()
    log(f"   牌张 {len(cards)} 张")

    names_path = pick_name_table(args.names)
    if args.import_names:
        target = names_path or (HERE / "card_names_zh.xlsx")
        recs = import_records(cards, read_name_sheet(Path(target)))
        res = write_name_sheet(Path(target), recs)
        log(f"   译名表已更新 → {res['path']}")
        log(f"   共 {res['total']} 张：已译 {res['translated']}，待补 {res['missing']}")
        names_path = Path(target)

    names_code, names_title, names_info = load_name_table(names_path) if names_path else ({}, {}, {})
    names = (names_code, names_title)
    if names_path and names_path.exists():
        log(f"   译名表 {names_path.name}: 已译 {len(names_code)} 条"
            f"（另有 {len(names_title)} 条按英文名匹配）")
        if not names_code:
            log("   （表里还没填中文名，本次仍显示英文）")
    elif names_path:
        log(f"   ! 找不到译名表 {names_path}，本次按英文名显示")
    else:
        log("   未找到译名表，卡牌显示英文名（--harvest 可生成模板）")

    log("[2/5] 扫描最新牌组 …")
    window, scanned = scan_recent(args.days)
    resolve_identities(window, cards, cards_by_title)
    log(f"   窗口内 {len(window)} 副 / 共扫描 {scanned} 副")

    log("[3/5] 抓取官方周精选与全站人气榜 …")
    dotw = resolve_identities(fetch_dotw(max(args.top_dotw * 2, 12)), cards, cards_by_title)
    popular = resolve_identities(fetch_popular(max(args.top_alltime * 2, 12)), cards, cards_by_title)

    # 选牌：官方精选 → 本周热门 → 历史人气（互不重复）
    seen: set[str] = set()

    def take(rows: list[dict], limit: int) -> list[dict]:
        picked = []
        for row in rows:
            if row["uuid"] in seen:
                continue
            seen.add(row["uuid"])
            picked.append(row)
            if len(picked) >= limit:
                break
        return picked

    dotw_pick = take(dotw, args.top_dotw)
    # 热度降序，同分取更新的
    window_sorted = sorted(window, key=lambda d: (hot_score(d), d.get("date", "")), reverse=True)
    hot_pick = take(window_sorted, args.top_hot)
    alltime_pick = take(popular, args.top_alltime)

    log(f"   收录: 周精选 {len(dotw_pick)} · 本周热门 {len(hot_pick)} · 人气榜 {len(alltime_pick)}")

    log("[4/5] 下载牌组详情 …")
    selected = dotw_pick + hot_pick + alltime_pick
    detailed: list[dict] = []
    for i, row in enumerate(selected, 1):
        raw = fetch_deck(row["uuid"])
        if not raw:
            continue
        detailed.append(build_deck(row, raw, cards, names))
        log(f"   ({i}/{len(selected)}) {row['title'][:56]} — {detailed[-1]['n_cards']} 张")

    by_uuid = {d["uuid"]: d for d in detailed}
    dotw_pick = [by_uuid[d["uuid"]] for d in dotw_pick if d["uuid"] in by_uuid]
    hot_pick = [by_uuid[d["uuid"]] for d in hot_pick if d["uuid"] in by_uuid]
    alltime_pick = [by_uuid[d["uuid"]] for d in alltime_pick if d["uuid"] in by_uuid]

    stats = compute_stats(window, names)

    if args.harvest and detailed:
        target = names_path or (HERE / "card_names_zh.xlsx")
        recs = harvest_records(detailed, cards, read_name_sheet(Path(target)))
        res = write_name_sheet(Path(target), recs)
        log(f"   译名工作表 → {res['path']}")
        log(f"   共 {res['total']} 张卡：已译 {res['translated']}，待译 {res['missing']}")

    log("[4/5] 下载身份卡图 …")
    imgs: set[str] = set()
    if not args.no_images:
        codes = [d.get("identity_code", "") for d in detailed]
        if args.dry_run:
            log("   (dry-run 跳过)")
        else:
            imgs = download_identity_images(codes, week_dir / "img")
            log(f"   已缓存 {len(imgs)} 张")
    else:
        log("   已跳过")

    if args.dry_run:
        log("dry-run：不写文件。统计如下：")
        log(json.dumps(stats, ensure_ascii=False, indent=2)[:2000])
        return 0

    log("[5/5] 生成文件 …")
    week_dir.mkdir(parents=True, exist_ok=True)
    (week_dir / "decklists").mkdir(exist_ok=True)

    issue = {
        "week_id": week_id,
        "year": iso.year,
        "week_no": iso.week,
        "days": args.days,
        "start": start.isoformat(),
        "generated": now.isoformat(),
        "generated_text": f"{now:%Y-%m-%d %H:%M}",
        "window_text": f"{start:%Y-%m-%d} → {now:%Y-%m-%d}（最近 {args.days} 天）",
    }

    sections = [
        ("1", "官方每周精选", "netrunnerdb.com/en/decklists/dotw · 最新几期", dotw_pick, ("dotw", "官方精选")),
        ("2", f"本周热门 Top {len(hot_pick)}", f"最近 {args.days} 天新牌组，按热度排序", hot_pick, ("hot", "本周热门")),
        ("3", "官方人气榜", "netrunnerdb.com 自带 Popular 排序 · 偏近期热度", alltime_pick, ("alltime", "人气榜")),
    ]

    html_out = render_week_html(issue, sections, stats, imgs)
    (week_dir / "index.html").write_text(html_out, encoding="utf-8")

    for deck in detailed:
        (week_dir / "decklists" / f"{deck['uuid']}.txt").write_text(decklist_txt(deck), encoding="utf-8")

    meta = {
        **issue,
        "total": stats["total"],
        "decks_shown": len(detailed),
        "stats": stats,
        "sections": {
            "dotw": [d["uuid"] for d in dotw_pick],
            "hot": [d["uuid"] for d in hot_pick],
            "alltime": [d["uuid"] for d in alltime_pick],
        },
    }
    (week_dir / "decks.json").write_text(
        json.dumps({"issue": meta, "decks": detailed}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (week_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [f"# NetrunnerDB 每周牌组摘要 · {week_id}", "", issue["window_text"], "",
          f"本周新牌组 {stats['total']} 副 · {SIDE_LABEL['runner']} {stats['sides']['runner']} / {SIDE_LABEL['corp']} {stats['sides']['corp']}", ""]
    for num, title, hint, decks, _badge in sections:
        if not decks:
            continue
        md.append(f"## {num}. {title}")
        md.append("")
        for deck in decks:
            md.append(decklist_md(deck))
            md.append("---")
            md.append("")
    (week_dir / "decks.md").write_text("\n".join(md), encoding="utf-8")

    # 存档目录
    issues = []
    for d in sorted(root.iterdir(), key=lambda p: p.name, reverse=True):
        if d.is_dir() and re.fullmatch(r"\d{4}-W\d{2}", d.name) and (d / "index.html").exists():
            m = {}
            if (d / "meta.json").exists():
                try:
                    m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    m = {}
            issues.append({
                "dir": d.name,
                "week_id": d.name,
                "window_text": m.get("window_text", ""),
                "total": m.get("total", 0),
                "decks_shown": m.get("decks_shown", 0),
            })
    (root / "index.html").write_text(render_archive_html(issues), encoding="utf-8")

    log(f"完成 → {week_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
