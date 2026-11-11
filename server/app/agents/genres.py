# -*- coding: utf-8 -*-
"""题材目录：客户端选择器与意图解析共用。"""

from __future__ import annotations

GENRES: list[dict] = [
    {
        "id": "xuanhuan",
        "name": "玄幻",
        "audience": ["male", "all"],
        "tags": ["升级流", "热血", "异世界"],
    },
    {
        "id": "xianxia",
        "name": "仙侠",
        "audience": ["male", "all"],
        "tags": ["修真", "门派", "长生"],
    },
    {
        "id": "dushi",
        "name": "都市",
        "audience": ["male", "female", "all"],
        "tags": ["逆袭", "商战", "日常"],
    },
    {
        "id": "xuanyi",
        "name": "悬疑",
        "audience": ["male", "female", "all"],
        "tags": ["推理", "反转", "罪案"],
    },
    {
        "id": "yanqing",
        "name": "言情",
        "audience": ["female", "all"],
        "tags": ["甜宠", "追妻", "双向奔赴"],
    },
    {
        "id": "gufeng",
        "name": "古言",
        "audience": ["female", "all"],
        "tags": ["宫斗", "权谋", "宅斗"],
    },
    {
        "id": "kehuan",
        "name": "科幻",
        "audience": ["male", "female", "all"],
        "tags": ["星际", "赛博", "末世"],
    },
    {
        "id": "lishi",
        "name": "历史",
        "audience": ["male", "all"],
        "tags": ["争霸", "种田", "权谋"],
    },
    {
        "id": "youxi",
        "name": "游戏",
        "audience": ["male", "all"],
        "tags": ["副本", "竞技", "系统"],
    },
    {
        "id": "qihuan",
        "name": "奇幻",
        "audience": ["male", "female", "all"],
        "tags": ["魔法", "冒险", "群像"],
    },
]


def list_genres() -> dict:
    return {"items": GENRES, "custom_allowed": True}
