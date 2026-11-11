# -*- coding: utf-8 -*-
"""
AI 封面：Pollinations 出底图 + 本地排版「书名 / 作者 / 著」
================================================================
· 底图：Pollinations 免费出图（flux / flux-anime…），只吃英文提示词
· 中文提示词：本地词表最长匹配自动转英文；识别不出的中文按题材模板兜底
  （不调用大模型，零额外费用、零网络等待）
· 文字：书名+作者+著 本地 Pillow 绘制，字体优先思源黑体/宋体（SIL OFL，可商用）
· 尺寸：按平台制式（番茄 1400×2100、晋江 200×280…）或自定义，底图放大请求后
  LANCZOS 缩放，小尺寸封面也清晰
· 体积：统一压到 5MB 以内（PNG 超限自动转 JPG）
· 兜底：出图接口不可用（402 / 超时 / 被拦）时不报错，改用纯代码绘制的
  渐变 + 柔光底图继续排版，返回 fallback=True 与 notice 供前端提示
"""

import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

from paths import ROOT, book_dir

POLLINATIONS = "https://image.pollinations.ai/prompt/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NovelStudio/1.0"
MIN_SIDE, MAX_SIDE = 64, 4096          # 自定义封面尺寸范围
REQUEST_MIN, REQUEST_MAX = 64, 2048    # Pollinations 出图尺寸限制
MAX_BYTES = 5 * 1024 * 1024            # 多数平台上限 5MB

# ---------------------------------------------------------------- 平台制式
PLATFORMS = [
    {"key": "fanqie", "name": "番茄小说", "width": 1400, "height": 2100, "fmt": "jpg",
     "note": "常规作品封面，3:4，书名/作者不要贴边"},
    {"key": "fanqie_multi", "name": "番茄多封面", "width": 600, "height": 800, "fmt": "jpg",
     "note": "已签约、20 万字以上作品可用"},
    {"key": "yuewen", "name": "起点 / 创世 / 云起 / 咪咕 / 塔读 / 酷匠", "width": 600,
     "height": 800, "fmt": "jpg", "note": "阅文系平台常用规格"},
    {"key": "qimao", "name": "七猫小说", "width": 1080, "height": 1920, "fmt": "jpg",
     "note": "竖屏比例"},
    {"key": "bilibili", "name": "哔哩轻小说", "width": 1080, "height": 1920, "fmt": "jpg",
     "note": "最小可接受 720×1280"},
    {"key": "jjwxc", "name": "晋江文学城", "width": 200, "height": 280, "fmt": "jpg",
     "note": "通常只支持 JPG，体积限制较严"},
    {"key": "zongheng", "name": "纵横中文网", "width": 240, "height": 320, "fmt": "jpg",
     "note": "老规格，上传前建议再确认"},
    {"key": "17k", "name": "17K小说网", "width": 189, "height": 272, "fmt": "jpg",
     "note": "部分资料要求文件较小"},
    {"key": "feilu", "name": "飞卢小说", "width": 120, "height": 160, "fmt": "jpg",
     "note": "尺寸偏小，注意清晰度"},
]

MODELS = [
    {"key": "flux", "name": "flux", "note": "通用写实 / 插画，稳定性最好，推荐"},
    {"key": "flux-anime", "name": "flux-anime", "note": "二次元、轻小说、动漫风"},
    {"key": "flux-3d", "name": "flux-3d", "note": "3D 立体质感、游戏 CG 风"},
    {"key": "turbo", "name": "turbo", "note": "出图最快，细节略弱"},
]

STYLES = [
    {"key": "gold", "name": "烫金古风", "color": [245, 219, 160], "stroke": [28, 18, 8],
     "scrim": [8, 10, 16], "light": False, "note": "深色底图 + 金字，仙侠/古言常用"},
    {"key": "white", "name": "素白简洁", "color": [255, 255, 255], "stroke": [12, 14, 18],
     "scrim": [8, 10, 14], "light": False, "note": "任何底图都稳，都市/悬疑通用"},
    {"key": "ink", "name": "墨黑现代", "color": [22, 24, 28], "stroke": [255, 255, 255],
     "scrim": [244, 245, 247], "light": True, "note": "浅色底图 + 黑字，青春/现实题材"},
]

LAYOUTS = [
    {"key": "top", "name": "书名在上", "note": "最常见，标题压在画面上方"},
    {"key": "middle", "name": "书名居中", "note": "主体画面偏下，标题居中"},
    {"key": "bottom", "name": "书名在下", "note": "主体画面在上，标题沉底"},
]

# ---------------------------------------------------------------- 字体
# 优先开源免费字体（SIL OFL 1.1 / Apache 2.0，可商用）；都没有时回退系统字体。
FONT_DIRS = [
    os.path.join(ROOT, "assets", "fonts"),
    os.path.join(os.environ.get("WINDIR") or r"C:\Windows", "Fonts"),
]
if os.environ.get("LOCALAPPDATA"):      # 缺失时不能拼出相对路径去误配当前目录
    FONT_DIRS.append(os.path.join(os.environ["LOCALAPPDATA"], "Microsoft", "Windows", "Fonts"))
# 手机端：系统自带思源黑体（CJK），没有内置字体时也能出中文封面
if os.path.isdir("/system/fonts"):
    FONT_DIRS.append("/system/fonts")

TITLE_FONT_FILES = [
    ("Source Han Serif SC Heavy (TrueType).ttf", None, "思源宋体 Heavy"),
    ("SourceHanSerifSC-Heavy.otf", None, "思源宋体 Heavy"),
    ("SourceHanSerifSC-Bold.otf", None, "思源宋体 Bold"),
    ("NotoSerifSC-Black.otf", None, "Noto Serif SC Black"),
    ("NotoSerifSC-Bold.otf", None, "Noto Serif SC Bold"),
    ("NotoSansSC-VF.ttf", "Bold", "思源黑体 Bold"),
    ("NotoSansSC-VF.otf", "Bold", "思源黑体 Bold"),
    ("NotoSansSC-Bold.otf", None, "思源黑体 Bold"),
    ("SourceHanSansCN-Bold.ttf", None, "思源黑体 Bold"),
    ("SourceHanSansCN-Heavy.ttf", None, "思源黑体 Heavy"),
    ("HarmonyOS_Sans_SC_Bold.ttf", None, "HarmonyOS Sans SC Bold"),
    ("NotoSansCJKsc-Bold.otf", None, "思源黑体 Bold"),
    ("NotoSansCJK-Bold.ttc", None, "思源黑体 Bold"),
    ("msyhbd.ttc", None, "微软雅黑 Bold"),
    ("simhei.ttf", None, "黑体"),
]

BODY_FONT_FILES = [
    ("NotoSansSC-VF.ttf", "Regular", "思源黑体 Regular"),
    ("NotoSansSC-VF.otf", "Regular", "思源黑体 Regular"),
    ("NotoSansSC-Regular.otf", None, "思源黑体 Regular"),
    ("SourceHanSansCN-Normal.ttf", None, "思源黑体 Regular"),
    ("SourceHanSansCN-Regular.otf", None, "思源黑体 Regular"),
    ("NotoSansSC-Medium.otf", None, "思源黑体 Medium"),
    ("NotoSansCJKsc-Regular.otf", None, "思源黑体 Regular"),
    ("NotoSansCJK-Regular.ttc", None, "思源黑体 Regular"),
    ("DroidSansFallbackFull.ttf", None, "Android 内置中文字体"),
    ("msyh.ttc", None, "微软雅黑"),
    ("Deng.ttf", None, "等线"),
    ("simhei.ttf", None, "黑体"),
]

CJK_RE = re.compile(r"[\u2e80-\u9fff\u3040-\u30ff\uac00-\ud7af\uff00-\uffef]")


class CoverError(Exception):
    """可直接展示给用户的封面错误（提示词不合规 / 出图失败 / 字体缺失）。"""


# ================================================================ 中文 → 英文词表
# 常用意象，替换后按原文顺序拼接；长词优先，避免「雨天」被「雨」先吃掉。
VOCAB = {
    "雨夜": "rainy night", "雨": "rain", "雪夜": "snowy night", "雪": "snow",
    "雾": "thick fog", "云海": "sea of clouds", "云": "clouds", "风": "wind",
    "黄昏": "dusk", "夕阳": "sunset", "日出": "sunrise", "晨光": "morning light",
    "月光": "moonlight", "星空": "starry sky", "月亮": "moon", "雷电": "lightning",
    "夜晚": "night", "深夜": "late night", "白天": "daylight", "天空": "sky",
    "城市": "city", "都市": "modern city", "街道": "street", "小巷": "narrow alley",
    "霓虹灯": "neon lights", "霓虹": "neon lights", "高楼": "skyscrapers", "写字楼": "office buildings",
    "地铁": "subway", "屋顶": "rooftop", "桥": "bridge", "窗": "window",
    "海": "ocean", "湖": "lake", "河": "river", "瀑布": "waterfall",
    "山": "mountain", "仙山": "floating immortal mountain", "雪山": "snow mountain",
    "森林": "forest", "树林": "woods", "沙漠": "desert", "草原": "grassland",
    "花": "flowers", "樱花": "cherry blossoms", "桃花": "peach blossoms",
    "梅花": "plum blossoms", "莲": "lotus", "竹": "bamboo", "藤": "vines",
    "宫殿": "ancient palace", "庭院": "courtyard", "寺庙": "temple",
    "楼阁": "chinese pavilion", "城墙": "city wall", "古堡": "castle",
    "废墟": "ruins", "战场": "battlefield", "教室": "classroom", "操场": "playground",
    "街道上": "on the street", "长街": "long street", "牌楼": "memorial arch",
    "灯笼": "red lanterns", "灯": "lantern", "红烛": "red candles",
    "剑": "sword", "剑影": "sword light", "刀": "blade", "弓": "bow",
    "龙": "eastern dragon", "凤凰": "phoenix", "鹤": "crane", "狼": "wolf",
    "蝴蝶": "butterflies", "猫": "cat", "鸟": "birds", "鱼": "fish",
    "少女": "young woman", "少年": "young man", "女人": "woman", "男人": "man",
    "女主": "heroine", "男主": "hero",
    "背影": "seen from behind", "剪影": "silhouette", "侧脸": "profile view",
    "古装": "ancient chinese costume", "汉服": "hanfu", "长发": "long hair",
    "面具": "mask", "眼睛": "eyes", "手": "hand", "人群": "crowd",
    "书": "old book", "卷轴": "scroll", "琴": "guqin", "笛": "flute",
    "火": "fire", "火焰": "flames", "烟": "smoke", "血": "blood",
    "魔法": "magic", "法阵": "magic circle", "光束": "glowing light",
    "机械": "machinery", "机甲": "mecha", "机器人": "robot", "飞船": "spaceship",
    "未来": "futuristic", "赛博": "cyberpunk", "宇宙": "outer space",
    "电影感": "cinematic", "插画": "illustration", "油画": "oil painting",
    "水墨": "chinese ink painting", "水彩": "watercolor", "厚涂": "digital painting",
    "写实": "photorealistic", "二次元": "anime style", "国风": "chinese style",
    "暗黑": "dark mood", "冷色调": "cold color palette", "暖色调": "warm color palette",
    "高对比": "high contrast", "逆光": "backlight", "光晕": "glow",
    "细节": "highly detailed", "精致": "intricate details", "大气": "epic",
    "构图": "composition", "竖版": "vertical composition", "极简": "minimalist",
    "海报": "poster design", "无文字": "no text", "无水印": "no watermark",
}

# 题材模板：既参与中文词命中打分，也在中文无法逐词翻译时兜底
THEMES = [
    {"key": "xianxia", "name": "玄幻仙侠",
     "terms": {"仙侠": "xianxia fantasy", "修仙": "immortal cultivation",
               "御剑": "flying on a sword", "飞剑": "flying sword",
               "宗门": "ancient sect", "丹药": "alchemy pills", "灵气": "spiritual energy",
               "飞升": "ascension to heaven", "仙界": "immortal realm",
               "道袍": "taoist robe", "江湖": "jianghu", "武侠": "wuxia",
               "剑客": "swordsman", "秘境": "secret realm", "法宝": "magic artifact",
               "阵法": "spirit formation", "悬空": "floating in the air",
               "古风": "ancient chinese aesthetic", "玄幻": "eastern fantasy"},
     "prompt": "xianxia fantasy cover art, immortal cultivator silhouette on a floating "
               "mountain, ancient chinese pavilions, sea of clouds, golden light, epic "
               "cinematic composition, highly detailed digital painting"},

    {"key": "urban", "name": "都市异能",
     "terms": {"都市异能": "urban supernatural", "异能": "superpower",
               "总裁": "businessman in suit", "商战": "corporate battle",
               "跑车": "sports car", "咖啡": "coffee shop", "夜店": "nightclub",
               "手机": "smartphone", "现代": "modern", "都市": "metropolitan"},
     "prompt": "modern urban fantasy cover art, city skyline at night, neon reflections on "
               "wet streets, lone figure seen from behind, dramatic blue and purple lighting, "
               "cinematic, highly detailed"},

    {"key": "mystery", "name": "悬疑推理",
     "terms": {"悬疑": "mystery thriller", "推理": "detective story",
               "凶案": "crime scene", "警探": "detective", "侦探": "investigator",
               "尸体": "mysterious body", "线索": "clue", "迷雾": "dense fog",
               "审讯": "interrogation room", "血迹": "blood stain", "档案": "case files",
               "诡异": "eerie"},
     "prompt": "mystery thriller cover art, dark rainy alley at night, single street lamp, "
               "thick fog, mysterious silhouette, noir film lighting, muted cold tones, "
               "cinematic, highly detailed"},

    {"key": "romance", "name": "古言宫斗",
     "terms": {"宫廷": "imperial palace", "皇上": "emperor", "王爷": "prince",
               "妃子": "imperial consort", "宫斗": "palace intrigue",
               "古言": "ancient romance", "和亲": "political marriage",
               "珠帘": "beaded curtain", "刺绣": "embroidery", "长安": "ancient capital",
               "府邸": "mansion"},
     "prompt": "ancient chinese romance cover art, palace courtyard, elegant hanfu woman in "
               "profile, red lanterns, falling petals, soft cinematic light, oriental "
               "aesthetic, highly detailed"},

    {"key": "youth", "name": "青春言情",
     "terms": {"校园": "school campus", "青春": "youth", "校服": "school uniform",
               "同桌": "deskmate", "告白": "confession", "恋爱": "romance",
               "毕业": "graduation", "盛夏": "midsummer", "单车": "bicycle",
               "初恋": "first love"},
     "prompt": "soft romantic cover art, warm evening light, cherry blossoms, distant couple "
               "silhouette, dreamy pastel tones, cinematic bokeh, highly detailed"},

    {"key": "scifi", "name": "科幻末世",
     "terms": {"科幻": "science fiction", "末世": "post-apocalyptic", "废土": "wasteland",
               "星舰": "starship", "太空": "deep space", "外星": "alien world",
               "病毒": "virus outbreak", "实验室": "laboratory", "文明": "lost civilization"},
     "prompt": "science fiction cover art, futuristic ruined megacity, giant ringed planet in "
               "the sky, lone survivor silhouette, cinematic concept art, teal and orange, "
               "highly detailed"},

    {"key": "horror", "name": "惊悚怪谈",
     "terms": {"恐怖": "horror", "惊悚": "thriller", "怪谈": "ghost story",
               "副本": "dangerous dungeon", "无限流": "infinite loop", "怨灵": "vengeful spirit",
               "阴森": "creepy atmosphere", "棺材": "coffin", "鬼": "ghost"},
     "prompt": "dark horror cover art, abandoned corridor, flickering light, unsettling "
               "atmosphere, deep shadows, cinematic, highly detailed"},

    {"key": "history", "name": "历史战争",
     "terms": {"历史": "historical", "战争": "war", "将军": "general",
               "铁骑": "armored cavalry", "烽火": "beacon fire", "三国": "three kingdoms",
               "王朝": "dynasty", "沙场": "battlefield", "战马": "war horse", "帝": "emperor"},
     "prompt": "historical war cover art, ancient chinese battlefield, armored cavalry "
               "silhouette, fluttering banners, dust and beacon smoke, epic cinematic "
               "lighting, highly detailed"},

    {"key": "west_fantasy", "name": "西幻魔法",
     "terms": {"西幻": "western fantasy", "精灵": "elf", "巨龙": "huge dragon",
               "骑士": "knight", "法师": "mage", "魔法阵": "magic circle", "兽人": "orc",
               "城堡": "castle", "魔戒": "magic ring"},
     "prompt": "western fantasy cover art, glowing magic circle, ancient castle, dragon "
               "silhouette in the storm, epic cinematic lighting, highly detailed"},
]

GENERIC_PROMPT = ("atmospheric chinese novel cover art, dramatic cinematic lighting, rich "
                  "colors, highly detailed digital painting")
TAIL = "cinematic lighting, highly detailed, no text, no watermark"
# 中文标点统一成空格；英文逗号保留，方便把英文片段拆开去重
NOISE_CHARS = "，。、；：！？“”‘’（）《》【】—…·;:!?\"'<>[]{}/\\|@#$%^&*_+=~`"

# 题材「暗示词」：本身已能翻译，但可用于判断题材倾向（命中越多越像该类型）
THEME_HINTS = {
    "xianxia": ["仙山", "云海", "雾", "山", "剑", "剑影", "楼阁", "古风", "鹤", "竹"],
    "urban": ["霓虹", "城市", "街道", "高楼", "写字楼", "地铁", "夜店", "跑车"],
    "mystery": ["雨夜", "深夜", "雾", "小巷", "血", "诡异", "档案"],
    "romance": ["宫殿", "庭院", "灯笼", "红烛", "梅花", "长安", "古装", "汉服", "桃花"],
    "youth": ["樱花", "校园", "操场", "盛夏", "花", "少年", "少女"],
    "scifi": ["赛博", "机甲", "废墟", "星空", "宇宙", "飞船", "未来"],
    "horror": ["阴森", "鬼", "棺材", "深夜", "雾"],
    "history": ["战场", "烽火", "战马", "将军", "城墙"],
    "west_fantasy": ["巨龙", "城堡", "魔法", "骑士", "森林"],
}


# ================================================================ 中文翻译
def _norm(text):
    """全角标点统一成空格，避免「仙山，剑」这种断句把词粘在一起。"""
    s = str(text or "")
    for ch in NOISE_CHARS:
        s = s.replace(ch, " ")
    return re.sub(r"\s+", " ", s).strip()


def has_cjk(text):
    return bool(CJK_RE.search(str(text or "")))


def _build_vocab():
    vocab = dict(VOCAB)
    for t in THEMES:
        vocab.update(t["terms"])
    return vocab, sorted(vocab, key=len, reverse=True)


_VOCAB, _KEYS = _build_vocab()


def _clean_en(parts):
    """合并英文片段：按逗号拆小段、去空、去完全重复。"""
    seen, out = set(), []
    for p in parts:
        for seg in re.split(r"[,;]", str(p)):
            seg = re.sub(r"\s+", " ", seg).strip(" .")
            if not seg:
                continue
            k = seg.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(seg)
    return ", ".join(out)


def translate_prompt(text):
    """中文提示词 → 英文（词表最长匹配 + 题材模板兜底）。

    返回 {prompt_en, translated, theme, matched, unknown}
      · 纯英文输入原样返回，translated=False
      · 中文命中率高：按原文顺序拼英文片段（英文部分整段保留）
      · 中文命中率低（口语化描述、生僻词多）：改用命中最多的题材模板，
        已识别出的片段作为补充，无法翻译的中文丢弃
    """
    raw = _norm(text)
    if not raw:
        return {"prompt_en": "", "translated": False, "theme": "", "matched": [], "unknown": 0}

    parts, matched, unknown = [], [], 0
    buf = ""

    def flush():
        nonlocal buf
        if buf.strip():
            parts.append(buf.strip())
            buf = ""

    i = 0
    while i < len(raw):
        hit = next((k for k in _KEYS if raw.startswith(k, i)), None)
        if hit:
            flush()
            parts.append(_VOCAB[hit])
            matched.append(hit)
            i += len(hit)
        else:
            ch = raw[i]
            if has_cjk(ch):
                flush()
                unknown += 1
            else:
                buf += ch
            i += 1
    flush()

    en = _clean_en(parts)
    translated = has_cjk(raw)
    hit_chars = sum(len(m) for m in matched)

    # 题材打分：题材词 2 分，暗示词 1 分
    scores = {}
    for t in THEMES:
        keys = set(t["terms"]) | set(THEME_HINTS.get(t["key"], []))
        scores[t["key"]] = sum(2 if m in t["terms"] else 1 for m in matched if m in keys)
    best_key = max(scores, key=scores.get) if scores else ""
    theme = next((t for t in THEMES if t["key"] == best_key and scores[best_key] > 0), None)
    low_hit = unknown > max(2, hit_chars)

    if translated and (low_hit or len(en.split()) < 4):
        base = theme["prompt"] if theme else GENERIC_PROMPT
        en = _clean_en([base, en])
    if translated and "no watermark" not in en.lower() and len(en.split()) < 8:
        en = _clean_en([en, TAIL])

    return {
        "prompt_en": en[:900],
        "translated": translated,
        "theme": theme["name"] if (theme and translated) else "",
        "matched": matched[:12],
        "unknown": unknown,
    }


# ================================================================ 字体
def _choice(kind):
    files = TITLE_FONT_FILES if kind == "title" else BODY_FONT_FILES
    for fn, variation, label in files:
        for d in FONT_DIRS:
            if not d:
                continue
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                return p, variation, label
    raise CoverError("没找到可用的中文字体：请把免费的思源黑体（NotoSansSC-Regular.otf）"
                     "放进 assets/fonts/，或确认系统装有微软雅黑 / 黑体。")


def font_label():
    """实际使用的字体（前端展示「免费商用字体」说明用）。"""
    try:
        _, _, t = _choice("title")
        _, _, b = _choice("body")
        return f"{t} + {b}"
    except CoverError:
        return ""


@lru_cache(maxsize=128)
def _font(kind, size):
    from PIL import ImageFont
    path, variation, _ = _choice(kind)
    f = ImageFont.truetype(path, max(6, int(size)))
    if variation:
        try:
            f.set_variation_by_name(variation)
        except Exception:       # 非变量字体或 Pillow 版本不支持，忽略
            pass
    return f


# ================================================================ 出底图
def _request_size(width, height):
    """按目标比例请求一张「足够大」的底图：小尺寸封面靠放大请求保证清晰。"""
    k = max(1.0, 1024.0 / max(1, min(width, height)))
    w, h = int(round(width * k)), int(round(height * k))
    w = max(REQUEST_MIN, min(REQUEST_MAX, w - w % 8))
    h = max(REQUEST_MIN, min(REQUEST_MAX, h - h % 8))
    return w, h


def build_url(prompt, width, height, model="flux", seed=None):
    params = {"width": int(width), "height": int(height), "model": model or "flux",
              "nologo": "true", "enhance": "false"}
    if seed not in (None, ""):
        try:
            params["seed"] = int(seed)
        except (TypeError, ValueError):
            raise CoverError(f"种子必须是整数：{seed}") from None
    return POLLINATIONS + urllib.parse.quote(prompt, safe="") + "?" + \
        urllib.parse.urlencode(params)


def _http_detail(raw, limit=200):
    """从错误响应体提取可读说明；二进制 / 乱码响应直接丢弃，避免把乱码带给用户。"""
    try:
        txt = raw.decode("utf-8", "replace")
    except Exception:
        return ""
    txt = "".join(ch for ch in txt if ch.isprintable())
    txt = re.sub(r"\s+", " ", txt).strip()
    if not txt or txt.count("\ufffd") > len(txt) * 0.1:
        return ""
    return txt[:limit]


def fetch_base(prompt, width, height, model="flux", seed=None, timeout=150):
    """从 Pollinations 拉底图字节；失败抛 CoverError（带中文原因，可直接展示）。"""
    prompt = sanitize_prompt(prompt)
    if not prompt:
        raise CoverError("底图提示词为空")
    if has_cjk(prompt):
        raise CoverError("提示词里还有中文没能转换成功，请换一种说法或直接写英文")

    url = build_url(prompt, width, height, model, seed)
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                       "Accept": "image/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                ctype = (r.headers.get("Content-Type") or "").lower()
            if ctype.startswith("image/") and len(data) > 2048:
                return data
            detail = ""
            try:
                detail = json.loads(data[:2000].decode("utf-8", "replace")).get("error") or ""
            except Exception:
                pass
            last = CoverError(f"出图接口返回异常（{ctype or '空响应'}）"
                              + (f"：{detail}" if detail else ""))
        except urllib.error.HTTPError as e:
            try:
                detail = _http_detail(e.read()[:600])
            except Exception:
                detail = ""
            last = CoverError(f"出图接口 HTTP {e.code}"
                              + (f"：{detail}" if detail else "，稍后重试或换 flux 模型"))
            if 400 <= e.code < 500 and e.code != 429:
                break
        except Exception as e:      # 超时 / DNS / 网络被拦
            last = CoverError(f"连接出图接口失败：{e}")
        if i < 2:                    # 最后一次重试失败后直接抛出，不再白等
            time.sleep(1.2 * (i + 1))
    raise last or CoverError("出图失败，请稍后重试")


def _ai_endpoint(base_url):
    """把用户填的 Base URL 拼成 OpenAI 兼容的 /images/generations 地址。"""
    b = str(base_url or "").strip().rstrip("/")
    if not b:
        return ""
    if b.endswith("/images/generations"):
        return b
    if not re.search(r"/v\d+$", b):
        b += "/v1"
    return b + "/images/generations"


def _ai_size(width, height):
    """按要求宽高比挑一档常见出图尺寸：多数 OpenAI 兼容服务只认这几档，
    底图拿回来后会 LANCZOS 缩放到封面目标尺寸。"""
    ratio = float(width) / max(1.0, float(height))
    best = min(((1024, 1536), (1536, 1024), (1024, 1024)),
               key=lambda s: abs(s[0] / s[1] - ratio))
    return "%dx%d" % best


def fetch_ai_base(prompt, width, height, api_key, base_url, model, timeout=180):
    """用用户配置的模型出底图（OpenAI 兼容 images/generations）。

    模型不支持出图（404 / 400 / 余额不足 / 没返回图片）时抛 CoverError，
    由 generate_cover 回退到原来的 Pollinations → 本地绘制链路。
    """
    if not api_key:
        raise CoverError("模型档案没有填 API Key")
    if not model:
        raise CoverError("模型档案没有设置模型名")
    url = _ai_endpoint(base_url)
    if not url:
        raise CoverError("模型档案没有设置 Base URL")
    body = json.dumps({
        "model": model,
        "prompt": sanitize_prompt(prompt),
        "n": 1,
        "size": _ai_size(width, height),
        "response_format": "b64_json",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + api_key,
        "User-Agent": USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        detail = _http_detail(e.read()[:800])
        raise CoverError("AI 模型出图失败（HTTP %s%s）" % (e.code, ("：" + detail) if detail else ""))
    except Exception as e:      # 超时 / DNS / 网址不对
        raise CoverError("连接 AI 模型失败：%s" % e)

    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        raise CoverError("AI 模型返回的不是 JSON")
    item = ((payload.get("data") or [{}])[0] or {})
    b64 = item.get("b64_json") or item.get("b64") or ""
    if b64:
        try:
            data = base64.b64decode(b64)
        except Exception:
            raise CoverError("AI 模型返回的图片无法解码")
        if len(data) > 2048:
            return data
    img_url = item.get("url") or ""
    if img_url:
        try:
            req2 = urllib.request.Request(img_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req2, timeout=timeout) as r2:
                data = r2.read()
            if len(data) > 2048:
                return data
        except Exception as e:
            raise CoverError("下载 AI 模型图片失败：%s" % e)
    err = payload.get("error")
    if isinstance(err, dict):
        err = err.get("message") or err.get("code")
    raise CoverError("AI 模型没有返回图片" + (("：" + str(err)[:120]) if err else ""))


def sanitize_prompt(prompt, limit=900):
    return re.sub(r"\s+", " ", str(prompt or "")).strip()[:limit]


# ---------------------------------------------------------------- 本地兜底底图
# 出图接口不可用（HTTP 402 额度不足 / 超时 / 网络被拦）时，用纯代码画一张底图，
# 保证封面照样能出，只是画面由渐变 + 柔光斑构成，不再有 AI 插画。
FALLBACK_COLORS = {
    "xianxia": ((22, 26, 60), (96, 80, 34), (245, 219, 160)),
    "urban": ((18, 24, 48), (72, 58, 140), (120, 140, 255)),
    "mystery": ((14, 19, 26), (44, 58, 74), (150, 180, 210)),
    "romance": ((52, 18, 30), (140, 56, 72), (255, 190, 170)),
    "youth": ((50, 34, 46), (198, 132, 116), (255, 225, 205)),
    "scifi": ((10, 26, 36), (28, 90, 102), (110, 225, 225)),
    "horror": ((10, 10, 12), (34, 34, 38), (95, 95, 100)),
    "history": ((34, 24, 13), (104, 86, 55), (230, 200, 140)),
    "west_fantasy": ((24, 15, 48), (72, 40, 118), (190, 150, 255)),
}
FALLBACK_DEFAULT = ((20, 24, 33), (56, 72, 92), (200, 220, 240))


def fallback_base(width, height, theme_key="", prompt=""):
    """纯代码绘制底图：题材配色纵向渐变 + 柔光斑 + 轻暗角，返回 PNG 字节。

    不依赖网络，秒出；同题材 + 同提示词结果可复现（按内容做随机种子）。
    """
    import random

    from PIL import Image, ImageDraw, ImageFilter

    W, H = int(width), int(height)
    top, bottom, glow = FALLBACK_COLORS.get(theme_key, FALLBACK_DEFAULT)
    rnd = random.Random(f"{theme_key}|{prompt}|{W}x{H}")

    grad = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / max(1, H - 1)
        grad.putpixel((0, y), (int(top[0] + (bottom[0] - top[0]) * t),
                               int(top[1] + (bottom[1] - top[1]) * t),
                               int(top[2] + (bottom[2] - top[2]) * t)))
    img = grad.resize((W, H)).convert("RGBA")

    # 柔光斑：模拟画面光源，避免纯渐变的塑料感
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    base_r = float(min(W, H))
    for _ in range(3):
        cx = rnd.randint(int(W * 0.08), int(W * 0.92))
        cy = rnd.randint(int(H * 0.06), int(H * 0.74))
        rr = rnd.randint(int(base_r * 0.22), int(base_r * 0.55))
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr),
                  fill=tuple(glow) + (rnd.randint(38, 70),))
    img = Image.alpha_composite(img, layer.filter(ImageFilter.GaussianBlur(base_r * 0.10)))

    # 上下轻暗角，画面收边、文字更聚焦
    vig = Image.new("L", (1, H))
    for y in range(H):
        t = abs(y / max(1, H - 1) - 0.5) * 2
        vig.putpixel((0, y), int(70 * t ** 1.6))
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shade.putalpha(vig.resize((W, H)))
    img = Image.alpha_composite(img, shade)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


# ================================================================ 排版辅助
def _rounded_layer(size, box, color, alpha, radius, fill=True, width=1):
    from PIL import Image, ImageDraw
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    col = tuple(color) + (alpha,)
    if fill:
        d.rounded_rectangle(box, radius=radius, fill=col)
    else:
        d.rounded_rectangle(box, radius=radius, outline=col, width=width)
    return layer


def _fade(size, color, strength=210, start_ratio=0.58):
    """底部压暗/提亮渐变，保证作者名在任何底图上都读得清。"""
    from PIL import Image
    W, H = size
    grad = Image.new("L", (1, H))
    for y in range(H):
        t = (y / max(1, H - 1) - start_ratio) / max(1e-6, 1 - start_ratio)
        grad.putpixel((0, y), 0 if t <= 0 else int(strength * min(1.0, t) ** 1.25))
    layer = Image.new("RGBA", (W, H), tuple(color) + (0,))
    layer.putalpha(grad.resize((W, H)))
    return layer


def _wrap(draw, text, font, max_w):
    """中英混排换行：CJK 逐字断，英文按单词断。"""
    tokens = re.findall(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*|[ \t]+|[^\s]", text)
    lines, cur = [], ""
    for t in tokens:
        cand = cur + t
        if cur and t.strip() and draw.textlength(cand, font=font) > max_w:
            lines.append(cur.rstrip())
            cur = t
        else:
            cur = cand
    if cur.strip():
        lines.append(cur.strip())
    return lines or [text]


def _fit(draw, text, max_w, max_lines, kind, start, minimum):
    """从大字号往下试，直到行数与宽度都放得下。"""
    size = max(minimum, int(start))
    while size > minimum:
        font = _font(kind, size)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) <= max_lines and \
                max(draw.textlength(l, font=font) for l in lines) <= max_w:
            return font, lines, size
        size = max(minimum, int(size * 0.92))
        if size == minimum:
            break
    font = _font(kind, minimum)
    lines = _wrap(draw, text, font, max_w)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…" if len(lines[-1]) > 1 else lines[-1]
    return font, lines, minimum


def _positions(draw, lines, font, center_x, top, step):
    out = []
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = center_x - (bbox[2] + bbox[0]) / 2
        out.append((line, x, top + i * step - bbox[1]))
    return out


def compose(base_bytes, width, height, title, author, style="gold", layout="top"):
    """把书名 + 作者 + 著 排到底图上，返回 PIL Image（RGB）。"""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    W, H = int(width), int(height)
    try:
        base = Image.open(io.BytesIO(base_bytes))
        base.load()
    except Exception as e:
        raise CoverError("底图解码失败：" + str(e))

    img = ImageOps.fit(base.convert("RGB"), (W, H), Image.LANCZOS,
                       centering=(0.5, 0.42)).convert("RGBA")
    st = next((s for s in STYLES if s["key"] == style), STYLES[0])
    accent = tuple(st["color"])
    stroke = tuple(st["stroke"])
    scrim = tuple(st["scrim"])
    light = bool(st["light"])
    draw = ImageDraw.Draw(img)

    pad = max(5, int(round(min(W, H) * 0.075)))
    max_w = W - 2 * pad
    title = (title or "").strip() or "未命名"
    author = (author or "").strip()

    # ---- 书名：字号自适应，最多 2~4 行
    start = min(int(round(W * 0.155)), int(round(H * 0.14)))
    minimum = max(8, int(round(W * 0.034)))
    max_lines = 2 if len(title) <= 8 else 3 if len(title) <= 20 else 4
    font_t, lines, t_size = _fit(draw, title, max_w, max_lines, "title", start, minimum)
    asc, desc = font_t.getmetrics()
    t_lh = asc + desc
    t_step = int(round(t_lh * 1.04))
    t_h = t_step * (len(lines) - 1) + t_lh

    # ---- 作者：字号跟随书名，超宽则缩
    a_text = author + (" 著" if author and not author.endswith("著") else "")
    a_size = max(8, int(round(t_size * 0.40)))
    font_a = _font("body", a_size)
    while a_text and a_size > 8 and draw.textlength(a_text, font=font_a) > max_w * 0.92:
        a_size -= 1
        font_a = _font("body", a_size)
    aa, ad = font_a.getmetrics()
    a_lh = aa + ad

    author_y = H - pad - a_lh
    divider_y = author_y - int(round(pad * 0.55))

    # ---- 书名纵向位置
    if layout == "bottom":
        t_y = author_y - int(round(pad * 1.0)) - t_h
    elif layout == "middle":
        t_y = int((H - t_h) * 0.44)
    else:
        t_y = pad + int(round(pad * 0.12))
    t_y = max(pad // 2, min(t_y, divider_y - int(round(pad * 0.4)) - t_h))

    # ---- 底层：底部渐变 + 书名半透明底衬（保证文字可读）
    img.alpha_composite(_fade((W, H), (252, 252, 252) if light else (4, 6, 10),
                              240 if light else 205, 0.55))
    panel_top = max(0, t_y - int(round(pad * 0.34)))
    panel_box = (pad * 0.42, panel_top, W - pad * 0.42,
                 min(H - 1, t_y + t_h + int(round(pad * 0.30))))
    img.alpha_composite(_rounded_layer((W, H), panel_box,
                                       (250, 250, 250) if light else scrim,
                                       170 if light else 108,
                                       max(3, int(round(min(W, H) * 0.03)))))

    # 细边框（内缩，不贴边）
    inset = max(2, int(round(min(W, H) * 0.032)))
    img.alpha_composite(_rounded_layer(
        (W, H), (inset, inset, W - 1 - inset, H - 1 - inset), accent, 74,
        max(2, int(round(min(W, H) * 0.018))), fill=False,
        width=max(1, int(round(W * 0.0035)))))

    # ---- 书名：先画一层模糊阴影，再画正文
    t_pos = _positions(draw, lines, font_t, W / 2, t_y, t_step)
    sw = max(1, int(round(t_size * 0.045))) if t_size >= 22 else 0
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    off = max(1, int(round(t_size * 0.035)))
    for line, x, y in t_pos:
        sd.text((x + off, y + off), line, font=font_t,
                fill=(255, 255, 255, 0) if light else (0, 0, 0, 165),
                stroke_width=sw, stroke_fill=(0, 0, 0, 165) if not light else (255, 255, 255, 0))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(1, t_size * 0.055))))
    for line, x, y in t_pos:
        draw.text((x, y), line, font=font_t, fill=accent + (255,),
                  stroke_width=sw, stroke_fill=stroke + (255,))

    # ---- 分隔线 + 作者名
    line_w = max(12, int(round(W * 0.16)))
    draw.line([(W // 2 - line_w // 2, divider_y), (W // 2 + line_w // 2, divider_y)],
              fill=accent + (150,), width=max(1, int(round(W * 0.003))))
    if a_text:
        sw_a = max(1, int(round(a_size * 0.05))) if a_size >= 20 else 0
        for line, x, y in _positions(draw, [a_text], font_a, W / 2, author_y, a_lh):
            draw.text((x, y), line, font=font_a, fill=accent + (255,),
                      stroke_width=sw_a, stroke_fill=stroke + (235,))

    return img.convert("RGB")


# ================================================================ 输出与保存
def encode(img, fmt="jpg"):
    """编码成字节：JPG 逐级降质直到 ≤5MB；PNG 超限自动改存 JPG。"""
    if str(fmt).lower() == "png":
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        if buf.tell() <= MAX_BYTES:
            return buf.getvalue(), "png"
        # 竖版大图 PNG 常超 5MB，多数平台也接受 JPG，直接转
    buf = io.BytesIO()
    for q in (94, 90, 86, 82, 78, 74, 70, 64, 58):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True, progressive=True, subsampling=1)
        if buf.tell() <= MAX_BYTES:
            break
    return buf.getvalue(), "jpg"


def save_cover(book, data, ext):
    """写入 data/<书>/cover.<ext>，并清掉旧格式的封面文件。"""
    d = book_dir(book)
    os.makedirs(d, exist_ok=True)
    for e in ("png", "jpg", "jpeg", "webp"):
        old = os.path.join(d, "cover." + e)
        if os.path.isfile(old):
            try:
                os.remove(old)
            except OSError:
                pass
    path = os.path.join(d, "cover." + ext)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _base_cache(book):
    """底图缓存：换书名/字体时不必重新出图（省时间、省流量）。"""
    d = book_dir(book)
    for e in ("png", "jpg", "jpeg", "webp"):
        p = os.path.join(d, "cover_base." + e)
        if os.path.isfile(p):
            return p
    return ""


def _save_base(book, data):
    d = book_dir(book)
    os.makedirs(d, exist_ok=True)
    try:
        from PIL import Image
        fmt = (Image.open(io.BytesIO(data)).format or "JPEG").lower()
    except Exception:
        fmt = "jpeg"
    ext = "png" if fmt == "png" else "webp" if fmt == "webp" else "jpg"
    path = os.path.join(d, "cover_base." + ext)
    with open(path, "wb") as f:
        f.write(data)
    return path


def clamp_int(v, lo, hi, default):
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def generate_cover(book, prompt="", width=1400, height=2100, title="", author="",
                   model="flux", style="gold", layout="top", fmt="jpg",
                   seed=None, reuse_base=False,
                   api_key="", base_url="", ai_model=""):
    """生成封面并落盘，返回给接口的元信息。

    参数：
      book    书名（data/ 下的目录名，调用方已清洗）
      prompt  提示词，可以是中文（自动转英文），也可以是英文
      width/height  目标像素尺寸（平台制式或自定义）
    """
    if not book:
        raise CoverError("请选择作品")
    W = clamp_int(width, MIN_SIDE, MAX_SIDE, 1400)
    H = clamp_int(height, MIN_SIDE, MAX_SIDE, 2100)
    t0 = time.time()

    tr = translate_prompt(prompt)
    en = tr["prompt_en"]
    theme_key = next((t["key"] for t in THEMES if t["name"] == tr["theme"]), "")
    base = b""
    fallback = False
    note = ""
    ai_used = False
    ai_note = ""
    reused = False
    if reuse_base:
        cached = _base_cache(book)
        if cached:
            with open(cached, "rb") as f:
                base = f.read()
                reused = bool(base)
    if not base:
        if not en:
            raise CoverError("没有可复用的底图：请先完整生成一次，或填写底图提示词重新出图")
        rw, rh = _request_size(W, H)
        # 配置了模型档案就优先用模型出图；模型不支持（404 / 400 / 无图片）时
        # 接着走原来的 Pollinations，再不行才用本地代码画底图。
        if api_key and ai_model:
            try:
                base = fetch_ai_base(en, rw, rh, api_key, base_url, ai_model)
                _save_base(book, base)
                ai_used = True
            except CoverError as e:
                ai_note = re.sub(r"\s+", " ", str(e))[:120]
        if not base:
            try:
                base = fetch_base(en, rw, rh, model, seed)
                _save_base(book, base)
            except CoverError as e:
                # 出图接口不可用（402 额度不足 / 超时 / 网络被拦）：纯代码画一张底图顶上，
                # 封面照常生成。降级底图不写 cover_base 缓存，之后重试仍会重新出图。
                fallback = True
                note = re.sub(r"\s+", " ", str(e))[:90]
                base = fallback_base(rw, rh, theme_key, en)

    img = compose(base, W, H, title, author, style, layout)
    data, ext = encode(img, fmt)
    save_cover(book, data, ext)

    if reused:
        source = "cached"
    elif ai_used:
        source = "ai"
    elif fallback:
        source = "local"
    else:
        source = "pollinations"

    return {
        "ok": True,
        "width": W,
        "height": H,
        "fmt": ext,
        "bytes": len(data),
        "model": "local" if fallback else (ai_model if ai_used else (model if not reused else "cached")),
        "source": source,
        "ai_model": ai_model if ai_used else "",
        "ai_note": ai_note,
        "fallback": fallback,
        "notice": (f"出图接口不可用（{note}），已用本地代码绘制底图" if fallback else ""),
        "prompt_zh": sanitize_prompt(prompt, 400),
        "prompt_en": en,
        "translated": tr["translated"],
        "theme": tr["theme"],
        "matched": tr["matched"],
        "style": style,
        "layout": layout,
        "font": font_label(),
        "elapsed": round(time.time() - t0, 1),
    }


def preset_list():
    """前端下拉：平台制式 + 模型 + 文字风格 + 版式。"""
    return {
        "platforms": [dict(p) for p in PLATFORMS],
        "models": [dict(m) for m in MODELS],
        "styles": [dict(s) for s in STYLES],
        "layouts": [dict(l) for l in LAYOUTS],
        "min_side": MIN_SIDE,
        "max_side": MAX_SIDE,
        "max_bytes": MAX_BYTES,
        "font": font_label(),
    }
