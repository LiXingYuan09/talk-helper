import unittest,ctypes,tempfile
from pathlib import Path
from unittest.mock import Mock
from view_worker import eligible,placement,intersects,verified_messages,MessagePool,read_selected,control_payload,correct_tail_row,restore_bound_messages,card_payload
from ipc import Packet,make_packet,DirectoryHeader,DirectoryEntry
from model import official_base,Snapshot
from selection import ChatSelection
from native_rows import pair_rows,NativeRows,LIST
from ipc import LayoutHeader,LayoutEntry

def record(text,id,sender=7,kind='文本'):
    return {'type':kind,'content':text,'sender_id':sender,'local_id':id,'sort_seq':id}
def chat(rows):
    return {'title':'测试','username':'person','area':(300,90,1200,600),'scale':1,'occupied':[], 'rows':[{'text':t,'rect':(368,100+i*50,500,130+i*50)} for i,t in enumerate(rows)],'toolbar_gap':(650,720,1100,750)}
class SelectedTests(unittest.TestCase):
    def test_clipped_card_never_sends_negative_or_stale_worker_coordinates(self):
        pool=MessagePool();items=verified_messages(chat(['你好']),[record('你好',1)]);pool.synchronize(items)
        key=pool.active[0];value=chat([]);value['native_rows']={}
        for anchor in ((300,-120,1200,100),(300,500,1200,740)):
            pool.states[key].observe(Snapshot('测试',items[0][1].messages,anchor,value['area'],0))
            value['native_rows']={anchor:{'item':123,'padding':142}}
            data=card_payload(value,pool,key)
            self.assertIsNone(data['anchor']);self.assertEqual(data['title'],'你好')
            self.assertFalse(make_packet(1,1,**data).flags&1)
        value['native_rows']={(300,-120,1200,100):{'item':123,'padding':142}}
        self.assertIsNone(placement(value,(300,-120,1200,100))[0])
    def test_scroll_retains_result_context_and_chosen_reply(self):
        pool=MessagePool();items=verified_messages(chat(['你好']),[record('你好',1)]);pool.synchronize(items)
        key,identity,_=pool.request(True);pool.complete(key,identity,{'candidates':['A','B'],'best_index':0},None)
        pool.command(pool.ids[key],2);pool.synchronize([])
        self.assertIn(identity,pool.states[key].cache)
        moved=Snapshot('测试',(('her','上下文变短',None),('her','你好',None)),(300,200,1200,500),(300,90,1200,600),1)
        pool.synchronize([(key,moved,'你好')])
        self.assertEqual(pool.states[key].snapshot.identity,identity)
        self.assertEqual(pool.states[key].snapshot.anchor,moved.anchor)
        self.assertEqual(pool.states[key].reply,'B');self.assertIsNone(pool.request(True))
    def test_known_repeated_row_restores_when_partial_or_ambiguous(self):
        records=[record('在吗',2),record('在吗',1)];pool=MessagePool()
        pool.synchronize(verified_messages(chat(['在吗','在吗']),records))
        key=pool.active[1];targets={123:(pool.ids[key],142)}
        value=chat([]);value['native_rows']={}
        native={'width':900,'rows':[dict(item=123,top=410,bottom=650,padding=142)]}
        pool.synchronize([])
        restored=restore_bound_messages(value,native,targets,pool,records,[])
        self.assertEqual([v[0] for v in restored],[key]);self.assertEqual(restored[0][1].anchor,(300,500,1200,740))
        pool.synchronize(restored);self.assertEqual(pool.active,[key])
    def test_binding_does_not_attach_to_recycled_or_changed_message(self):
        records=[record('你好',1)];pool=MessagePool();pool.synchronize(verified_messages(chat(['你好']),records))
        key=pool.active[0];targets={123:(pool.ids[key],142)};value=chat([]);value['native_rows']={}
        native={'width':900,'rows':[dict(item=456,top=10,bottom=240,padding=142)]}
        self.assertEqual(restore_bound_messages(value,native,targets,pool,records,[]),[])
        native['rows'][0]['item']=123
        self.assertEqual(restore_bound_messages(value,native,targets,pool,[record('换了文字',1)],[]),[])
        self.assertEqual(restore_bound_messages(value,native,targets,pool,[record('你好',1,2)],[]),[])
        native['rows'].append(dict(native['rows'][0]));self.assertEqual(restore_bound_messages(value,native,targets,pool,records,[]),[])
    def test_native_scan_skips_null_base_free_region(self):
        reader=NativeRows.__new__(NativeRows)
        reader.base=0x100000;reader.list=0;reader.last_scan=0;reader.scan_cursor=0;reader.handle=1
        def query(handle,address,out,size):
            region=out._obj
            if address==0:region.base=None;region.length=0x1000;region.state=0x10000;return size
            if address==0x1000:
                region.base=0x1000;region.length=8;region.state=0x1000;region.kind=0x20000;region.protect=4;return size
            return 0
        reader.k=Mock();reader.k.VirtualQueryEx.side_effect=query
        reader.read=lambda a,n:(reader.base+LIST).to_bytes(8,'little')
        reader.valid=lambda a:a==0x1000;reader.name=lambda a:'chat_message_list'
        self.assertEqual(reader.locate(),0x1000)
    def test_native_layout_ipc_sizes(self):
        self.assertEqual(ctypes.sizeof(LayoutHeader),36);self.assertEqual(ctypes.sizeof(LayoutEntry),20)
    def test_native_binding_requires_unique_geometry(self):
        value=chat(['你好']);value['rows'][0]['rect']=(368,100,500,130)
        native={'width':900,'rows':[{'item':123,'top':10,'bottom':40,'padding':0}]}
        self.assertEqual(pair_rows(value,native)[(368,100,500,130)]['item'],123)
        native['rows'].append(dict(native['rows'][0],item=456));self.assertEqual(pair_rows(value,native),{})
    def test_dense_row_uses_only_its_reserved_space(self):
        value=chat(['你好']);anchor=(300,100,1200,319)
        next_row=(300,319,1200,396);value['occupied']=[anchor,next_row]
        value['native_rows']={anchor:{'item':1,'padding':142}}
        rect,_=placement(value,anchor);self.assertEqual(rect,(368,183,672,284))
        self.assertFalse(intersects(rect,next_row));self.assertLess(rect[3],anchor[3])
        value['native_rows']={};self.assertIsNone(placement(value,anchor)[0])
    def test_reserved_card_cannot_cover_another_native_row(self):
        value=chat(['你好']);anchor=(300,100,1200,319)
        value['native_rows']={anchor:{'item':1,'padding':142}}
        value['occupied']=[anchor,(300,190,1200,240)]
        self.assertIsNone(placement(value,anchor)[0])
    def test_only_plain_text_is_eligible(self):
        for kind in ['图片','视频','小程序','文件/链接/卡片','语音','动画表情']:self.assertFalse(eligible(record('secret',1,kind=kind)))
        for text in ['https://example.test','www.example.test','mp://id','wx://id']:self.assertFalse(eligible(record(text,1)))
        self.assertTrue(eligible(record('几点见面？',1)))
    def test_each_incoming_has_own_identity_and_outgoing_never_gets_card(self):
        items=verified_messages(chat(['你好','我知道','几点见面？']),[record('几点见面？',3),record('我知道',2,2),record('你好',1)])
        self.assertEqual([x[0] for x in items],['person:1:1','person:3:3'])
        self.assertEqual([x[2] for x in items],['你好','几点见面？'])
        self.assertNotIn('几点见面？',str(items[0][1].messages))
    def test_order_disambiguates_repeated_words(self):
        items=verified_messages(chat(['好的','好的']),[record('好的',2),record('好的',1)])
        self.assertEqual(len(items),2);self.assertNotEqual(items[0][0],items[1][0])
        self.assertEqual(verified_messages(chat(['好的']),[record('好的',2),record('好的',1)]),[])
    def test_partial_neighbor_disambiguates_without_generating_for_partial_row(self):
        value=chat(['在吗','在吗']);first,last=value['rows']
        first['fully_visible']=True;last['fully_visible']=False
        value['alignment_rows']=[first,last];value['rows']=[first]
        records=[record('在吗',2),record('在吗',1)]
        items=verified_messages(value,records)
        self.assertEqual([item[0] for item in items],['person:1:1'])
        self.assertEqual(items[0][1].messages,(('her','在吗',None),))
        first['fully_visible']=False
        self.assertEqual(verified_messages(value,records),[])
    def test_latest_tail_uses_measured_content_when_accessible_bounds_are_displaced(self):
        value=chat(['在吗']);row=value['rows'][0];row.update(rect=(368,560,1200,640),fully_visible=False)
        value['alignment_rows']=[row];value['rows']=[];value['occupied']=[row['rect']]
        native={'width':900,'last_item':123,'rows':[dict(item=123,top=430,bottom=510,padding=0,content_top=436,content_bottom=478)]}
        correct_tail_row(value,native,[record('在吗',2)])
        self.assertEqual(value['rows'][0]['rect'],(368,520,1200,600))
        self.assertEqual(pair_rows(value,native)[(368,520,1200,600)]['item'],123)
        self.assertEqual(len(verified_messages(value,[record('在吗',2)])),1)
    def test_tail_correction_rejects_wrong_identity_outgoing_or_clipped_content(self):
        for change in ('identity','outgoing','content'):
            value=chat(['在吗']);row=value['rows'][0];row.update(rect=(368,560,1200,640),fully_visible=False)
            value['alignment_rows']=[row];value['rows']=[];value['occupied']=[row['rect']]
            native={'width':900,'last_item':123,'rows':[dict(item=123,top=430,bottom=510,padding=0,content_top=436,content_bottom=478)]}
            latest=record('在吗',2)
            if change=='identity':native['last_item']=456
            elif change=='outgoing':latest['sender_id']=2
            else:native['rows'][0]['content_bottom']=530
            correct_tail_row(value,native,[latest]);self.assertEqual(value['rows'],[])
    def test_media_and_urls_are_not_in_context(self):
        items=verified_messages(chat(['几点见面？']),[record('几点见面？',3),record('https://secret.test',2),record('secret',1,kind='小程序')])
        self.assertEqual([m[1] for m in items[0][1].messages],['几点见面？'])
    def test_selection_is_fail_closed_and_account_specific(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'selection.json';s=ChatSelection(p,'account-A');self.assertFalse(s.enabled('person'))
            s.set('person','同名',True);s.set('group@chatroom','同名',True)
            self.assertTrue(ChatSelection(p,'account-A').enabled('group@chatroom'))
            self.assertFalse(ChatSelection(p,'account-B').enabled('person'))
            s.set('person','同名',False);self.assertFalse(s.enabled('person'));self.assertTrue(s.enabled('group@chatroom'))
    def test_deselected_chat_does_not_read_messages(self):
        db=Mock();db.resolve_chat.return_value='person';db.get_messages.return_value=['text']
        self.assertEqual(read_selected(db,'名字',set()),('person',[]));db.get_messages.assert_not_called()
        self.assertEqual(read_selected(db,'名字',{'person'}),('person',['text']))
    def test_request_gate_stops_deselected_or_paused_network_work(self):
        pool=MessagePool();pool.synchronize(verified_messages(chat(['你好']),[record('你好',1)]))
        self.assertIsNone(pool.request(False));self.assertIsNone(pool.pending)
        pool.paused=True;self.assertIsNone(pool.request(True));pool.paused=False;self.assertIsNotNone(pool.request(True))
        self.assertIsNone(pool.request(True))
    def test_results_and_candidate_selection_do_not_leak_between_messages(self):
        pool=MessagePool();pool.synchronize(verified_messages(chat(['你好','几点见面？']),[record('几点见面？',2),record('你好',1)]))
        key,identity,snapshot=pool.request(True);result={'candidates':['回复A','回复B'],'best_index':0};pool.complete(key,identity,result,None)
        pool.command(pool.ids[key],2);self.assertEqual(pool.states[key].reply,'回复B')
        other=next(k for k in pool.active if k!=key);self.assertIsNone(pool.states[other].result)
        self.assertNotEqual(pool.ids[key],pool.ids[other]);self.assertIsNotNone(pool.request(True))
    def test_card_stays_below_own_message_and_never_uses_another_gap(self):
        c=chat([]);c['occupied']=[(300,100,1200,160),(300,165,1200,220)]
        self.assertEqual(placement(c,(368,100,500,160)),(None,False))
        c['occupied']=[(300,100,1200,160)];rect,_=placement(c,(368,100,500,160));self.assertEqual(rect[:2],(368,166))
        self.assertTrue(all(not intersects(rect,r) for r in c['occupied']))
    def test_high_dpi_text_column(self):
        c=chat([]);c.update(area=(450,135,1800,1050),scale=1.5,occupied=[(450,150,1800,225)])
        self.assertEqual(placement(c,(450,150,1800,225)),((552,234,1008,386),False))
    def test_no_messages_or_media_in_directory_protocol(self):
        self.assertEqual(ctypes.sizeof(Packet),10152);self.assertEqual(ctypes.sizeof(DirectoryHeader),28);self.assertEqual(ctypes.sizeof(DirectoryEntry),268)
        self.assertNotIn('avatar',dict(Packet._fields_));self.assertNotIn('content',dict(DirectoryEntry._fields_))
        p=make_packet(1,1,card_id=27);self.assertEqual(p.card_id,27)
    def test_controller_is_marked_and_deselected(self):
        p=make_packet(1,1,**control_payload(chat([]),False,MessagePool()))
        self.assertTrue(p.flags&64);self.assertFalse(p.flags&128)
    def test_official_api_only(self):
        self.assertEqual(official_base('https://api.deepseek.com/v1'),'https://api.deepseek.com/v1')
        with self.assertRaises(ValueError):official_base('https://openrouter.ai/api/v1')
if __name__=='__main__':unittest.main()
