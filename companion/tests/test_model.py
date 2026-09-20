import json
import unittest
import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel
from browser_use.llm.messages import SystemMessage, UserMessage, AssistantMessage, ContentPartTextParam, ContentPartImageParam, ImageURL
from browser_use.llm.exceptions import ModelProviderError
from flubber.model import ResponsesModel, response_messages


class Answer(BaseModel):
    answer: str


def response_json(text):
    return {
        'id': 'resp_test', 'object': 'response', 'created_at': 1,
        'model': 'gpt-6-luna', 'status': 'completed', 'error': None,
        'output': [{'id': 'msg_test', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                    'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}],
        'usage': {'input_tokens': 10, 'output_tokens': 3, 'total_tokens': 13,
                  'input_tokens_details': {'cached_tokens': 2}, 'output_tokens_details': {'reasoning_tokens': 0}}
    }


class ModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_sends_responses_structured_output_and_reasoning(self):
        captured = []
        def handler(request):
            captured.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200, json=response_json('{"answer":"ready"}'))
        client = AsyncOpenAI(api_key='test-not-a-real-key', http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        model = ResponsesModel('unused', client=client)
        answer = await model.ainvoke([SystemMessage(content='Help.'), UserMessage(content='Ready?')], Answer)
        self.assertEqual(answer.completion.answer, 'ready')
        path, params = captured[0]
        self.assertEqual(path, '/v1/responses')
        self.assertEqual(params['model'], 'gpt-6-luna')
        self.assertEqual(params['reasoning'], {'effort': 'low'})
        self.assertFalse(params['store'])
        self.assertEqual(params['text']['format']['type'], 'json_schema')
        self.assertNotIn('temperature', params)
        self.assertEqual(answer.usage.total_tokens, 13)
        await model.close()

    async def test_authentication_error_does_not_expose_key(self):
        def handler(request):
            return httpx.Response(401, json={'error': {'message': 'Bad key sk-private', 'type': 'invalid_request_error'}})
        client = AsyncOpenAI(api_key='test', max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        model = ResponsesModel('unused', client=client)
        with self.assertRaises(ModelProviderError) as caught:
            await model.ainvoke([UserMessage(content='Hello')], Answer)
        self.assertNotIn('sk-private', str(caught.exception))
        self.assertIn('API key', str(caught.exception))
        await model.close()

    async def test_images_and_assistant_history_are_serialized(self):
        messages = response_messages([
            UserMessage(content=[ContentPartTextParam(text='This page'), ContentPartImageParam(image_url=ImageURL(url='data:image/png;base64,AA=='))]),
            AssistantMessage(content=[ContentPartTextParam(text='An earlier result')])
        ])
        self.assertEqual(messages[0]['content'][1]['type'], 'input_image')
        self.assertEqual(messages[1]['content'], 'An earlier result')


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_key_requests_a_push_to_talk_transcription_session(self):
        from flubber.voice import create_voice_key
        captured = []
        def handler(request):
            captured.append((request.url.path, request.headers['Authorization'], json.loads(request.content)))
            return httpx.Response(200, json={'value': 'ek_short_lived', 'expires_at': 1})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            self.assertEqual(await create_voice_key('sk-test', 'gpt-live-transcribe', client), 'ek_short_lived')
        path, auth, body = captured[0]
        self.assertEqual(path, '/v1/realtime/client_secrets')
        self.assertEqual(auth, 'Bearer sk-test')
        self.assertEqual(body['session']['type'], 'transcription')
        self.assertEqual(body['session']['audio']['input']['transcription']['model'], 'gpt-live-transcribe')
        self.assertIsNone(body['session']['audio']['input']['turn_detection'])

    async def test_voice_key_errors_are_readable(self):
        from flubber.voice import create_voice_key
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={}))) as client:
            with self.assertRaisesRegex(RuntimeError, 'API key'):
                await create_voice_key('sk-test', 'gpt-live-transcribe', client)
