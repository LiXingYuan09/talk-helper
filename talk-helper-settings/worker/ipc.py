"""Authenticated, bounded transcript IPC. No image capture is used."""
import ctypes as c
from ctypes import wintypes as w
import time
import hashlib

MAGIC, VERSION, PROOF = 0x54484241, 13, 0x54485031
ANCHORED, PAUSED, HAS_REPLY, BUSY, ERROR = 1, 2, 4, 8, 16
RETRY, NEXT_REPLY, TOGGLE_PAUSE = 1, 2, 4

class Packet(c.Structure):
    _pack_=1
    _fields_=[('magic',c.c_uint32),('version',c.c_uint32),('token',c.c_uint64),('sequence',c.c_uint64),
              ('flags',c.c_uint32),('anchor',c.c_int32*4),('area',c.c_int32*4),
              ('title',c.c_wchar*128),('status',c.c_wchar*256),('body',c.c_wchar*4096),('reply',c.c_wchar*512),('tension',c.c_int32),('card_id',c.c_uint64),('assistant_name',c.c_wchar*48)]

class CopyData(c.Structure):
    _fields_=[('dwData',c.c_size_t),('cbData',w.DWORD),('lpData',c.c_void_p)]

def bounded_text(text,units):
    return str(text or '').replace('\0','').encode('utf-16-le','replace')[:(units-1)*2].decode('utf-16-le','ignore')

def make_packet(token,sequence,*,title='',status='',body='',reply='',anchor=None,area=None,tension=-1,compact=False,paused=False,busy=False,error=False,card_id=0,control=False,enabled=False,assistant_name='talk helper'):
    if not -1<=tension<=9:raise ValueError('Invalid tension')
    p=Packet();p.magic=MAGIC;p.version=VERSION;p.token=token;p.sequence=sequence;p.tension=tension;p.card_id=card_id
    p.flags=(ANCHORED if anchor and area else 0)|(HAS_REPLY if reply else 0)|(32 if compact else 0)|(PAUSED if paused else 0)|(BUSY if busy else 0)|(ERROR if error else 0)|(64 if control else 0)|(128 if enabled else 0)
    for field,rect in (('anchor',anchor),('area',area)):
        if rect:
            if len(rect)!=4 or not all(0<=int(x)<=32768 for x in rect) or rect[2]<=rect[0] or rect[3]<=rect[1]:raise ValueError('Invalid card bounds')
            getattr(p,field)[:]=rect
    p.title=bounded_text(title,128);p.status=bounded_text(status,256);p.body=bounded_text(body,4096);p.reply=bounded_text(reply,512)
    p.assistant_name=bounded_text(assistant_name,48)
    return p

class NativePanel:
    def __init__(self,parent,panel,parent_pid,token):
        self.parent,self.panel,self.parent_pid,self.token=int(parent),int(panel),int(parent_pid),int(token)
        self.sequence=0;self.last_payload={};self.last_sent={};self.directory_sequence=0;self.layout_sequence=0;self.last_layout=None;self.settings_sequence=0
        self.u=c.WinDLL('user32',use_last_error=True)
        for n in ('IsWindow','IsIconic'):
            fn=getattr(self.u,n);fn.argtypes=[w.HWND];fn.restype=w.BOOL
        self.u.GetParent.argtypes=[w.HWND];self.u.GetParent.restype=w.HWND
        self.u.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)]
        self.u.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,c.c_int]
        self.u.SendMessageTimeoutW.argtypes=[w.HWND,w.UINT,c.c_size_t,c.c_ssize_t,w.UINT,w.UINT,c.POINTER(c.c_size_t)]
        self.u.SendMessageTimeoutW.restype=c.c_size_t
        if c.sizeof(Packet)!=10152 or not self.alive() or self.send(0x8011)!=PROOF:raise RuntimeError('Native view validation failed')
    def send(self,msg,wp=0,lp=0):
        result=c.c_size_t();ok=self.u.SendMessageTimeoutW(self.panel,msg,wp,lp,3,1500,c.byref(result))
        return int(result.value) if ok else None
    def alive(self):
        if not self.u.IsWindow(self.parent) or not self.u.IsWindow(self.panel) or self.u.GetParent(self.panel)!=self.parent:return False
        for hwnd in (self.parent,self.panel):
            pid=w.DWORD();self.u.GetWindowThreadProcessId(hwnd,c.byref(pid))
            if pid.value!=self.parent_pid:return False
        name=c.create_unicode_buffer(128);self.u.GetClassNameW(self.panel,name,128)
        return name.value=='TalkHelper.Inline.Card.v13r2'
    def minimized(self):return bool(self.u.IsIconic(self.parent))
    def poll(self):return self.send(0x8013,self.token) or 0
    def update(self,**payload):
        now=time.monotonic()
        card_id=payload.get('card_id',0)
        if payload==self.last_payload.get(card_id) and now-self.last_sent.get(card_id,0)<1:return True
        p=make_packet(self.token,self.sequence+1,**payload);d=CopyData(MAGIC,c.sizeof(p),c.addressof(p))
        if self.send(0x4a,0,c.addressof(d))==1:
            self.sequence+=1;self.last_payload[card_id]=dict(payload);self.last_sent[card_id]=now;return True
        return False

    def choices(self):
        return self.send(0x8015,self.token) or 0
    def following(self,reader):
        import struct
        address=self.send(0x8018,self.token);raw=reader.read(address,32) if address else b''
        if len(raw)!=32:return {}
        size,mode,events,moves,visible,retained,micros,reserved=struct.unpack('<8I',raw)
        if size!=32 or mode!=1 or reserved or retained>512 or visible>retained:return {}
        return dict(scroll_positioning='native-ui-events',scroll_events=events,scroll_moves=moves,native_visible_cards=visible,retained_cards=retained,max_follow_microseconds=micros)
    def settings(self,values,scope=0,key_present=False,status='',error=False):
        self.settings_sequence+=1
        p=SettingsPacket();p.magic=0x54485313;p.version=13;p.token=self.token;p.sequence=self.settings_sequence
        p.scope=scope;p.context=values['context'];p.thinking=bool(values['thinking']);p.key_present=key_present;p.flags=2 if error else 1
        for field,key in SETTINGS_FIELDS.items():setattr(p,field,bounded_text(values[key],dict(SettingsPacket._fields_)[field]._length_))
        p.status=bounded_text(status,256);d=CopyData(p.magic,c.sizeof(p),c.addressof(p))
        return self.send(0x4a,0,c.addressof(d))==1
    def settings_draft(self,reader):
        address=self.send(0x8017,self.token)
        raw=reader.read(address,c.sizeof(SettingsPacket)) if address else b''
        if len(raw)!=c.sizeof(SettingsPacket):raise ValueError('设置读取失败，请重新打开设置。')
        p=SettingsPacket.from_buffer_copy(raw)
        if p.magic!=0x54485313 or p.version!=13 or p.token!=self.token or p.flags!=0 or p.scope>1000000:raise ValueError('设置请求无效，请重新打开设置。')
        values={key:getattr(p,field) for field,key in SETTINGS_FIELDS.items()}
        values.update(context=p.context,thinking=bool(p.thinking))
        key=p.key;scope=p.scope;c.memset(c.addressof(p),0,c.sizeof(p))
        return values,scope,key
    def layout(self,list_address,targets):
        value=(int(list_address),tuple(sorted((int(item),int(card),int(padding)) for item,(card,padding) in targets.items())))
        changed=value!=self.last_layout;self.layout_sequence+=1
        header=LayoutHeader(0x54485212,13,self.token,self.layout_sequence,value[0],len(value[1]))
        entries=(LayoutEntry*len(value[1]))(*(LayoutEntry(*entry) for entry in value[1]))
        raw=bytes(header)+bytes(entries);buffer=c.create_string_buffer(raw);d=CopyData(0x54485212,len(raw),c.addressof(buffer))
        ok=self.send(0x4a,0,c.addressof(d))==1
        if ok:self.last_layout=value
        return ok,changed
    def directory(self,entries):
        self.directory_sequence+=1
        header=DirectoryHeader(0x54484311,13,self.token,self.directory_sequence,len(entries))
        items=(DirectoryEntry*len(entries))()
        for i,entry in enumerate(entries):
            items[i].id=entry['id'];items[i].enabled=bool(entry['enabled']);items[i].group=bool(entry['group'])
            items[i].name=bounded_text(entry['name'],128)
        raw=c.string_at(c.byref(header),c.sizeof(header))+bytes(items)
        buf=c.create_string_buffer(raw);d=CopyData(0x54484311,len(raw),c.addressof(buf))
        return self.send(0x4a,0,c.addressof(d))==1

class DirectoryHeader(c.Structure):
    _pack_=1
    _fields_=[('magic',c.c_uint32),('version',c.c_uint32),('token',c.c_uint64),('sequence',c.c_uint64),('count',c.c_uint32)]
class DirectoryEntry(c.Structure):
    _pack_=1
    _fields_=[('id',c.c_uint32),('enabled',c.c_uint32),('group',c.c_uint32),('name',c.c_wchar*128)]
class LayoutHeader(c.Structure):
    _pack_=1
    _fields_=[('magic',c.c_uint32),('version',c.c_uint32),('token',c.c_uint64),('sequence',c.c_uint64),('list',c.c_uint64),('count',c.c_uint32)]
class LayoutEntry(c.Structure):
    _pack_=1
    _fields_=[('item',c.c_uint64),('card',c.c_uint64),('padding',c.c_uint32)]

SETTINGS_FIELDS={'assistant':'assistant_name','base':'deepseek_base_url','model':'deepseek_model','relationship':'relationship','style':'style','phrases':'common_phrases',
                 'self_mbti':'self_mbti','self_rating':'self_rating','self_strengths':'self_strengths','self_challenges':'self_challenges',
                 'other_alias':'other_alias','other_mbti':'other_mbti','other_rating':'other_rating','stage':'stage',
                 'met_context':'met_context','known_duration':'known_duration','recent_events':'recent_events',
                 'contact_pattern':'contact_pattern','goal':'goal','feeling':'feeling'}
class SettingsPacket(c.Structure):
    _pack_=1
    _fields_=[('magic',c.c_uint32),('version',c.c_uint32),('token',c.c_uint64),('sequence',c.c_uint64),
              ('scope',c.c_uint32),('context',c.c_uint32),('thinking',c.c_uint32),('key_present',c.c_uint32),('flags',c.c_uint32),
              ('assistant',c.c_wchar*48),('base',c.c_wchar*256),('model',c.c_wchar*128),('relationship',c.c_wchar*128),
              ('style',c.c_wchar*1024),('phrases',c.c_wchar*1024),('key',c.c_wchar*256),('status',c.c_wchar*256),
              ('self_mbti',c.c_wchar*16),('self_rating',c.c_wchar*4),('self_strengths',c.c_wchar*256),
              ('self_challenges',c.c_wchar*256),('other_alias',c.c_wchar*64),('other_mbti',c.c_wchar*16),
              ('other_rating',c.c_wchar*4),('stage',c.c_wchar*128),('met_context',c.c_wchar*256),
              ('known_duration',c.c_wchar*128),('recent_events',c.c_wchar*768),('contact_pattern',c.c_wchar*512),
              ('goal',c.c_wchar*128),('feeling',c.c_wchar*256)]
