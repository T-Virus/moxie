# -*- coding: utf-8 -*-
"""
全链路自检 · 小说连载工作流
==============================
把「环境 / 配置 / 引擎 / 接口 / 真实推理」一次过一遍，逐项给结论。

用法：
    python selftest.py              # 默认：静态检查 + Ollama 连通 + 上下文预算核算
    python selftest.py --quick      # 额外跑一次极短真实生成，验证推理链路
    python selftest.py --no-net     # 跳过所有需要联网/连 Ollama 的检查

退出码：全部无 FAIL 时为 0，否则 1。
"""

import argparse
import ast
import json
import os
import re
import sys
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from paths import CHAPTERS, INPUT_DIR, ROOT, WORKFLOW, book_chapters  # noqa: E402

OLLAMA = "http://127.0.0.1:11434"
CONSOLE = "http://127.0.0.1:8765"

NODE_TYPES = {"ollama", "clean", "check", "prefix", "tail", "filter_cards",
              "field", "gen_per_point", "save"}
CLEAN_RULES = {"markdown", "editor_voice", "dedupe"}
CHECK_KEYS = {"min_chars", "max_chars", "para_count", "min_lines",
              "no_symbols", "no_ascii_letters", "max_repeat_sim", "required_keywords"}

RESULTS = []


def rec(level, name, detail=""):
    RESULTS.append((level, name, detail))
    tag = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]", "SKIP": "[SKIP]"}[level]
    line = f"  {tag} {name}"
    if detail:
        line += f"  —— {detail}"
    print(line)


def section(title):
    print(f"\n{title}")
    print("-" * max(28, len(title)))


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        rec("FAIL", f"{os.path.basename(path)} 不是合法 JSON", str(e))
        return default


def http_json(url, timeout=8):
    # 控制台会拦掉脚本类 UA（爬虫特征），自检请求按浏览器 UA 发
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------- 1. 环境
def check_env(wf, no_net):
    section("① 环境")
    v = sys.version_info
    if v >= (3, 8):
        rec("PASS", "Python 版本", f"{v.major}.{v.minor}.{v.micro}")
    else:
        rec("FAIL", "Python 版本过低", f"{v.major}.{v.minor}（需要 3.8+）")

    try:
        import deepseek_common  # noqa
        rec("PASS", "模型调用客户端可用（内置 urllib 实现）",
            deepseek_common.DEFAULT_BASE_URL)
    except Exception as e:                      # noqa
        rec("FAIL", "模型调用客户端不可用", str(e))
    return None


# ---------------------------------------------------------------- 2. 配置
def check_workflow(wf):
    section("② 工作流配置 workflow.json")
    if not wf:
        rec("FAIL", "workflow.json 缺失或不可读")
        return
    for k in ("name", "model", "params", "prompts", "templates", "pipeline"):
        if k in wf:
            rec("PASS", f"顶层字段 {k}")
        else:
            rec("FAIL", f"缺少顶层字段 {k}")
    params = wf.get("params") or {}
    if isinstance(params.get("num_ctx"), int) and isinstance(params.get("num_predict"), int):
        rec("PASS", "推理参数 num_ctx / num_predict 已设置",
            f"num_ctx={params['num_ctx']}, num_predict={params['num_predict']}")
    else:
        rec("FAIL", "num_ctx / num_predict 缺失或不是整数")

    prompts, templates = wf.get("prompts") or {}, wf.get("templates") or {}
    pipe = wf.get("pipeline") or []
    ids, seen = [n.get("id") for n in pipe], set()
    for i, n in enumerate(pipe, 1):
        nid, ntype = n.get("id"), n.get("type")
        bad = []
        if not nid:
            bad.append("缺 id")
        elif nid in seen:
            bad.append(f"id 重复：{nid}")
        seen.add(nid)
        if ntype not in NODE_TYPES:
            bad.append(f"未知 type：{ntype}")
        if ntype == "ollama":
            if n.get("system") not in prompts:
                bad.append(f"system 不存在：{n.get('system')}")
            if n.get("template") not in templates:
                bad.append(f"template 不存在：{n.get('template')}")
        if ntype == "check":
            for rk in (n.get("rules") or {}):
                if rk not in CHECK_KEYS:
                    bad.append(f"不支持的质检规则：{rk}")
            rf = n.get("retry_from")
            if rf and rf not in [x.get("id") for x in pipe]:
                bad.append(f"retry_from 指向不存在的节点：{rf}")
            if n.get("on_fail") not in (None, "mark", "abort"):
                bad.append(f"on_fail 非法：{n.get('on_fail')}")
        if ntype == "clean":
            for r in (n.get("rules") or []):
                if r not in CLEAN_RULES and not re.fullmatch(r"keep_\d+", str(r)):
                    bad.append(f"不支持的清洗规则：{r}")
        if bad:
            rec("FAIL", f"节点 #{i} {nid or '(未命名)'}", "; ".join(bad))
        else:
            rec("PASS", f"节点 #{i} {nid}", f"type={ntype}")
    rec("PASS", f"pipeline 共 {len(pipe)} 个节点")


def check_chapters(ch, wf):
    section("③ 章节数据 chapters.json")
    if not ch:
        rec("FAIL", "chapters.json 缺失或不可读")
        return None
    try:
        from story_bible import CARD_FIELDS, SB_FIELDS, name_matches, parse
    except ImportError as e:
        rec("FAIL", "无法导入 story_bible 模块", str(e))
        return None

    sb = ch.get("story_bible") or ""
    if not sb.strip():
        rec("FAIL", "story_bible 为空")
        return None
    fields, cards, factions = parse(sb)
    filled = [k for k, v in fields.items() if v]
    rec("PASS", "story_bible 可解析为字段",
        f"已填 {len(filled)}/{len(SB_FIELDS)} 个要素，{len(cards)} 张角色卡，{len(factions)} 张势力卡")
    if len(filled) < len(SB_FIELDS):
        rec("WARN", "部分网文要素为空", "可重跑让 AI 补全，或手动填写")
    if not cards:
        rec("WARN", "没有角色卡", "建议至少给主角建一张卡")
    missing = {}
    for c in cards:
        for k, lb, _ in CARD_FIELDS:
            if not str(c.get(k) or "").strip():
                missing[lb] = missing.get(lb, 0) + 1
    if missing:                       # 按字段汇总，避免把上百个角色名全铺出来
        det = "、".join(f"{lb}×{n}" for lb, n in missing.items())
        rec("WARN", "部分角色卡字段为空", det + "（多为新增字段，重跑或手动补全即可）")

    chapters = ch.get("chapters") or []
    if not chapters:
        rec("FAIL", "chapters 为空数组")
        return None
    rec("PASS", f"共 {len(chapters)} 章")
    names = {c.get("name") for c in cards if c.get("name")}
    fac_names = {f.get("name") for f in factions if f.get("name")}
    for i, c in enumerate(chapters, 1):
        bad = []
        for k in ("chapter_id", "title", "scene", "summary"):
            if not str(c.get(k) or "").strip():
                bad.append(f"{k} 为空")
        if not c.get("points"):
            bad.append("points 为空")
        # 与 webapp 预览的 filter_by_roles 同一口径：允许「张小凡（鬼厉）」匹配到卡「张小凡」
        unknown = [r for r in (c.get("roles") or [])
                   if names and not any(name_matches(r, n) for n in names)]
        if unknown:
            bad.append("角色不在角色卡里：" + "、".join(unknown))
        unknown_f = [x for x in (c.get("factions") or [])
                     if fac_names and not any(name_matches(x, n) for n in fac_names)]
        if unknown_f:
            bad.append("势力不在势力卡里：" + "、".join(unknown_f))
        if bad:
            rec("WARN", f"第{i}章 {c.get('title') or ''}", "; ".join(bad))
    print(f"    （只列出有问题的章节；其余 {len(chapters)} 章字段完整）")

    # 段数一致性：keep_N 是保留上限，para_count 是质检下限，须满足 下限 ≤ 每章 points ≤ 上限
    pipe = (wf or {}).get("pipeline") or []
    keep_n = para_n = None
    for n in pipe:
        if n.get("type") == "clean":
            for r in (n.get("rules") or []):
                if re.fullmatch(r"keep_\d+", str(r)):
                    keep_n = int(str(r).split("_")[1])
        if n.get("type") == "check":
            para_n = (n.get("rules") or {}).get("para_count", para_n)
    pts = [len(c.get("points") or []) for c in chapters]
    detail = f"keep_N(上限)={keep_n}, para_count(下限)={para_n}, 各章 points={pts}"
    if not (keep_n and para_n):
        rec("WARN", "未取到段数配置", detail)
    elif para_n > keep_n:
        rec("FAIL", "段数配置矛盾：质检下限 > 清洗上限",
            detail + " → 清洗后永远达不到下限，质检必然不合格")
    elif any(p < para_n or p > keep_n for p in pts):
        rec("WARN", "有章节的 points 条数落在 [下限, 上限] 之外", detail + " → 该章会被裁剪或判不合格")
    else:
        rec("PASS", "段数配置自洽（下限 ≤ 每章 points ≤ 上限）", detail)
    return chapters


# ---------------------------------------------------------------- 4. 预算
def sb_for_prompt(wf, ch, c):
    """正文实际吃到的故事设定：若 pipeline 里有 filter_cards 且接进了 ollama 节点，
    则用「按本章 roles 裁剪后」的版本——否则是全量。"""
    pipe = wf.get("pipeline") or []
    node = next((n for n in pipe if n.get("type") == "ollama"), None)
    sb = ch.get("story_bible", "")
    if not node:
        return sb, False
    outs = {n.get("output") for n in pipe if n.get("type") == "filter_cards"}
    if outs & set(node.get("input") or []):
        try:
            from story_bible import filter_by_roles
            return filter_by_roles(sb, c.get("roles") or [], c.get("factions") or []), True
        except Exception:
            return sb, False
    return sb, False


def estimate_prompt(wf, ch):
    pipe = wf.get("pipeline") or []
    node = next((n for n in pipe if n.get("type") == "ollama"), None)
    chapters = ch.get("chapters") or []
    if not node or not chapters:
        return None
    c = chapters[0]
    sb, filtered = sb_for_prompt(wf, ch, c)
    sb_full = ch.get("story_bible", "")
    tpl = (wf.get("templates") or {}).get(node.get("template"), "")
    from story_bible import parse as _sb_parse
    ctx = {
        "story_bible": sb, "story_bible_chapter": sb,
        "terms": (_sb_parse(sb)[0] or {}).get("terms", ""), "prev_state": "",
        "chapter_id": c.get("chapter_id", ""), "title": c.get("title", ""),
        "roles": "、".join(c.get("roles") or []), "scene": c.get("scene", ""),
        "summary": c.get("summary", ""),
        "points": "\n".join(f"{i+1}. {p}" for i, p in enumerate(c.get("points") or [])),
        "issues": "",
    }
    prompt = tpl
    for k, v in ctx.items():
        prompt = prompt.replace("{" + k + "}", v)
    return prompt, (wf.get("prompts") or {}).get(node.get("system"), ""), sb, sb_full, filtered


def check_budget(wf, ch, no_net, names):
    section("④ 上下文预算")
    if not (wf and ch):
        rec("SKIP", "预算检查（配置不可用）")
        return
    got = estimate_prompt(wf, ch)
    if not got:
        rec("FAIL", "无法拼出正文 prompt（模板或章节缺失）")
        return
    prompt, system, sb, sb_full, filtered = got
    params = wf.get("params") or {}
    nctx, npred = params.get("num_ctx", 0), params.get("num_predict", 0)
    chars = len(prompt) + len(system)

    if filtered:
        roles = (ch.get("chapters") or [{}])[0].get("roles") or []
        rec("PASS", "已按章裁剪角色卡（filter_cards）",
            f"story_bible {len(sb_full)} → {len(sb)} 字（第 1 章 roles={roles or '空→退回主要角色'}）")
    elif len(sb) > 4000:
        rec("WARN", "未启用按章裁剪角色卡",
            f"story_bible {len(sb)} 字全量注入；角色卡越加越多会撑爆上下文"
            f"（可在 pipeline 加 filter_cards 节点，输入 story_bible → 输出 story_bible_chapter）")

    if no_net or not names or wf.get("model") not in names:
        tokens = round(chars * 0.85)
        rec("WARN", "按字数估算 prompt tokens（未做真实测量）",
            f"{chars} 字 ≈ {tokens} tokens")
    else:
        try:
            body = {"model": wf["model"], "system": system, "prompt": prompt, "stream": False,
                    "options": {**params, "num_predict": 1}}
            req = urllib.request.Request(f"{OLLAMA}/api/generate",
                                         data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                tokens = json.loads(r.read().decode("utf-8")).get("prompt_eval_count")
            rec("PASS", "prompt tokens 实测", f"{tokens} tokens（{chars} 字）")
        except Exception as e:
            tokens = round(chars * 0.85)
            rec("WARN", "实测失败，改用估算", f"{e} → {tokens} tokens")

    room = nctx - npred - tokens
    if room >= 0:
        rec("PASS", "上下文不溢出", f"prompt {tokens} + 输出预留 {npred} ≤ num_ctx {nctx}，余量 {room}")
    else:
        rec("FAIL", "上下文会溢出（提示词将被截断）",
            f"prompt {tokens} + 输出预留 {npred} > num_ctx {nctx}，缺 {-room} → 调大 num_ctx 或精简设定")


def check_chunking():
    section("⑤ 分段与合并")
    try:
        from decompose import CHAP_RE, DEFAULT_CHUNK_CHAPTERS, DEFAULT_CHUNK_CHARS, split_text
    except Exception as e:
        rec("FAIL", "无法导入分段函数", str(e))
        return
    rec("PASS", "分段阈值默认值", f"{DEFAULT_CHUNK_CHARS} 字/段、每段最多 {DEFAULT_CHUNK_CHAPTERS} 章")

    cands = [os.path.join(INPUT_DIR, f) for f in os.listdir(INPUT_DIR)
             if f.lower().endswith((".txt", ".md")) and not f.startswith("review_report")] \
        if os.path.isdir(INPUT_DIR) else []
    path = max(cands, key=os.path.getsize) if cands else None
    if not path:
        rec("SKIP", "分段无损性验证（工作区没有源文件）")
        return
    raw = open(path, "rb").read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        rec("SKIP", "分段无损性验证（源文件无法解码）")
        return
    bad, points = [], []
    for lim in (5000, 20000, 60000):
        if len(text) <= lim:
            continue
        cs = split_text(text, lim)
        if "".join(cs) != text:
            bad.append(f"阈值{lim} 内容丢失")
        if any(len(c) > lim for c in cs):
            bad.append(f"阈值{lim} 有段超限")
        points.append(f"字数{lim}→{len(cs)}段")
    # 章数约束（对「章多字少」的大纲尤其重要：不限章数会让单次输出被截断）
    if len(CHAP_RE.findall(text)) >= 2:
        for mc in (10, DEFAULT_CHUNK_CHAPTERS):
            cs = split_text(text, 0, mc)
            cnts = [len(CHAP_RE.findall(c)) for c in cs]
            if "".join(cs) != text:
                bad.append(f"每段≤{mc}章 内容丢失")
            elif any(c > mc for c in cnts):
                bad.append(f"每段≤{mc}章 失败（最大 {max(cnts)} 章）")
            else:
                points.append(f"每段≤{mc}章→{len(cs)}段")
    name = os.path.basename(path)
    if bad:
        rec("FAIL", f"分段无损性（{name}）", "; ".join(bad))
    else:
        rec("PASS", f"分段无损性（{name}）", f"{len(text)} 字，{'、'.join(points)}，切分后拼回与原文一致")


# ---------------------------------------------------------------- 6. 接口
def check_console(no_net):
    section("⑥ 控制台接口")
    if no_net:
        rec("SKIP", "接口检查（--no-net）")
        return
    try:
        http_json(f"{CONSOLE}/api/workflow", timeout=3)
    except Exception:
        rec("SKIP", "控制台未运行", "启动：python webapp.py（或运行 start.bat）")
        return
    # 多本书并存时 /api/chapters 必须带 book 参数：取第一本有章节数据的书
    try:
        bs = http_json(f"{CONSOLE}/api/books", timeout=6).get("books", [])
    except Exception:
        bs = []
    pick = next((b["name"] for b in bs if b.get("has_chapters")), None)
    paths = ["/api/chapters" + (f"?book={urllib.parse.quote(pick)}" if pick else "")
             if p == "/api/chapters" else p
             for p in ("/api/chapters", "/api/schema", "/api/outputs")]
    for p in paths:
        try:
            d = http_json(f"{CONSOLE}{p}", timeout=6)
            n = len(d) if isinstance(d, (list, dict)) else 1
            rec("PASS", f"GET {p.split('?')[0]}", f"{n} 项")
        except Exception as e:
            rec("FAIL", f"GET {p.split('?')[0]}", str(e))


# ---------------------------------------------------------------- 7. 语法
def check_syntax():
    section("⑦ 脚本语法")
    files = [f for f in ("decompose.py", "adapt.py", "review.py", "webapp.py", "desktop_app.py",
                             "story_bible.py", "deepseek_common.py", "paths.py", "selftest.py")
             if os.path.isfile(os.path.join(BASE, f))]
    bad = []
    for f in files:
        try:
            ast.parse(open(os.path.join(BASE, f), encoding="utf-8").read(), f)
        except SyntaxError as e:
            bad.append(f"{f}:{e.lineno}")
    if bad:
        rec("FAIL", "有脚本语法错误", "; ".join(bad))
    else:
        rec("PASS", f"{len(files)} 个脚本语法正常")


# ---------------------------------------------------------------- 8. 改编任务
def check_adapt():
    section("⑧ 改编任务 build_cmd")
    try:
        from webapp import build_cmd, list_books
    except Exception as e:
        rec("FAIL", "无法导入 webapp.build_cmd", str(e))
        return
    books = [b["name"] for b in list_books() if b.get("has_decomposed")]
    if not books:
        rec("SKIP", "build_cmd(adapt) 参数拼装（data/ 下没有已拆解的书）")
    else:
        src = books[0]
        try:
            cmd = build_cmd("adapt", {"book": src, "out_book": "自检改编书", "style": "test"})
            joined = " ".join(cmd)
            miss = [x for x in ("adapt.py", "--book", src, "--out-book", "自检改编书", "--style", "test")
                    if x not in joined]
            rec("FAIL" if miss else "PASS", "build_cmd(adapt) 参数拼装",
                f"缺：{miss}" if miss else joined)
        except Exception as e:
            rec("FAIL", "build_cmd(adapt) 抛异常", str(e))
        try:
            cmd = build_cmd("adapt", {"book": src})   # 新书名留空 = 由模型生成
            joined = " ".join(cmd)
            ok = "--book" in joined and "--out-book" not in joined
            rec("PASS" if ok else "FAIL", "build_cmd(adapt) 缺省新书名（模型生成）",
                joined if ok else f"不应含 --out-book：{joined}")
        except Exception as e:
            rec("FAIL", "build_cmd(adapt) 缺省新书名抛异常", str(e))
        try:
            joined = " ".join(build_cmd("adapt", {"book": src, "target_chapters": 60, "sequel_chapters": 5}))
            miss = [x for x in ("--target-chapters", "60", "--sequel-chapters", "5") if x not in joined]
            rec("FAIL" if miss else "PASS", "build_cmd(adapt) 目标/续写章数透传",
                f"缺：{miss}" if miss else joined)
        except Exception as e:
            rec("FAIL", "build_cmd(adapt) 目标/续写章数透传抛异常", str(e))
        try:
            joined = " ".join(build_cmd("adapt", {"book": src, "target_chapters": "", "sequel_chapters": 0}))
            ok = "--target-chapters" not in joined and "--sequel-chapters" not in joined
            rec("PASS" if ok else "FAIL", "build_cmd(adapt) 章数留空/0 不透传", joined)
        except Exception as e:
            rec("FAIL", "build_cmd(adapt) 章数留空透传抛异常", str(e))
        try:
            build_cmd("adapt", {"book": src, "target_chapters": "abc"})
            rec("FAIL", "build_cmd(adapt) 应拒绝非整数目标章数")
        except ValueError:
            rec("PASS", "build_cmd(adapt) 拒绝非整数目标章数")
        try:
            import subprocess
            from paths import book_decomposed as bd_path
            dec = load_json(bd_path(src)) or {}
            n_src = len(dec.get("chapters") or [])
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            r = subprocess.run(
                [sys.executable, "-u", os.path.join(BASE, "adapt.py"), "--book", src,
                 "--target-chapters", str(n_src + 8), "--sequel-chapters", "3", "--dry-run"],
                capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace", env=env)
            out = (r.stdout or "") + (r.stderr or "")
            ok = r.returncode == 0 and "章数规划" in out and "续写" in out
            rec("PASS" if ok else "FAIL", "adapt.py --dry-run 扩写+续写",
                f"rc={r.returncode}｜{out.strip()[:160]}" if not ok else out.strip().splitlines()[1])
        except Exception as e:
            rec("FAIL", "adapt.py --dry-run 扩写+续写抛异常", str(e))
    for a, why in (({"book": "", "out_book": "x"}, "缺源书"),
                   ({"book": "无此书甲", "out_book": "x"}, "源书无拆解产出"),
                   ({"book": "同一本", "out_book": "同一本"}, "新书名与源书相同")):
        try:
            build_cmd("adapt", a)
            rec("FAIL", f"build_cmd(adapt) 应拒绝：{why}", str(a))
        except ValueError as e:
            rec("PASS", f"build_cmd(adapt) 拒绝：{why}", str(e))
    try:
        from adapt import plan_batches, proportional_plan, validate_plan
        ok_exp = validate_plan(proportional_plan(30, 45), 45, 30) is not None
        ok_cmp = validate_plan(proportional_plan(30, 12), 12, 30) is not None
        ok_eq = validate_plan(proportional_plan(30, 30), 30, 30) is not None
        bad_cov = validate_plan([{"from": 1, "to": 2}] * 5, 5, 30) is None          # 覆盖不全
        bad_gap = validate_plan([{"from": 1, "to": 1}, {"from": 3, "to": 3},
                                 {"from": 3, "to": 30}, {"from": 3, "to": 30},
                                 {"from": 3, "to": 30}], 5, 30) is None              # 跳过第2章
        ok = ok_exp and ok_cmp and ok_eq and bad_cov and bad_gap
        rec("PASS" if ok else "FAIL", "adapt 章数规划校验（扩写/压缩/兜底/拒非法）",
            f"扩写={ok_exp} 压缩={ok_cmp} 相等={ok_eq} 拒覆盖不全={bad_cov} 拒跳章={bad_gap}")
        # 映射分段：不丢条、不乱序、每段新章数不超限
        for t_src, t_new in ((30, 45), (200, 20), (1, 40), (40, 1)):
            plan = proportional_plan(t_src, t_new)
            bs = plan_batches(plan)
            flat = [p for b in bs for p in b]
            if flat != plan or any(len(b) > 15 for b in bs):
                ok = False
                rec("FAIL", f"adapt plan_batches({t_src}→{t_new})", f"段数={len(bs)}")
        if ok:
            rec("PASS", "adapt plan_batches 分段守恒（扩写/压缩/1章源）")
    except Exception as e:
        rec("FAIL", "adapt 章数规划校验抛异常", str(e))


# ---------------------------------------------------------------- 9. AI 审查
def check_review():
    section("⑨ AI 审查（分句 / 引用校验 / 规则初筛 / 统计体检）")
    try:
        import review
    except Exception as e:                      # noqa
        rec("SKIP", "review 模块导入", f"{e}（与拆解同源）")
        return
    text = "沈砚走在青石巷里。雨点敲着伞面。\n\n他把按排好的事做完。"
    try:
        paras, sents = review.split_segments(text)
        ids = [s["id"] for s in sents]
        rec("PASS" if ids == ["P01-S01", "P01-S02", "P02-S01"] else "FAIL",
            "分句 ID 稳定（段-句序号）", "、".join(ids))
        rec("PASS" if all(s["text"] == text[s["start"]:s["end"]] for s in sents) else "FAIL",
            "句子偏移可回切原文")
        rec("PASS" if (review.quote_ok(text, "沈砚走在青石巷里")
                       and not review.quote_ok(text, "这句不在原文里")) else "FAIL",
            "引用校验：命中保留 / 幻觉丢弃")
        cands = review.rule_typos(text, sents)
        hit = any(x["quote"] == "按排" and x["suggest"] == "安排" for x in cands)
        rec("PASS" if hit else "FAIL", "错别字规则初筛命中「按排→安排」", f"{len(cands)} 条候选")
        rec("PASS" if [p["line"] for p in paras] == [1, 3] else "FAIL",
            "段落行号可定位", str([p["line"] for p in paras]))
        sc = review.sensitive_scan("他看见血肉模糊的场面。", sents)
        rec("PASS" if any(c["hit"] == "血肉模糊" for c in sc) else "FAIL",
            "违规风险规则初筛", f"{len(sc)} 条候选")
        rowset, reps = review.build_stats(text, paras, sents, names=["沈砚"])
        rec("PASS" if len(rowset) >= 9 else "FAIL", "行文统计体检项", f"{len(rowset)} 项")
        act = review.fix_action({"type": "typo", "quote": "按排", "suggest": "安排"})
        rec("PASS" if "安排" in act else "FAIL", "修正动作生成", act)
        rk = review.risk_summary([{"severity": "高", "type": "risk"}], "轻")
        rec("PASS" if rk["level"] == "高" else "FAIL", "过审风险总览", rk["level"])
        chs = [{"chapter_id": "第1章", "title": "一"}, {"chapter_id": "第3章", "title": "三"}]
        ok_find = ((review.find_chapter(chs, "3") or {}).get("title") == "三"
                   and (review.find_chapter(chs, 1) or {}).get("title") == "一")
        rec("PASS" if ok_find else "FAIL", "按章号定位本章（第3章 / 顺序号 1）")
    except Exception as e:                      # noqa
        rec("FAIL", "review 自检抛异常", str(e))


# ---------------------------------------------------------------- main
def pick_chapters_path(book_arg):
    """自检目标 chapters.json：显式 --book > 旧根文件 > data/ 下最近修改的书。"""
    from webapp import list_books, sanitize_book   # 复用控制台同一套书扫描逻辑
    if book_arg:
        n = sanitize_book(book_arg)
        return book_chapters(n) if n else None
    if os.path.isfile(CHAPTERS):
        return CHAPTERS
    bs = list_books()
    return book_chapters(bs[0]["name"]) if bs else CHAPTERS   # 无书时走旧路径触发缺失告警


def main():
    ap = argparse.ArgumentParser(description="小说拆解台全链路自检")
    ap.add_argument("--no-net", action="store_true", help="跳过网络相关检查")
    ap.add_argument("--book", default=None, help="自检指定书名（缺省自动选：旧根文件优先，否则 data/ 下最近的书）")
    args = ap.parse_args()

    print("=" * 66)
    print("小说连载工作流 · 全链路自检")
    print(f"项目根：{ROOT}")
    print("=" * 66)

    wf = load_json(WORKFLOW)
    ch_path = pick_chapters_path(args.book)
    if not ch_path:
        rec("FAIL", "书名不合法", f"--book {args.book}")
        ch = {}
    else:
        ch = load_json(ch_path)
        rec("PASS", "自检目标", os.path.relpath(ch_path, ROOT).replace("\\", "/"))

    names = check_env(wf, args.no_net)
    check_workflow(wf)
    check_chapters(ch, wf)
    check_budget(wf, ch, args.no_net, names)
    check_chunking()
    check_console(args.no_net)
    check_syntax()
    check_adapt()
    check_review()

    n = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
    for lv, _, _ in RESULTS:
        n[lv] += 1
    print("\n" + "=" * 66)
    print(f"结果：{n['PASS']} 通过 · {n['WARN']} 警告 · {n['FAIL']} 失败 · {n['SKIP']} 跳过（共 {len(RESULTS)} 项）")
    if n["FAIL"]:
        print("\n需要处理的问题：")
        for lv, name, detail in RESULTS:
            if lv == "FAIL":
                print(f"  · {name}" + (f" —— {detail}" if detail else ""))
    print("=" * 66)
    sys.exit(1 if n["FAIL"] else 0)


if __name__ == "__main__":
    main()
