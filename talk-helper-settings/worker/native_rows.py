"""Read structural Qt row bindings only. Text/eligibility come from the existing DB/UIA path."""
import ctypes as c
import struct
import time
from host_compat import identify_weixin_dll
from ctypes import wintypes as w

LIST, MODEL, VIEWMODEL, TEXTMODEL, TEXTMETA = 0x8fd5dd8,0x8f0fc28,0x9329148,0x930c9b8,0x879970
SPECS={
    '4.1.13.65':dict(list=LIST,model=MODEL,viewmodel=VIEWMODEL,item=TEXTMODEL,row_meta=TEXTMETA,
                     model_field=0x200,identity=0x1c0bc60,other=0x1c09a80),
    '4.1.15.13':dict(list=0x920ec28,model=0x9180ba8,viewmodel=0x958a5a8,item=0x956d338,row_meta=0x889a50,
                     model_field=0x278,identity=0x1c18b30,other=0x1c16580),
}

class Module(c.Structure):
    _fields_=[('size',w.DWORD),('id',w.DWORD),('pid',w.DWORD),('global_uses',w.DWORD),('uses',w.DWORD),
              ('base',c.c_void_p),('length',w.DWORD),('handle',c.c_void_p),('name',c.c_wchar*256),('path',c.c_wchar*260)]
class Region(c.Structure):
    _fields_=[('base',c.c_void_p),('allocation',c.c_void_p),('allocation_protect',w.DWORD),('partition',c.c_ushort),
              ('length',c.c_size_t),('state',w.DWORD),('protect',w.DWORD),('kind',w.DWORD)]

def pair_rows(chat,native):
    """Unique geometry match; pooled/unbound rows are excluded by the reader."""
    area=chat['area'];scale=(area[2]-area[0])/native['width']
    if not .5<=scale<=3:return {}
    result={}
    for row in chat['rows']:
        top,bottom=row['rect'][1],row['rect'][3]
        matches=[n for n in native['rows'] if abs(area[1]+n['top']*scale-top)<=3 and abs(area[1]+n['bottom']*scale-bottom)<=3]
        if len(matches)==1:
            n=matches[0];result[row['rect']]={'item':n['item'],'padding':round(n['padding']*scale)}
    return result

class NativeRows:
    def __init__(self,pid):
        self.pid=pid;self.base=0;self.list=0;self.last_scan=0;self.scan_cursor=0;self.handle=None;self.spec=None
        self.k=c.WinDLL('kernel32',use_last_error=True)
        self.k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];self.k.OpenProcess.restype=w.HANDLE
        self.k.ReadProcessMemory.argtypes=[w.HANDLE,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
        self.k.VirtualQueryEx.argtypes=[w.HANDLE,c.c_void_p,c.POINTER(Region),c.c_size_t];self.k.VirtualQueryEx.restype=c.c_size_t
        self.k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];self.k.CreateToolhelp32Snapshot.restype=w.HANDLE
        self.k.Module32FirstW.argtypes=[w.HANDLE,c.POINTER(Module)];self.k.Module32NextW.argtypes=[w.HANDLE,c.POINTER(Module)]
        self.k.K32GetModuleFileNameExW.argtypes=[w.HANDLE,c.c_void_p,w.LPWSTR,w.DWORD]
        self.k.K32GetModuleFileNameExW.restype=w.DWORD
        self.k.CloseHandle.argtypes=[w.HANDLE]
        self.handle=self.k.OpenProcess(0x410,False,pid)
        snap=self.k.CreateToolhelp32Snapshot(24,pid)
        try:
            m=Module();m.size=c.sizeof(m);ok=self.k.Module32FirstW(snap,c.byref(m))
            while ok:
                if m.name.lower()=='weixin.dll':
                    full=c.create_unicode_buffer(32768)
                    length=self.k.K32GetModuleFileNameExW(self.handle,m.handle,full,len(full))
                    path=full.value if 0<length<len(full) else m.path
                    version=identify_weixin_dll(path)
                    if version in SPECS:self.base=m.base;self.spec=SPECS[version];break
                ok=self.k.Module32NextW(snap,c.byref(m))
        finally:self.k.CloseHandle(snap)
    def close(self):
        if self.handle:self.k.CloseHandle(self.handle);self.handle=None
    def read(self,address,size):
        if not address or not self.handle or not 0<size<=2*1024*1024:return b''
        out=c.create_string_buffer(size);got=c.c_size_t()
        return out.raw if self.k.ReadProcessMemory(self.handle,address,out,size,c.byref(got)) and got.value==size else b''
    def word(self,address):
        b=self.read(address,8);return struct.unpack('<Q',b)[0] if b else 0
    def valid(self,obj):return bool(obj and self.word(self.word(obj+8)+8)==obj)
    def name(self,obj):
        # QObjectPrivate::ExtraData::objectName; never read message or nickname fields.
        sd=self.word(self.word(self.word(obj+8)+48)+40);b=self.read(sd,24)
        if not b:return ''
        _,n,_,_,off=struct.unpack('<iiIIq',b)
        if not 0<n<128 or abs(off)>100000:return ''
        return self.read(sd+off,n*2).decode('utf-16le','replace')
    def children(self,obj):
        data=self.word(self.word(obj+8)+24);b=self.read(data,16)
        if not b:return []
        _,capacity,start,end=struct.unpack('<4i',b)
        if not 0<=start<=end<=capacity<=3000:return []
        return [self.word(data+16+8*i) for i in range(start,end)]
    def geometry(self,obj):
        d=self.word(obj+40)
        if d!=self.word(obj+8)+0x120:return None
        b=self.read(d+20,16);return struct.unpack('<4i',b) if b else None
    def locate(self):
        if not self.base:return 0
        spec=getattr(self,'spec',None) or SPECS['4.1.13.65']
        now=time.monotonic()
        if self.list and self.word(self.list)==self.base+spec['list'] and self.valid(self.list):return self.list
        if now-self.last_scan<10:return 0
        self.last_scan=now;a=self.scan_cursor;r=Region();needle=struct.pack('<Q',self.base+spec['list'])
        while self.k.VirtualQueryEx(self.handle,a,c.byref(r),c.sizeof(r)):
            start=r.base or 0;end=start+r.length
            if end<=a:break
            if r.state==0x1000 and r.kind==0x20000 and r.protect in (4,8,64,128):
                for chunk in range(max(start,a),end,2*1024*1024):
                    data=self.read(chunk,min(2*1024*1024,end-chunk));off=0
                    while True:
                        off=data.find(needle,off)
                        if off<0:break
                        obj=chunk+off
                        if obj%8==0 and self.valid(obj) and self.name(obj)=='chat_message_list':self.list=obj;return obj
                        off+=8
                    if time.monotonic()-now>4:
                        self.scan_cursor=chunk+len(data);return 0
            a=end
        self.scan_cursor=0
        return 0
    def snapshot(self):
        spec=getattr(self,'spec',None) or SPECS['4.1.13.65']
        obj=self.locate();g=self.geometry(obj) if obj else None
        if not g or g[2]<g[0]:return None
        model=self.word(obj+spec['model_field']);vt=self.word(model)
        # The extension may replace only this instance's table. Original identity methods stay intact.
        if self.word(vt)!=self.base+spec['identity'] or self.word(vt+8)!=self.base+spec['other']:return None
        vm=self.word(model+0x78)
        if self.word(vm)!=self.base+spec['viewmodel']:return None
        start,end=self.word(vm+0x88),self.word(vm+0x90)
        if not start or not start<=end<=start+3000*16:return None
        items={self.word(start+i*16) for i in range((end-start)//16)};rows=[]
        for viewport in self.children(obj):
            for row in self.children(viewport):
                item=self.word(row+0x250);vtable=self.word(row)
                if not item or item not in items or self.word(item)!=self.base+spec['item'] or self.word(vtable)!=self.base+spec['row_meta'] or not self.valid(row):continue
                rect=self.geometry(row);m=self.read(self.word(row+8)+0x108,8)
                if rect and m and rect[0]>=0:
                    padding=struct.unpack('<4h',m)[3];value=dict(item=item,top=rect[1],bottom=rect[3]+1,padding=max(0,padding))
                    content=[self.geometry(child) for child in self.children(row) if self.name(child) in ('avatar_container','outer_content_vbox')]
                    content=[r for r in content if r and 0<=r[1]<=r[3]<rect[3]-rect[1]+1]
                    if len(content)==2:value.update(content_top=rect[1]+min(r[1] for r in content),content_bottom=rect[1]+max(r[3]+1 for r in content))
                    rows.append(value)
        return dict(list=obj,model=model,items=items,last_item=self.word(end-16) if end>start else 0,rows=rows,width=g[2]-g[0]+1)
