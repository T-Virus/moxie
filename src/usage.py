# -*- coding: utf-8 -*-
"""
Token 用量与成本统计
====================
每次模型调用（不管跑在控制台进程还是拆解/扩写子进程里）都往
data/_system/usage.jsonl 追加一行：

  {ts, stage, book, chapter_no, model, prompt_tokens, completion_tokens, elapsed}

- tokens 优先取 API 返回的 usage；端点不回 usage 时按字符数估算（约 1.7 字 / token），
  并标注 estimated=true，统计页据此提示「估算值」。
- 追加写 + 单行 JSON：进程崩溃最多丢最后一行；多进程同时写各开各的句柄，
  Windows 下不做跨进程锁（最坏情况是个别行交错，读取端跳过坏行即可，不炸统计）。
- 费用 = tokens × config/studio.json 里的单价（prices.in / prices.out，元/百万）。
"""

import json
import os
import threading
import time

from paths import DATA_DIR

_LOCK = threading.RLock()
SYS_DIR = os.path.join(DATA_DIR, "_system")
USAGE_FILE = os.path.join(SYS_DIR, "usage.jsonl")

# 上下文由「发起调用的那一层」在调用前写入（线程本地），记录时带出
_CTX = threading.local()


def set_context(stage="", book="", chapter_no=""):
    _CTX.stage = stage or ""
    _CTX.book = book or ""
    _CTX.chapter_no = str(chapter_no or "")


def _estimate_tokens(text):
    """没有 usage 时的估算：中文约 1.5 字 / token，英文约 4 字符 / token。
    按字符类别分别折算，比「总字数 ÷ 1.7」更贴近实际（中英混排时误差小很多）。"""
    if not text:
        return 0
    s = str(text)
    cjk = 0
    for ch in s:
        if "\u3400" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff":
            cjk += 1
    other = len(s) - cjk
    return max(1, int(cjk / 1.5 + other / 4))


def record(model, prompt_text, completion_text, elapsed=0.0, usage=None, stage=None):
    """记录一次调用。usage 为 API 返回的 usage 对象/dict（可为 None）。

    会按模型名反查「模型档案」：命中就把 profile 名字与当时的单价快照进记录行——
    之后改单价不回溯旧账，每个模型的成本各算各的。"""
    try:
        pt = ct = 0
        est_p = est_c = True
        if usage:
            gt = (lambda k: int(getattr(usage, k, 0) or (usage.get(k, 0) if isinstance(usage, dict) else 0) or 0))
            pt, ct = gt("prompt_tokens"), gt("completion_tokens")
            # 端点可能只回一侧 token：缺的那一侧单独估算，不能因为另一侧有值就把 0 记进去
            est_p, est_c = not pt, not ct
        if est_p:
            pt = _estimate_tokens(prompt_text)
        if est_c:
            ct = _estimate_tokens(completion_text)
        estimated = est_p or est_c
        pid, prof, pin, pout = None, None, None, None
        try:
            import studio
            pid, prof = studio.find_profile_by_model(model)
            if prof:
                pin = float(prof.get("price_in") or 0) or None
                pout = float(prof.get("price_out") or 0) or None
        except Exception:  # noqa
            pass
        row = {
            "ts": round(time.time(), 3),
            "date": time.strftime("%Y-%m-%d"),
            "stage": stage if stage is not None else (getattr(_CTX, "stage", "") or ""),
            "book": getattr(_CTX, "book", "") or "",
            "chapter_no": str(getattr(_CTX, "chapter_no", "") or ""),
            "model": model or "",
            "profile": (prof.get("name") if prof else "") or "",
            "price_in": pin, "price_out": pout,
            "prompt_tokens": pt, "completion_tokens": ct,
            "elapsed": round(float(elapsed or 0), 2),
            "estimated": estimated,
        }
        line = json.dumps(row, ensure_ascii=False)
        with _LOCK:
            os.makedirs(SYS_DIR, exist_ok=True)
            with open(USAGE_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:  # noqa —— 统计是附加能力，绝不能反过来把主流程搞挂
        pass


def iter_rows():
    """逐行读出全部用量记录（坏行跳过）。"""
    try:
        with open(USAGE_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


def summary(prices=None, days=30):
    """聚合：总量 + 按工序 / 按模型 / 按档案（服务商）/ 按书 / 近 N 天曲线 + 费用折算。

    每行记录自带单价快照（记录时从模型档案带出）：成本按行计算，
    档案没填单价的行用全局兜底单价（studio.prices）。"""
    pin = pout = 0.0
    if isinstance(prices, dict):
        try:
            pin, pout = float(prices.get("in") or 0), float(prices.get("out") or 0)
        except (TypeError, ValueError):
            pin = pout = 0.0
    total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
             "elapsed": 0.0, "estimated": 0}
    by_stage, by_model, by_book, by_day, by_profile = {}, {}, {}, {}, {}
    cost_all = 0.0
    cutoff = time.time() - days * 86400
    for r in iter_rows():
        # 与图表保持一致：所有汇总都只看所选时间窗，否则「近 7 天」下卡片还是全量，数字对不上
        ts = float(r.get("ts") or 0)
        if ts and ts < cutoff:
            continue
        total["calls"] += 1
        pt, ct = int(r.get("prompt_tokens") or 0), int(r.get("completion_tokens") or 0)
        el = float(r.get("elapsed") or 0)
        total["prompt_tokens"] += pt
        total["completion_tokens"] += ct
        total["elapsed"] += el
        if r.get("estimated"):
            total["estimated"] += 1
        # 这一行的成本：优先行内单价快照，其次全局兜底
        rin = r.get("price_in") if r.get("price_in") is not None else pin
        rout = r.get("price_out") if r.get("price_out") is not None else pout
        try:
            cost = pt * float(rin or 0) / 1e6 + ct * float(rout or 0) / 1e6
        except (TypeError, ValueError):
            cost = 0.0
        cost_all += cost

        def _acc(tbl, key):
            d = tbl.setdefault(key or "（未标注）", {"calls": 0, "prompt_tokens": 0,
                                                    "completion_tokens": 0, "elapsed": 0.0,
                                                    "cost": 0.0})
            d["calls"] += 1
            d["prompt_tokens"] += pt
            d["completion_tokens"] += ct
            d["elapsed"] += el
            d["cost"] += cost
        _acc(by_stage, r.get("stage"))
        _acc(by_model, r.get("model"))
        _acc(by_profile, r.get("profile") or r.get("model") or "（未知档案）")
        if r.get("book"):
            _acc(by_book, r.get("book"))
        _acc(by_day, r.get("date") or time.strftime("%Y-%m-%d", time.localtime(ts or time.time())))
    for tbl in (by_stage, by_model, by_book, by_day, by_profile):
        for d in tbl.values():
            d["elapsed"] = round(d["elapsed"], 1)
            d["cost"] = round(d["cost"], 4)
    total["elapsed"] = round(total["elapsed"], 1)
    return {
        "total": total,
        "cost": {"all": round(cost_all, 4), "currency": "CNY",
                 "prices": {"in": pin, "out": pout}},
        "by_stage": by_stage, "by_model": by_model, "by_profile": by_profile,
        "by_book": by_book,
        "by_day": dict(sorted(by_day.items())),
        "days": days,
    }


def clear():
    """清空统计：调用记录 + 码字统计一起清（页面上两块都属于「统计」）。
    返回各文件是否真的删掉了，前端据此提示「已清空」而不是静默失败。"""
    writing_file = os.path.join(DATA_DIR, "_system", "writing.json")
    removed = {"usage": False, "writing": False}
    with _LOCK:
        for key, path in (("usage", USAGE_FILE), ("writing", writing_file)):
            try:
                os.remove(path)
                removed[key] = True
            except FileNotFoundError:
                removed[key] = True      # 本来就没有，也算清空成功
            except OSError:
                pass
    return removed
