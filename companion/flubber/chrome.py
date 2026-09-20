from __future__ import annotations

import asyncio
import json
import os
import platform
from pathlib import Path
from urllib.parse import urlparse
import urllib.request
import urllib.error


def local_endpoint(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {'http', 'ws'} and parsed.hostname in {'localhost', '127.0.0.1', '::1'} and bool(parsed.port)
    except ValueError:
        return False


def profile_roots() -> list[Path]:
    home = Path.home()
    if platform.system() == 'Windows':
        local = Path(os.environ.get('LOCALAPPDATA', str(home / 'AppData/Local')))
        return [local / 'Google/Chrome/User Data', local / 'Chromium/User Data']
    if platform.system() == 'Darwin':
        return [home / 'Library/Application Support/Google/Chrome', home / 'Library/Application Support/Chromium']
    return [home / '.config/google-chrome', home / '.config/chromium', home / '.config/google-chrome-beta']


def _http_ws(endpoint: str) -> str:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(endpoint.rstrip('/') + '/json/version', timeout=2) as response:
        url = json.load(response)['webSocketDebuggerUrl']
    if not local_endpoint(url):
        raise RuntimeError('Chrome returned a non-local debugging endpoint.')
    return url


def _discover(explicit: str = '') -> str:
    if explicit:
        if not local_endpoint(explicit):
            raise RuntimeError('FLUBBER_CDP_URL must be a local http:// or ws:// endpoint with a port.')
        return _http_ws(explicit) if explicit.startswith('http:') else explicit
    for root in profile_roots():
        try:
            rows = (root / 'DevToolsActivePort').read_text(encoding='utf-8').splitlines()
            port = int(rows[0])
            if not 1 <= port <= 65535:
                continue
            try:
                return _http_ws(f'http://127.0.0.1:{port}')
            except urllib.error.HTTPError as error:
                # Chrome 147+ may disable /json discovery; its exact local WS path still works.
                if error.code in {403, 404} and len(rows) > 1 and rows[1].startswith('/devtools/browser/'):
                    return f'ws://127.0.0.1:{port}{rows[1]}'
            except (OSError, ValueError, KeyError):
                continue
        except (OSError, ValueError, IndexError):
            continue
    raise RuntimeError('Open chrome://inspect/#remote-debugging and enable remote debugging for this Chrome instance, then try again.')


async def discover(explicit: str = '') -> str:
    return await asyncio.to_thread(_discover, explicit)


async def find_marked_target(browser, source: dict) -> str:
    response = await browser.cdp_client.send_raw('Target.getTargets')
    token = source['token']
    expression = 'document.documentElement.getAttribute("data-flubber-tab") === ' + json.dumps(token)
    origin = urlparse(source['url']).netloc
    candidates = [t for t in response['targetInfos'] if t.get('type') == 'page'
                  and urlparse(t.get('url', '')).netloc == origin]
    for target in candidates:
        session = await browser.get_or_create_cdp_session(target['targetId'], focus=False)
        try:
            result = await browser.cdp_client.send_raw('Runtime.evaluate', {
                'expression': expression, 'returnByValue': True
            }, session_id=session.session_id)
            if result.get('result', {}).get('value') is True:
                return target['targetId']
        except Exception:
            continue
    raise RuntimeError('The starting tab changed or this companion is connected to another Chrome profile. Return to the page, click Flubber’s toolbar icon, and submit again.')
