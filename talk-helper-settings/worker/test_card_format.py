"""The visible card carries bounded, clearly labeled model estimates."""
import unittest

from card_format import compact_analysis, card_header
from ipc import make_packet
from view_worker import ANALYSIS_PADDING, placement


class CardFormatTests(unittest.TestCase):
    def test_binary_and_intent_weights_are_labeled_as_estimates(self):
        result = {'answers': {
            'literal_question': {'noul': 0.07},
            'true_intent': {'choice': 'confirm_you_care', 'probabilities': {
                'confirm_you_care': 0.72, 'vent_anger': 0.08,
                'request_action': 0.02, 'seek_explanation': 0.02,
                'casual_chat': 0.12, 'close_topic': 0.04}},
            'danger_level': {'score': 8.6},
            'best_action': {'choice': 'check_history'},
            'should_reply_now': {'noul': 0.18},
        }, 'guidance': {'actions': ['翻看昨晚聊天，确认对方指的是哪一句，再回答。']}}
        status = compact_analysis(result)
        self.assertIn('信息足够直接答复？', status)
        self.assertIn('是 18%', status)
        self.assertIn('先核实 82%', status)
        self.assertIn('模型权重', status)
        self.assertIn('核对过往内容 72%', status)
        self.assertIn('紧张度：9/9', status)
        self.assertIn('翻看昨晚聊天', status)
        self.assertLess(len(status), 255)
        self.assertEqual(make_packet(1, 1, status=status).status, status)

    def test_explicit_no_contact_has_no_made_up_percentages(self):
        status = compact_analysis({'do_not_send': True, 'guidance': {
            'actions': ['现在停止发消息，尊重对方明确提出的不联系要求。']}})
        self.assertIn('停止发消息', status)
        self.assertNotIn('%', status)

    def test_time_stays_in_header_and_tall_card_uses_own_reserved_row(self):
        self.assertEqual(card_header('talk helper', '09-28 19:12'), 'talk helper · 09-28 19:12')
        self.assertEqual(card_header('X' * 47, '09-28 19:12'), 'X' * 28 + '…')
        anchor = (300, 100, 1200, 471)
        chat = {'area': (300, 90, 1200, 600), 'scale': 1, 'occupied': [anchor, (300, 471, 1200, 550)],
                'native_rows': {anchor: {'item': 1, 'padding': ANALYSIS_PADDING}}}
        self.assertEqual(placement(chat, anchor), ((368, 183, 672, 435), False))
