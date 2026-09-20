from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def local_network():
    # Chrome and the companion are local even when the user has an HTTP/SOCKS proxy.
    for variable in ('NO_PROXY', 'no_proxy'):
        values = [v.strip() for v in os.environ.get(variable, '').split(',') if v.strip()]
        for host in ('127.0.0.1', 'localhost', '::1'):
            if host not in values:
                values.append(host)
        os.environ[variable] = ','.join(values)


@dataclass(frozen=True)
class Settings:
    api_key: str
    state_dir: Path
    pairing_token: str
    cdp_url: str = ""
    model: str = "gpt-6-luna"
    voice_model: str = "gpt-live-transcribe"
    reasoning: str = "low"
    max_steps: int = 40
    port: int = 8765


def load_settings() -> Settings:
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
    local_network()
    # Set these before Browser Use is imported.
    os.environ.setdefault('ANONYMIZED_TELEMETRY', 'false')
    os.environ.setdefault('BROWSER_USE_CLOUD_SYNC', 'false')
    os.environ.setdefault('BROWSER_USE_LOGGING_LEVEL', 'error')
    state_dir = Path(os.environ.get('FLUBBER_STATE_DIR', str(ROOT / '.flubber'))).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        state_dir.chmod(0o700)
    except OSError:
        pass
    token_path = state_dir / 'pairing-token'
    if token_path.exists():
        token = token_path.read_text(encoding='utf-8').strip()
    else:
        token = secrets.token_urlsafe(32)
        token_path.write_text(token, encoding='utf-8')
        try:
            token_path.chmod(0o600)
        except OSError:
            pass
    if len(token) < 32:
        raise RuntimeError('The local pairing token is invalid. Remove .flubber/pairing-token and restart.')
    effort = os.environ.get('FLUBBER_REASONING_EFFORT', 'low')
    if effort not in {'none', 'low', 'medium', 'high', 'xhigh', 'max'}:
        raise RuntimeError('Unsupported FLUBBER_REASONING_EFFORT.')
    max_steps = int(os.environ.get('FLUBBER_MAX_STEPS', '40'))
    if not 1 <= max_steps <= 200:
        raise RuntimeError('FLUBBER_MAX_STEPS must be between 1 and 200.')
    return Settings(
        api_key=os.environ.get('OPENAI_API_KEY', '').strip(), state_dir=state_dir,
        pairing_token=token, cdp_url=os.environ.get('FLUBBER_CDP_URL', '').strip(),
        model=os.environ.get('FLUBBER_MODEL', '').strip() or 'gpt-6-luna',
        voice_model=os.environ.get('FLUBBER_VOICE_MODEL', '').strip() or 'gpt-live-transcribe',
        reasoning=effort, max_steps=max_steps
    )
