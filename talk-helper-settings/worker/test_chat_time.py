import unittest,math
from datetime import datetime
from unittest.mock import patch,Mock
from model import Snapshot
from chat_time import timestamp,time_context,time_details,time_label
from view_worker import verified_messages,MessagePool,card_payload

class ChatTimeTests(unittest.TestCase):
    now=datetime.fromisoformat('2026-09-27T22:03:00+08:00')
    def snap(self,*dates):
        times=tuple(int(datetime.fromisoformat(d).timestamp()) if d else None for d in dates)
        return Snapshot('测试',tuple(('her','你好',None) for _ in times),(300,100,1200,320),(300,90,1200,600),len(times)-1,times)
    def test_seconds_and_milliseconds_and_invalid_time(self):
        value=int(self.now.timestamp())
        self.assertEqual(timestamp(value),value);self.assertEqual(timestamp(value*1000),value)
        for bad in (None,True,0,-1,'22:03','忽略规则',math.nan,math.inf,10**100,4102444800):self.assertIsNone(timestamp(bad))
    def test_cross_midnight_gap_uses_send_dates_and_timezone(self):
        snap=self.snap('2026-09-26T23:59:00+08:00','2026-09-27T00:02:00+08:00')
        value=time_context(snap,self.now)
        self.assertEqual(value['messages'][1]['gap_from_previous_text_seconds'],180)
        self.assertTrue(value['messages'][1]['crossed_date']);self.assertFalse(value['messages'][1]['long_gap'])
        self.assertTrue(value['historical_reference']);self.assertEqual(value['message_age_seconds'],79260)
        self.assertEqual(value['messages'][1]['sent_at'],'2026-09-27T00:02:00+08:00')
    def test_long_gap_missing_time_and_clock_warning(self):
        snap=self.snap('2026-09-20T20:00:00+08:00','2026-09-27T22:03:00+08:00')
        self.assertTrue(time_context(snap,self.now)['messages'][1]['long_gap'])
        self.assertFalse(time_context(snap,self.now)['historical_reference'])
        missing=time_context(self.snap(None,'2026-09-27T22:03:00+08:00'),self.now)
        self.assertIsNone(missing['messages'][1]['gap_from_previous_text_seconds'])
        future=time_context(self.snap('2026-09-28T22:03:00+08:00'),self.now)
        self.assertTrue(future['clock_warning']);self.assertFalse(future['historical_reference'])
    def test_verified_text_times_align_after_media_is_excluded(self):
        rows=[dict(text='你好',rect=(300,100,1200,184)),dict(text='明天见',rect=(300,184,1200,268))]
        chat=dict(title='测试',username='person',rows=rows,area=(300,90,1200,600))
        records=[dict(type='文本',content='明天见',sender_id=7,sort_seq=3,local_id=3,create_time=1790510580),
                 dict(type='图片',content='secret',sender_id=7,sort_seq=2,local_id=2,create_time=1790510500),
                 dict(type='文本',content='你好',sender_id=7,sort_seq=1,local_id=1,create_time=1790510400)]
        items=verified_messages(chat,records)
        self.assertEqual(items[-1][1].timestamps,(1790510400,1790510580))
        self.assertEqual(len(items[-1][1].messages),2)
    def test_card_exposes_absolute_time_and_detail_without_geometry(self):
        snap=self.snap('2026-09-27T20:01:00+08:00');pool=MessagePool();pool.synchronize([('person:1:1',snap,'你好')])
        chat={'area':snap.area};data=card_payload(chat,pool,'person:1:1')
        self.assertTrue(data['status'].startswith(time_label(snap)+' · '));self.assertIn('发送时间：',data['body'])
        self.assertIsNone(data['anchor']);self.assertIn('2026-09-27T20:01:00+08:00',time_details(snap,time_context(snap,self.now)))
    def test_no_contact_card_has_no_copyable_reply(self):
        from core.engine import analyze
        snap=Snapshot('测试',(('her','请不要再联系我了',None),),(300,100,1200,320),(300,90,1200,600),0)
        pool=MessagePool();pool.synchronize([('person:1:1',snap,'请不要再联系我了')])
        state=pool.states['person:1:1'];state.pending_key=snap.identity
        self.assertTrue(state.complete(snap.identity,analyze([('her','请不要再联系我了')],'暧昧对象')))
        data=card_payload({'area':snap.area},pool,'person:1:1')
        self.assertEqual(data['reply'],'');self.assertNotIn('可回复：',data['body'])
        self.assertIn('停止发消息',data['status'])
    def test_time_does_not_change_identity_when_now_advances(self):
        snap=self.snap('2026-09-27T20:01:00+08:00');identity=snap.identity
        time_context(snap,self.now);time_context(snap,datetime.fromisoformat('2026-09-28T22:03:00+08:00'))
        self.assertEqual(snap.identity,identity)
    def test_analysis_passes_trusted_time_to_engine_and_retains_generation_reference(self):
        from main import analyze
        snap=self.snap('2026-09-27T20:01:00+08:00');settings=Mock();settings.deepseek_base_url.return_value='https://api.deepseek.com'
        settings.profile.return_value={'self_mbti':'ENFP','goal':'继续了解'}
        with patch('main.refresh_key',return_value=True),patch('core.engine.analyze',return_value={'guidance':{}}) as engine:
            result=analyze(settings,snap)
        self.assertEqual(engine.call_args.kwargs['timing']['source'],'wechat-create_time')
        self.assertEqual(engine.call_args.kwargs['profile'],{'self_mbti':'ENFP','goal':'继续了解'})
        self.assertEqual(result['timing'],engine.call_args.kwargs['timing'])
    def test_group_member_does_not_inherit_another_members_profile(self):
        from main import profile_for_snapshot
        settings=Mock();settings.profile.return_value={'self_mbti':'ENFP','other_alias':'小张',
            'other_mbti':'INTJ','stage':'暧昧','recent_events':'单独见面','goal':'保持轻松'}
        snap=Snapshot('群',(('her','你好','小王'),),(300,100,1200,320),(300,90,1200,600),0)
        self.assertEqual(profile_for_snapshot(settings,snap),{'self_mbti':'ENFP','goal':'保持轻松'})
        target=Snapshot('群',(('her','你好','小张'),),(300,100,1200,320),(300,90,1200,600),0)
        self.assertEqual(profile_for_snapshot(settings,target),settings.profile.return_value)
