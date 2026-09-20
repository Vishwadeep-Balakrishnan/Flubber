import tempfile
import unittest
from pathlib import Path
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer
from flubber.config import Settings
from flubber.server import create_app
from test_tasks import ControlledEngine


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(api_key='test-not-real', state_dir=Path(self.temp.name), pairing_token='a' * 43)
        self.engine = ControlledEngine()
        self.voice_calls = []
        async def fake_voice_key(api_key, model):
            self.voice_calls.append((api_key, model))
            return 'ek_test_ephemeral'
        self.client = TestClient(TestServer(create_app(self.settings, self.engine, fake_voice_key)), headers={
            'Host': '127.0.0.1:8765', 'Authorization': 'Bearer ' + self.settings.pairing_token,
            'Origin': 'chrome-extension://' + 'a' * 32
        })
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def test_health_never_returns_the_api_key(self):
        response = await self.client.get('/v1/health')
        self.assertEqual(response.status, 200)
        text = await response.text()
        self.assertNotIn('test-not-real', text)
        self.assertIn('gpt-6-luna', text)

    async def test_bad_pairing_code_is_rejected(self):
        response = await self.client.get('/v1/tasks', headers={'Authorization': 'Bearer wrong'})
        self.assertEqual(response.status, 401)

    async def test_website_origin_and_rebinding_host_are_rejected(self):
        response = await self.client.get('/v1/tasks', headers={'Origin': 'https://example.com'})
        self.assertEqual(response.status, 403)
        response = await self.client.get('/v1/tasks', headers={'Host': 'evil.example'})
        self.assertEqual(response.status, 403)

    async def test_internal_page_and_missing_marker_are_rejected(self):
        response = await self.client.post('/v1/tasks', json={'command':'Hello','request_id':'one','source':{'url':'chrome://settings','token':'a'*32}})
        self.assertEqual(response.status, 400)
        response = await self.client.post('/v1/tasks', json={'command':'Hello','request_id':'one','source':{'url':'https://example.com'}})
        self.assertEqual(response.status, 400)

    async def test_task_start_update_stop(self):
        response = await self.client.post('/v1/tasks', json={'command':'Fill the form','request_id':'one','source':{'url':'https://example.com','token':'a'*32}})
        self.assertEqual(response.status, 202)
        run = await response.json()
        await self.engine.ready.wait()
        update = await self.client.post(f'/v1/tasks/{run["id"]}/update', json={'text':'Use Weekly'})
        self.assertEqual(update.status, 202)
        stop = await self.client.post(f'/v1/tasks/{run["id"]}/stop', json={})
        self.assertEqual(stop.status, 202)

    async def test_practice_page_is_available_without_a_model_call(self):
        response = await self.client.get('/test')
        self.assertEqual(response.status, 200)
        self.assertIn('Flubber practice page', await response.text())
        self.assertEqual(self.engine.revisions, [])

    async def test_voice_returns_only_an_ephemeral_key(self):
        response = await self.client.post('/v1/voice', json={})
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data['key'], 'ek_test_ephemeral')
        self.assertNotIn('test-not-real', await response.text())
        self.assertEqual(self.voice_calls, [('test-not-real', 'gpt-live-transcribe')])
        response = await self.client.post('/v1/voice', json={}, headers={'Authorization': 'Bearer wrong'})
        self.assertEqual(response.status, 401)

    async def test_live_socket_requires_extension_origin_and_pairing_code(self):
        with self.assertRaises(Exception):
            await self.client.ws_connect('/live', headers={'Origin': 'https://example.com'})
        ws = await self.client.ws_connect('/live')
        await ws.send_json({'code': 'wrong'})
        message = await ws.receive()
        self.assertIn(message.type, {WSMsgType.CLOSE, WSMsgType.CLOSED})
        await ws.close()

    async def test_live_socket_pushes_task_progress(self):
        ws = await self.client.ws_connect('/live')
        await ws.send_json({'code': self.settings.pairing_token})
        first = await ws.receive_json(timeout=5)
        self.assertIsNone(first['current'])
        await self.client.post('/v1/tasks', json={'command':'Fill the form','request_id':'one','source':{'url':'https://example.com','token':'a'*32}})
        seen = []
        while 'Entering text' not in seen:
            snapshot = await ws.receive_json(timeout=5)
            seen.append(snapshot['current']['message'])
        self.engine.finish.set()
        while (await ws.receive_json(timeout=5))['current']['status'] != 'completed':
            pass
        await ws.close()
