"""Mint short-lived OpenAI Realtime keys so the side panel can stream voice over WebRTC.

The real API key never leaves the companion. The side panel receives an ephemeral
key that only opens one transcription session and expires after two minutes.
"""
from __future__ import annotations

import httpx

CLIENT_SECRETS_URL = 'https://api.openai.com/v1/realtime/client_secrets'


def session_config(model: str) -> dict:
    return {
        'expires_after': {'anchor': 'created_at', 'seconds': 120},
        'session': {
            'type': 'transcription',
            'audio': {'input': {
                'transcription': {'model': model},
                # Push-to-talk: the panel commits the audio buffer when the mic is released.
                'turn_detection': None,
                'noise_reduction': {'type': 'near_field'},
            }},
        },
    }


async def create_voice_key(api_key: str, model: str, client: httpx.AsyncClient | None = None) -> str:
    owned = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        response = await client.post(CLIENT_SECRETS_URL, json=session_config(model),
                                     headers={'Authorization': f'Bearer {api_key}'})
    except httpx.HTTPError as error:
        raise RuntimeError('Could not reach OpenAI for voice. Check the internet connection.') from error
    finally:
        if owned:
            await client.aclose()
    if response.status_code != 200:
        messages = {
            401: 'OpenAI rejected the API key. Update companion/.env and restart.',
            403: f'This OpenAI project does not have access to {model}.',
            404: f'{model} is not available to this OpenAI project.',
            429: 'OpenAI usage or rate limit reached. Check API billing and limits.',
        }
        raise RuntimeError(messages.get(response.status_code, f'OpenAI voice setup returned HTTP {response.status_code}.'))
    data = response.json()
    value = data.get('value') or (data.get('client_secret') or {}).get('value')
    if not isinstance(value, str) or not value:
        raise RuntimeError('OpenAI did not return a voice session key.')
    return value
