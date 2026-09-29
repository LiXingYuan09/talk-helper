"""Fixed talk helper question set. Instructions/criteria in English; chat text stays Chinese."""

from __future__ import annotations

JUDGE_QUESTIONS: dict = {
    "literal_question": {
        "type": "noul",
        "instructions": (
            "Does the latest message have an explicit, straightforward conversational purpose? "
            "Use the actual thread. A short reply, punctuation or delay alone is not evidence of subtext."
        ),
        "criteria": {
            "true": (
                "The visible words are a straightforward statement, question, share, joke or plan; "
                "there is no specific contextual evidence of another meaning."
            ),
            "false": (
                "The words and preceding exchange directly support a different meaning, such as "
                "an explicit reminder, contradiction or clearly contextualized sarcasm. Do not infer a test "
                "or blame from brevity, emoji or response time."
            ),
        },
    },
    "true_intent": {
        "type": "choice",
        "distribution": True,
        "instructions": (
            "Which observable conversational function best fits the latest message? "
            "Do not claim access to private motives. Prefer the literal ask unless the surrounding "
            "words provide concrete contrary evidence. A no-contact request is a boundary to respect, "
            "not an anger test or invitation to continue. Also assign relative model weights to every "
            "listed function; these weights describe your uncertainty, not real-world probabilities."
        ),
        "criteria": {
            "confirm_you_care": (
                "They explicitly ask whether you remember or followed something previously stated. "
                "Check the actual prior content; do not call an ordinary question a loyalty test."
            ),
            "vent_anger": (
                "They explicitly describe hurt, frustration or a complaint and want it heard. "
                "Do not infer anger from a short or delayed reply."
            ),
            "request_action": (
                "They explicitly ask for a concrete action, time, deliverable, or decision. "
                "Do not recast an ordinary request as a test."
            ),
            "seek_explanation": (
                "They want a factual explanation of why something happened. "
                "They asked why or what is going on, not mainly for an apology or a new plan."
            ),
            "casual_chat": (
                "Light talk, banter, sharing, or a brief check-in without a concrete request "
                "or explicit conflict. This is the default for ambiguous short messages."
            ),
            "close_topic": (
                "They accepted an answer or explicitly ended this topic peacefully. "
                "A request to stop contact also means do not continue, whatever emotion is unknown."
            ),
        },
    },
    "danger_level": {
        "type": "score",
        "instructions": (
            "Rate only the intensity of conflict explicitly visible in the current exchange. "
            "This is a display heuristic, not a measurement of a person's feelings or relationship fate. "
            "Do not raise the score for short replies, delay or past conflict already resolved. "
            "An explicit active threat or ultimatum remains important."
        ),
        "criteria": [
            "Ordinary chat or joke; no stated complaint or conflict.",
            "A gentle reminder or difference in preference, without visible conflict.",
            "A mild, specific complaint; they still exchange practical information.",
            "They directly say a particular action bothered them or ask that it change.",
            "A repeated unresolved complaint or explicit sarcasm in context; more care is needed.",
            "They plainly state hurt or frustration and want a substantive response.",
            "They directly blame a repeated behavior; the conflict is open.",
            "They state a clear boundary or last chance connected to a specific behavior.",
            "An explicit current ultimatum or credible serious consequence is on the table.",
            "They explicitly end the relationship, request no contact, or a serious immediate safety risk is stated.",
        ],
    },
    "should_reply_now": {
        "type": "noul",
        "instructions": (
            "Is there enough verified information to give a substantive answer in the next message? "
            "This does not decide whether to send at all; consider chat.timing separately. "
            "Choose false when the requested fact or user's ability to commit is unknown, the topic is "
            "already closed, or the other person asked for no contact. Do not manufacture a memory or promise."
        ),
        "criteria": {
            "true": (
                "The requested fact, known mistake, or agreed time/place appears in the chat "
                "and a factual response would be relevant."
            ),
            "false": (
                "A key fact is missing, a commitment is unverified, the topic is closed, "
                "or further contact would violate a stated boundary."
            ),
        },
    },
    "best_action": {
        "type": "choice",
        "instructions": (
            "Choose one evidence-based main action, while respecting verified dates and long gaps. "
            "Do not combine an apology, interrogation, invitation and plan in one message. "
            "Do not default to agreeing or acknowledging when the latest message asks a concrete "
            "question, contains a factual discrepancy, or requests an unverified commitment. "
            "If a past fact is missing, check history before claiming to remember. "
            "If they requested no contact, choose say_less and recommend no message."
        ),
        "criteria": {
            "answer": (
                "Answer the actual question directly when the answer is visible and verified in the chat. "
                "Do not substitute empathy or a follow-up question for an available answer."
            ),
            "clarify": (
                "Ask exactly one missing fact that changes the answer or next step. "
                "Use when it cannot be checked from available history."
            ),
            "check_history": (
                "Look up prior chat or facts before taking a position. "
                "Use when they ask you to repeat, recall, or prove you remember something specific."
            ),
            "apologize": (
                "Lead with a sincere apology for a real mistake or hurt already identified. "
                "Not for an unnamed forgotten thing when you should first find out what it was."
            ),
            "give_commitment": (
                "Offer only a concrete promise, deadline or arrangement the user is known to be able to keep; "
                "otherwise verify first."
            ),
            "explain": (
                "Explain what happened or why, without leading with apology or a new plan."
            ),
            "acknowledge": (
                "Show you heard them and care, without new facts, an apology, or a plan. "
                "Use only when they mainly share a feeling or experience and have no concrete ask."
            ),
            "set_boundary": (
                "State a real limit or respectfully disagree with a request that the user cannot "
                "verify, fulfil, or reasonably accept; offer only feasible alternatives."
            ),
            "say_less": (
                "Keep it short or send nothing. Respect a no-contact request, a closed topic "
                "or a clearly low-information exchange."
            ),
            "make_plan": (
                "Propose or confirm logistics (time, place, task) for a non-conflict request "
                "such as a meal or a meeting."
            ),
        },
    },
    "she_needs": {
        "type": "choice",
        "instructions": (
            "Which response type is most supported by the latest visible words? "
            "This field is a response-planning hint, not knowledge of their inner needs. "
            "Explicit acceptance or a request not to contact means nothing further now. "
            "Do not treat ordinary ambiguity as a hidden attention test."
        ),
        "criteria": {
            "apology": (
                "They need a sincere apology for hurt or a mistake, and they have not accepted one yet."
            ),
            "action": (
                "They need a concrete action, time, commitment, recap of a named fact, or follow-through, "
                "and they have not yet accepted one."
            ),
            "explanation": (
                "They need a clear explanation of what happened or why, and have not received it."
            ),
            "care": (
                "They directly ask whether you heard, remembered or understood a stated concern; "
                "respond to that concern without pretending to read their mind."
            ),
            "nothing": (
                "The topic was clearly closed, no answer was requested, or they explicitly asked "
                "not to be contacted. Do not turn a boundary into a test."
            ),
        },
    },
    "tension_resolved": {
        "type": "noul",
        "instructions": (
            "Does the visible exchange show no active conflict now? "
            "A short reply is insufficient to infer tension; an explicit unresolved complaint "
            "or boundary means the issue is still open."
        ),
        "criteria": {
            "true": (
                "They accepted, resumed ordinary exchange, or no conflict appeared in the chat."
            ),
            "false": (
                "A complaint, disagreement, boundary or ultimatum remains explicitly unresolved."
            ),
        },
    },
}


def build_state(messages: list, relationship: str, keep: int = 10,
                reply_to: str | None = None,timing: dict | None = None,
                profile: dict | None = None) -> dict:
    """messages: (from, text) / (from, text, name) / dict（name 可选）。from 只认 her/me。

    name = 群里的发言人；有 name 就当群聊（chat.is_group）。reply_to = 群里指定的回复对象。
    """
    cleaned = []
    for item in messages:
        if isinstance(item, dict):
            who, text, name = item.get("from"), item.get("text"), item.get("name")
        else:
            who, text = item[0], item[1]
            name = item[2] if len(item) > 2 else None
        if who not in ("her", "me"):
            raise ValueError(f"message from must be 'her' or 'me', got {who!r}")
        message = {"from": who, "text": str(text)}
        if name:
            message["name"] = str(name)
        cleaned.append(message)
    cleaned = cleaned[-keep:]
    latest_from = cleaned[-1]["from"] if cleaned else "her"
    chat = {
        "relationship": relationship,
        "messages": cleaned,
        "latest_from": latest_from,
        "is_group": any("name" in m for m in cleaned),
    }
    if reply_to:
        chat["reply_to"] = str(reply_to)
    if timing:chat['timing']=timing
    if profile:chat['profile']=profile
    return {"chat": chat}


def build_rank_question(candidates: list[str]) -> dict:
    """Build the best_reply choice question. criteria values stay in original Chinese."""
    if not 2 <= len(candidates) <= 3:
        raise ValueError("build_rank_question expects 2 or 3 candidate replies")
    keys = ("reply_a", "reply_b", "reply_c")[:len(candidates)]
    return {
        "best_reply": {
            "type": "choice",
            "instructions": (
                "Which reviewed reply best serves the visible request and one chosen main action? "
                "Prefer the user's natural voice, a concrete next step and an easy exit. "
                "Penalize mind-reading, pressure, over-promising and off-topic lines. "
                "If facts are missing, favor an honest check or one necessary clarification."
            ),
            "criteria": {key: text for key, text in zip(keys, candidates)},
        }
    }
