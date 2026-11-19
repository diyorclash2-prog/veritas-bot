import ast
import asyncio
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import urllib.request


def load_autobook():
    # Load the effective definitions without bot startup, secrets or live DB access.
    tree = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
    names = {
        '_autobook_host', '_autobook_catalog_url_ok', '_autobook_download_url_ok',
        '_autobook_json', '_autobook_pick_format', '_autobook_candidate_for_lang',
        'autobook_import_one', 'autobook_run',
    }
    definitions = {
        node.name: node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    }
    assert set(definitions) == names
    namespace = {'asyncio': asyncio, 'json': json, 'urllib': urllib,
                 'book_catalog': Mock(candidate=Mock(side_effect=TimeoutError)), 'AUTOBOOK_LANGS': ['en'], 'AUTOBOOK_ENABLED': True,
                 'AUTOBOOK_PER_RUN': 1, 'AUTOBOOK_LOCK': asyncio.Lock(),
                 'log': Mock(), 'one': Mock(return_value=None),
                 'execute': Mock(), 'now': Mock(return_value=10000)}
    state = {'page:en': '3', 'rr': '0'}
    namespace['_autobook_state_get'] = lambda key, default='': state.get(key, default)
    namespace['_autobook_state_set'] = Mock(side_effect=lambda key, value: state.update({key: str(value)}))
    module = ast.Module(body=list(definitions.values()), type_ignores=[])
    exec(compile(module, 'bot.py', 'exec'), namespace)
    return namespace, state


class AutobookTimeoutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns, self.state = load_autobook()

    async def test_timeout_is_failed_and_does_not_write_import_or_send(self):
        ctx = Mock()
        with patch.object(urllib.request, 'urlopen', side_effect=TimeoutError('private detail')) as request:
            result = await self.ns['autobook_import_one'](ctx, 'en')
        self.assertEqual(result, ('failed', 'AUTOBOOK_CATALOG_TIMEOUT'))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.state['page:en'], '3')
        self.ns['_autobook_state_set'].assert_not_called()
        self.ns['execute'].assert_not_called()
        self.assertEqual(ctx.mock_calls, [])
        self.assertNotIn('private detail', str(self.ns['log'].mock_calls))

    async def test_run_releases_lock_and_next_run_can_recover(self):
        with patch.object(urllib.request, 'urlopen', side_effect=TimeoutError) as request:
            stats = await self.ns['autobook_run'](Mock(), limit=1)
        self.assertEqual(stats['failed'], 1)
        self.ns['book_catalog'].candidate.assert_called_once()
        self.assertEqual(stats['empty'], 0)
        self.assertEqual(request.call_count, 1)
        self.assertFalse(self.ns['AUTOBOOK_LOCK'].locked())
        self.assertEqual(self.state['page:en'], '3')
        response = Mock()
        response.read.return_value = b'{"results": [], "next": null}'
        with patch.object(urllib.request, 'urlopen') as request:
            request.return_value.__enter__.return_value = response
            stats = await self.ns['autobook_run'](Mock(), limit=1)
        self.assertEqual(stats['empty'], 1)
        self.assertEqual(stats['failed'], 0)
        self.assertFalse(self.ns['AUTOBOOK_LOCK'].locked())

    def test_timeout_never_resets_or_retries_page(self):
        for page in ('1', '3'):
            with self.subTest(page=page):
                self.state['page:en'] = page
                with patch.object(urllib.request, 'urlopen', side_effect=TimeoutError) as request:
                    with self.assertRaises(TimeoutError):
                        self.ns['_autobook_candidate_for_lang']('en')
                self.assertEqual(request.call_count, 1)
                self.assertEqual(self.state['page:en'], page)
        self.ns['_autobook_state_set'].assert_not_called()

    def test_catalog_host_check_still_blocks_network(self):
        with patch.object(urllib.request, 'urlopen') as request:
            with self.assertRaisesRegex(RuntimeError, 'AUTOBOOK_CATALOG_HOST_NOT_ALLOWED'):
                self.ns['_autobook_json']('https://example.invalid/books')
        request.assert_not_called()

    async def test_unrelated_errors_are_not_reported_as_timeouts(self):
        self.state['page:en'] = '1'
        with patch.object(urllib.request, 'urlopen', side_effect=ValueError('invalid response')):
            with self.assertRaises(ValueError):
                await self.ns['autobook_import_one'](Mock(), 'en')

    def test_candidate_still_requires_public_domain_language_and_safe_format(self):
        def item(sid, **changes):
            value = {'id': sid, 'copyright': False, 'languages': ['en'],
                     'formats': {'application/epub+zip': 'https://www.gutenberg.org/book.epub'}}
            value.update(changes)
            return value
        valid = item(5)
        self.ns['_autobook_json'] = Mock(return_value={'results': [
            item(1, copyright=True), item(2, languages=['fr']),
            item(3, formats={'application/epub+zip': 'https://example.invalid/book.epub'}),
            valid,
        ]})
        result = self.ns['_autobook_candidate_for_lang']('en')
        self.assertEqual(result, (valid, 'en', 'epub', 'application/epub+zip',
                                  'https://www.gutenberg.org/book.epub'))


if __name__ == '__main__':
    unittest.main()
