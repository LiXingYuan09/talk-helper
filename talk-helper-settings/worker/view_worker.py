"""Selected chats, one independent result per verified incoming text message."""
import argparse,ctypes as c,os,queue,re,sys,tempfile,threading,time
from pathlib import Path
from collections import OrderedDict
from dataclasses import replace
from ctypes import wintypes as w
from main import load_settings,install_network_guard,analyze,safe_error,message_body,RuntimeStatus,normalized
from model import AdviceState,Snapshot
from ipc import NativePanel
from direct_data import ConversationDB
from selection import ChatSelection
from native_rows import NativeRows,pair_rows
from helper_settings import HelperSettings
from chat_time import timestamp,time_label,time_details
from card_format import compact_analysis,card_header

PENDING_PADDING=142
ANALYSIS_PADDING=294

def eligible(record):
    return record.get('type')=='文本' and bool(str(record.get('content') or '').strip()) and not re.search(r'(?i)(?:https?://|www\.|weixin://|wx://|mp://)',str(record.get('content') or ''))

def intersects(a,b):return a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]

def chat_title(name,chat_input):
    return ((name.Name if name else '') or (chat_input.Name if chat_input else '') or '').strip()

def outgoing(record):return bool(record.get('is_self',record.get('sender_id')==2))

def correct_tail_row(chat,native,records):
    """Qt's final accessible row can include a displaced timestamp rectangle.

    Only correct the native model's last text item, after the database's newest
    incoming text and the final accessible row agree. Measure visible content
    from the original avatar/text containers, rather than an estimated offset.
    """
    visible=chat.get('alignment_rows',[])
    if not native or not records or not visible:return
    latest=records[0];row=visible[-1]
    if not eligible(latest) or outgoing(latest) or normalized(row['text'])!=normalized(message_body(latest,chat['username'].endswith('@chatroom'))):return
    candidates=[r for r in native['rows'] if r['item']==native.get('last_item') and 'content_bottom' in r]
    if len(candidates)!=1:return
    bound=candidates[0];area=chat['area'];scale=(area[2]-area[0])/native['width']
    if not .5<=scale<=3:return
    top=round(area[1]+bound['top']*scale);bottom=round(area[1]+bound['bottom']*scale)
    old=row['rect'];delta=old[1]-top
    if abs((old[3]-bottom)-delta)>3 or abs(delta)>max(0,bound['bottom']-bound['top']-bound['padding'])*scale:return
    content_top=area[1]+bound['content_top']*scale;content_bottom=area[1]+bound['content_bottom']*scale
    if content_top<area[1] or content_bottom>area[3]+1:return
    corrected=dict(row,rect=(old[0],top,old[2],bottom),fully_visible=True)
    chat['alignment_rows'][-1]=corrected
    chat['rows']=[r for r in chat['rows'] if r is not row]+[corrected]
    chat['rows'].sort(key=lambda r:r['rect'][3])
    chat['occupied']=[corrected['rect'] if r==old else r for r in chat['occupied']]

def placement(chat,anchor):
    """Stay directly below the verified incoming row; never use an unrelated gap."""
    area=chat['area'];scale=chat['scale'];width=round(304*scale);pad=round(8*scale)
    bound=chat.get('native_rows',{}).get(tuple(anchor));reserved=bound.get('padding',0) if bound else 0
    height=round((252 if reserved>=ANALYSIS_PADDING else 101)*scale)
    occupied=[r for r in chat['occupied'] if not (reserved and tuple(r)==tuple(anchor))]
    if area[2]-area[0]>=width+pad*2:
        # This host's UIA row may include the avatar and full-width whitespace.
        # For such rows use the text column measured on the version-guarded host.
        column=area[0]+round(68*scale) if anchor[2]-anchor[0]>=.8*(area[2]-area[0]) else anchor[0]
        x=max(area[0]+pad,column);y=anchor[3]-reserved+round(6*scale)
        rect=(x,y,x+width,y+height)
        if rect[1]>=max(anchor[1],area[1]) and rect[2]<=area[2]-pad and rect[3]<=area[3]-pad and (not reserved or rect[3]<=anchor[3]) and not any(intersects(rect,r) for r in occupied):return rect,False
    return None,False

class ChatRegion:
    def __init__(self,parent):
        import uiautomation as auto
        self.auto=auto;self.parent=parent;auto.InitializeUIAutomationInCurrentThread();auto.SetGlobalSearchTimeout(1)
        self.u=c.WinDLL('user32');self.u.ClientToScreen.argtypes=[w.HWND,c.POINTER(w.POINT)]
        self.u.GetClientRect.argtypes=[w.HWND,c.POINTER(w.RECT)];self.u.GetDpiForWindow.argtypes=[w.HWND];self.u.GetDpiForWindow.restype=w.UINT
    def scan(self):
        root=self.auto.ControlFromHandle(self.parent);todo=[(root,0)];lst=name=left=right=chat_input=None;seen=0
        while todo and seen<1200:
            node,depth=todo.pop();seen+=1
            try:
                aid=node.AutomationId or ''
                if aid.endswith('chat_message_list'):lst=node
                elif aid.endswith('chat_input_field'):chat_input=node
                elif aid.endswith('current_chat_name_label'):name=node
                elif aid.endswith('chatinput_toolbar_left_view'):left=node
                elif aid.endswith('chatinput_toolbar_right_view'):right=node
                if depth<32:todo.extend((child,depth+1) for child in node.GetChildren())
            except Exception:pass
        title=chat_title(name,chat_input)
        if not lst or not title:return None
        origin=w.POINT();client=w.RECT()
        if not self.u.ClientToScreen(self.parent,c.byref(origin)) or not self.u.GetClientRect(self.parent,c.byref(client)):return None
        def rect(node):
            r=node.BoundingRectangle
            return (max(0,r.left-origin.x),max(0,r.top-origin.y),min(client.right,r.right-origin.x),min(client.bottom,r.bottom-origin.y))
        area=rect(lst);occupied=[];rows=[];alignment_rows=[];gap=None
        for node in lst.GetChildren():
            try:
                r=rect(node)
                if r[2]<=r[0] or r[3]<=r[1] or not intersects(r,area):continue
                occupied.append(r)
                if 'chat_bubble_item_view' in (node.AutomationId or ''):
                    row={'text':(node.Name or '').strip(),'rect':r,'fully_visible':r[1]>=area[1] and r[3]<=area[3]}
                    alignment_rows.append(row)
                    if row['fully_visible']:rows.append(row)
            except Exception:pass
        if left and right:
            def buttons(root):
                todo=[(root,0)];found=[]
                while todo:
                    item,depth=todo.pop()
                    try:
                        if item.ControlTypeName=='ButtonControl':
                            r=rect(item)
                            if r[2]>r[0] and r[3]>r[1]:found.append(r)
                        if depth<10:todo.extend((child,depth+1) for child in item.GetChildren())
                    except Exception:pass
                return found
            a,b=rect(left),rect(right);lb,rb=buttons(left),buttons(right)
            gap=(max(r[2] for r in lb)+8,max(a[1],b[1]),min(r[0] for r in rb)-8,min(a[3],b[3])) if lb and rb else None
        return {'title':title,'area':area,'rows':sorted(rows,key=lambda r:r['rect'][3]),'alignment_rows':sorted(alignment_rows,key=lambda r:r['rect'][3]),
                'occupied':occupied,'toolbar_gap':gap,'scale':(self.u.GetDpiForWindow(self.parent) or 96)/96}

def verified_messages(chat,records,context_n=12):
    """Unique ordered text alignment also disambiguates repeated adjacent words."""
    group=chat['username'].endswith('@chatroom');ordered=list(reversed(records));pairs=[]
    for row in chat.get('alignment_rows',chat['rows']):
        candidates=[i for i,r in enumerate(ordered) if eligible(r) and normalized(row['text'])==normalized(message_body(r,group))]
        if candidates:pairs.append((row,candidates))
    if not pairs:return []
    forward=[];previous=None
    for row,candidates in pairs:
        possible={i for i in candidates if previous is None or any(j<i for j in previous)}
        forward.append(possible);previous=possible
    backward=[None]*len(pairs);following=None
    for pos in range(len(pairs)-1,-1,-1):
        possible={i for i in pairs[pos][1] if following is None or any(j>i for j in following)}
        backward[pos]=possible;following=possible
    result=[]
    for pos,(row,_) in enumerate(pairs):
        if not row.get('fully_visible',True):continue
        possible=forward[pos]&backward[pos]
        if len(possible)!=1:continue
        index=next(iter(possible));record=ordered[index]
        if outgoing(record):continue
        context=ordered[max(0,index-context_n+1):index+1]
        messages=tuple(('me' if outgoing(r) else 'her',message_body(r,group),r.get('sender_username') or None) for r in context if eligible(r))
        times=tuple(timestamp(r.get('create_time')) for r in context if eligible(r))
        if not messages:continue
        key=f"{chat['username']}:{record.get('sort_seq')}:{record.get('local_id')}"
        result.append((key,Snapshot(chat['title'],messages,row['rect'],chat['area'],len(messages)-1,times),message_body(record,group)))
    return result

class MessagePool:
    def __init__(self):self.states=OrderedDict();self.ids={};self.sources={};self.next_id=1;self.active=[];self.paused=False;self.pending=None;self.retry=set()
    def synchronize(self,items):
        present={key for key,_,_ in items}
        for key,state in self.states.items():
            if key not in present:state.changing()
        self.active=[]
        for key,snapshot,text in items[:80]:
            if key not in self.states:
                self.states[key]=AdviceState();self.ids[key]=self.next_id;self.next_id+=1
            state=self.states[key];state.paused=self.paused
            if state.snapshot and self.sources.get(key)==text and (not snapshot.timestamps or state.snapshot.timestamps[-1:]==snapshot.timestamps[-1:]) and (state.cache or state.pending_key or state.attempted):
                snapshot=replace(state.snapshot,anchor=snapshot.anchor,area=snapshot.area)
            state.observe(snapshot);self.sources[key]=text
            self.states.move_to_end(key);self.active.append(key)
        while len(self.states)>500:
            expired=next(iter(self.states))
            if self.pending and expired==self.pending[0]:break
            self.states.pop(expired);self.ids.pop(expired,None);self.sources.pop(expired,None)
    def request(self,enabled):
        if not enabled or self.paused or self.pending:return None
        for key in reversed(self.active):
            state=self.states[key];request=state.request(force=key in self.retry)
            if request:
                self.retry.discard(key);identity,snapshot=request;self.pending=(key,identity);return key,identity,snapshot
        return None
    def complete(self,key,identity,result,error):
        if self.pending!=(key,identity):return False
        self.pending=None;state=self.states.get(key)
        if state:state.complete(identity,result,error)
        return bool(result)
    def command(self,card_id,code):
        if code==4:
            self.paused=not self.paused
            for state in self.states.values():state.paused=self.paused
            return
        key=next((key for key,id in self.ids.items() if id==card_id),None)
        if key and key in self.active:
            if code==1:self.retry.add(key)
            elif code==2:self.states[key].next_candidate()

def restore_bound_messages(chat,native,targets,pool,records,verified):
    """A previously verified model item stays known while its widget is clipped.

    Match both the pinned native item and the original database message key/body;
    never guess a new identity from repeated text in a partially visible row.
    """
    if not native:return verified
    result=list(verified);present={key for key,_,_ in verified};keys={id:key for key,id in pool.ids.items()}
    known={f"{chat['username']}:{r.get('sort_seq')}:{r.get('local_id')}":r for r in records if eligible(r) and not outgoing(r)}
    area=chat['area'];scale=(area[2]-area[0])/native['width']
    if not .5<=scale<=3:return result
    for item,(id,_) in targets.items():
        key=keys.get(id);record=known.get(key);state=pool.states.get(key)
        if not key or key in present or not state or not state.snapshot or not record:continue
        if pool.sources.get(key)!=message_body(record,chat['username'].endswith('@chatroom')):continue
        rows=[r for r in native['rows'] if r['item']==item]
        if len(rows)!=1:continue
        row=rows[0];rect=(area[0],round(area[1]+row['top']*scale),area[2],round(area[1]+row['bottom']*scale))
        if not intersects(rect,area):continue
        chat['native_rows'][rect]={'item':item,'padding':round(row['padding']*scale)}
        result.append((key,replace(state.snapshot,anchor=rect,area=area),pool.sources[key]));present.add(key)
    return sorted(result,key=lambda value:value[1].anchor[3])

def card_payload(chat,pool,key):
    state=pool.states[key];source=pool.sources[key]
    status='等待生成这条建议…';body='对应消息：'+source;tension=-1
    timing=state.result.get('timing') if state.result else None
    body=time_details(state.snapshot,timing)+'\r\n\r\n'+body
    if state.paused:status='分析已暂停'
    elif state.result:
        result=state.result;g=result['guidance'];tension=round(result['answers']['danger_level']['score']);status=compact_analysis(result)
        body+='\r\n\r\n理解：'+g['summary']+'\r\n\r\n可以这样做：\r\n'+'\r\n'.join(f'{i}. {a}' for i,a in enumerate(g['actions'],1))
        if not result.get('do_not_send'):body+='\r\n\r\n可回复：\r\n'+state.reply
        body+='\r\n\r\n注意：'+g['avoid']
    elif state.pending_key:status='DeepSeek 正在生成这条建议…'
    elif state.visible_key in state.errors:status=state.errors[state.visible_key]
    label=time_label(state.snapshot)
    if label and not state.result:status=label+' · '+status
    # Only content crosses this IPC. Current geometry and viewport clipping are
    # owned by the native item binding, including partially visible rows.
    return dict(card_id=pool.ids[key],title=source,anchor=None,area=chat['area'],status=status,body=body,reply=state.reply,tension=tension,paused=pool.paused)

def control_payload(chat,enabled,pool,choice_id=0,assistant_name='talk helper'):
    area=(chat or {}).get('area');gap=(chat or {}).get('toolbar_gap');anchor=None
    if gap and area and gap[2]-gap[0]>=160*chat['scale'] and gap[3]-gap[1]>=25*chat['scale']:
        anchor=(gap[0],gap[1],min(gap[2],gap[0]+round(320*chat['scale'])),gap[3])
    done=sum(bool(pool.states[key].result) for key in pool.active)
    label=f'{assistant_name} · 选择聊天 · {done}/{len(pool.active)}条建议' if enabled else f'{assistant_name} · 选择聊天（未启用）'
    if chat and not choice_id:label=f'{assistant_name} · 正在核对聊天身份'
    return dict(card_id=0,title=chat['title'] if chat else '',anchor=anchor,area=area,compact=True,control=True,enabled=enabled,paused=pool.paused,status=label,reply=str(choice_id) if choice_id else '',assistant_name=assistant_name)

def read_selected(db,title,selected):
    username=db.resolve_chat(title)
    return username,db.get_messages(username,150) if username and username in selected else []

def ensure_chat_directory(directory,username,title,selected):
    if not username or any(item['username']==username for item in directory):return False
    next_id=max((item['id'] for item in directory),default=0)+1
    if next_id>1000000:return False
    if len(directory)>=3000:
        removable=next((item for item in reversed(directory) if item['username'] not in selected),None)
        if not removable:return False
        directory.remove(removable)
    directory.append(dict(id=next_id,username=username,name=title,group=username.endswith('@chatroom')))
    return True

def run(args):
    c.WinDLL('user32').SetProcessDpiAwarenessContext(c.c_void_p(-4));install_network_guard();settings=load_settings(args.config)
    preferences=HelperSettings(args.config,settings);account=''
    panel=NativePanel(args.parent,args.panel,args.parent_pid,args.token);status=RuntimeStatus(args.config)
    status.update(worker_revision='analysis-card-13r2-v1',layout='original-wechat',media_analyzed=False,per_message=True,selection_required=True,time_source='wechat-create_time',time_aware=True)
    ui=ChatRegion(args.parent);native=NativeRows(args.parent_pid);layout_targets={};pool=MessagePool();queries=queue.Queue();results=queue.Queue();completed=queue.Queue();stop=threading.Event()
    def db_work():
        with tempfile.TemporaryDirectory(prefix='talk-helper-selected-') as temp:
            try:
                db=ConversationDB(wechat_pid=args.parent_pid,workdir=temp,keys_file=os.path.join(temp,'no-key-cache.json'))
                results.put(('ready',0,(db.wxid,db.chat_directory(),len(db._keys),len(db._db_files))))
            except Exception:results.put(('failed',0,None));return
            while not stop.is_set():
                try:epoch,title,selected=queries.get(timeout=.25)
                except queue.Empty:continue
                try:
                    results.put(('records',epoch,read_selected(db,title,selected)))
                except Exception:results.put(('records',epoch,(None,[])))
    threading.Thread(target=db_work,name='talk-helper-local-data').start()
    chat=None;records=[];username=None;epoch=0;ready=False;pending=False;last_query=0;selection=None;directory=[];old_ids=set();directory_dirty=False
    try:
        while panel.alive():
            try:current=ui.scan() if not panel.minimized() else None
            except Exception:current=None
            # Losing a slow accessibility snapshot is not a chat switch. Native
            # positioning continues independently and validates current row IDs.
            if current is None:time.sleep(.35);continue
            if (current or {}).get('title')!=(chat or {}).get('title'):
                epoch+=1;records=[];username=None;pool.synchronize([]);last_query=0;layout_targets.clear()
            chat=current
            while not results.empty():
                kind,token,value=results.get_nowait()
                if kind=='ready':
                    account,directory,key_count,db_count=value;selection=ChatSelection(Path(args.config).with_name('chat-selection.json'),account);ready=True;directory_dirty=True
                    for i,item in enumerate(directory,1):item['id']=i
                    status.update(stage='db_ready',key_count=key_count,db_count=db_count,directory_count=len(directory))
                elif kind=='failed':status.update(stage='db_failed')
                else:
                    pending=False
                    if token==epoch and chat:username,records=value
            command=panel.poll()
            if command:
                code=command&15;card_id=command>>4
                if code in (5,6):
                    scope=card_id;key='';error='';saved=False
                    try:
                        if code==6:
                            values,scope,key=panel.settings_draft(native)
                            item=next((entry for entry in directory if entry['id']==scope),None)
                            if scope and not item:raise ValueError('无法核对该聊天，请重新打开设置。')
                            preferences.apply(values,account,item['username'] if item else '',key);saved=True
                            pool.pending=None
                            for state in pool.states.values():
                                state.cache.clear();state.attempted.clear();state.errors.clear();state.pending_key=None
                        item=next((entry for entry in directory if entry['id']==scope),None)
                        if scope and not item:raise ValueError('无法核对该聊天，请重新打开设置。')
                    except ValueError as exc:error=str(exc)
                    except Exception:error='设置保存失败，请重试。'
                    finally:key=''
                    item=next((entry for entry in directory if entry['id']==scope),None)
                    values=preferences.values(account,item['username'] if item else '')
                    panel.settings(values,scope,key_present=bool(preferences.key),status=error or ('已保存；新的建议使用这些设置。' if saved else '身份与风格可只用于当前聊天；接口与助手名称始终共用。'),error=bool(error))
                elif code==8:
                    item=next((entry for entry in directory if entry['id']==card_id),None)
                    if selection and item:
                        selection.set(item['username'],item['name'],not selection.enabled(item['username']));directory_dirty=True
                        if username==item['username']:epoch+=1;records=[];pool.synchronize([]);last_query=0
                else:pool.command(card_id,code)
            for _ in range(64):
                choice=panel.choices()
                if not choice:break
                id,enabled=choice>>1,bool(choice&1);item=next((entry for entry in directory if entry['id']==id),None)
                if selection and item:
                    selection.set(item['username'],item['name'],enabled);directory_dirty=True
                    if username==item['username']:epoch+=1;records=[];pool.synchronize([]);last_query=0
            enabled=bool(selection and selection.enabled(username))
            if username and chat and ensure_chat_directory(directory,username,chat['title'],selection.selected if selection else {}):directory_dirty=True
            if directory_dirty:
                panel.directory([dict(id=item['id'],name=item['name'],group=item['group'],enabled=selection.enabled(item['username'])) for item in directory]);directory_dirty=False
            if chat and username and enabled:
                current_settings=preferences.snapshot(account,username)
                chat['username']=username
                try:structure=native.snapshot()
                except Exception:structure=None
                correct_tail_row(chat,structure,records)
                chat['native_rows']=pair_rows(chat,structure) if structure else {}
                identified=verified_messages(chat,records,current_settings.context())
                pool.synchronize(restore_bound_messages(chat,structure,layout_targets,pool,records,identified))
                if structure:
                    layout_targets={item:value for item,value in layout_targets.items() if item in structure['items']}
                    for key in pool.active:
                        bound=chat['native_rows'].get(tuple(pool.states[key].snapshot.anchor))
                        if bound:layout_targets[bound['item']]=(pool.ids[key],ANALYSIS_PADDING if pool.states[key].result else PENDING_PADDING)
            else:pool.synchronize([]);layout_targets.clear();structure=None
            while not completed.empty():
                key,identity,result,error,revision=completed.get_nowait()
                if revision!=preferences.revision:continue
                if pool.complete(key,identity,result,error):status.update(api_ok=status.values['api_ok']+1)
            now=time.monotonic()
            if ready and chat and not pending and now-last_query>=3:
                queries.put((epoch,chat['title'],set(selection.selected)));pending=True;last_query=now
            request=pool.request(enabled)
            if request:
                key,identity,snapshot=request
                def work(key=key,identity=identity,snapshot=snapshot,view=current_settings,revision=preferences.revision):
                    try:completed.put((key,identity,analyze(view,snapshot),None,revision))
                    except Exception as e:completed.put((key,identity,None,safe_error(e),revision))
                threading.Thread(target=work,daemon=True).start()
            choice_id=next((item['id'] for item in directory if item['username']==username),0)
            assistant_name=preferences.values()['assistant_name']
            accepted=panel.update(**control_payload(chat,enabled,pool,choice_id,assistant_name));ids={pool.ids[key] for key in pool.active};inline=0
            layout_ok,layout_changed=panel.layout(structure['list'],layout_targets) if structure else (True,False) if enabled else panel.layout(0,{})
            for id in old_ids-ids:panel.update(card_id=id,title='',anchor=None,area=None)
            for key in pool.active:
                data=card_payload(chat,pool,key)
                data['assistant_name']=card_header(assistant_name,time_label(pool.states[key].snapshot))
                if layout_changed:data['anchor']=None
                accepted=panel.update(**data) and accepted;inline+=bool(data['anchor'])
            old_ids=ids
            follow=panel.following(native);inline=follow.get('native_visible_cards',inline)
            status.update(**follow)
            status.update(stage='selected_text' if enabled and pool.active else 'selected_waiting_text' if enabled else 'chat_not_selected',
                          chat_enabled=enabled,selected_chat_count=len(selection.selected) if selection else 0,
                          visible_incoming_texts=len(pool.active),inline_cards=inline,generated_advice=sum(bool(pool.states[key].result) for key in pool.active),native_packet_accepted=accepted,
                          native_reflow_accepted=layout_ok,reserved_messages=len(layout_targets),
                          native_module_found=bool(native.base),native_list_found=bool(native.list),
                          native_rows=len(structure['rows']) if structure else 0,
                          matched_native_rows=len((chat or {}).get('native_rows',{})),
                          row_geometry=[r['rect'][1::2] for r in (chat or {}).get('rows',[])],
                          native_geometry=[(r['top'],r['bottom']) for r in structure['rows']] if structure else [],
                          list_geometry=(chat or {}).get('area'),
                          time_recognized_messages=sum(bool(pool.states[key].snapshot.timestamps and pool.states[key].snapshot.timestamps[-1] is not None) for key in pool.active))
            time.sleep(.35)
    except Exception as exc:
        import traceback
        frame=traceback.extract_tb(exc.__traceback__)[-1]
        status.last=0;status.update(worker_error_type=type(exc).__name__,worker_error_site=f'{Path(frame.filename).name}:{frame.lineno}')
    finally:stop.set();panel.layout(0,{});native.close();status.last=0;status.update(stage='worker_error' if 'worker_error_type' in status.values else 'stopped')
    return 0

if __name__=='__main__':
    if '--self-test' in sys.argv:
        from core.engine import analyze as probe
        result=probe([('her','请不要再联系我了')],'朋友')
        raise SystemExit(0 if result.get('do_not_send') and not result['best_reply'] else 1)
    parser=argparse.ArgumentParser()
    for name in ('parent','panel','parent-pid','token'):parser.add_argument('--'+name,type=int,required=True)
    parser.add_argument('--config',required=True);raise SystemExit(run(parser.parse_args()))
