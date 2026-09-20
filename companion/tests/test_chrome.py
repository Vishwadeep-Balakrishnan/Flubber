import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from flubber.chrome import local_endpoint, _discover, find_marked_target


class DiscoveryTests(unittest.TestCase):
    def test_only_local_debugging_endpoints_are_accepted(self):
        self.assertTrue(local_endpoint('ws://127.0.0.1:9222/devtools/browser/one'))
        for endpoint in ['https://evil.example:9222','ws://evil.example:9222','file:///tmp/chrome','http://127.0.0.1']:
            self.assertFalse(local_endpoint(endpoint))
        with self.assertRaises(RuntimeError):
            _discover('ws://evil.example:9222/target')

    def test_stale_profile_is_skipped_in_favor_of_live_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            one=Path(directory)/'one';two=Path(directory)/'two';one.mkdir();two.mkdir()
            (one/'DevToolsActivePort').write_text('1234\n/devtools/browser/stale')
            (two/'DevToolsActivePort').write_text('5678\n/devtools/browser/live')
            with patch('flubber.chrome.profile_roots',return_value=[one,two]),patch('flubber.chrome._http_ws',side_effect=[urllib.error.URLError('closed'), 'ws://127.0.0.1:5678/devtools/browser/live']):
                self.assertEqual(_discover(),'ws://127.0.0.1:5678/devtools/browser/live')

    def test_chrome_147_discovery_uses_the_local_file_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'DevToolsActivePort').write_text('5678\n/devtools/browser/known')
            failure=urllib.error.HTTPError('http://127.0.0.1:5678/json/version',404,'Not Found',{},None)
            with patch('flubber.chrome.profile_roots',return_value=[root]),patch('flubber.chrome._http_ws',side_effect=failure):
                self.assertEqual(_discover(),'ws://127.0.0.1:5678/devtools/browser/known')


class TargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_page_urls_are_disambiguated_by_marker(self):
        async def send(method,params=None,session_id=None):
            if method=='Target.getTargets':
                return {'targetInfos':[{'type':'page','targetId':'one','url':'https://example.test/same'}, {'type':'page','targetId':'two','url':'https://example.test/same'}]}
            return {'result':{'value':session_id=='two'}}
        async def session(target_id,focus=False):return SimpleNamespace(session_id=target_id)
        browser=SimpleNamespace(cdp_client=SimpleNamespace(send_raw=send),get_or_create_cdp_session=session)
        self.assertEqual(await find_marked_target(browser,{'url':'https://example.test/same','token':'marker'}),'two')

    async def test_a_missing_marker_never_falls_back_to_an_arbitrary_tab(self):
        async def send(method,params=None,session_id=None):
            return {'targetInfos':[{'type':'page','targetId':'one','url':'https://example.test/same'}]} if method=='Target.getTargets' else {'result':{'value':False}}
        async def session(target_id,focus=False):return SimpleNamespace(session_id=target_id)
        browser=SimpleNamespace(cdp_client=SimpleNamespace(send_raw=send),get_or_create_cdp_session=session)
        with self.assertRaises(RuntimeError):
            await find_marked_target(browser,{'url':'https://example.test/same','token':'missing'})
