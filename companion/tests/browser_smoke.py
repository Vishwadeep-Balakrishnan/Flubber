"""Real Browser Use + CDP smoke test with scripted model replies; no OpenAI requests."""
import argparse
import asyncio
import os
import re
import json
import tempfile
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ['ANONYMIZED_TELEMETRY'] = 'false'
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'
os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'error'

from flubber.config import Settings
from flubber.model import ResponsesModel
from flubber.tasks import TaskManager
from flubber import engine as engine_module


class ScriptedResponses:
    def __init__(self):
        self.step = 0
        self.pause_at = None
        self.gate = None

    async def parse(self, **params):
        output_format = params['text_format']
        if 'verdict' in output_format.model_fields:
            parsed = output_format.model_validate({'verdict': True})
        else:
            if self.pause_at == self.step:
                self.pause_at = None
                self.gate.set()
                await asyncio.Future()
            chunks = []
            for message in params['input']:
                content = message.get('content', '')
                chunks.append(content if isinstance(content, str) else '\n'.join(p.get('text', '') for p in content))
            text = '\n'.join(chunks)
            names = ['name', 'frequency', 'reminders', 'save']
            if self.step < len(names):
                name = names[self.step]
                pattern = r'\[(\d+)\][^\n]*\bid=[\"\x27]?' + name + r'(?:[\"\x27\s/>])'
                matches = re.findall(pattern, text)
                if not matches:
                    lines = [line for line in text.split('\n') if any(word in line for word in names)]
                    raise RuntimeError('Could not find fixture control '+name+': '+repr(lines[-15:]))
                index = int(matches[-1])
                action = ({'input': {'index': index, 'text': 'Vishwa', 'clear': True}} if self.step == 0
                          else {'select_dropdown': {'index': index, 'text': 'Monthly' if 'Use Monthly instead' in text else 'Weekly'}} if self.step == 1
                          else {'click': {'index': index}})
                self.step += 1
            else:
                if 'Saved for Vishwa' not in text:
                    raise RuntimeError('The practice page did not show the expected saved result.')
                frequency = 'monthly' if 'Use Monthly instead' in text else 'weekly'
                if 'Updates: '+frequency not in text:
                    raise RuntimeError('The corrected frequency was not saved on the page.')
                action = {'done': {'text':f'Saved for Vishwa. Updates: {frequency}. Reminders: on.', 'success':True}}
            parsed = output_format.model_validate({'memory':'Practice fixture only.', 'next_goal':'Complete the practice form.', 'evaluation_previous_goal':'Observed the page.', 'action':[action]})
        return SimpleNamespace(status='completed', output_parsed=parsed, usage=None)


class ScriptedClient:
    def __init__(self): self.responses = ScriptedResponses()
    async def close(self): pass


class OfflineModel(ResponsesModel):
    def __init__(self, api_key, model, reasoning): super().__init__('unused', model, reasoning, ScriptedClient())


async def main(args):
    engine_module.ResponsesModel = OfflineModel
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(api_key='offline-test-only', state_dir=Path(directory), pairing_token='test'*11, cdp_url=args.cdp, max_steps=10)
        engine = engine_module.BrowserUseEngine(settings)
        manager = TaskManager(settings.state_dir, engine)
        await manager.start('Enter Vishwa, choose Weekly, enable reminders, and save preferences.',
                            {'site':'practice.local','url':args.page,'token':args.token}, 'offline-smoke')
        await manager.current.supervisor
        result = manager.snapshot()['current']
        print('SMOKE_RESULT',result['status'],result['result'])
        if result['status'] != 'completed':
            await manager.close()
            raise SystemExit(1)
        client = engine.browser.cdp_client
        await engine.browser.start()
        session = await engine.browser.get_or_create_cdp_session()
        await client.send_raw('Page.navigate', {'url':args.page}, session_id=session.session_id)
        await asyncio.sleep(0.5)
        await client.send_raw('Runtime.evaluate', {'expression':'document.documentElement.setAttribute("data-flubber-tab",'+json.dumps(args.token)+')'}, session_id=session.session_id)
        await manager.start('Enter Vishwa, choose Weekly, enable reminders, and save preferences.',
                            {'site':'practice.local','url':args.page,'token':args.token}, 'offline-smoke-second')
        await manager.current.supervisor
        if manager.current.status != 'completed' or engine.browser.cdp_client is not client:
            print('Second run failed',manager.current.public())
            await manager.close()
            raise SystemExit(1)
        print('PASS: a second task reused the existing Chrome connection.')
        async def reset_fixture():
            await engine.browser.start()
            session = await engine.browser.get_or_create_cdp_session()
            await client.send_raw('Page.navigate', {'url':args.page}, session_id=session.session_id)
            await asyncio.sleep(0.5)
            await client.send_raw('Runtime.evaluate', {'expression':'document.documentElement.setAttribute("data-flubber-tab",'+json.dumps(args.token)+')'}, session_id=session.session_id)

        await reset_fixture()
        gate = asyncio.Event()
        class SteeringModel(ResponsesModel):
            count = 0
            def __init__(self, api_key, model, reasoning):
                provider = ScriptedClient()
                if SteeringModel.count == 0:
                    provider.responses.pause_at = 1
                    provider.responses.gate = gate
                SteeringModel.count += 1
                super().__init__('unused', model, reasoning, provider)
        engine_module.ResponsesModel = SteeringModel
        run = await manager.start('Enter Vishwa, choose Weekly, enable reminders, and save preferences.',
                                  {'site':'practice.local','url':args.page,'token':args.token}, 'offline-smoke-steer')
        await asyncio.wait_for(gate.wait(), 30)
        await manager.update(run['id'], 'Use Monthly instead of Weekly.')
        await manager.current.supervisor
        if manager.current.status != 'completed' or 'monthly' not in manager.current.result:
            print('Steering failed',manager.current.public())
            await manager.close()
            raise SystemExit(1)
        print('PASS: a typed correction cancelled live pending model work and saved Monthly on the real page.')

        await reset_fixture()
        gate.clear()
        SteeringModel.count = 0
        run = await manager.start('Enter Vishwa, choose Weekly, enable reminders, and save preferences.',
                                  {'site':'practice.local','url':args.page,'token':args.token}, 'offline-smoke-stop')
        await asyncio.wait_for(gate.wait(), 30)
        await manager.stop(run['id'])
        await manager.current.supervisor
        if manager.current.status != 'stopped':
            await manager.close()
            raise SystemExit(1)
        print('PASS: Stop cancelled live pending model work before the remaining page actions.')
        await manager.close()
        print('PASS: real Browser Use actions, mascot input wrapper, verified fixture result, no OpenAI network calls.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cdp',required=True)
    parser.add_argument('--page',required=True)
    parser.add_argument('--token',required=True)
    asyncio.run(main(parser.parse_args()))
