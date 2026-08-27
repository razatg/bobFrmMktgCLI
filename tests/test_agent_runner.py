import asyncio
import json
import unittest

from server.agent_runner import AgentRunner


class AgentRunnerTests(unittest.TestCase):
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
