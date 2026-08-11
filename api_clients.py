from __future__ import annotations

import asyncio
import base64
import copy
import json
import mimetypes
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

try:
    from .router_core import GenerationInput, RouteEntry
except (
    ImportError
):  # pragma: no cover - AstrBot may add the plugin directory to sys.path.
    from router_core import GenerationInput, RouteEntry


class RoutedModelError(RuntimeError):
    """Raised when every configured API key fails to produce a routed response."""


class RoutedModelHTTPError(RoutedModelError):
    def __init__(self, status_code: int, response_excerpt: str) -> None:
        super().__init__(f"HTTP {status_code}: {response_excerpt}")
        self.status_code = status_code

    @property
    def should_try_next_key(self) -> bool:
        return self.status_code in {401, 403, 408, 409, 429} or self.status_code >= 500


class RoutedModelClient:
    def __init__(
        self,
        request_timeout_seconds: float = 90.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._request_timeout_seconds = request_timeout_seconds
        self._session = session
        self._owns_session = session is None
        self._key_offsets: dict[str, int] = {}
        self._key_offset_lock = asyncio.Lock()

    async def close(self) -> None:
        if (
            self._owns_session
            and self._session is not None
            and not self._session.closed
        ):
            await self._session.close()

    async def generate(
        self,
        route_entry: RouteEntry,
        generation_input: GenerationInput,
    ) -> str:
        api_keys = route_entry.api_keys or ("",)
        ordered_api_keys = await self._rotate_api_keys(route_entry.route_id, api_keys)
        final_error: Exception | None = None

        for api_key_index, api_key in enumerate(ordered_api_keys):
            try:
                if route_entry.provider_kind == "gemini":
                    return await self._generate_gemini(
                        route_entry, generation_input, api_key
                    )
                return await self._generate_openai_compatible(
                    route_entry,
                    generation_input,
                    api_key,
                )
            except RoutedModelHTTPError as error:
                final_error = error
                has_another_key = api_key_index + 1 < len(ordered_api_keys)
                if not error.should_try_next_key or not has_another_key:
                    break
            except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                final_error = error
                if api_key_index + 1 >= len(ordered_api_keys):
                    break

        if final_error is None:
            raise RoutedModelError("No routed model request was attempted.")
        raise RoutedModelError(str(final_error)) from final_error

    async def _rotate_api_keys(
        self,
        route_id: str,
        api_keys: tuple[str, ...],
    ) -> tuple[str, ...]:
        async with self._key_offset_lock:
            current_offset = self._key_offsets.get(route_id, 0) % len(api_keys)
            self._key_offsets[route_id] = (current_offset + 1) % len(api_keys)
        return api_keys[current_offset:] + api_keys[:current_offset]

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._request_timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._owns_session = True
        return self._session

    async def _generate_openai_compatible(
        self,
        route_entry: RouteEntry,
        generation_input: GenerationInput,
        api_key: str,
    ) -> str:
        request_url = self._build_openai_request_url(route_entry.api_base_url)
        request_headers = {"Content-Type": "application/json"}
        if api_key:
            request_headers["Authorization"] = f"Bearer {api_key}"

        request_payload = {
            "model": route_entry.model_name,
            "messages": await self._build_openai_messages(generation_input),
            "stream": False,
        }
        response_payload = await self._post_json(
            request_url, request_headers, request_payload
        )
        response_text = self._extract_openai_response_text(response_payload)
        if not response_text:
            raise RoutedModelError(
                "The routed model returned an empty OpenAI-compatible response."
            )
        return response_text

    async def _generate_gemini(
        self,
        route_entry: RouteEntry,
        generation_input: GenerationInput,
        api_key: str,
    ) -> str:
        request_url = self._build_gemini_request_url(
            route_entry.api_base_url,
            route_entry.model_name,
        )
        request_headers = {"Content-Type": "application/json"}
        if api_key:
            request_headers["x-goog-api-key"] = api_key

        request_payload = await self._build_gemini_payload(generation_input)
        response_payload = await self._post_json(
            request_url, request_headers, request_payload
        )
        response_text = self._extract_gemini_response_text(response_payload)
        if not response_text:
            raise RoutedModelError(
                "The routed model returned an empty Gemini response."
            )
        return response_text

    async def _post_json(
        self,
        request_url: str,
        request_headers: Mapping[str, str],
        request_payload: Mapping[str, Any],
    ) -> Any:
        session = await self._get_session()
        async with session.post(
            request_url,
            headers=dict(request_headers),
            json=dict(request_payload),
        ) as response:
            response_text = await response.text()
            if response.status < 200 or response.status >= 300:
                response_excerpt = response_text.replace("\n", " ")[:500]
                raise RoutedModelHTTPError(response.status, response_excerpt)
            try:
                return json.loads(response_text)
            except json.JSONDecodeError as error:
                raise RoutedModelError(
                    "The routed model returned invalid JSON."
                ) from error

    @staticmethod
    def _build_openai_request_url(api_base_url: str) -> str:
        normalized_base_url = api_base_url.rstrip("/")
        if normalized_base_url.endswith("/chat/completions"):
            return normalized_base_url
        return f"{normalized_base_url}/chat/completions"

    @staticmethod
    def _build_gemini_request_url(api_base_url: str, model_name: str) -> str:
        normalized_base_url = api_base_url.rstrip("/")
        encoded_model_name = quote(model_name, safe="-_.")
        if "{model}" in normalized_base_url:
            return normalized_base_url.replace("{model}", encoded_model_name)
        if normalized_base_url.endswith(":generateContent"):
            return normalized_base_url
        return f"{normalized_base_url}/models/{encoded_model_name}:generateContent"

    async def _build_openai_messages(
        self,
        generation_input: GenerationInput,
    ) -> list[dict[str, Any]]:
        messages = self._sanitize_contexts(generation_input.contexts)
        if generation_input.system_prompt:
            messages.insert(
                0,
                {"role": "system", "content": generation_input.system_prompt},
            )

        current_user_parts: list[dict[str, Any]] = []
        combined_user_text = "\n".join(
            text
            for text in (generation_input.prompt, *generation_input.extra_user_texts)
            if text
        )
        if combined_user_text:
            current_user_parts.append({"type": "text", "text": combined_user_text})

        for image_url in generation_input.image_urls:
            normalized_image_url = await self._normalize_media_as_data_url(image_url)
            if normalized_image_url:
                current_user_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": normalized_image_url},
                    }
                )

        if current_user_parts:
            content: str | list[dict[str, Any]]
            if (
                len(current_user_parts) == 1
                and current_user_parts[0].get("type") == "text"
            ):
                content = str(current_user_parts[0]["text"])
            else:
                content = current_user_parts
            messages.append({"role": "user", "content": content})
        return messages

    async def _build_gemini_payload(
        self,
        generation_input: GenerationInput,
    ) -> dict[str, Any]:
        sanitized_contexts = self._sanitize_contexts(generation_input.contexts)
        contents: list[dict[str, Any]] = []
        system_texts: list[str] = []

        for context_message in sanitized_contexts:
            role = str(context_message.get("role", "user"))
            text_content = self._flatten_content_to_text(context_message.get("content"))
            if not text_content:
                continue
            if role == "system":
                system_texts.append(text_content)
                continue
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": text_content}]})

        if generation_input.system_prompt:
            system_texts.insert(0, generation_input.system_prompt)

        current_user_parts: list[dict[str, Any]] = []
        combined_user_text = "\n".join(
            text
            for text in (generation_input.prompt, *generation_input.extra_user_texts)
            if text
        )
        if combined_user_text:
            current_user_parts.append({"text": combined_user_text})

        for media_path in (*generation_input.image_urls, *generation_input.audio_urls):
            inline_media = await self._read_media_as_gemini_inline_data(media_path)
            if inline_media:
                current_user_parts.append({"inline_data": inline_media})

        if current_user_parts:
            contents.append({"role": "user", "parts": current_user_parts})

        request_payload: dict[str, Any] = {"contents": contents}
        if system_texts:
            request_payload["systemInstruction"] = {
                "parts": [{"text": "\n".join(system_texts)}]
            }
        return request_payload

    @staticmethod
    def _sanitize_contexts(
        contexts: tuple[dict[str, Any], ...],
    ) -> list[dict[str, Any]]:
        sanitized_contexts: list[dict[str, Any]] = []
        for raw_context in contexts:
            if not isinstance(raw_context, Mapping):
                continue
            if (
                raw_context.get("role") == "checkpoint"
                or raw_context.get("type") == "checkpoint"
            ):
                continue
            sanitized_context = copy.deepcopy(dict(raw_context))
            sanitized_context.pop("_no_save", None)
            sanitized_contexts.append(sanitized_context)
        return sanitized_contexts

    @staticmethod
    def _flatten_content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""

        text_parts: list[str] = []
        for content_part in content:
            if not isinstance(content_part, Mapping):
                continue
            part_type = content_part.get("type")
            if part_type in {"text", "input_text", "output_text"}:
                text_value = content_part.get("text")
                if text_value:
                    text_parts.append(str(text_value))
        return "\n".join(text_parts)

    @staticmethod
    async def _normalize_media_as_data_url(media_location: str) -> str:
        if media_location.startswith(("http://", "https://", "data:")):
            return media_location
        media_path = Path(media_location)
        if not media_path.is_file():
            return ""
        media_bytes = await asyncio.to_thread(media_path.read_bytes)
        mime_type = (
            mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
        )
        encoded_media = base64.b64encode(media_bytes).decode("ascii")
        return f"data:{mime_type};base64,{encoded_media}"

    @staticmethod
    async def _read_media_as_gemini_inline_data(
        media_location: str,
    ) -> dict[str, str] | None:
        if media_location.startswith("data:") and ";base64," in media_location:
            metadata, encoded_data = media_location.split(",", 1)
            mime_type = metadata[5:].split(";", 1)[0] or "application/octet-stream"
            return {"mime_type": mime_type, "data": encoded_data}
        if media_location.startswith(("http://", "https://")):
            return None

        media_path = Path(media_location)
        if not media_path.is_file():
            return None
        media_bytes = await asyncio.to_thread(media_path.read_bytes)
        mime_type = (
            mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
        )
        return {
            "mime_type": mime_type,
            "data": base64.b64encode(media_bytes).decode("ascii"),
        }

    @staticmethod
    def _extract_openai_response_text(response_payload: Any) -> str:
        if not isinstance(response_payload, Mapping):
            return ""
        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first_choice = choices[0]
        if not isinstance(first_choice, Mapping):
            return ""
        message = first_choice.get("message")
        if not isinstance(message, Mapping):
            return ""

        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts = [
                str(content_part.get("text", ""))
                for content_part in content
                if isinstance(content_part, Mapping)
                and content_part.get("type") in {"text", "output_text"}
            ]
            return "".join(text_parts).strip()

        reasoning_content = message.get("reasoning_content")
        return str(reasoning_content).strip() if reasoning_content else ""

    @staticmethod
    def _extract_gemini_response_text(response_payload: Any) -> str:
        if not isinstance(response_payload, Mapping):
            return ""
        candidates = response_payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return ""
        first_candidate = candidates[0]
        if not isinstance(first_candidate, Mapping):
            return ""
        content = first_candidate.get("content")
        if not isinstance(content, Mapping):
            return ""
        parts = content.get("parts")
        if not isinstance(parts, list):
            return ""
        text_parts = [
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, Mapping) and part.get("text")
        ]
        return "".join(text_parts).strip()
