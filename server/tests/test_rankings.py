# -*- coding: utf-8 -*-
"""公开榜单抓取：解析器、接口与热门写作调研合并。"""

from __future__ import annotations

from app.agents.contracts import SkillContext
from app.agents.skills import genre_research as gr
from app.config import Settings
from app.services import rankings


def test_parse_qidian_mobile_rank():
    html = (
        '<div class="y-list__item" data-index="0">'
        '<a href="//m.qidian.com/book/1050460263/" title="神宠供应商最新章节在线阅读">'
        '<div class="_topTitle_1"><div class="_ranking_1 _front_1">1</div>'
        '<h2 class="_title_1" title="月票榜第1位">神宠供应商</h2></div>'
        '<p class="_bookDesc_1">海洋纪元，人类与变异海兽共存。</p>'
        '<p class="_subTitle_1">轻泉流响 <em>·</em> 轻小说 <em>·</em> 71.46万字</p>'
        "</a></div>"
    )
    items = rankings._parse_qidian(html, 10)
    assert len(items) == 1
    assert items[0].title == "神宠供应商"
    assert items[0].author == "轻泉流响"
    assert items[0].genre == "轻小说"
    assert items[0].rank == 1
    assert items[0].url == "https://www.qidian.com/book/1050460263/"


def test_qidian_category_url_mapping():
    url = rankings._qidian_url("玄幻")
    assert "/catid21/" in url
    assert "/rank/yuepiao/" in url
    assert "source=m_jump" in url
    assert "/catid-1/" in rankings._qidian_url("未知题材")


def test_fanqie_audience_category_url_mapping():
    assert rankings._fanqie_url("female", "古言") == "https://fanqienovel.com/rank/0_1_1139"
    assert rankings._fanqie_url("female", "未知题材") == "https://fanqienovel.com/rank/0_1"
    assert rankings._fanqie_url("male", "玄幻") == "https://fanqienovel.com/rank/1_1_258"
    assert rankings._fanqie_url("male", None) == "https://fanqienovel.com/rank/1_1"


def test_parse_fanqie_tolerates_undefined():
    html = (
        '<script>window.__INITIAL_STATE__={"rank":{"rankVersion":undefined,'
        '"book_list":[{"bookId":"9","bookName":"女频样本","author":"乙"}]}}</script>'
    )
    items = rankings._parse_fanqie(html, 10)
    assert len(items) == 1
    assert items[0].title == "女频样本"
    assert items[0].rank == 1


def test_parse_fanqie_cleans_private_chars():
    html = (
        '<script>window.__INITIAL_STATE__={"rank":{"book_list":['
        '{"bookId":"11","bookName":"惹\\ue49c枝","author":"空留","currentPos":1,"read_count":"276"}'
        ']}}</script>'
    )
    items = rankings._parse_fanqie(html, 10)
    assert len(items) == 1
    assert items[0].title == "惹枝"
    assert items[0].url.endswith("/page/11")
    assert items[0].rank == 1


def test_parse_zongheng_month_ticket_rank():
    html = (
        'monthTicketRankList:[{bookId:1435440,bookName:"齐天",authorId:1,'
        'authorName:"日落红尘",number:5508,rankNo:1}]'
    )
    items = rankings._parse_zongheng(html, 10)
    assert len(items) == 1
    assert items[0].title == "齐天"
    assert items[0].author == "日落红尘"
    assert items[0].url.endswith("/book/1435440.html")


def test_parse_jinjiang_links():
    html = '<a href="onebook.php?novelid=273">水晶般透明</a>'
    items = rankings._parse_jinjiang(html, 10)
    assert len(items) == 1
    assert items[0].title == "水晶般透明"
    assert "novelid=273" in items[0].url


def test_parse_hongxiu_female_rank():
    html = (
        '<div class="book-rank-list"><ul>'
        '<li><span class="num1">1</span><a class="name" href="/book/8263527304935303" '
        'target="_blank">恰似寒光遇骄阳</a></li>'
        '<li><span class="num2">2</span><a class="name" href="/book/21855922801825904" '
        'target="_blank">摄政王他又在掐我桃花</a></li>'
        "</ul></div>"
    )
    items = rankings._parse_hongxiu(html, 10)
    assert [item.title for item in items] == ["恰似寒光遇骄阳", "摄政王他又在掐我桃花"]
    assert items[0].rank == 1
    assert items[0].url == "https://www.hongxiu.com/book/8263527304935303"


def test_parse_xxsy_female_rank():
    html = (
        '<ul class="ranking-list">'
        '<li class="n2" data-bookid="36582934803415908">'
        '<span class="piao">千山茶客</span><span class="num">1</span>'
        '<p><a href="/book/36582934803415908" target="_blank">来日有信</a></p></li>'
        '<li class="n2" data-bookid="35553339803245509">'
        '<span class="piao">爱吃肉包的妞</span><span class="num">2</span>'
        '<p><a href="/book/35553339803245509" target="_blank">长生修仙从族学开始</a></p></li>'
        "</ul>"
    )
    items = rankings._parse_xxsy(html, 10)
    assert [item.title for item in items] == ["来日有信", "长生修仙从族学开始"]
    assert items[0].author == "千山茶客"
    assert items[0].rank == 1
    assert items[0].url == "https://www.xxsy.net/book/36582934803415908"


def test_rankings_endpoint_requires_auth_and_returns_sources(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.rankings.fetch_rankings_sync",
        lambda settings, limit=20, genre=None, audience=None, refresh=False: (
            [
                {
                    "site": "fanqie",
                    "rank": 1,
                    "title": "榜单书",
                    "author": "作者",
                    "url": "https://example.com/1",
                    "genre": "",
                    "summary": "",
                    "extra": {},
                }
            ],
            [{"site": "fanqie", "label": "番茄小说排行榜", "ok": True, "count": 1}],
        ),
    )
    assert client.get("/v1/rankings", headers={}).status_code == 401

    registered = client.post(
        "/v1/auth/register",
        json={"email": "rank@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    body = client.get("/v1/rankings", headers=headers).json()
    assert body["items"][0]["title"] == "榜单书"
    assert body["sources"][0]["ok"] is True


def test_fetch_female_uses_female_sources(monkeypatch):
    captured: list[str] = []

    class _Response:
        status_code = 200
        text = ""

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            captured.append(url)
            return _Response()

    rankings._CACHE.clear()
    monkeypatch.setattr(rankings.httpx, "Client", _Client)
    settings = Settings(env="test", ranking_enabled=True, ranking_timeout_seconds=0.1)
    _, reports = rankings.fetch_rankings_sync(
        settings, limit=5, genre="古言", audience="female", refresh=True
    )
    assert all("qidian" not in url and "zongheng" not in url for url in captured)
    assert any("xxsy.net/rank" in url for url in captured)
    assert any("hongxiu.com/rank" in url for url in captured)
    assert {report["site"] for report in reports} == {"xxsy", "hongxiu", "jinjiang"}


def test_genre_research_merges_web_ranking(monkeypatch):
    monkeypatch.setattr(
        gr,
        "fetch_rankings_sync",
        lambda settings, limit=20, genre=None, audience=None, refresh=False: (
            [{"site": "fanqie", "rank": 2, "title": "榜单样本", "author": "甲", "genre": "悬疑", "summary": ""}],
            [{"site": "fanqie", "label": "番茄小说排行榜", "ok": True, "count": 1}],
        ),
    )
    monkeypatch.setattr(
        gr,
        "call_json",
        lambda *args, **kwargs: {
            "works": [
                {
                    "title": "模型样本",
                    "hook": "钩子",
                    "three_chapter_summary": "前三章",
                    "tags": ["悬疑"],
                }
            ],
            "takeaways": ["强开局"],
            "sources": [],
        },
    )
    settings = Settings(env="test", ranking_enabled=True, model_stub=False)
    ctx = SkillContext(settings=settings, model="stub", api_key="test")
    result = gr.GenreResearchSkill().run(
        gr.GenreResearchInput(
            title="测试书",
            genre_name="悬疑",
            audience="male",
            length="long",
        ),
        ctx,
    )
    assert any(source.type == "web_ranking" for source in result.sources)
    assert any("番茄小说排行榜" in work.title for work in result.works)
    assert any("禁止同名" in item for item in result.takeaways)
