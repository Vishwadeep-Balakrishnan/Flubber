"""Save your OpenAI API key locally in companion/.env. The extension never sees it."""
import getpass
import os
import argparse
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument('--if-missing', action='store_true')
    args = parser.parse_args()
    if args.if_missing:
        from dotenv import dotenv_values
        if os.environ.get('OPENAI_API_KEY') or dotenv_values(root / '.env').get('OPENAI_API_KEY'):
            return
    key = getpass.getpass('Paste your OpenAI API key (hidden), then press Enter: ').strip()
    if not key or any(c.isspace() for c in key) or len(key) < 20:
        raise SystemExit('That does not look like an API key. Nothing was saved.')
    path = root / '.env'
    # Replace only the key line, retaining optional local browser configuration.
    lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    lines = [line for line in lines if not line.startswith('OPENAI_API_KEY=')]
    lines.insert(0, 'OPENAI_API_KEY=' + key)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    try:
        path.chmod(0o600)
    except OSError:
        pass
    print('Key saved in companion/.env. Start the companion to connect Flubber.')


if __name__ == '__main__':
    main()
