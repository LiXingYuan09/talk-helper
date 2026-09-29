# -*- coding: utf-8 -*-
"""整条链的唯一入口：对话 → 起草 3 条 → talk helper 一次判断+排序 → 结构化结果。

平台无关。SSE 消费者、悬浮窗、命令行 demo 都只调 analyze()。
"""
from __future__ import annotations

import re

try:
    from .draft import draft_candidates
    from .deepseek_judge import ask_deepseek, _validated_answers, _validated_guidance, _validated_replies
    from .jev_client import JevError
    from .questions import JUDGE_QUESTIONS, build_rank_question, build_state
except ImportError:
    from draft import draft_candidates
    from deepseek_judge import ask_deepseek, _validated_answers, _validated_guidance, _validated_replies
    from jev_client import JevError
    from questions import JUDGE_QUESTIONS, build_rank_question, build_state

_REPLY_IDX = {"reply_a": 0, "reply_b": 1, "reply_c": 2}
_NO_CONTACT = re.compile(
    r"^(?:请|以后|你|麻烦你|求你)?\s*(?:不要|别)\s*(?:再)?\s*"
    r"(?:联系我|找我|打扰我|给我发(?:消息|信息))(?:了|啦|吧|好吗)?[。！!]*$"
)


def _no_contact_request(messages: list, reply_to: str | None) -> bool:
    """Only a clear direct request; quoted, mixed or group messages need context."""
    if reply_to or not messages:
        return False
    last = messages[-1]
    if isinstance(last, dict):
        who, content, speaker = last.get("from"), last.get("text"), last.get("name")
    else:
        who, content = last[:2]
        speaker = last[2] if len(last) > 2 else None
    return who == "her" and not speaker and bool(_NO_CONTACT.fullmatch(str(content or "").strip()))


def _respect_no_contact(reply_to):
    # Empty reply deliberately makes the native Copy command a no-op.
    return {
        "candidates": [""], "best_index": 0, "best_reply": "", "scores": [0.0] * 3,
        "answers": {"danger_level": {"type": "score", "score": 7}},
        "guidance": {
            "summary": "对方明确要求不要再联系；按这句话的边界处理，不猜测原因。",
            "actions": ["现在停止发消息，尊重对方明确提出的不联系要求。",
                        "除非对方之后主动重新联系，否则不要换账号、托人传话或试探。"],
            "avoid": "不要发送解释、道歉、追问或挽回消息，也不要绕开对方的边界。",
        },
        "usage": {}, "reply_to": reply_to, "do_not_send": True,
    }


def analyze(messages: list, relationship: str, model: str | None = None,
            timeout: float = 30, context: int = 10, provider: str = "deepseek",
            reply_to: str | None = None, style: str = "", thinking: bool = False,
            base_url: str | None = None, timing: dict | None = None,
            profile: dict | None = None) -> dict:
    """messages: [(from, text)] from ∈ {her, me}，最新一条在最后；
    群聊里可以带第三项 name（说这句话的人），单聊不带。
    context: 起草和判断各看最近多少条消息（用户设置里的「参考上下文」）。
    provider: 仅接受 deepseek；整条链固定直连 DeepSeek。
    reply_to: 群聊里指定回复给谁；None = 正常回复。
    style: 用户自己描述的说话风格，起草和事实校对时保留。
    thinking: 起草时是否开思考模式，只影响起草，默认关。
    model=None 用该来源的默认模型；DeepSeek 可传自定义 base_url。

    返回 {candidates, best_index, best_reply, scores, answers, guidance, usage, reply_to}。
    guidance 包含本轮解读 summary、2~3 条具体行动 actions 和一个避免事项 avoid。
    scores 是候选间的模型选择概率（0~1），取自 best_reply.probabilities，不代表现实回复成功率。
    单候选不排序，scores 为全 0；多候选的排序结果无效时抛 JevError，供界面提示重试。
    只有对方最新说话时才有意义调它——是不是该触发由调用方判断（看 latest_from）。
    """
    if provider != "deepseek":
        raise JevError("talk helper 仅支持 DeepSeek 直连。")
    if _no_contact_request(messages, reply_to):
        return _respect_no_contact(reply_to)
    candidates = draft_candidates(messages, relationship, provider=provider,
                                  model=model, timeout=timeout, keep=context, reply_to=reply_to,
                                  style=style, thinking=thinking, base_url=base_url,timing=timing,profile=profile)
    if (not isinstance(candidates, list) or not 1 <= len(candidates) <= 3
            or any(not isinstance(text, str) or not text.strip() for text in candidates)):
        raise JevError("未生成可用的回复候选，请重新分析或补充聊天上下文。")

    questions = dict(JUDGE_QUESTIONS)
    if len(candidates) >= 2:  # 起草只给了 1 条就没什么可排的，判断题照问
        questions.update(build_rank_question(candidates))
    state = build_state(messages, relationship, keep=context, reply_to=reply_to,timing=timing,profile=profile)
    result = ask_deepseek(state, questions, base_url or "https://api.deepseek.com",
                          model or "deepseek-flash", timeout=timeout, thinking=thinking,
                          drafts=candidates, style=style)

    candidates = _validated_replies(result, len(candidates))
    answers = _validated_answers(result, questions)
    guidance = _validated_guidance(result)
    best_index = 0  # A single candidate needs no ranking question.
    scores = [0.0, 0.0, 0.0]
    if len(candidates) >= 2:
        ranking = answers["best_reply"]
        probabilities = ranking["probabilities"]
        best_index = _REPLY_IDX[ranking["choice"]]
        for key, value in probabilities.items():
            scores[_REPLY_IDX[key]] = float(value)

    return {
        "candidates": candidates,
        "best_index": best_index,
        "best_reply": candidates[best_index],
        "scores": scores,
        "answers": answers,
        "guidance": guidance,
        "usage": result.get("usage") or {},
        "reply_to": reply_to,
    }
