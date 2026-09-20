"""A Browser Use chat-model adapter using OpenAI Responses, not Chat Completions."""
from __future__ import annotations

from typing import Any

from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage
from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError
from openai import AsyncOpenAI, APIStatusError, APIConnectionError, RateLimitError


def response_messages(messages: list[Any], model: str = 'gpt-6-luna') -> list[dict[str, Any]]:
    result = []
    for message in messages:
        role = message.role
        content = message.content
        if isinstance(content, str) or content is None:
            result.append({'role': role, 'content': content or ''})
            continue
        parts = []
        for part in content:
            if part.type == 'text':
                parts.append({'type': 'output_text' if role == 'assistant' else 'input_text', 'text': part.text})
            elif part.type == 'image_url':
                if role != 'user':
                    raise ModelProviderError(message='Images must be user inputs.', model=model)
                parts.append({'type': 'input_image', 'image_url': part.image_url.url, 'detail': part.image_url.detail})
            elif part.type == 'refusal':
                parts.append({'type': 'output_text', 'text': part.refusal})
        # Easy assistant messages accept a string, avoiding response-output annotations.
        if role == 'assistant':
            result.append({'role': role, 'content': '\n'.join(p['text'] for p in parts)})
        else:
            result.append({'role': role, 'content': parts})
    return result


class ResponsesModel:
    """Browser Use calls ainvoke(); this sends each step to the OpenAI Responses API."""
    provider = 'openai'
    _verified_api_keys = True

    def __init__(self, api_key: str, model: str = 'gpt-6-luna', reasoning: str = 'low', client: Any = None):
        self.model = self.name = self.model_name = model
        self.reasoning = reasoning
        self.last_error = None
        self.client = client or AsyncOpenAI(api_key=api_key, base_url='https://api.openai.com/v1', timeout=90, max_retries=1)

    async def ainvoke(self, messages: list[Any], output_format: Any = None, **kwargs: Any):
        params = {
            'model': self.model, 'input': response_messages(messages, self.model),
            'reasoning': {'effort': self.reasoning}, 'store': False,
            'max_output_tokens': 8192,
        }
        try:
            if output_format is not None:
                response = await self.client.responses.parse(**params, text_format=output_format)
                completion = response.output_parsed
            else:
                response = await self.client.responses.create(**params)
                completion = response.output_text
            if response.status == 'incomplete':
                raise ModelOutputTruncatedError(message='Model output was incomplete. Try a smaller task.', model=self.model)
            if completion is None:
                raise ModelProviderError(message='The model did not return a usable response.', model=self.model)
            self.last_error = None
            usage = response.usage
            mapped = None
            if usage:
                details = getattr(usage, 'input_tokens_details', None)
                mapped = ChatInvokeUsage(
                    prompt_tokens=usage.input_tokens,
                    prompt_cached_tokens=getattr(details, 'cached_tokens', None),
                    prompt_cache_creation_tokens=None, prompt_image_tokens=None,
                    completion_tokens=usage.output_tokens, total_tokens=usage.total_tokens
                )
            return ChatInvokeCompletion(completion=completion, usage=mapped, stop_reason=response.status)
        except RateLimitError as error:
            self.last_error = 'OpenAI usage or rate limit reached. Check API billing and limits.'
            raise ModelRateLimitError(message=self.last_error, model=self.model) from error
        except APIStatusError as error:
            messages = {
                401: 'OpenAI rejected the API key. Update companion/.env and restart.',
                403: f'This OpenAI project does not have access to {self.model}.',
                404: f'{self.model} is not available to this OpenAI project.',
            }
            self.last_error = messages.get(error.status_code, f'OpenAI returned HTTP {error.status_code}.')
            raise ModelProviderError(
                message=self.last_error,
                status_code=error.status_code, model=self.model
            ) from error
        except APIConnectionError as error:
            self.last_error = 'Could not reach OpenAI. Check the internet connection and proxy settings.'
            raise ModelProviderError(message=self.last_error, model=self.model) from error

    async def close(self):
        await self.client.close()
