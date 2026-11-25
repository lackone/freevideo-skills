#!/usr/bin/env python3
"""Generate an image on the local FreeVideo engine and return the local file path.

Defaults: 16:9, standard tier (4 MP), minimax-h3-image.
Only the final local file path is printed to stdout on success; progress goes to stderr.
Failures are reported as one short Chinese sentence on stderr with exit code 1.

Settings come from command-line flags, otherwise defaults. Token and service
address are auto-discovered when unset.
  --origin      service address, default http://127.0.0.1:8188
  --token-path  explicit override for the agent token file
  --output-dir  directory for the final image, default <cwd>/images
                (relative to the current working directory; prefer an absolute path)
"""
import argparse
import datetime
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def discover_origin(cli_origin=None):
    return (cli_origin or "http://127.0.0.1:8188").rstrip("/")


def _http_get(url, timeout=10):
    req = urllib.request.Request(url, method="GET")
    with OPENER.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def discover_service():
    """Agent discovery: GET /freevideo/agent, then the connect spec.

    Returns (api_base, token_path). The service advertises its API base and a
    connect URL whose plain-text spec names the local agent token file.
    """
    origin = ORIGIN
    meta = json.loads(_http_get(origin + "/freevideo/agent"))
    api_base = meta.get("base") or "/freevideo/agent/v1"
    connect_url = meta.get("connect") or (origin + "/freevideo/agent/v1/connect?lang=zh")
    token_path = None
    for line in _http_get(connect_url).splitlines():
        s = line.strip()
        if s.startswith("令牌文件") or s.lower().startswith("token file"):
            for sep in ("：", ":"):
                if sep in s:
                    token_path = s.split(sep, 1)[1].strip()
                    break
            break
    return api_base, pathlib.Path(token_path) if token_path else None


ORIGIN = "http://127.0.0.1:8188"
BASE = ORIGIN + "/freevideo/agent/v1"


def default_output():
    """Default output dir: <cwd>/images, so the caller's working dir decides where it lands."""
    return pathlib.Path.cwd() / "images"


RETRIES = 2
RETRY_WAIT = 0.8
TERMINAL_FAIL = {"failed", "cancelled", "canceled", "interrupted", "error"}
# FreeVideo /jobs API schema: kind="image" prompt is a string with minLength=1,
# maxLength=2000 (measured in Python len() characters). The full prompt sent to
# the API is the user's raw text + the enriched rewrite concatenated, so the
# combined result must stay at or under this limit.
MAX_PROMPT_CHARS = 2000


class FreeVideoError(RuntimeError):
    """User-facing error: printed as one short Chinese sentence."""


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def read_token(cli_token=None):
    global BASE
    token_path = pathlib.Path(cli_token) if cli_token else None
    if token_path is None:
        try:
            api_base, token_path = discover_service()
            if api_base.startswith(("http://", "https://")):
                BASE = api_base
            else:
                BASE = ORIGIN + api_base
        except Exception as e:
            log("服务发现失败：%s" % _brief(e))
            token_path = None
    if token_path is None or not token_path.is_file():
        raise FreeVideoError("未找到 FreeVideo 令牌文件，请确认引擎已启动，或用 --token-path 指定路径")
    try:
        tok = token_path.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise FreeVideoError("读取 FreeVideo 令牌失败：%s" % e)
    if not tok:
        raise FreeVideoError("FreeVideo 令牌为空，请重新启动 FreeVideo")
    return tok


def _brief(text, n=500):
    return str(text).replace("\n", " ")[:n]


def call(method, path, token, body=None, timeout=70):
    data = None if body is None else json.dumps(body).encode("utf-8")
    last = None
    for attempt in range(RETRIES + 1):
        req = urllib.request.Request(
            BASE + path,
            data=data,
            method=method,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            with OPENER.open(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            if e.code >= 500 and attempt < RETRIES:
                log("HTTP %d, retry %d/%d" % (e.code, attempt + 1, RETRIES))
                time.sleep(RETRY_WAIT)
                continue
            raise FreeVideoError("接口 HTTP %d：%s" % (e.code, _brief(detail)))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < RETRIES:
                log("网络错误, retry %d/%d" % (attempt + 1, RETRIES))
                time.sleep(RETRY_WAIT)
                continue
    raise FreeVideoError("无法连接 FreeVideo 服务（%s），请确认它已启动" % _brief(last))


def _media_url(url_path):
    if url_path.startswith(("http://", "https://")):
        return url_path
    return ORIGIN + url_path


def download(url_path, token, out_file):
    req = urllib.request.Request(
        _media_url(url_path), headers={"Authorization": "Bearer " + token}
    )
    data = None
    last = None
    for attempt in range(RETRIES + 1):
        try:
            with OPENER.open(req, timeout=180) as resp:
                data = resp.read()
            break
        except urllib.error.HTTPError as e:
            raise FreeVideoError("下载图片失败，HTTP %d：%s" % (e.code, _brief(e.read().decode("utf-8", "replace"))))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < RETRIES:
                log("下载重试 %d/%d" % (attempt + 1, RETRIES))
                time.sleep(RETRY_WAIT)
                continue
    if data is None:
        raise FreeVideoError("下载图片失败：%s" % _brief(last))
    if not data:
        raise FreeVideoError("下载到的图片为空")
    if not (
        data.startswith(b"\xff\xd8")
        or data.startswith(b"\x89PNG")
        or data.startswith(b"RIFF")
    ):
        raise FreeVideoError("下载结果不是有效图片，请重试")
    try:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(data)
    except OSError as e:
        raise FreeVideoError("保存图片失败：%s" % e)
    return len(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--aspect", default="16:9", choices=["1:1", "16:9", "9:16", "4:3", "3:4"])
    ap.add_argument("--tier", default="standard", choices=["standard", "high"])
    ap.add_argument("--model", default="minimax-h3-image", choices=["minimax-h3-image", "qwen-image-2.1-turbo"])
    ap.add_argument("--label", default="")
    ap.add_argument("--output-dir", default=str(default_output()), help="保存目录（默认 当前工作目录/images；调用方应传绝对路径）")
    ap.add_argument("--origin", default=None, help="FreeVideo 服务地址，默认 http://127.0.0.1:8188")
    ap.add_argument("--token-path", default=None, help="显式指定 agent token 文件路径（可选覆盖）")
    args = ap.parse_args()

    global ORIGIN, BASE
    ORIGIN = discover_origin(args.origin)
    BASE = ORIGIN + "/freevideo/agent/v1"

    # Enforce the API's hard prompt limit before making any request.
    n = len(args.prompt)
    if n < 1:
        raise FreeVideoError("提示词为空，接口要求至少 1 个字符")
    if n > MAX_PROMPT_CHARS:
        raise FreeVideoError(
            "提示词 %d 字符，超过接口上限 %d 字符（原生+润色合计），请精简后重试" % (n, MAX_PROMPT_CHARS)
        )
    log("prompt length %d chars" % n)

    token = read_token(args.token_path)
    ref = "fv-img-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    spec = {
        "kind": "image",
        "prompt": args.prompt,
        "aspect": args.aspect,
        "tier": args.tier,
        "model": args.model,
        "label": args.label or "生成图",
        "ref": ref,
    }
    ans = call("POST", "/jobs", token, spec)
    job = ans.get("job", ans)
    jid = job.get("id")
    if not jid:
        raise FreeVideoError("提交任务失败：%s" % _brief(json.dumps(ans, ensure_ascii=False)))
    log("submitted " + str(jid))

    deadline = time.time() + 900
    while True:
        if time.time() > deadline:
            raise FreeVideoError("生成超时（任务 %s）" % jid)
        ans = call("GET", "/jobs/%s?wait=25" % jid, token, timeout=75)
        job = ans.get("job", ans)
        status = job.get("status")
        if status == "succeeded":
            break
        if status in TERMINAL_FAIL or job.get("error"):
            err = job.get("error") or {}
            msg = err.get("message", "") if isinstance(err, dict) else str(err)
            raise FreeVideoError("生成失败（%s）：%s" % (status, _brief(msg)))
        log("status " + str(status))

    result = job.get("result") or {}
    url_path = result.get("url")
    if not url_path:
        raise FreeVideoError(
            "任务成功但没有图片地址：%s" % _brief(json.dumps(job, ensure_ascii=False))
        )
    parts = [p for p in url_path.split("/") if p]
    stem = parts[-2] if len(parts) >= 2 and parts[-1] == "file" else parts[-1]
    if not stem.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        stem += ".jpg"
    out_file = pathlib.Path(args.output_dir) / stem
    size = download(url_path, token, out_file)
    log("saved %d bytes" % size)
    print(str(out_file.resolve()))


if __name__ == "__main__":
    try:
        main()
    except FreeVideoError as e:
        log(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        log("已取消")
        sys.exit(130)
    except Exception as e:
        log("未预期的错误：%s: %s" % (type(e).__name__, _brief(e)))
        sys.exit(1)
