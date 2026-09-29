# -*- coding: utf-8 -*-
"""设置持久化。DeepSeek key 只进环境变量，绝不落文件；其余非敏感设置落 config.json。

key 的持久化走 Windows 用户环境变量（注册表 HKCU\\Environment，跟 setx 写的是同一个地方）。
读的时候先看进程环境，没有就直接读注册表——IDE 启动时把环境快照拿走了，之后再 Run 继承的还是旧环境，
只靠 os.environ 会「保存了下次打开还是没有」。"""
from __future__ import annotations

import ctypes
import json
import os
import sys  # 只为下面这一处：打包后 __file__ 指向临时解包目录，config.json 得放在 exe 旁边才存得住
from urllib.parse import urlsplit, urlunsplit

_ROOT = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CONFIG = os.path.join(_ROOT, "config.json")
_DEFAULT_RELATIONSHIP = "romantic partners"
_DEFAULT_CONTEXT = 10
_DEEPSEEK_ENV = "DEEPSEEK_API_KEY"
_DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"

def relationship() -> str:
    """每次都重新读文件，改设置不用重启进程。"""
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            return json.load(f).get("relationship") or _DEFAULT_RELATIONSHIP
    except (OSError, ValueError):
        return _DEFAULT_RELATIONSHIP

def context() -> int:
    """参考上下文条数：起草和判断各看最近多少条消息。3~30，缺失/脏数据一律退默认值。"""
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            n = int(json.load(f).get("context", _DEFAULT_CONTEXT))
    except (OSError, ValueError, TypeError):
        return _DEFAULT_CONTEXT
    return max(3, min(30, n))

def style() -> str:
    """用户自己描述的说话风格（可选，自由文本），只喂给起草模型。默认空 = 只照着最近的消息模仿。"""
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            return str(json.load(f).get("style") or "")
    except (OSError, ValueError):
        return ""

def draft_provider() -> str:
    """兼容旧调用；当前版本整条分析链固定为 DeepSeek 直连。"""
    return "deepseek"

def normalize_deepseek_base_url(value: str) -> str:
    """校验并规范 OpenAI 兼容 Base URL；用户也可误填完整 chat/completions 地址。"""
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return _DEFAULT_DEEPSEEK_BASE_URL
    parsed = urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Base URL 必须是完整的 http(s) 地址")
    path = parsed.path.rstrip("/")
    suffix = "/chat/completions"
    if path.endswith(suffix):
        path = path[:-len(suffix)].rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")

def deepseek_base_url() -> str:
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            value = json.load(f).get("deepseek_base_url")
        return normalize_deepseek_base_url(value or _DEFAULT_DEEPSEEK_BASE_URL)
    except (OSError, ValueError, TypeError):
        return _DEFAULT_DEEPSEEK_BASE_URL

def deepseek_model() -> str:
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            value = str(json.load(f).get("deepseek_model") or "").strip()
    except (OSError, ValueError, TypeError):
        value = ""
    return value or _DEFAULT_DEEPSEEK_MODEL

def reply_target() -> bool:
    """群聊指定回复对象：开了才在界面上选回复给谁、才把对象喂给模型。默认关。"""
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            return bool(json.load(f).get("reply_target", False))
    except (OSError, ValueError):
        return False

def thinking() -> bool:
    """DeepSeek 是否开思考模式：慢且可能增加 token 消耗，默认关。"""
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            return bool(json.load(f).get("thinking", False))
    except (OSError, ValueError):
        return False

def check_update() -> bool:
    """启动时要不要去 GitHub 查一次最新版本号：默认开，只出这一次网，设置里能关。"""
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            return bool(json.load(f).get("check_update", False))
    except (OSError, ValueError):
        return False

def _get_key(env_name: str) -> str:
    """进程环境优先；没有就读注册表并带进进程环境，之后 core/ 里按 os.environ 读就有了。"""
    v = os.environ.get(env_name, "").strip()
    if not v:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                v = str(winreg.QueryValueEx(k, env_name)[0]).strip()
        except Exception:  # 非 Windows / 没这个值
            v = ""
        if v:
            os.environ[env_name] = v
    return v

def _set_key(env_name: str, value: str) -> None:
    """只写进程环境 + HKCU\\Environment，不写任何文件。"""
    os.environ[env_name] = value
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, env_name, 0, winreg.REG_SZ, value)
        # 广播一下，之后新开的终端/进程就能看到；已经开着的 IDE 看不到也无所谓，启动时会读注册表
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 5000, None)
    except Exception:
        pass  # 非 Windows（本机 Mac 开发）走不到，忽略

def deepseek_key() -> str:
    return _get_key(_DEEPSEEK_ENV)

def has_deepseek_key() -> bool:
    return bool(deepseek_key())

def service_ready() -> bool:
    """当前所选模型服务是否已具备调用所需的密钥。"""
    return has_deepseek_key()

def save(deepseek_key_text: str | None, relationship_text: str, context_n: int | None = None,
         reply_target_on: bool | None = None, style_text: str | None = None,
         thinking_on: bool | None = None, check_update_on: bool | None = None,
         deepseek_base_url_text: str | None = None,
         deepseek_model_text: str | None = None) -> None:
    """每个参数为空/None = 保留当前值。key 只写进程环境 + HKCU\\Environment，不写任何文件。"""
    if deepseek_key_text:
        _set_key(_DEEPSEEK_ENV, deepseek_key_text)
    n = context() if context_n is None else max(3, min(30, int(context_n)))
    target = reply_target() if reply_target_on is None else bool(reply_target_on)
    style_v = style() if style_text is None else str(style_text).strip()  # 空串 = 清掉
    think = thinking() if thinking_on is None else bool(thinking_on)
    check = check_update() if check_update_on is None else bool(check_update_on)
    base_url = (deepseek_base_url() if deepseek_base_url_text is None
                else normalize_deepseek_base_url(deepseek_base_url_text))
    model = deepseek_model() if deepseek_model_text is None else str(deepseek_model_text).strip()
    if not model:
        model = _DEFAULT_DEEPSEEK_MODEL
    with open(_CONFIG, "w", encoding="utf-8") as f:
        json.dump({"relationship": relationship_text, "context": n, "model_provider": "deepseek",
                   "reply_target": target, "style": style_v, "thinking": think,
                   "check_update": check, "deepseek_base_url": base_url,
                   "deepseek_model": model}, f, ensure_ascii=False)
