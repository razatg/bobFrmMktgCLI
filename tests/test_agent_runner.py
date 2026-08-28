import asyncio
import json
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from server.agent_runner import AgentRunner


class AgentRunnerTests(unittest.TestCase):
    def test_timeout_is_explicit_and_process_group_is_stopped(self):
        async def exercise():
            with tempfile.TemporaryDirectory() as directory:
                executable = os.path.join(directory, 'fake-codex')
                with open(executable, 'w', encoding='utf-8') as handle:
                    handle.write('#!/bin/sh\nsleep 30\n')
                os.chmod(executable, os.stat(executable).st_mode | stat.S_IXUSR)
                runner = AgentRunner(executable=executable)

                async def emit(_event):
                    pass

                with patch.dict(os.environ, {'BOB_RUNTIME': 'desktop'}):
                    with self.assertRaisesRegex(RuntimeError, 'agent timed out after 1 seconds'):
                        await runner.run('codex', None, 'test', directory,
                                         type('Policy', (), {'environment': None, 'model': None,
                                                             'timeout_seconds': 1,
                                                             'max_output_bytes': 1000})(),
                                         emit)

        asyncio.run(exercise())

    def test_large_codex_jsonl_event_exceeds_default_stream_line_limit(self):
        async def exercise():
            stream = asyncio.StreamReader(limit=64 * 1024)
            response = 'x' * (128 * 1024)
            stream.feed_data((json.dumps({
                'type': 'item.completed',
                'item': {'type': 'agent_message', 'text': response},
            }) + '\n').encode())
            stream.feed_eof()
            events = []

            async def emit(event):
                events.append(event)

            thread_id, final = await AgentRunner._read_jsonl(
                stream, 2_000_000, emit, 'existing-session'
            )
            self.assertEqual(thread_id, 'existing-session')
            self.assertEqual(final, response)
            self.assertEqual(len(events), 1)

        asyncio.run(exercise())

    def test_codex_output_limit_is_still_enforced(self):
        async def exercise():
            stream = asyncio.StreamReader()
            stream.feed_data(b'x' * 100)
            stream.feed_eof()

            async def emit(_event):
                pass

            with self.assertRaisesRegex(RuntimeError, 'agent output limit exceeded'):
                await AgentRunner._read_jsonl(stream, 50, emit)

        asyncio.run(exercise())


if __name__ == '__main__':
    unittest.main()
