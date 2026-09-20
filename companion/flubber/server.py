from __future__ import annotations

import asyncio
import hmac
import re
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web
from .tasks import TaskManager
from .voice import create_voice_key

EXTENSION_ORIGIN = re.compile(r'^chrome-extension://[a-p]{32}$')
TEXT_LIMIT = 6000
MANAGER_KEY = web.AppKey('manager', TaskManager)


def required_text(data, field, limit=TEXT_LIMIT):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise web.HTTPBadRequest(text=f'{field} must be nonempty text, at most {limit} characters.')
    return value.strip()


def same_code(provided, expected) -> bool:
    return isinstance(provided, str) and hmac.compare_digest(provided.encode(), expected.encode())


def create_app(settings, engine, voice_key=create_voice_key):
    manager = TaskManager(settings.state_dir, engine)

    @web.middleware
    async def access(request, handler):
        if request.host not in {f'127.0.0.1:{settings.port}', f'localhost:{settings.port}'}:
            raise web.HTTPForbidden(text='Invalid local host.')
        origin = request.headers.get('Origin', '')
        if origin and not EXTENSION_ORIGIN.fullmatch(origin):
            raise web.HTTPForbidden(text='Only the paired Flubber extension can call this API.')
        headers = {
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
            'Access-Control-Allow-Headers': 'Authorization,Content-Type',
        }
        if origin:
            headers['Access-Control-Allow-Origin'] = origin
            headers['Vary'] = 'Origin'
            if request.headers.get('Access-Control-Request-Private-Network') == 'true':
                headers['Access-Control-Allow-Private-Network'] = 'true'
        if request.method == 'OPTIONS':
            return web.Response(status=204, headers=headers)
        if request.path.startswith('/v1/'):
            provided = request.headers.get('Authorization', '').removeprefix('Bearer ')
            if not same_code(provided, settings.pairing_token):
                return web.json_response({'error': 'Pairing code rejected. Reconnect Flubber.'}, status=401, headers=headers)
        try:
            response = await handler(request)
        except ValueError as error:
            response = web.json_response({'error': str(error)}, status=409)
        except web.HTTPException as error:
            response = web.json_response({'error': error.text}, status=error.status)
        except RuntimeError as error:
            response = web.json_response({'error': str(error)}, status=502)
        if not response.prepared:
            response.headers.update(headers)
        return response

    app = web.Application(middlewares=[access], client_max_size=20000)
    app[MANAGER_KEY] = manager

    async def health(request):
        return web.json_response({'ok': True, 'model': settings.model, 'voice_model': settings.voice_model,
                                  'key_configured': bool(settings.api_key), 'engine': 'browser-use 0.13.11'})

    async def snapshot(request):
        return web.json_response(manager.snapshot())

    async def start(request):
        if not settings.api_key:
            return web.json_response({'error': 'Add your OpenAI API key to companion/.env and restart the companion.'}, status=503)
        try:
            data = await request.json()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text='Invalid request JSON.')
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text='Invalid request body.')
        command = required_text(data, 'command')
        request_id = required_text(data, 'request_id', 120)
        source = data.get('source')
        if not isinstance(source, dict):
            raise web.HTTPBadRequest(text='Select a website tab first.')
        url = source.get('url', '')
        if not isinstance(url, str) or urlparse(url).scheme not in {'http', 'https'}:
            raise web.HTTPBadRequest(text='Flubber works on ordinary website tabs, not Chrome internal pages.')
        token = source.get('token', '')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,100}', token):
            raise web.HTTPBadRequest(text='The starting tab marker is missing. Submit again from Flubber.')
        source = {'token': token, 'url': url, 'site': urlparse(url).netloc}
        result = await manager.start(command, source, request_id)
        return web.json_response(result, status=202)

    async def update(request):
        data = await request.json()
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text='Invalid update.')
        result = await manager.update(request.match_info['id'], required_text(data, 'text'))
        return web.json_response(result, status=202)

    async def stop(request):
        return web.json_response(await manager.stop(request.match_info['id']), status=202)

    async def voice(request):
        if not settings.api_key:
            return web.json_response({'error': 'Add your OpenAI API key to companion/.env and restart the companion.'}, status=503)
        key = await voice_key(settings.api_key, settings.voice_model)
        return web.json_response({'key': key, 'model': settings.voice_model})

    async def live(request):
        """Origin-checked WebSocket that pushes task progress to the side panel as it happens."""
        if not EXTENSION_ORIGIN.fullmatch(request.headers.get('Origin', '')):
            raise web.HTTPForbidden(text='Only the Flubber extension can open the live connection.')
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4096)
        await ws.prepare(request)
        try:
            hello = await ws.receive_json(timeout=5)
        except Exception:
            hello = None
        if not isinstance(hello, dict) or not same_code(hello.get('code'), settings.pairing_token):
            await ws.close(code=4401, message=b'Pairing code rejected')
            return ws
        queue = manager.watch()
        reader = asyncio.ensure_future(ws.receive())
        try:
            await ws.send_json(manager.snapshot())
            while True:
                change = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({reader, change}, return_when=asyncio.FIRST_COMPLETED)
                if change in done:
                    await ws.send_json(change.result())
                else:
                    change.cancel()
                if reader in done:
                    if reader.result().type in {web.WSMsgType.CLOSE, web.WSMsgType.CLOSING, web.WSMsgType.CLOSED, web.WSMsgType.ERROR}:
                        break
                    reader = asyncio.ensure_future(ws.receive())  # Ignore anything else the client sends.
        finally:
            reader.cancel()
            manager.unwatch(queue)
            await ws.close()
        return ws

    async def test_page(request):
        filename = request.match_info.get('name', 'index.html')
        if filename not in {'index.html', 'fixture.js'}:
            raise web.HTTPNotFound()
        return web.FileResponse(Path(__file__).resolve().parents[1] / 'test-page' / filename)

    async def home(request):
        return web.Response(text='Flubber companion is running. Open the Flubber extension to connect.')

    async def cleanup(app):
        await manager.close()

    app.router.add_get('/', home)
    app.router.add_get('/live', live)
    app.router.add_get('/test', test_page)
    app.router.add_get('/test/{name}', test_page)
    app.router.add_get('/v1/health', health)
    app.router.add_get('/v1/tasks', snapshot)
    app.router.add_post('/v1/tasks', start)
    app.router.add_post('/v1/tasks/{id}/update', update)
    app.router.add_post('/v1/tasks/{id}/stop', stop)
    app.router.add_post('/v1/voice', voice)
    app.on_cleanup.append(cleanup)
    return app
