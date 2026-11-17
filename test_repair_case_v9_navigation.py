"""Exercise real V9 handlers offline without importing bot startup or live data."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def handlers():
    tree = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
    env = {
        'STATE': {},
        'InlineKeyboardButton': InlineKeyboardButton,
        'InlineKeyboardMarkup': InlineKeyboardMarkup,
        'ensure_user': Mock(),
        'one': Mock(return_value=None),
        'main_menu_markup': Mock(return_value=None),
        'db': Mock(side_effect=AssertionError('Unexpected database write')),
    }
    names = {
        'root_choice_markup', 'v9_entry_markup', 'v9_teacher_markup',
        'v9_student_markup', 'v9_callback', 'v9_private_input',
    }
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            if node.name in env:
                env['_fixed_old_' + node.name] = env[node.name]
            module = ast.Module(body=[node], type_ignores=[])
            exec(compile(module, 'bot.py', 'exec'), env)
    return env


class V9NavigationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = handlers()
        self.state = self.env['STATE']
        self.ctx = NS(user_data={})
        self.user = NS(id=101)

    async def click(self, data):
        query = NS(data=data, from_user=self.user, answer=AsyncMock(),
                   edit_message_text=AsyncMock())
        await self.env['v9_callback'](NS(callback_query=query), self.ctx)
        return query

    async def test_home_and_root_buttons_cancel_only_current_v9_input(self):
        destinations = ('root:choose', 'root:v8', 'root:v9', 'v9:home',
                        'v9:teacher:home', 'v9:student:home')
        for destination in destinations:
            for mode in ('v9_plan_class', 'v9_new_group_subject', 'v9_join_group'):
                with self.subTest(destination=destination, mode=mode):
                    other = {'mode': 'v9_plan_class'}
                    self.state.update({101: {'mode': mode}, 202: other})
                    query = await self.click(destination)
                    self.assertNotIn(101, self.state)
                    self.assertIs(self.state[202], other)
                    query.edit_message_text.assert_awaited_once()
        unrelated = {'mode': 'owner_message'}
        self.state[101] = unrelated
        await self.click('root:choose')
        self.assertIs(self.state[101], unrelated)

    async def test_cancelled_plan_does_not_consume_next_text(self):
        self.state[101] = {'mode': 'v9_plan_class'}
        await self.click('v9:teacher:home')
        msg = NS(text='Oddiy xabar', message_id=55, chat=NS(type='private'),
                 reply_text=AsyncMock())
        await self.env['v9_private_input'](
            NS(effective_message=msg, effective_user=self.user), self.ctx)
        self.assertNotIn(101, self.state)
        msg.reply_text.assert_not_awaited()
        self.env['db'].assert_not_called()

    async def test_cancel_lesson_then_old_publish_button_cannot_write(self):
        self.state[101] = {'mode': 'v9_lesson_mode', 'group_id': 7}
        self.env['one'].side_effect = [
            {'teacher_id': 101, 'title': 'Math', 'subject': 'Math', 'join_code': 'CODE'},
            None, {'n': 0},
        ]
        query = await self.click('v9:group:7')
        query.edit_message_text.assert_awaited_once()
        self.assertNotIn(101, self.state)
        query = await self.click('v9:lessonmode:material_only')
        self.assertTrue(query.answer.await_args.kwargs['show_alert'])
        query.edit_message_text.assert_not_awaited()
        self.env['db'].assert_not_called()

    async def test_back_to_lesson_stops_ai_input(self):
        self.state[101] = {'mode': 'v9_ai_lesson', 'lesson_id': 8}
        self.env['one'].side_effect = [
            {'group_teacher': 202, 'group_id': 7, 'title': 'Lesson',
             'group_title': 'Math', 'ai_mode': 'material_only'},
            {'member': 1},
        ]
        query = await self.click('v9:lesson:view:8')
        self.assertNotIn(101, self.state)
        query.edit_message_text.assert_awaited_once()

    async def test_denied_navigation_preserves_input_and_access_checks(self):
        for destination, record in (
            ('v9:group:7', {'teacher_id': 202}),
            ('v9:lesson:view:8', {'group_teacher': 202, 'group_id': 7}),
        ):
            with self.subTest(destination=destination):
                original = {'mode': 'v9_lesson_title', 'group_id': 9}
                self.state[101] = original
                self.env['one'].side_effect = [record, None]
                query = await self.click(destination)
                self.assertIs(self.state[101], original)
                self.assertTrue(query.answer.await_args.kwargs['show_alert'])
                query.edit_message_text.assert_not_awaited()

    async def test_non_navigation_action_keeps_active_session(self):
        original = {'mode': 'v9_lesson_mode', 'group_id': 7}
        self.state[101] = original
        await self.click('v9:lessonmode:invalid')
        self.assertIs(self.state[101], original)
        self.env['db'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
