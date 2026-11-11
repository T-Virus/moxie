# -*- coding: utf-8 -*-
"""公开榜单抓取：只取书名/作者/排名/链接等元数据，不抓正文。

男频：起点月票榜（移动端绕过 probe.js）、番茄男频、纵横月票榜、晋江；
女频：潇湘书院、红袖添香、晋江（起点女频 qdmm 全站 probe.js 挑战，暂不可抓；
番茄榜单标题使用私用区字体混淆，仅保留男频兜底，不作为女频主源）。
抓取失败自动跳过并记录原因；结果优先缓存到 Redis，无 Redis 时退回进程内缓存（默认 6 小时）。
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from ..config import Settings
from ..redis_client import try_redis

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
SOURCE_URLS = {
    "qidian": "https://m.qidian.com/rank/yuepiao/?source=m_jump%2F%2F%2F%2F",
    "fanqie": "https://fanqienovel.com/rank",
    "zongheng": "https://www.zongheng.com/rank",
    "jinjiang": "http://www.jjwxc.net/topten.php?orderstr=1",
    "hongxiu": "https://www.hongxiu.com/rank",
    "xxsy": "https://www.xxsy.net/rank",
}
SOURCE_LABELS = {
    "qidian": "起点月票榜",
    "fanqie": "番茄小说排行榜",
    "zongheng": "纵横月票榜",
    "jinjiang": "晋江排行榜",
    "hongxiu": "红袖添香排行榜",
    "xxsy": "潇湘书院排行榜",
}
# 起点移动端分类榜 catId（来自榜单页 filters；全站为 -1）
QIDIAN_CATEGORIES = {
    "玄幻": 21,
    "奇幻": 1,
    "武侠": 2,
    "仙侠": 22,
    "都市": 4,
    "现实": 15,
    "军事": 6,
    "历史": 5,
    "游戏": 7,
    "体育": 8,
    "科幻": 9,
    "悬疑": 10,
    "悬疑灵异": 10,
    "诸天": 20109,
    "诸天无限": 20109,
    "轻小说": 12,
}
# 番茄分类榜：/rank/{gender}_1_{catId}，gender 0=女频、1=男频（2 为热读榜，带分类无效）
FANQIE_CATEGORIES = {
    "male": {
        "玄幻": 258,
        "奇幻": 1141,
        "仙侠": 1140,
        "都市": 261,
        "现实": 261,
        "历史": 273,
        "军事": 504,
        "悬疑": 751,
        "悬疑灵异": 751,
        "科幻": 8,
        "游戏": 746,
        "体育": 746,
        "衍生": 718,
    },
    "female": {
        "古言": 1139,
        "古代言情": 1139,
        "宫斗": 246,
        "宅斗": 246,
        "古言脑洞": 253,
        "言情": 749,
        "现言": 749,
        "甜宠": 749,
        "青春": 749,
        "都市": 267,
        "职场": 750,
        "婚恋": 750,
        "豪门": 748,
        "总裁": 748,
        "悬疑": 747,
        "女频悬疑": 747,
        "科幻": 8,
        "末世": 8,
        "奇幻": 248,
        "玄幻": 248,
        "玄幻言情": 248,
        "种田": 23,
        "年代": 79,
        "快穿": 24,
        "星光": 745,
        "娱乐": 745,
        "民国": 1017,
    },
}
_CACHE: dict[str, tuple[float, list[dict], list[dict]]] = {}


@dataclass
class RankingItem:
    site: str
    rank: int
    title: str
    author: str = ""
    url: str = ""
    genre: str = ""
    summary: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(text: str) -> str:
    """去掉站点字体混淆用的私用区字符，并压缩空白。"""
    text = html_lib.unescape(text or "")
    text = "".join(ch for ch in text if not ("\ue000" <= ch <= "\uf8ff"))
    return re.sub(r"\s+", " ", text).strip()


def _balanced_json(text: str, key: str) -> dict | None:
    start = text.find(key)
    if start < 0:
        return None
    start = text.find("{", start)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for pos in range(start, len(text)):
        ch = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = text[start : pos + 1].replace(":undefined", ":null")
                try:
                    return json.loads(raw)
                except ValueError:
                    return None
    return None


def _parse_fanqie(html: str, limit: int) -> list[RankingItem]:
    data = _balanced_json(html, "window.__INITIAL_STATE__")
    if not data:
        return []
    books: list[dict] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("bookName"):
                books.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    items: list[RankingItem] = []
    seen: set[str] = set()
    for index, book in enumerate(books[:limit], 1):
        title = _clean(str(book.get("bookName") or ""))
        if not title or title in seen:
            continue
        seen.add(title)
        book_id = str(book.get("bookId") or "")
        items.append(
            RankingItem(
                site="fanqie",
                rank=int(book.get("currentPos") or index),
                title=title,
                author=_clean(str(book.get("author") or "")),
                url=f"https://fanqienovel.com/page/{book_id}" if book_id else "",
                genre=_clean(str(book.get("categoryV2") or book.get("cateName") or "")),
                summary=_clean(str(book.get("abstract") or ""))[:300],
                extra={"read_count": str(book.get("read_count") or "")},
            )
        )
    return items


def _parse_zongheng(html: str, limit: int) -> list[RankingItem]:
    pattern = re.compile(
        r'\{bookId:(\d+),bookName:"([^"]+)",authorId:\d+,authorName:"([^"]+)"'
    )
    items: list[RankingItem] = []
    seen: set[str] = set()
    for book_id, title, author in pattern.findall(html):
        title = _clean(title)
        if not title or title in seen:
            continue
        seen.add(title)
        items.append(
            RankingItem(
                site="zongheng",
                rank=len(items) + 1,
                title=title,
                author=_clean(author),
                url=f"https://www.zongheng.com/book/{book_id}.html",
            )
        )
        if len(items) >= limit:
            break
    return items


def _parse_jinjiang(html: str, limit: int) -> list[RankingItem]:
    pattern = re.compile(
        r'href="[^"]*?onebook\.php\?novelid=(\d+)"[^>]*>(.*?)</a>',
        re.I | re.S,
    )
    items: list[RankingItem] = []
    seen: set[str] = set()
    for novel_id, raw_title in pattern.findall(html):
        title = _clean(re.sub(r"<[^>]+>", " ", raw_title))
        if not title or title in seen:
            continue
        seen.add(title)
        items.append(
            RankingItem(
                site="jinjiang",
                rank=len(items) + 1,
                title=title,
                url=f"https://www.jjwxc.net/onebook.php?novelid={novel_id}",
            )
        )
        if len(items) >= limit:
            break
    return items


def _parse_hongxiu(html: str, limit: int) -> list[RankingItem]:
    """红袖添香排行榜（女频）：热销榜/风云榜等多个榜单块均为 li > a.name。"""
    pattern = re.compile(
        r'<li>\s*<span class="num\d*">\d+</span>\s*'
        r'<a class="name" href="/book/(\d+)"[^>]*>(.*?)</a>',
        re.I | re.S,
    )
    items: list[RankingItem] = []
    seen: set[str] = set()
    for book_id, raw_title in pattern.findall(html):
        title = _clean(re.sub(r"<[^>]+>", " ", raw_title))
        if not title or title in seen:
            continue
        seen.add(title)
        items.append(
            RankingItem(
                site="hongxiu",
                rank=len(items) + 1,
                title=title,
                url=f"https://www.hongxiu.com/book/{book_id}",
            )
        )
        if len(items) >= limit:
            break
    return items


def _parse_xxsy(html: str, limit: int) -> list[RankingItem]:
    """潇湘书院（女频）排行榜：li[data-bookid] 内含作者、名次与书名。"""
    items: list[RankingItem] = []
    seen: set[str] = set()
    for block in re.split(r'<li[^>]*data-bookid="', html)[1:]:
        book_id = block[: block.find('"')]
        title_match = re.search(rf'<a href="/book/{book_id}"[^>]*>(.*?)</a>', block, re.S)
        if not book_id or not title_match:
            continue
        title = _clean(re.sub(r"<[^>]+>", " ", title_match.group(1)))
        if not title or title in seen:
            continue
        seen.add(title)
        author_match = re.search(r'class="piao"[^>]*>(.*?)</span>', block, re.S)
        rank_match = re.search(r'class="num"[^>]*>(\d+)<', block)
        items.append(
            RankingItem(
                site="xxsy",
                rank=int(rank_match.group(1)) if rank_match else len(items) + 1,
                title=title,
                author=_clean(re.sub(r"<[^>]+>", " ", author_match.group(1))) if author_match else "",
                url=f"https://www.xxsy.net/book/{book_id}",
            )
        )
        if len(items) >= limit:
            break
    return items


def _parse_qidian(html: str, limit: int) -> list[RankingItem]:
    """解析 m.qidian.com 月票榜：移动端 + source=m_jump 参数可绕过 probe.js 挑战。"""
    blocks = re.split(r'<div class="y-list__item"', html)
    items: list[RankingItem] = []
    seen: set[str] = set()
    for index, block in enumerate(blocks[1:], 1):
        href = re.search(r'href="([^"]*/book/(\d+)/?)"', block)
        title_match = re.search(r'class="_title_[^"]*"[^>]*>([^<]+)<', block)
        if not href or not title_match:
            continue
        title = _clean(title_match.group(1))
        if not title or title in seen:
            continue
        seen.add(title)
        rank_match = re.search(r'class="_ranking_[^"]*"[^>]*>(\d+)<', block)
        sub_match = re.search(r'class="_subTitle_[^"]*"[^>]*>(.*?)</p>', block, re.S)
        desc_match = re.search(r'class="_bookDesc_[^"]*"[^>]*>(.*?)</p>', block, re.S)
        sub_parts = [
            _clean(re.sub(r"<[^>]+>", " ", part))
            for part in re.split(r"·", re.sub(r"<[^>]+>", "·", sub_match.group(1)))
            if _clean(re.sub(r"<[^>]+>", " ", part))
        ] if sub_match else []
        items.append(
            RankingItem(
                site="qidian",
                rank=int(rank_match.group(1)) if rank_match else index,
                title=title,
                author=sub_parts[0] if sub_parts else "",
                url=f"https://www.qidian.com/book/{href.group(2)}/",
                genre=sub_parts[1] if len(sub_parts) > 1 else "",
                summary=_clean(re.sub(r"<[^>]+>", " ", desc_match.group(1)))[:300] if desc_match else "",
                extra={"words": sub_parts[2] if len(sub_parts) > 2 else ""},
            )
        )
        if len(items) >= limit:
            break
    return items


_PARSERS = {
    "qidian": _parse_qidian,
    "fanqie": _parse_fanqie,
    "zongheng": _parse_zongheng,
    "jinjiang": _parse_jinjiang,
    "hongxiu": _parse_hongxiu,
    "xxsy": _parse_xxsy,
}


def _qidian_url(genre: str | None = None) -> str:
    """按题材拼起点分类榜；未知题材回落全站榜。"""
    cat_id = QIDIAN_CATEGORIES.get((genre or "").strip())
    month = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m")
    cat_part = f"catid{cat_id}" if cat_id is not None else "catid-1"
    return f"https://m.qidian.com/rank/yuepiao/{cat_part}/{month}/?source=m_jump%2F%2F%2F%2F"


def _fanqie_url(audience: str, genre: str | None = None) -> str:
    """按男女频与题材拼番茄分类榜；未知题材回落该频道的全站榜。"""
    gender = "1" if audience == "male" else "0"
    cat_id = FANQIE_CATEGORIES.get(audience, {}).get((genre or "").strip())
    if cat_id is None:
        return f"https://fanqienovel.com/rank/{gender}_1"
    return f"https://fanqienovel.com/rank/{gender}_1_{cat_id}"


def _cache_key(
    sources: list[str], limit: int, genre: str | None = None, audience: str = "male"
) -> str:
    return f"rankings:v2:{audience}:{','.join(sources)}:{limit}:{genre or ''}"


def _read_cache(settings: Settings, key: str) -> tuple[list[dict], list[dict]] | None:
    entry = _CACHE.get(key)
    if entry and entry[0] > time.time():
        return entry[1], entry[2]
    client = try_redis(settings, decode_responses=True)
    if client is None:
        return None
    try:
        raw = client.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        return list(data.get("items") or []), list(data.get("sources") or [])
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


def _write_cache(settings: Settings, key: str, items: list[dict], sources: list[dict]) -> None:
    ttl = max(60, int(settings.ranking_cache_seconds))
    _CACHE[key] = (time.time() + ttl, items, sources)
    client = try_redis(settings, decode_responses=True)
    if client is None:
        return
    try:
        client.setex(key, ttl, json.dumps({"items": items, "sources": sources}, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


def fetch_rankings_sync(
    settings: Settings,
    *,
    limit: int = 20,
    sources: list[str] | None = None,
    genre: str | None = None,
    audience: str | None = None,
    refresh: bool = False,
) -> tuple[list[dict], list[dict]]:
    """同步抓取榜单元数据。

    audience=female 时默认取潇湘书院/红袖/晋江；否则走起点+番茄男频等。
    genre 用于分类榜，题材未知时抓该频道全站榜。
    """
    limit = max(1, min(50, int(limit)))
    if not settings.ranking_enabled:
        return [], [{"site": "all", "ok": False, "error": "ranking_disabled", "count": 0}]
    audience = "female" if (audience or "").strip() == "female" else "male"
    if sources:
        selected = sources
    elif audience == "female":
        selected = [s.strip() for s in settings.ranking_female_sources.split(",") if s.strip()]
    else:
        selected = [s.strip() for s in settings.ranking_sources.split(",") if s.strip()]
    selected = [s for s in selected if s in SOURCE_URLS]
    if audience == "female":
        # 起点女频 qdmm 全站启用了 probe.js 挑战，纵横向以男频为主
        selected = [s for s in selected if s not in ("qidian", "zongheng")]
    selected = selected[:4]
    if not selected:
        return [], []

    key = _cache_key(selected, limit, genre, audience)
    if not refresh:
        cached = _read_cache(settings, key)
        if cached is not None:
            return cached

    items: list[dict] = []
    reports: list[dict] = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    with httpx.Client(
        follow_redirects=True,
        timeout=settings.ranking_timeout_seconds,
        headers=headers,
    ) as client:
        for site in selected:
            report = {
                "site": site,
                "label": SOURCE_LABELS.get(site, site),
                "ok": False,
                "count": 0,
                "fetched_at": fetched_at,
            }
            try:
                request_headers = (
                    {"User-Agent": MOBILE_UA, "Referer": "https://m.qidian.com/"}
                    if site == "qidian"
                    else None
                )
                if site == "qidian":
                    source_url = _qidian_url(genre)
                elif site == "fanqie":
                    source_url = _fanqie_url(audience, genre)
                else:
                    source_url = SOURCE_URLS[site]
                response = client.get(source_url, headers=request_headers)
                report["status"] = response.status_code
                if response.status_code >= 400:
                    report["error"] = f"http_{response.status_code}"
                else:
                    if site == "jinjiang":
                        response.encoding = "gbk"
                    parsed = _PARSERS[site](response.text, limit)
                    report["ok"] = bool(parsed)
                    report["count"] = len(parsed)
                    if not parsed:
                        report["error"] = "no_items"
                    items.extend(item.to_dict() for item in parsed)
            except Exception as exc:  # noqa: BLE001
                report["error"] = type(exc).__name__
            reports.append(report)

    if items:
        _write_cache(settings, key, items, reports)
    return items, reports
