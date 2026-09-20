import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from flubber.pointer import MascotPointer
from flubber.tasks import TaskManager
from test_tasks import ControlledEngine


class PointerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.log = []
        async def send(method, params=None, session_id=None):
            self.log.append((method, params or {}, session_id))
            return {'identifier': 'script-1'} if method == 'Page.addScriptToEvaluateOnNewDocument' else {'result': {'value': True}}
        self.client = SimpleNamespace(send_raw=send)
        manager = SimpleNamespace(get_target_id_from_session_id=lambda sid:'target-1')
        self.browser = SimpleNamespace(cdp_client=self.client, session_manager=manager)
        self.revision = 0
        self.stopped = False
        def checkpoint(revision):
            if self.stopped or revision != self.revision:
                raise asyncio.CancelledError()
        self.control = SimpleNamespace(checkpoint=checkpoint)
        self.pointer = MascotPointer(self.browser, self.control, 0, 'target-1')
        self.pointer.install()

    async def asyncTearDown(self):
        await self.pointer.close()

    async def test_mascot_moves_before_the_real_click(self):
        await self.client.send_raw('Input.dispatchMouseEvent', {'type':'mousePressed','x':10,'y':20}, session_id='session')
        methods=[item[0] for item in self.log]
        self.assertEqual(methods[-1], 'Input.dispatchMouseEvent')
        self.assertTrue(any('__flubberOverlayV2.move(10, 20' in item[1].get('expression','') for item in self.log[:-1]))

    async def test_stop_blocks_real_input(self):
        self.stopped=True
        with self.assertRaises(asyncio.CancelledError):
            await self.client.send_raw('Input.insertText', {'text':'should not type'}, session_id='session')
        self.assertFalse(any(m[0]=='Input.insertText' for m in self.log))

    async def test_stale_revision_and_browser_close_are_blocked(self):
        self.revision=1
        with self.assertRaises(asyncio.CancelledError):
            await self.client.send_raw('Page.navigate', {'url':'https://example.com'}, session_id='session')
        self.revision=0
        with self.assertRaises(RuntimeError):
            await self.client.send_raw('Browser.close')

    async def test_screenshot_temporarily_hides_the_mascot(self):
        await self.client.send_raw('Input.dispatchMouseEvent', {'type':'mouseMoved','x':10,'y':20}, session_id='session')
        self.log.clear()
        await self.client.send_raw('Page.captureScreenshot', {}, session_id='session')
        self.assertIn('visible(false)', self.log[0][1]['expression'])
        self.assertEqual(self.log[1][0], 'Page.captureScreenshot')
        self.assertIn('visible(true)', self.log[2][1]['expression'])
