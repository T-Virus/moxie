# -*- coding: utf-8 -*-
"""
DeepSeek 在线调用公用工具（OpenAI 兼容协议，纯标准库实现）
==========================================================
不依赖 openai SDK：手机端（Chaquopy）里第三方包的可用性不可控，
这里直接用 urllib 调 /chat/completions，非流式与流式两条路径都支持。

安全约定：API Key 只从环境变量 DEEPSEEK_API_KEY 或命令行 --api-key 读取，
不写死、不落盘。
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"


def _record_usage(usage_obj, model, prompt_text, completion_text, elapsed):
    """把这次调用记进用量统计（tokens / 耗时 / 阶段）。统计失败绝不影响主流程。"""
    try:
        import usage
        stage = getattr(usage._CTX, "stage", "") or os.environ.get("MOBIT_STAGE", "")
        usage.record(model, prompt_text, completion_text, elapsed=elapsed,
                     usage=usage_obj, stage=stage)
    except Exception:  # noqa
        pass


class JsonParseError(ValueError):
    """模型输出不是合法 JSON。原始文本挂在 .raw 上，便于落盘排查。"""

    def __init__(self, raw, cause):
        super().__init__(f"模型输出不是合法 JSON：{cause}")
        self.raw = raw


class OutputTruncated(JsonParseError):
    """模型输出写到了长度上限（finish_reason=length），JSON 因此没写完。

    和「模型写坏了 JSON」不是一回事：原样重试只会得到同样被截断的结果，
    调用方应当把输入再切小（或要求模型少输出），而不是重试。
    """

    def __init__(self, raw, cause="输出达到长度上限被截断"):
        super().__init__(raw, cause)
        self.raw = raw


def resolve_base_url(cli=None):
    return cli or os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)


def key_or_empty(cli=None):
    """取 Key，没有就返回空串——供任务判断能否走「本地模式」，不退出、不报错。"""
    return (cli or os.environ.get("DEEPSEEK_API_KEY", "")).strip()


def strip_code_fence(s):
    s = s.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, flags=re.DOTALL)
    return m.group(1) if m else s


# ---------------------------------------------------------------- 轻量响应对象
class _Msg:
    def __init__(self, content=None, reasoning_content=None):
        self.content = content
        self.reasoning_content = reasoning_content


class _Delta:
    def __init__(self, content=None, reasoning_content=None):
        self.content = content
        self.reasoning_content = reasoning_content


class _Choice:
    def __init__(self, message=None, delta=None, finish_reason=None):
        self.message = message
        self.delta = delta
        self.finish_reason = finish_reason


class _Usage:
    def __init__(self, prompt_tokens=0, completion_tokens=0):
        self.prompt_tokens = int(prompt_tokens or 0)
        self.completion_tokens = int(completion_tokens or 0)


class _Resp:
    def __init__(self, choices, usage=None):
        self.choices = choices
        self.usage = usage


class _StreamEvent:
    def __init__(self, choice):
        self.choices = [choice] if choice else []


def _chat_url(base_url):
    return (base_url or DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"


def _ssl_context():
    """显式加载 CA：Android 上没有 /etc/ssl/certs，必须用随包的 cacert.pem。"""
    try:
        import ssl
        cafile = os.environ.get("SSL_CERT_FILE", "")
        if cafile and os.path.isfile(cafile):
            return ssl.create_default_context(cafile=cafile)
        return ssl.create_default_context()
    except Exception:
        return None


def _open(url, api_key, payload, timeout):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    kwargs = {}
    if url.lower().startswith("https"):
        ctx = _ssl_context()
        if ctx is not None:
            kwargs["context"] = ctx
    try:
        return urllib.request.urlopen(req, timeout=timeout, **kwargs)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:1200]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code}: {detail or e.reason}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"连接失败：{getattr(e, 'reason', e)}") from None


def _parse_resp(obj):
    choices = []
    for c in obj.get("choices") or []:
        m = c.get("message") or {}
        choices.append(_Choice(_Msg(m.get("content"), m.get("reasoning_content")),
                               finish_reason=c.get("finish_reason")))
    u = obj.get("usage") or {}
    usage = _Usage(u.get("prompt_tokens"), u.get("completion_tokens")) if u else None
    return _Resp(choices, usage)


def _stream_events(url, api_key, payload, timeout):
    """SSE 逐行解析；返回可迭代对象（与 openai SDK 的 stream 用法一致）。"""
    resp = _open(url, api_key, payload, timeout)
    try:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                data = line[5:].strip()
            else:
                continue
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            c = choices[0]
            d = c.get("delta") or {}
            yield _StreamEvent(_Choice(delta=_Delta(d.get("content"), d.get("reasoning_content")),
                                       finish_reason=c.get("finish_reason")))
    finally:
        try:
            resp.close()
        except Exception:
            pass


class _Completions:
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url

    def create(self, **kw):
        timeout = kw.pop("timeout", 600)
        stream = bool(kw.pop("stream", False))
        payload = {k: v for k, v in kw.items() if v is not None}
        url = _chat_url(self.base_url)
        if stream:
            payload["stream"] = True
            return _stream_events(url, self.api_key, payload, timeout)
        resp = _open(url, self.api_key, payload, timeout)
        try:
            text = resp.read().decode("utf-8", "replace")
        finally:
            try:
                resp.close()
            except Exception:
                pass
        try:
            obj = json.loads(text)
        except ValueError:
            raise RuntimeError(f"服务端返回的不是 JSON：{text[:400]}")
        if isinstance(obj, dict) and obj.get("error"):
            err = obj["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise RuntimeError(f"接口返回错误：{msg}")
        return _parse_resp(obj)


class _Chat:
    def __init__(self, api_key, base_url):
        self.completions = _Completions(api_key, base_url)


class OpenAI:
    """最小可用的 OpenAI 兼容客户端（只实现 chat.completions.create）。"""

    def __init__(self, api_key=None, base_url=None, **kwargs):
        self.chat = _Chat(api_key, resolve_base_url(base_url))


def empty_content_reason(resp, choice, model, max_tokens):
    """模型返回空正文时，拼一句能直接定位问题的说明。

    空 content 有几种完全不同的成因（模型名不对 / 推理模型吃光预算 / 不支持
    response_format / 被安全策略拦截），只报「返回了空内容」用户无从下手。
    """
    if choice is None:
        return (f"模型返回了空内容（model={model}）：响应里没有 choices，"
                "请确认模型名是否可用、端点是否需要 /v1")
    finish = str(getattr(choice, "finish_reason", "") or "")
    msg = getattr(choice, "message", None)
    reasoning = getattr(msg, "reasoning_content", None) if msg else None
    usg = getattr(resp, "usage", None)
    ct = getattr(usg, "completion_tokens", None) if usg else None
    bits = [f"model={model}", f"finish_reason={finish or '未知'}"]
    if ct is not None:
        bits.append(f"completion_tokens={ct}")
    s = "模型返回了空内容（" + ", ".join(bits) + "）"
    if reasoning:
        s += (f"：输出预算被推理过程占满（reasoning_content {len(str(reasoning))} 字），"
              "content 为空；请改用非推理模型")
    elif finish == "length":
        s += f"：还没写出正文就触到 max_tokens={max_tokens}，请调大上限或换模型"
    elif finish == "content_filter":
        s += "：内容被安全策略拦截"
    elif finish == "stop":
        s += ("：模型正常结束但没产出文本，多半是该模型不支持 "
              "response_format=json_object，或模型名在此端点不可用")
    return s


DEFAULT_MAX_TOKENS = 8192        # 单次输出上限；显式给出，避免服务端默认更小把长 JSON 写断
# 推理型模型（如 deepseek-v4-flash）会先把输出预算花在思维链上。进程内记住
# 「这个模型实测要多少 token」，后续分段直接按该预算起步，避免每段都先用 8192
# 失败一次再重试——那样每段都要多烧一遍推理，成本和耗时都是数倍。
_MODEL_BUDGET = {}


def _remember_budget(model, tokens):
    if tokens > _MODEL_BUDGET.get(model, 0):
        _MODEL_BUDGET[model] = tokens


def chat_json(api_key, base_url, model, system, prompt, timeout=600, retries=1,
              temperature=0.2, max_tokens=DEFAULT_MAX_TOKENS):
    """调用 DeepSeek 并返回解析后的 dict。

    结构化抽取（拆解/图谱/审查）默认 temperature=0.2：
    低温能显著减少「同一份材料两次拆出不同章号 / 不同字段名」的抖动。
    模型偶发会返回非法 JSON（例如字符串里出现未转义的英文引号），
    这种情况重试一次通常就正常，因此默认 retries=1。
    输出被长度上限写断（finish_reason=length）时抛 OutputTruncated 且**不重试**：
    同样的输入再问一次只会同样被截断，要把输入切小才有意义。
    全部失败时抛最后一个异常，原始文本（若是 JSON 解析失败）挂在 .raw 上。
    """
    # 没显式给 base_url 时回落到 DeepSeek（环境变量 DEEPSEEK_BASE_URL 或内置默认），
    # 否则请求会打到 api.openai.com，国内网络下直接超时。
    base_url = resolve_base_url(base_url)
    last = None
    capped = False      # 老端点/小模型不认 8k 输出上限时，退到 4096 再试一次
    json_mode = True    # 端点不支持 response_format 时会回空内容，第二次去掉该参数重试
    base_max = max_tokens       # 扩容重试失败时回落到用户原本给的上限
    max_tokens = max(int(max_tokens or 0), _MODEL_BUDGET.get(model, 0)) or DEFAULT_MAX_TOKENS
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            kwargs = dict(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
        except Exception as e:  # 超时 / 连接错误等：重试而不是立刻放弃（原实现会直接冒泡）
            last = e
            msg = str(e)
            if not capped and max_tokens > 4096 and ("max_tokens" in msg or "maximum" in msg.lower()):
                # 扩容后的上限被拒时退回原值，别把本来就是 8192 的调用降到 4096
                prev = max_tokens
                capped, max_tokens = True, (base_max if prev > base_max else 4096)
                print(f"    [!] 该模型/端点不接受 max_tokens={prev}，"
                      f"改用 {max_tokens} 重试：{msg[:120]}", file=sys.stderr)
                continue
            if json_mode and ("response_format" in msg or "json_object" in msg):
                # 端点不支持 JSON 模式：去掉该参数再试
                json_mode = False
                print("    [!] 端点不支持 response_format=json_object：去掉该参数重试",
                      file=sys.stderr)
                continue
            if attempt < retries:
                print(f"    [重试 {attempt + 1}/{retries}] 模型请求失败（{type(e).__name__}）：{e}",
                      file=sys.stderr)
            continue
        choices = getattr(resp, "choices", None) or []
        choice = choices[0] if choices else None
        content = choice.message.content if choice else None
        raw = strip_code_fence(content or "")
        if not raw:
            last = ValueError(empty_content_reason(resp, choice, model, max_tokens))
            finish = str(getattr(choice, "finish_reason", "") or "") if choice else ""
            msg_obj = getattr(choice, "message", None) if choice else None
            has_reasoning = bool(getattr(msg_obj, "reasoning_content", None)) if msg_obj else False
            # 推理型模型先把预算花在思维链上：content 为空且（有 reasoning 或触到 length）时，
            # 一次跳到 32768 再试（翻倍要多烧一轮推理，成本翻倍），并记住该模型的预算。
            if (has_reasoning or finish == "length") and not capped and max_tokens < 32768 \
                    and attempt < retries:
                max_tokens = 32768
                _remember_budget(model, max_tokens)
                print(f"    [!] 输出被推理过程占满，max_tokens 提到 {max_tokens} 重试"
                      f"（该模型为推理型，结构化任务建议改用非推理模型）", file=sys.stderr)
                continue
            # 「正常结束却没有文本」通常是对面不认 response_format=json_object：
            # 去掉该参数、靠提示词约束 JSON，再试一次（提示词里本来就写了只输出 JSON）
            if json_mode and finish == "stop" and attempt < retries:
                json_mode = False
                print("    [!] 端点未返回内容，可能不支持 response_format=json_object："
                      "去掉该参数重试", file=sys.stderr)
            continue
        _record_usage(getattr(resp, "usage", None), model, system + "\n" + prompt, raw,
                      time.time() - t0)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            if str(getattr(choice, "finish_reason", "") or "") == "length":
                # JSON 被截断也是「输出预算不够」：先扩容重试，别急着让调用方切小输入——
                # 一旦退化成反复二分，段数会指数增长，任务永远跑不完。
                if not capped and max_tokens < 32768 and attempt < retries:
                    max_tokens = 32768
                    _remember_budget(model, max_tokens)
                    print(f"    [!] JSON 被 max_tokens 截断，提到 {max_tokens} 重试"
                          f"（该模型为推理型，结构化任务建议改用非推理模型）", file=sys.stderr)
                    continue
                raise OutputTruncated(raw, f"输出超过 max_tokens={max_tokens} 被截断，"
                                           f"JSON 未写完（{e}）")
            last = JsonParseError(raw, e)
    raise last if last is not None else RuntimeError("模型调用失败：未获得有效返回")


def chat_text(api_key, base_url, model, system, prompt, timeout=600, retries=1, temperature=0.7):
    """调用 DeepSeek 并返回纯文本（用于正文扩写等不需要 JSON 的场景）。

    与 chat_json 的区别：不要求模型返回 JSON、不使用 response_format，
    也不做 JSON 解析——直接把模型正文原文返回。
    同样在 base_url 为空时回落 DeepSeek，并让超时/连接错误也能重试，
    否则正文生成会把请求打到 api.openai.com 后直接失败。
    """
    base_url = resolve_base_url(base_url)
    last = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                timeout=timeout,
            )
        except Exception as e:  # noqa: 超时 / 连接错误 → 重试
            last = e
            if attempt < retries:
                print(f"    [重试 {attempt + 1}/{retries}] 正文请求失败（{type(e).__name__}）：{e}",
                      file=sys.stderr)
            continue
        text = (resp.choices[0].message.content or "").strip()
        if text:
            _record_usage(getattr(resp, "usage", None), model, system + "\n" + prompt, text,
                          time.time() - t0)
            return text
        last = ValueError("模型返回了空文本")
    raise last if last is not None else RuntimeError("模型调用失败：未获得有效返回")


def chat_text_stream(api_key, base_url, model, system, prompt,
                     timeout=600, temperature=0.7, on_delta=None, retries=1):
    """流式版 chat_text：模型每产出一段增量就回调 on_delta(delta)，
    结束后返回完整文本。on_delta 里抛异常会中断流（用于用户点「停止」）。

    建立连接失败（未产出任何内容）时重试；已经开始吐字后不再重试，
    避免同一章正文被拼接两遍。
    """
    base_url = resolve_base_url(base_url)
    parts = []
    attempt = 0
    t0 = time.time()
    while True:
        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                timeout=timeout,
                stream=True,
            )
            for ev in resp:
                if not getattr(ev, "choices", None):
                    continue
                d = ev.choices[0].delta
                piece = getattr(d, "content", None)
                if piece:
                    parts.append(piece)
                    if on_delta:
                        on_delta(piece)
            full = "".join(parts).strip()
            # 流式响应多数端点不回 usage：record 内部会按字符估算并标注 estimated
            _record_usage(None, model, system + "\n" + prompt, full, time.time() - t0)
            return full
        except Exception as e:  # noqa: 连接阶段失败可重试；已吐字后直接抛
            if parts or attempt >= retries:
                raise
            attempt += 1
            print(f"    [重试 {attempt}/{retries}] 正文流式请求失败（{type(e).__name__}）：{e}",
                  file=sys.stderr)
