"""Trusted send times from WeChat create_time; never parse chat text or images."""
from datetime import datetime
from math import isfinite

def timestamp(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)):return None
    try:
        value=float(value)
        if not isfinite(value):return None
        if value>=100_000_000_000:value/=1000
        # Reject missing/corrupt dates rather than inventing a date from sort_seq.
        return int(value) if 946684800<=value<4102444800 else None
    except (ValueError,OverflowError):return None

def duration(seconds):
    if seconds is None:return '未知'
    seconds=max(0,int(seconds))
    if seconds<60:return f'{seconds}秒'
    if seconds<3600:return f'{seconds//60}分钟'
    if seconds<86400:return f'{seconds//3600}小时{seconds%3600//60}分钟'
    return f'{seconds//86400}天{seconds%86400//3600}小时'

def time_context(snapshot,now=None):
    now=(now or datetime.now().astimezone())
    if now.tzinfo is None:now=now.astimezone()
    values=snapshot.timestamps if len(snapshot.timestamps)==len(snapshot.messages) else (None,)*len(snapshot.messages)
    messages=[];previous=None
    for index,value in enumerate(values):
        value=timestamp(value)
        item={'message_index':index,'sent_at':None,'gap_from_previous_text_seconds':None}
        if value is not None:
            sent=datetime.fromtimestamp(value,now.tzinfo)
            item.update(sent_at=sent.isoformat(timespec='seconds'),unix_seconds=value)
            if previous is not None and value>=previous:
                item['gap_from_previous_text_seconds']=value-previous
                item['crossed_date']=sent.date()!=datetime.fromtimestamp(previous,now.tzinfo).date()
                item['long_gap']=value-previous>=1800
        messages.append(item);previous=value
    latest=messages[-1] if messages else {}
    age=int(now.timestamp())-latest['unix_seconds'] if 'unix_seconds' in latest else None
    return dict(source='wechat-create_time',evaluated_at=now.isoformat(timespec='seconds'),
                timezone=now.strftime('%z'),messages=messages,message_age_seconds=age,
                historical_reference=age is not None and age>=21600,
                clock_warning=age is not None and age<0)

def time_label(snapshot):
    value=timestamp(snapshot.timestamps[-1]) if snapshot.timestamps else None
    return datetime.fromtimestamp(value).astimezone().strftime('%m-%d %H:%M') if value is not None else ''

def time_details(snapshot,timing=None):
    timing=timing or time_context(snapshot)
    latest=timing['messages'][-1] if timing['messages'] else {}
    if not latest.get('sent_at'):return '发送时间：未知（不推测）'
    text='发送时间：'+latest['sent_at']+'\r\n与上一条文字间隔：'+duration(latest.get('gap_from_previous_text_seconds'))
    text+='\r\n本次生成参考时间：'+timing['evaluated_at']
    text+='\r\n距生成时：'+duration(timing['message_age_seconds'])
    if timing['clock_warning']:text+='\r\n消息时间领先设备时间，请核对时钟。'
    if timing['historical_reference']:text+='\r\n这是历史消息；不要默认对方现在仍在等回复。'
    return text
