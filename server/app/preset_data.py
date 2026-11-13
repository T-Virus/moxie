# -*- coding: utf-8 -*-
"""全量预设值（题材/枚举/分类/标签），作为数据库种子与 /presets 接口的权威来源。

前端各 Tab 的预设值集中在此，启动时由 seed.ensure_presets 入库；运行期前端统一从
GET /presets 拉取，不再硬编码。结构： type -> [ {value, audience?}, ... ]。
- audience 仅题材(genre)使用，逗号分隔（male/female/all）；其它类型缺省视为 "all"。
- 用户自定义的新选项也可写入 presets 表（account_id 归属），与系统预设一并返回。
"""

from __future__ import annotations

PRESET_DATA: dict[str, list[dict]] = {
    # —— 题材（全类型，跨频/男频/女频）——
    "genre": [
        {"value": "玄幻", "audience": "male,female,all"},
        {"value": "仙侠", "audience": "male,female,all"},
        {"value": "修真", "audience": "male,female"},
        {"value": "都市", "audience": "male,female,all"},
        {"value": "现实", "audience": "all"},
        {"value": "科幻", "audience": "all"},
        {"value": "悬疑", "audience": "all"},
        {"value": "灵异", "audience": "male,female"},
        {"value": "轻小说", "audience": "all"},
        {"value": "同人", "audience": "all"},
        {"value": "二次元", "audience": "all"},
        {"value": "动漫", "audience": "all"},
        {"value": "无限流", "audience": "all"},
        {"value": "末世", "audience": "all"},
        {"value": "系统流", "audience": "all"},
        {"value": "重生", "audience": "all"},
        {"value": "穿越", "audience": "all"},
        {"value": "种田", "audience": "female,male,all"},
        {"value": "废土", "audience": "all"},
        {"value": "克苏鲁", "audience": "all"},
        {"value": "规则怪谈", "audience": "all"},
        {"value": "盗墓", "audience": "male"},
        {"value": "探险", "audience": "male"},
        {"value": "寻宝", "audience": "male"},
        {"value": "诸天万界", "audience": "all"},
        {"value": "治愈", "audience": "all"},
        {"value": "史诗", "audience": "male"},
        {"value": "民间", "audience": "all"},
        {"value": "无脑爽文", "audience": "all"},
        {"value": "短篇", "audience": "all"},
        {"value": "怪谈", "audience": "female,male"},
        {"value": "武侠", "audience": "male"},
        {"value": "奇幻", "audience": "male"},
        {"value": "历史", "audience": "male"},
        {"value": "军事", "audience": "male"},
        {"value": "游戏", "audience": "male"},
        {"value": "体育", "audience": "male"},
        {"value": "洪荒", "audience": "male"},
        {"value": "封神", "audience": "male"},
        {"value": "西游", "audience": "male"},
        {"value": "神话", "audience": "male"},
        {"value": "谍战", "audience": "male,female"},
        {"value": "特工", "audience": "male"},
        {"value": "进化", "audience": "male"},
        {"value": "异能", "audience": "male,female"},
        {"value": "丧尸", "audience": "all"},
        {"value": "灵气复苏", "audience": "male,female"},
        {"value": "高武", "audience": "male"},
        {"value": "国术", "audience": "male"},
        {"value": "赛博", "audience": "male,female"},
        {"value": "史前", "audience": "male"},
        {"value": "原始", "audience": "male"},
        {"value": "部落", "audience": "male"},
        {"value": "领主", "audience": "male"},
        {"value": "网游", "audience": "male"},
        {"value": "全息", "audience": "male"},
        {"value": "电竞", "audience": "male,female"},
        {"value": "篮球", "audience": "male"},
        {"value": "足球", "audience": "male"},
        {"value": "格斗", "audience": "male"},
        {"value": "星舰", "audience": "male"},
        {"value": "外星", "audience": "male"},
        {"value": "武道", "audience": "male"},
        {"value": "争霸", "audience": "male"},
        {"value": "言情", "audience": "female"},
        {"value": "古言", "audience": "female"},
        {"value": "现言", "audience": "female"},
        {"value": "幻言", "audience": "female"},
        {"value": "仙侠情缘", "audience": "female"},
        {"value": "宅斗", "audience": "female"},
        {"value": "女尊", "audience": "female"},
        {"value": "纯爱", "audience": "female,male"},
        {"value": "百合", "audience": "female"},
        {"value": "耽美", "audience": "male"},
        {"value": "无CP", "audience": "female,male"},
        {"value": "穿书", "audience": "female"},
        {"value": "快穿", "audience": "female"},
        {"value": "西幻", "audience": "female"},
        {"value": "年代文", "audience": "female"},
        {"value": "校园", "audience": "female,male"},
        {"value": "娱乐圈", "audience": "female"},
        {"value": "豪门", "audience": "female"},
        {"value": "萌宠", "audience": "female"},
        {"value": "团宠", "audience": "female"},
        {"value": "神医", "audience": "female"},
        {"value": "王妃", "audience": "female"},
        {"value": "七零", "audience": "female"},
        {"value": "八零", "audience": "female"},
        {"value": "清穿", "audience": "female"},
        {"value": "民国", "audience": "female"},
        {"value": "魔法", "audience": "female"},
        {"value": "推理", "audience": "female"},
        {"value": "职场", "audience": "female,male"},
        {"value": "婚恋", "audience": "female"},
        {"value": "萌宝", "audience": "female"},
        {"value": "权谋", "audience": "female,male"},
        {"value": "宫斗", "audience": "female"},
        {"value": "朝堂", "audience": "female,male"},
        {"value": "武侠言情", "audience": "female"},
        {"value": "甜宠", "audience": "female,male"},
        {"value": "虐恋", "audience": "female"},
        {"value": "兽世", "audience": "female"},
        {"value": "哨向", "audience": "female,male"},
        {"value": "ABO", "audience": "female,male"},
        {"value": "机甲", "audience": "female,male"},
        {"value": "星际", "audience": "female,male"},
        {"value": "虫族", "audience": "female,male"},
        {"value": "美食", "audience": "female,male"},
        {"value": "基建", "audience": "female,male"},
        {"value": "探案", "audience": "female,male"},
    ],
    # —— 角色：性别 ——
    "character_gender": [{"value": v} for v in (
        "男", "女", "双性", "无性别", "非二元", "变性", "其他", "未知",
    )],
    # —— 角色：种族 ——
    "character_race": [{"value": v} for v in (
        "人族", "妖族", "魔族", "灵族", "神族", "仙族", "兽族", "鬼族", "龙族", "巫族",
        "机械族", "异族", "混血", "半妖", "半人", "精灵", "矮人", "血族", "鲛人", "巨人",
        "树人", "翼族", "修罗", "佛门", "天族", "未知",
    )],
    # —— 角色：剧情功能 ——
    "character_role": [{"value": v} for v in (
        "主角", "男主", "女主", "配角", "男配", "女配", "反派", "正派", "群像", "工具人",
        "导师", "挚友", "宿敌", "卧底", "旁观者", "路人",
    )],
    # —— 角色：阵营 ——
    "character_camp": [{"value": v} for v in (
        "正道", "魔道", "邪道", "正派", "反派", "中立", "亦正亦邪", "隐世", "散修", "朝廷",
        "江湖", "妖界", "仙门", "佛门", "混沌", "蛮族", "外域", "未知",
    )],
    # —— 势力：大类 ——
    "faction_category": [{"value": v} for v in (
        "宗门", "家族", "朝廷", "商会", "帮派", "军队", "组织", "门派", "联盟", "圣地",
        "古族", "学宫", "书院", "神殿", "王朝", "公会", "教派", "海域", "魔门", "妖国",
        "亡灵", "佣兵团", "隐世",
    )],
    # —— 势力：类型 ——
    "faction_type": [{"value": v} for v in (
        "宗门", "家族", "朝廷", "商会", "帮派", "军队", "组织", "门派", "联盟", "圣地",
        "古族", "学宫", "神殿", "王朝", "公会", "教派", "魔门", "妖国", "佣兵团", "隐世",
    )],
    # —— 势力：立场 ——
    "faction_stance": [{"value": v} for v in (
        "正派", "反派", "中立", "亦正亦邪", "正义", "邪恶", "灰色地带", "守序", "混乱", "未知",
    )],
    # —— 道具：类别 ——
    "item_category": [{"value": v} for v in (
        "法宝", "法器", "功法", "丹药", "材料", "信物", "武器", "防具", "符箓", "阵法",
        "灵宠", "宝物", "秘籍", "灵草", "矿石", "机关", "毒药", "药方", "神兵", "其他",
    )],
    # —— 道具：品阶 ——
    "item_grade": [{"value": v} for v in (
        "凡品", "黄阶", "玄阶", "地阶", "天阶", "灵品", "玄品", "地品", "天品", "仙品",
        "神品", "圣品", "道器", "王品", "帝品", "超品", "禁忌", "未知",
    )],
    # —— 作品信息：主题标签 ——
    "info_theme": [{"value": v} for v in (
        "成长", "复仇", "逆袭", "守护", "权谋", "救赎", "热血", "悬疑", "群像", "打脸",
        "甜宠", "虐恋", "家国", "探索", "宿命", "爱情", "言情", "修仙", "穿越", "重生",
        "系统", "种田", "末日", "废柴", "天才", "江湖", "宫斗", "宅斗", "争霸", "养成",
        "无限流", "克苏鲁", "赛博", "科幻", "异能", "灵气复苏", "美食", "神豪", "直播", "游戏",
        "电竞", "复仇爽文",
    )],
    # —— 作品信息：叙事人称 ——
    "info_person": [{"value": v} for v in (
        "第一人称", "第二人称", "第三人称限知", "第三人称全知", "多视角", "双视角交替", "主客观交替",
    )],
    # —— 作品信息：文风与语言 ——
    "info_voice": [{"value": v} for v in (
        "快节奏爽文", "慢热细腻", "文艺青年", "网络梗幽默", "古典半文半白", "简洁硬朗", "华丽唯美",
        "幽默讽刺", "悬念铺垫", "电影画面感", "冷峻克制", "古雅厚重", "轻小说", "吐槽风",
        "严肃文学", "纪实冷硬", "诗意抒情", "通俗直白",
    )],
    # —— 作品信息：基调 ——
    "info_tone": [{"value": v} for v in (
        "热血", "轻松", "黑暗", "治愈", "悬疑", "虐心", "温馨", "史诗", "搞笑", "燃",
        "悲壮", "苍凉", "诡谲", "浪漫", "唯美", "硬核", "轻喜剧", "暗黑",
    )],
    # —— 作品信息：读者年龄段 ——
    "info_age": [{"value": v} for v in (
        "学生党", "12-18", "14-17", "18-24", "25-34", "35+", "40+", "50+", "年轻群体", "成熟读者", "全年龄",
    )],
    # —— 作品信息：更新频率 ——
    "info_update": [{"value": v} for v in (
        "日更", "双更", "多更", "爆发", "三日一更", "周更", "周双更", "月更", "季更", "不定期", "停更",
    )],
    # —— 作品信息：连载节奏 ——
    "info_pace": [{"value": v} for v in (
        "快节奏", "稳节奏", "慢热", "慢节奏", "适中", "张弛有度", "紧凑",
    )],
    # —— 作品信息：内容分级 ——
    "info_rating": [{"value": v} for v in (
        "全年龄", "12+", "16+", "18+", "青少年", "无限制",
    )],
    # —— 作品信息：目标平台 ——
    "info_platform": [{"value": v} for v in (
        "番茄", "起点", "晋江", "七猫", "飞卢", "QQ阅读", "纵横", "17K", "知乎", "豆瓣",
        "刺猬猫", "少年梦", "塔读", "掌阅", "书旗", "咪咕", "次元",
    )],
    # —— 作品信息：核心卖点（前端 InfoTab 已接入该类型）——
    "info_selling_point": [{"value": v} for v in (
        "强反转", "高爽点", "群像刻画", "细腻情感", "世界观宏大", "悬念密集",
        "成长线清晰", "反套路", "烧脑设定", "治愈日常", "家国情怀", "宿命感",
    )],
    # —— 作品大纲：结局类型 ——
    "outline_ending": [{"value": v} for v in (
        "HE 圆满", "BE 悲剧", "开放式", "反转结局", "双结局", "暗线收束", "闭环结局", "留白",
        "苦乐参半", "救赎结局", "毁灭结局", "新生结局", "悬念结局",
    )],
    # —— 章节：状态（新增枚举预设）——
    "chapter_status": [{"value": v} for v in (
        "已生成", "待修订", "草稿", "大纲", "已锁定", "已发布",
    )],
    # —— 章节：钩子类型（新增枚举预设）——
    "chapter_hook_type": [{"value": v} for v in (
        "悬念", "反转", "危机", "伏笔", "情感", "冲突", "揭秘", "转折",
    )],
}
