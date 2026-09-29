"""Compact, evidence-limited text shown inside each native WeChat analysis card."""

from math import isfinite
from unicodedata import east_asian_width

INTENT_LABELS = {
    'confirm_you_care': '核对过往内容',
    'vent_anger': '表达不满',
    'request_action': '要求具体行动',
    'seek_explanation': '询问原因',
    'casual_chat': '闲聊或分享',
    'close_topic': '结束话题',
}


def _percent(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
        return None
    if not 0 <= value <= 1:
        return None
    return round(value * 100)


def _question(answers):
    action = (answers.get('best_action') or {}).get('choice')
    risk = (answers.get('danger_level') or {}).get('score')
    options = []
    if isinstance(risk, (int, float)) and not isinstance(risk, bool) and risk >= 4:
        options.append(('tension_resolved', '这轮分歧已经化解？', '尚未化解'))
    if action in ('check_history', 'clarify'):
        options.append(('should_reply_now', '信息足够直接答复？', '先核实'))
    options.append(('literal_question', '主要按字面理解？', '另有语境'))
    for key, label, negative in options:
        yes = _percent((answers.get(key) or {}).get('noul'))
        if yes is not None:
            return [label, f'- 是 {yes}%   - {negative} {100-yes}%']
    return []


def _intent_lines(answers):
    answer = answers.get('true_intent') or {}
    probabilities = answer.get('probabilities')
    if not isinstance(probabilities, dict) or not probabilities:
        choice = answer.get('choice')
        return ['可能的对话用途', '- ' + INTENT_LABELS[choice]] if choice in INTENT_LABELS else []
    ranked = sorted(((key, value) for key, value in probabilities.items()
                     if key in INTENT_LABELS and _percent(value) is not None),
                    key=lambda item: item[1], reverse=True)
    if len(ranked) < 2:
        return []
    first = _percent(ranked[0][1])
    second = min(100 - first, _percent(ranked[1][1]))
    return ['可能的对话用途 · 模型权重',
            f'- {INTENT_LABELS[ranked[0][0]]} {first}%',
            f'- {INTENT_LABELS[ranked[1][0]]} {second}%',
            f'- 其他 {100-first-second}%']


def _short(text, length=55):
    value = ' '.join(str(text or '').split())
    return value if len(value) <= length else value[:length-1].rstrip() + '…'


def compact_analysis(result):
    """Percentages are model-relative hints, never claims about someone's mind."""
    guidance = result.get('guidance') or {}
    action = ((guidance.get('actions') or [''])[0])
    if result.get('do_not_send'):
        return '对方明确要求停止联系\r\n当前动作\r\n- ' + _short(action)
    answers = result.get('answers') or {}
    lines = _question(answers) + _intent_lines(answers)
    risk = (answers.get('danger_level') or {}).get('score')
    if isinstance(risk, (int, float)) and not isinstance(risk, bool) and isfinite(risk):
        lines.append(f'紧张度：{max(0, min(9, round(risk)))}/9')
    lines += ['当前动作', '- ' + _short(action)]
    return '\r\n'.join(lines)


def card_header(assistant_name, time_label):
    name = str(assistant_name or 'talk helper')
    label = str(time_label or '')
    header = f'{name} · {label}' if label else name
    def units(value):
        return sum(2 if east_asian_width(char) in 'FW' else 1 for char in value)
    if units(header) <= 29:
        return header
    if units(name) <= 29:
        return name
    trimmed = ''
    for char in name:
        if units(trimmed + char + '…') > 29:
            break
        trimmed += char
    return trimmed + '…'
