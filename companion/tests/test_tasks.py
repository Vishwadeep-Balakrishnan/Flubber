import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from flubber.tasks import TaskManager, ACTIVE


class ControlledEngine:
    def __init__(self):
        self.revisions = []
        self.ready = asyncio.Event()
        self.finish = asyncio.Event()
        self.cleanup_count = 0

    async def execute(self, run, revision):
        self.revisions.append((revision, run.task_prompt()))
        try:
            run.checkpoint(revision)
            await run.emit('running', 'Entering text', action=True)
            self.ready.set()
            await self.finish.wait()
            run.checkpoint(revision)
            return {'success': True, 'result': 'The page confirms it was saved.'}
        finally:
            self.cleanup_count += 1


class TaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = ControlledEngine()
        self.manager = TaskManager(Path(self.temp.name), self.engine)

    async def asyncTearDown(self):
        await self.manager.close()
        self.temp.cleanup()

    async def start(self, request_id='request-1'):
        result = await self.manager.start('Fill the form.', {'site': 'example.test'}, request_id)
        await self.engine.ready.wait()
        return result

    async def test_start_completion_and_persistence(self):
        await self.start()
        self.engine.finish.set()
        await self.manager.current.supervisor
        self.assertEqual(self.manager.current.status, 'completed')
        self.assertEqual(len(self.manager.history), 1)
        restored = TaskManager(Path(self.temp.name), ControlledEngine())
        self.assertEqual(restored.history[0]['result'], 'The page confirms it was saved.')

    async def test_stop_does_not_become_completed(self):
        run = await self.start()
        await self.manager.stop(run['id'])
        await self.manager.current.supervisor
        self.assertEqual(self.manager.current.status, 'stopped')
        self.assertEqual(self.engine.cleanup_count, 1)

    async def test_update_cancels_old_revision_before_new_execution(self):
        run = await self.start()
        await self.manager.update(run['id'], 'Use Weekly instead.')
        for _ in range(20):
            await asyncio.sleep(0)
            if len(self.engine.revisions) == 2:
                break
        self.assertEqual(len(self.engine.revisions), 2)
        self.assertEqual(self.engine.cleanup_count, 1)
        self.assertIn('Use Weekly instead.', self.engine.revisions[-1][1])
        self.engine.finish.set()
        await self.manager.current.supervisor
        self.assertEqual(self.manager.current.status, 'completed')
        self.assertEqual(len(self.manager.history), 1)

    async def test_duplicate_request_is_idempotent_and_second_task_rejected(self):
        one = await self.start()
        same = await self.manager.start('Fill the form.', {}, 'request-1')
        self.assertEqual(one['id'], same['id'])
        with self.assertRaises(ValueError):
            await self.manager.start('Another task', {}, 'request-2')

    async def test_restart_never_replays_an_active_task(self):
        await self.start()
        restored = TaskManager(Path(self.temp.name), ControlledEngine())
        self.assertEqual(restored.snapshot()['current']['status'], 'interrupted')
        self.assertEqual(len(restored.history), 1)
        self.assertIsNone(restored.current)

    async def test_stale_revision_is_blocked(self):
        run = await self.start()
        previous = self.manager.current.revision
        await self.manager.update(run['id'], 'A correction')
        with self.assertRaises(asyncio.CancelledError):
            self.manager.current.checkpoint(previous)

    async def test_terminal_task_cannot_accept_updates(self):
        run = await self.start()
        self.engine.finish.set()
        await self.manager.current.supervisor
        with self.assertRaises(ValueError):
            await self.manager.update(run['id'], 'Too late')
