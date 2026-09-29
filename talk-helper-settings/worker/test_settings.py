import unittest,tempfile,json,sqlite3,ctypes
from pathlib import Path
from unittest.mock import Mock
from helper_settings import HelperSettings
from direct_data import ConversationDB
from view_worker import chat_title,verified_messages,ensure_chat_directory
from ipc import SettingsPacket,CopyData,NativePanel,make_packet

class SettingsTests(unittest.TestCase):
    def test_new_contact_is_selectable_even_when_directory_is_full(self):
        directory=[dict(id=i+1,username=f'p{i}',name=str(i),group=False) for i in range(3000)]
        self.assertTrue(ensure_chat_directory(directory,'new-person','新联系人',{'p2999'}))
        self.assertEqual(len(directory),3000);self.assertEqual(directory[-1]['id'],3001)
        self.assertIn('p2999',{r['username'] for r in directory})
        self.assertFalse(ensure_chat_directory(directory,'new-person','新联系人',{}))
    def setup_store(self,tmp):
        legacy=Mock();legacy.deepseek_key.return_value='legacy-test-key'
        secrets=Mock();secrets.read.return_value=''
        return HelperSettings(Path(tmp)/'config.json',legacy,secrets),secrets
    def test_scoped_profiles_and_global_connection_are_applied_without_cross_chat_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,secrets=self.setup_store(tmp);v=store.values();v.update(relationship='同事',style='直接简短',common_phrases='收到\n好的',assistant_name='小助手')
            store.apply(v,'account','person')
            self.assertEqual(store.values('account','person')['relationship'],'同事')
            self.assertEqual(store.values('account','other')['relationship'],'朋友')
            self.assertEqual(store.values('other-account','person')['relationship'],'朋友')
            self.assertEqual(store.values('account','other')['assistant_name'],'小助手')
            self.assertIn('收到',store.snapshot('account','person').style())
            self.assertEqual(HelperSettings(store.path,store.fallback,secrets).values('account','person')['style'],'直接简短')
    def test_subjective_relationship_profile_stays_in_selected_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,_=self.setup_store(tmp);values=store.values();values.update(
                self_mbti='enfp',self_rating='72',self_strengths='表达直接',self_challenges='容易着急',
                other_alias='A',other_mbti='INTJ',other_rating='81',stage='认识三个月的朋友',
                met_context='共同朋友介绍',known_duration='三个月',recent_events='一次见面；一次改期',
                contact_pattern='双方都偶尔主动',goal='继续了解',feeling='有点紧张 3/10')
            store.apply(values,'account','person')
            own=store.snapshot('account','person').profile()
            self.assertEqual(own['self_mbti'],'ENFP');self.assertEqual(own['other_rating'],'81')
            self.assertEqual(own['recent_events'],'一次见面；一次改期')
            self.assertEqual(store.snapshot('account','other').profile(),{})
            self.assertEqual(store.snapshot('other-account','person').profile(),{})
            self.assertNotIn('A',str(store.snapshot().profile()))
            self.assertNotIn('other_mbti',store.data)
            store.apply(values)
            self.assertEqual(store.snapshot().profile(),{})
            self.assertNotIn('self_mbti',store.data)
    def test_invalid_profile_labels_and_scores_are_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,_=self.setup_store(tmp)
            for changes in ({'self_mbti':'ESFP?'},{'other_mbti':'XXXX'},
                            {'self_rating':'101'},{'other_rating':'-1'},
                            {'recent_events':'x'*768}):
                values=store.values();values.update(changes)
                with self.subTest(changes=changes),self.assertRaises(ValueError):store.apply(values,'account','person')
                self.assertFalse(store.path.exists())
    def test_malformed_saved_profile_is_ignored_without_cross_chat_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,_=self.setup_store(tmp)
            store.data['chat_profiles']={'account':{'person':'not a profile'}}
            self.assertEqual(store.values('account','person')['self_mbti'],'')
            store.data['chat_profiles']='unexpected'
            self.assertEqual(store.snapshot('account','person').profile(),{})
    def test_official_endpoint_validation_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,secrets=self.setup_store(tmp);v=store.values();v['deepseek_base_url']='https://openrouter.ai/api/v1'
            with self.assertRaises(ValueError):store.apply(v,key='new-test-key')
            secrets.write.assert_not_called();self.assertFalse(store.path.exists())
            v['deepseek_base_url']='https://api.deepseek.com/v1/chat/completions';store.apply(v)
            self.assertEqual(store.values()['deepseek_base_url'],'https://api.deepseek.com/v1')
    def test_key_never_written_to_config_and_blank_keeps_current_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,secrets=self.setup_store(tmp);store.apply(store.values(),key='new-test-key')
            secrets.write.assert_called_once_with('new-test-key');self.assertNotIn('test-key',store.path.read_text())
            store.apply(store.values());self.assertEqual(store.key,'new-test-key');self.assertEqual(secrets.write.call_count,1)
    def test_invalid_fields_do_not_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,secrets=self.setup_store(tmp)
            for changed in ({'assistant_name':''},{'deepseek_model':''},{'context':31},{'style':'x'*1024}):
                v=store.values();v.update(changed)
                with self.assertRaises(ValueError):store.apply(v)
                self.assertFalse(store.path.exists())
    def test_contact_title_falls_back_to_input_accessible_name(self):
        field=Mock();field.Name='我的朋友'
        self.assertEqual(chat_title(None,field),'我的朋友')
        header=Mock();header.Name='';self.assertEqual(chat_title(header,field),'我的朋友')
        header.Name='群聊';self.assertEqual(chat_title(header,field),'群聊')
    def test_exact_contact_lookup_has_no_like_limit_and_obeys_display_remark(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'contact.db';conn=sqlite3.connect(path)
            conn.execute('CREATE TABLE contact(username TEXT,nick_name TEXT,remark TEXT)')
            conn.executemany('INSERT INTO contact VALUES(?,?,?)',[(f'p{i}',f'name{i}','') for i in range(80)]+[('special','%',''),('renamed','%','新备注'),('no-session','从未打开','')]);conn.commit();conn.close()
            db=ConversationDB.__new__(ConversationDB);db._db_files=[('contact',str(path),0)];db._open=lambda _:sqlite3.connect(path)
            self.assertEqual(db.resolve_chat('%'),'special');self.assertEqual(db.resolve_chat('新备注'),'renamed')
            db.get_sessions=lambda limit:[];db.account='self_abcd'
            self.assertIn('no-session',{r['username'] for r in db.chat_directory()})
            conn=sqlite3.connect(path);conn.execute('INSERT INTO contact VALUES(?,?,?)',('duplicate','%',''));conn.commit();conn.close()
            self.assertIsNone(db.resolve_chat('%'))
    def test_sender_direction_uses_verified_identity_not_shared_numeric_id(self):
        chat={'title':'朋友','username':'person','rows':[{'text':'你好','rect':(1,1,2,2)}],'area':(0,0,100,100)}
        record={'type':'文本','content':'你好','sender_id':2,'is_self':False,'sort_seq':1,'local_id':1}
        self.assertEqual(len(verified_messages(chat,[record])),1)
        record['sender_id']=8;record['is_self']=True;self.assertEqual(verified_messages(chat,[record]),[])
    def test_same_name_contact_uses_only_unique_visible_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            contact=Path(tmp)/'contact.db';session=Path(tmp)/'session.db'
            with sqlite3.connect(contact) as conn:
                conn.execute('CREATE TABLE contact(username TEXT,nick_name TEXT,remark TEXT)')
                conn.executemany('INSERT INTO contact VALUES(?,?,?)',[('a','0.0',''),('b','0.0','')])
            conn.close()
            with sqlite3.connect(session) as conn:
                conn.execute('CREATE TABLE SessionTable(username TEXT,is_hidden INTEGER)')
                conn.executemany('INSERT INTO SessionTable VALUES(?,?)',[('a',0),('b',1)])
            conn.close()
            db=ConversationDB.__new__(ConversationDB);db._db_files=[('contact',str(contact),0),('session',str(session),0)]
            db._open=lambda rel:sqlite3.connect(contact if rel=='contact' else session)
            self.assertEqual(db.resolve_chat('0.0'),'a')
            with sqlite3.connect(session) as conn:conn.execute('UPDATE SessionTable SET is_hidden=0')
            conn.close()
            self.assertIsNone(db.resolve_chat('0.0'))
            with sqlite3.connect(session) as conn:conn.execute('DELETE FROM SessionTable')
            conn.close()
            self.assertIsNone(db.resolve_chat('0.0'))
    def test_settings_ipc_and_assistant_label(self):
        self.assertEqual(ctypes.sizeof(SettingsPacket),11868)
        packet=make_packet(1,1,assistant_name='小助手');self.assertEqual(packet.assistant_name,'小助手')
    def test_profile_fields_round_trip_through_settings_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,_=self.setup_store(tmp);values=store.values();values.update(self_mbti='ENFP',other_alias='A',goal='继续了解',recent_events='一次见面')
            panel=NativePanel.__new__(NativePanel);panel.settings_sequence=0;panel.token=7
            sent=[]
            def send(msg,wp=0,lp=0):
                if msg==0x4a:
                    data=CopyData.from_address(lp)
                    sent.append(ctypes.string_at(data.lpData,data.cbData))
                    return 1
                return 123
            panel.send=send
            self.assertTrue(panel.settings(values,scope=123,key_present=True))
            packet=SettingsPacket.from_buffer_copy(sent[0])
            self.assertEqual((packet.scope,packet.self_mbti,packet.other_alias,packet.goal,packet.recent_events),
                             (123,'ENFP','A','继续了解','一次见面'))
            packet.flags=0
            raw=bytes(packet)
            class Reader:
                def read(self,address,size):return raw if address==123 and size==len(raw) else b''
            received,scope,key=panel.settings_draft(Reader())
            self.assertEqual(scope,123);self.assertEqual(received['self_mbti'],'ENFP')
            self.assertEqual(received['goal'],'继续了解');self.assertEqual(key,'')

if __name__=='__main__':unittest.main()
