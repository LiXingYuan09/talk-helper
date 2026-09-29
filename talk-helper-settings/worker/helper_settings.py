"""Scoped preferences; API secrets use the Windows credential store."""
import ctypes as c
from ctypes import wintypes as w
import json,os,re
from pathlib import Path
from model import official_base

RELATION_FIELDS=('self_mbti','self_rating','self_strengths','self_challenges','other_alias','other_mbti','other_rating',
                 'stage','met_context','known_duration','recent_events','contact_pattern','goal','feeling')
PROFILE=('relationship','style','common_phrases','context','thinking')+RELATION_FIELDS
LIMITS={'assistant_name':47,'deepseek_base_url':255,'deepseek_model':127,'relationship':127,'style':1023,'common_phrases':1023,
        'self_mbti':15,'self_rating':3,'self_strengths':255,'self_challenges':255,'other_alias':63,'other_mbti':15,
        'other_rating':3,'stage':127,'met_context':255,'known_duration':127,'recent_events':767,
        'contact_pattern':511,'goal':127,'feeling':255}
RELATIONS={'friends':'朋友','romantic partners':'恋人','family':'家人','colleagues':'同事'}

class Credential(c.Structure):
    _fields_=[('flags',w.DWORD),('kind',w.DWORD),('target',w.LPWSTR),('comment',w.LPWSTR),
              ('written',w.FILETIME),('size',w.DWORD),('blob',c.POINTER(c.c_ubyte)),
              ('persist',w.DWORD),('count',w.DWORD),('attributes',c.c_void_p),('alias',w.LPWSTR),('username',w.LPWSTR)]

class SecretStore:
    target='TalkHelper.DeepSeek.API'
    def __init__(self):
        self.a=c.WinDLL('advapi32',use_last_error=True)
        self.a.CredReadW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.POINTER(c.POINTER(Credential))]
        self.a.CredWriteW.argtypes=[c.POINTER(Credential),w.DWORD]
        self.a.CredFree.argtypes=[c.c_void_p]
    def read(self):
        value=c.POINTER(Credential)()
        if not self.a.CredReadW(self.target,1,0,c.byref(value)):return ''
        try:
            v=value.contents
            return c.string_at(v.blob,v.size).decode('utf-16le') if v.size<=512 else ''
        finally:self.a.CredFree(value)
    def write(self,text):
        raw=text.encode('utf-16le');blob=(c.c_ubyte*len(raw)).from_buffer_copy(raw)
        value=Credential();value.kind=1;value.target=self.target;value.persist=2
        value.size=len(raw);value.blob=blob;value.username='DeepSeek'
        try:
            if not self.a.CredWriteW(c.byref(value),0):raise ValueError('API Key 保存失败，请重试。')
        finally:c.memset(blob,0,len(raw))

class SettingsView:
    _talkhelper_snapshot=True
    def __init__(self,data,key):self.data=dict(data);self.key=key
    def relationship(self):return self.data['relationship']
    def context(self):return self.data['context']
    def thinking(self):return self.data['thinking']
    def deepseek_model(self):return self.data['deepseek_model']
    def deepseek_base_url(self):return self.data['deepseek_base_url']
    def deepseek_key(self):
        if self.key:os.environ['DEEPSEEK_API_KEY']=self.key
        return self.key
    def style(self):
        text=self.data['style'];phrases=self.data['common_phrases']
        return text+('\n我的常用语（只在自然合适时参考，不要硬塞）：\n'+phrases if phrases else '')
    def profile(self):
        return {name:self.data[name] for name in RELATION_FIELDS if self.data.get(name)}

class HelperSettings:
    def __init__(self,path,fallback,secrets=None):
        self.path=Path(path);self.fallback=fallback;self.secrets=secrets or SecretStore();self.revision=0;self.reload()
    def reload(self):
        try:self.data=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.data={}
        if not isinstance(self.data,dict):self.data={}
        self.key=self.secrets.read() or self.fallback.deepseek_key()
    def values(self,account='',username=''):
        values=dict(assistant_name='talk helper',deepseek_base_url='https://api.deepseek.com',deepseek_model='deepseek-flash',
                    relationship='朋友',context=12,thinking=False,style='',common_phrases='',
                    **{name:'' for name in RELATION_FIELDS})
        values.update({k:v for k,v in self.data.items() if k in values and k not in RELATION_FIELDS})
        all_profiles=self.data.get('chat_profiles',{})
        profiles=all_profiles.get(account,{}) if account and isinstance(all_profiles,dict) else {}
        profile=profiles.get(username,{}) if isinstance(profiles,dict) else {}
        if isinstance(profile,dict):
            values.update({k:profile[k] for k in PROFILE if k in profile and isinstance(profile[k],(str,int,bool))})
        values['relationship']=RELATIONS.get(values['relationship'],values['relationship'])
        values['context']=max(3,min(30,int(values['context'])));values['thinking']=bool(values['thinking'])
        return values
    def snapshot(self,account='',username=''):return SettingsView(self.values(account,username),self.key)
    def apply(self,values,account='',username='',key=''):
        clean={}
        for name,limit in LIMITS.items():
            text=str(values.get(name,'')).strip()
            if '\0' in text or len(text.encode('utf-16le'))//2>limit:raise ValueError('设置内容过长，请缩短后保存。')
            clean[name]=text
        if not clean['assistant_name']:raise ValueError('请填写助手名称。')
        if not clean['deepseek_model']:raise ValueError('请填写 DeepSeek 模型名称。')
        if not clean['relationship']:raise ValueError('请选择或填写聊天对象身份。')
        for name in ('self_mbti','other_mbti'):
            if clean[name] and not re.fullmatch(r'[EI][NS][FT][JP](?:-[AT])?',clean[name].upper()):
                raise ValueError('MBTI 请填写四个字母（如 ENFP），不知道可留空。')
            clean[name]=clean[name].upper()
        for name in ('self_rating','other_rating'):
            if clean[name] and (not clean[name].isdigit() or not 0<=int(clean[name])<=100):
                raise ValueError('主观评分请填写 0～100，或留空。')
        clean['deepseek_base_url']=official_base(clean['deepseek_base_url'])
        try:clean['context']=int(values['context'])
        except (ValueError,TypeError,KeyError):raise ValueError('上下文条数请填写 3～30。')
        if not 3<=clean['context']<=30:raise ValueError('上下文条数请填写 3～30。')
        clean['thinking']=bool(values.get('thinking'))
        key=str(key).strip()
        if '\0' in key or len(key.encode('utf-16le'))>510:raise ValueError('API Key 格式不正确。')
        updated=json.loads(json.dumps(self.data))
        updated.update({k:v for k,v in clean.items() if k not in PROFILE or (not username and k not in RELATION_FIELDS)})
        updated['model_provider']='deepseek';updated['check_update']=False
        if username:
            if not account:raise ValueError('尚未识别微信账号，请稍后重试。')
            updated.setdefault('chat_profiles',{}).setdefault(account,{})[username]={k:clean[k] for k in PROFILE}
        if key:self.secrets.write(key)
        tmp=self.path.with_suffix('.settings.tmp')
        try:
            tmp.write_text(json.dumps(updated,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.path)
        except OSError:raise ValueError('配置文件保存失败，请确认程序文件夹可写。')
        self.data=updated
        if key:self.key=key
        self.revision+=1
