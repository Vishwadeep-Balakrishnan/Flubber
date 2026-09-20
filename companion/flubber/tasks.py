from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ACTIVE = {'queued', 'connecting', 'running', 'waiting', 'stopping'}


def safe_error(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return 'The task reached its time limit. Review the current page before trying again.'
    text = str(error) or type(error).__name__
    text = re.sub(r'sk-[A-Za-z0-9_-]+', '[redacted]', text)
    if 'opening handshake' in text.lower() or 'websocket' in text.lower() and 'timeout' in text.lower():
        return 'Chrome did not connect. Accept Chrome’s remote debugging Allow prompt, then retry.'
    return text[:700]


@dataclass
class Run:
    manager: Any
    command: str
    source: dict
    request_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = 'queued'
    message: str = 'Starting your task'
    started_at: float = field(default_factory=lambda: time.time() * 1000)
    ended_at: float | None = None
    result: str = ''
    steps: int = 0
    revision: int = 0
    updates: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    target_id: str | None = None
    stopped: bool = False
    child: asyncio.Task | None = None
    supervisor: asyncio.Task | None = None

    def checkpoint(self, revision: int):
        if self.stopped or revision != self.revision:
            raise asyncio.CancelledError()

    def task_prompt(self) -> str:
        text = self.command
        if self.updates:
            text += '\n\nUser updates in order (latest wins):\n' + '\n'.join(f'- {u}' for u in self.updates)
        if self.events:
            text += '\n\nActions already attempted; inspect the current page before repeating anything:\n'
            text += '\n'.join(e['label'] for e in self.events[-15:])
        return text

    async def emit(self, status, message, action=False):
        if self.stopped:
            raise asyncio.CancelledError()
        self.status = status
        self.message = str(message)[:600]
        if action:
            self.steps += 1
            self.events.append({'label': self.message, 'at': time.time() * 1000})
            self.events = self.events[-100:]
        self.manager.persist()

    def public(self):
        return {
            'id': self.id, 'request_id': self.request_id, 'command': self.command,
            'site': self.source.get('site', 'Browser tab'), 'status': self.status,
            'message': self.message, 'startedAt': self.started_at, 'endedAt': self.ended_at,
            'result': self.result, 'steps': self.steps, 'updates': list(self.updates),
            'events': list(self.events[-8:]), 'revision': self.revision
        }


class TaskManager:
    def __init__(self, state_dir: Path, engine):
        self.state_dir = state_dir
        self.path = state_dir / 'tasks.json'
        self.engine = engine
        self.current: Run | None = None
        self.history = []
        self.previous = None
        self.lock = asyncio.Lock()
        self.watchers: set[asyncio.Queue] = set()
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            self.history = data.get('history', [])[:100]
            self.previous = data.get('current')
            if self.previous and self.previous.get('status') in ACTIVE:
                self.previous.update(status='interrupted', message='The companion restarted. Review the page before starting again.',
                                     result='The companion restarted. Review the current page before starting a new task; previously submitted actions may have completed.',
                                     endedAt=time.time() * 1000)
                self._remember(self.previous)
        except (OSError, ValueError, TypeError, AttributeError):
            self.history, self.previous = [], None

    def snapshot(self):
        return {'current': self.current.public() if self.current else self.previous,
                'history': self.history}

    def watch(self) -> asyncio.Queue:
        """Live listeners (the side panel WebSocket) receive the newest snapshot on every change."""
        queue = asyncio.Queue(maxsize=1)
        self.watchers.add(queue)
        return queue

    def unwatch(self, queue):
        self.watchers.discard(queue)

    def persist(self):
        snapshot = self.snapshot()
        for queue in self.watchers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(snapshot)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(self.path)

    def _remember(self, result):
        self.history = [result, *[r for r in self.history if r.get('id') != result['id']]][:100]

    async def start(self, command: str, source: dict, request_id: str):
        async with self.lock:
            if self.current and self.current.status in ACTIVE:
                if self.current.request_id == request_id:
                    return self.current.public()
                raise ValueError('A task is already running. Send an update or press Stop first.')
            for previous in self.history:
                if previous.get('request_id') == request_id:
                    return previous
            run = Run(self, command, source, request_id)
            self.current = run
            self.previous = None
            self.persist()
            run.supervisor = asyncio.create_task(self._supervise(run))
            return run.public()

    async def _supervise(self, run):
        try:
            async with asyncio.timeout(900):
                while not run.stopped:
                    revision = run.revision
                    run.child = asyncio.create_task(self.engine.execute(run, revision))
                    try:
                        result = await run.child
                    except asyncio.CancelledError:
                        if run.stopped:
                            break
                        if revision != run.revision:
                            continue
                        raise
                    if revision != run.revision:
                        continue
                    run.status = 'completed' if result['success'] else 'failed'
                    run.message = 'Task complete' if result['success'] else 'Task needs attention'
                    run.result = str(result['result'])[:12000]
                    break
        except asyncio.CancelledError:
            run.stopped = True
        except Exception as error:
            run.status = 'failed'
            run.message = safe_error(error)
            run.result = run.message
        finally:
            if run.stopped:
                run.status = 'stopped'
                run.message = 'Task stopped'
                run.result = 'Stopped issuing further actions. Actions already submitted may have completed.'
            run.ended_at = time.time() * 1000
            self._remember(run.public())
            self.persist()

    async def update(self, run_id, text):
        async with self.lock:
            run = self.current
            if not run or run.id != run_id or run.status not in ACTIVE or run.stopped:
                raise ValueError('This task is no longer running. Start a new task instead.')
            if len(run.updates) >= 50:
                raise ValueError('This task has many revisions. Stop it and start a fresh task.')
            run.updates.append(text)
            run.revision += 1
            run.status = 'running'
            run.message = 'Applying your update before the next action'
            self.persist()
            if run.child and not run.child.done() and not run.child.cancelling():
                run.child.cancel()
            return run.public()

    async def stop(self, run_id):
        async with self.lock:
            run = self.current
            if not run or run.id != run_id:
                raise ValueError('This task was not found.')
            if run.status not in ACTIVE:
                return run.public()
            run.stopped = True
            run.revision += 1
            run.status = 'stopping'
            run.message = 'Stopping further actions'
            self.persist()
            if run.child and not run.child.done() and not run.child.cancelling():
                run.child.cancel()
            return run.public()

    async def close(self):
        if self.current and self.current.status in ACTIVE:
            await self.stop(self.current.id)
            if self.current.supervisor:
                try:
                    await asyncio.wait_for(asyncio.shield(self.current.supervisor), 10)
                except (TimeoutError, asyncio.CancelledError):
                    pass
        if hasattr(self.engine, 'close'):
            await self.engine.close()
