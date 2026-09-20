from __future__ import annotations

import argparse
import asyncio
import logging
from flubber.config import load_settings


def main():
    parser = argparse.ArgumentParser(description='Run Flubber’s local companion.')
    parser.add_argument('--check', action='store_true', help='Check local dependencies and key configuration without making an API request.')
    args = parser.parse_args()
    settings = load_settings()
    from flubber.engine import BrowserUseEngine
    from flubber.server import create_app
    from aiohttp import web
    # Keep the user's terminal focused on setup/errors; progress belongs in the panel.
    logging.disable(logging.INFO)
    if args.check:
        from importlib.metadata import version
        print(f'Browser Use: {version("browser-use")}')
        print(f'OpenAI SDK: {version("openai")}')
        print(f'Model: {settings.model}')
        print(f'Voice model: {settings.voice_model}')
        print('API key configured:', 'yes' if settings.api_key else 'no')
        print('No OpenAI request or browser action was performed.')
        return
    if not settings.api_key:
        print('No OpenAI key yet. Run configure.py to save it locally, then restart.')
    print('\nFlubber companion is running')
    print(f'Pairing code: {settings.pairing_token}')
    print('Paste this code into Flubber’s Connect dialog. It is not your OpenAI key.')
    print(f'Practice page: http://127.0.0.1:{settings.port}/test')
    print('Keep this terminal open while using Flubber.\n')
    logging.getLogger('aiohttp.access').setLevel(logging.ERROR)
    web.run_app(create_app(settings, BrowserUseEngine(settings)), host='127.0.0.1', port=settings.port, access_log=None)


if __name__ == '__main__':
    main()
