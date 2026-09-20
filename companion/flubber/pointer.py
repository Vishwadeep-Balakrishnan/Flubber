from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]


class MascotPointer:
    """Wrap the real CDP transport: animate the mascot before actual input is sent."""

    def __init__(self, browser, control, revision: int, target_id: str):
        self.browser = browser
        self.control = control
        self.revision = revision
        self.client = browser.cdp_client
        self.original = self.client.send_raw
        image = base64.b64encode((ROOT / 'extension/assets/icon-128.png').read_bytes()).decode('ascii')
        self.source = (Path(__file__).with_name('mascot.js')).read_text(encoding='utf-8').replace('__FLUBBER_IMAGE__', json.dumps(image))
        self.allowed = {target_id}
        self.scripts = {}
        self.sessions = set()

    def install(self):
        self.client.send_raw = self.send

    async def js(self, expression, session_id):
        result = await self.original('Runtime.evaluate', {
            'expression': expression, 'returnByValue': True, 'awaitPromise': True
        }, session_id=session_id)
        if result.get('exceptionDetails'):
            raise RuntimeError('Could not draw the Flubber action pointer on this page.')
        return result.get('result', {}).get('value')

    async def ensure(self, session_id):
        if session_id not in self.scripts:
            result = await self.original('Page.addScriptToEvaluateOnNewDocument', {'source': self.source}, session_id=session_id)
            self.scripts[session_id] = result['identifier']
        self.sessions.add(session_id)
        await self.js(self.source, session_id)

    async def prepare_element(self, index):
        """Position the mascot for DOM-based selection actions that emit no mouse input."""
        self.control.checkpoint(self.revision)
        node = await self.browser.get_element_by_index(index)
        if node is None:
            return
        sid = getattr(node, 'session_id', None)
        if not sid:
            session = await self.browser.get_or_create_cdp_session(focus=False)
            sid = session.session_id
        self.control.checkpoint(self.revision)
        await self.original('DOM.scrollIntoViewIfNeeded', {'backendNodeId': node.backend_node_id}, session_id=sid)
        resolved = await self.original('DOM.resolveNode', {'backendNodeId': node.backend_node_id}, session_id=sid)
        object_id = resolved['object']['objectId']
        try:
            result = await self.original('Runtime.callFunctionOn', {
                'objectId': object_id, 'functionDeclaration': 'function(){const r=this.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}}',
                'returnByValue': True
            }, session_id=sid)
            point = result.get('result', {}).get('value')
            if point:
                self.control.checkpoint(self.revision)
                await self.ensure(sid)
                await self.js(f'globalThis.__flubberOverlayV2.move({json.dumps(point["x"])},{json.dumps(point["y"])},"move")', sid)
        finally:
            await self.original('Runtime.releaseObject', {'objectId': object_id}, session_id=sid)
        self.control.checkpoint(self.revision)

    async def allowed_target(self, target_id):
        if target_id in self.allowed:
            return True
        try:
            info = (await self.original('Target.getTargetInfo', {'targetId': target_id}))['targetInfo']
            if info.get('openerId') in self.allowed:
                self.allowed.add(target_id)
                return True
            if info.get('type') == 'iframe':
                # OOPIF target IDs normally equal frame IDs; accept only a frame in our page tree.
                for parent_id in list(self.allowed):
                    session = await self.browser.get_or_create_cdp_session(parent_id, focus=False)
                    tree = await self.original('Page.getFrameTree', session_id=session.session_id)
                    def contains(node):
                        return node.get('frame', {}).get('id') == target_id or any(contains(c) for c in node.get('childFrames', []))
                    if contains(tree['frameTree']):
                        self.allowed.add(target_id)
                        return True
        except asyncio.CancelledError:
            raise
        except Exception:
            return False
        return False

    async def send(self, method, params=None, session_id=None):
        params = params or {}
        mutation = (method.startswith('Input.') or method in {
            'Runtime.evaluate', 'Runtime.callFunctionOn', 'Page.navigate', 'Page.reload',
            'Page.handleJavaScriptDialog', 'DOM.setFileInputFiles', 'DOM.setAttributeValue',
            'DOM.scrollIntoViewIfNeeded',
            'Target.createTarget', 'Target.closeTarget', 'Target.activateTarget', 'Browser.close'
        })
        sensitive_read = method in {'Page.captureScreenshot', 'Page.printToPDF', 'DOMSnapshot.captureSnapshot',
                                   'Accessibility.getFullAXTree', 'DOM.getDocument', 'DOM.getFlattenedDocument'}
        if mutation or sensitive_read:
            self.control.checkpoint(self.revision)
            if method == 'Browser.close':
                raise RuntimeError('Flubber will not close your whole browser.')
            target = params.get('targetId')
            if not target and session_id:
                target = self.browser.session_manager.get_target_id_from_session_id(session_id)
            if session_id and not target:
                raise RuntimeError('The browser session no longer belongs to an available task tab.')
            if target and not await self.allowed_target(target):
                raise RuntimeError('This task is limited to its starting tab and tabs opened from it.')
            if method in {'Page.navigate', 'Target.createTarget'}:
                url = params.get('url', 'about:blank')
                if not (url == 'about:blank' or urlparse(url).scheme in {'http', 'https'}):
                    raise RuntimeError('Flubber can navigate ordinary websites only.')

        if method == 'Input.dispatchMouseEvent' and session_id:
            await self.ensure(session_id)
            x, y = params.get('x', 0), params.get('y', 0)
            kind = 'click' if params.get('type') == 'mousePressed' else 'move'
            await self.js(f'globalThis.__flubberOverlayV2.move({json.dumps(x)}, {json.dumps(y)}, {json.dumps(kind)})', session_id)
            self.control.checkpoint(self.revision)
        elif method in {'Input.insertText', 'Input.dispatchKeyEvent'} and session_id:
            await self.ensure(session_id)
            await self.js('''(() => {
                const r = document.activeElement?.getBoundingClientRect();
                return globalThis.__flubberOverlayV2.move(r?.width ? r.x + r.width / 2 : innerWidth / 2,
                    r?.height ? r.y + r.height / 2 : innerHeight / 2, "type");
            })()''', session_id)
            self.control.checkpoint(self.revision)
        elif method == 'Page.navigate' and session_id:
            await self.ensure(session_id)
            await self.js('globalThis.__flubberOverlayV2.move(innerWidth/2,innerHeight/2,"move")', session_id)
            self.control.checkpoint(self.revision)

        if method == 'Page.captureScreenshot':
            hidden = []
            for sid in list(self.sessions):
                try:
                    await self.js('globalThis.__flubberOverlayV2?.visible(false)', sid)
                    hidden.append(sid)
                except Exception:
                    pass
            try:
                return await self.original(method, params, session_id=session_id)
            finally:
                for sid in hidden:
                    try:
                        await self.js('globalThis.__flubberOverlayV2?.visible(true)', sid)
                    except Exception:
                        pass
        result = await self.original(method, params, session_id=session_id)
        if method == 'Target.createTarget' and result.get('targetId'):
            self.allowed.add(result['targetId'])
        return result

    async def pause(self):
        for sid in list(self.sessions):
            try:
                await asyncio.wait_for(self.js('globalThis.__flubberOverlayV2?.destroy()', sid), 2)
            except Exception:
                pass

    async def close(self):
        for sid in list(self.sessions):
            try:
                await asyncio.wait_for(self.js('globalThis.__flubberOverlayV2?.destroy()', sid), 2)
                identifier = self.scripts.get(sid)
                if identifier:
                    await self.original('Page.removeScriptToEvaluateOnNewDocument', {'identifier': identifier}, session_id=sid)
            except Exception:
                pass
        self.client.send_raw = self.original
