import asyncio
import json
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from server.agent_runner import AgentRunner, compact_codex_event, estimate_usage, normalized_bob_error, redact_event_text


class AgentRunnerTests(unittest.TestCase):
    def test_exact_failed_bob_auth_marker_becomes_typed_event(self):
        event = {'type':'item.completed','item':{'type':'command_execution','status':'failed',
                 'command':'./bob fetch --query account_daily',
                 'aggregated_output':'BOB_ERROR_CODE=GOOGLE_AUTH_REQUIRED\nerror: connect first'}}
        self.assertEqual(normalized_bob_error(event), {
            'type':'bob.error','code':'GOOGLE_AUTH_REQUIRED',
        })
        event['item']['status'] = 'completed'
        self.assertIsNone(normalized_bob_error(event))
        event['item']['status'] = 'failed'
        event['item']['aggregated_output'] = 'error: GOOGLE_AUTH_REQUIRED was mentioned in prose'
        self.assertIsNone(normalized_bob_error(event))

    def test_jsonl_reader_emits_raw_command_then_typed_bob_error(self):
        async def exercise():
            stream = asyncio.StreamReader()
            stream.feed_data((json.dumps({'type':'item.completed','item':{
                'type':'command_execution','status':'failed',
                'aggregated_output':'BOB_ERROR_CODE=GOOGLE_AUTH_REQUIRED\nerror: connect first',
            }})+'\n').encode())
            stream.feed_eof(); events=[]
            async def emit(event): events.append(event)
            await AgentRunner._read_jsonl(stream, 10000, emit)
            self.assertEqual(events[-1], {'type':'bob.error','code':'GOOGLE_AUTH_REQUIRED'})
            self.assertEqual(len(events), 2)
        asyncio.run(exercise())

    def test_cumulative_usage_becomes_per_job_estimates_and_handles_reset(self):
        previous = {'input_tokens': 800, 'cached_input_tokens': 500, 'output_tokens': 80}
        current = {'input_tokens': 1100, 'cached_input_tokens': 700, 'output_tokens': 120}
        self.assertEqual(estimate_usage(current, previous), {
            'input_tokens': 300, 'cached_input_tokens': 200, 'output_tokens': 40,
        })
        reset = {'input_tokens': 90, 'cached_input_tokens': 50, 'output_tokens': 12}
        self.assertEqual(estimate_usage(reset, current), reset)

    def test_compact_event_keeps_usage_but_omits_command_arguments_and_large_output(self):
        usage = compact_codex_event({'type': 'turn.completed', 'usage': {
            'input_tokens': 123, 'cached_input_tokens': 45, 'output_tokens': 6,
            'irrelevant': 999,
        }})
        self.assertEqual(usage, {'type': 'turn.completed', 'usage': {
            'input_tokens': 123, 'cached_input_tokens': 45, 'output_tokens': 6,
        }})
        command = compact_codex_event({'type': 'item.completed', 'item': {
            'type': 'command_execution',
            'command': './bob fetch --developer-token super-secret --query account_daily',
            'status': 'completed', 'aggregated_output': 'x' * 100_000,
        }})
        encoded = json.dumps(command).encode()
        self.assertLessEqual(len(encoded), 8 * 1024)
        self.assertEqual(command['item']['tool'], 'bob')
        self.assertEqual(command['item']['subcommand'], 'fetch')
        self.assertNotIn('super-secret', encoded.decode())
        self.assertNotIn('aggregated_output', command['item'])
        self.assertEqual(compact_codex_event({'type':'bob.error','code':'GOOGLE_AUTH_REQUIRED'}),
                         {'type':'bob.error','code':'GOOGLE_AUTH_REQUIRED'})

    def test_compact_event_redacts_secret_and_path_from_preview(self):
        event = compact_codex_event({'type': 'error', 'message':
                                     'developer_token=abc123 failed at /Users/someone/private/file'})
        self.assertIn('[REDACTED]', event['error'])
        self.assertIn('[path]', event['error'])
        self.assertNotIn('abc123', event['error'])
        self.assertLessEqual(len(redact_event_text('é' * 3000, 2048).encode()), 2048)

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
