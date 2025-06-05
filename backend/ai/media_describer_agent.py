from __future__ import annotations

"""Media Describer Agent

This agent takes a list of MediaUrl objects (images or videos) together with the
original user query and produces a MediaTimelinePayload.  It relies on an
external multimodal LLM provided through the OpenRouter API.  The goal is to
obtain a concise, textual timeline that can be consumed by the correlator
agent without having to embed raw BinaryContent objects.

The implementation purposefully keeps the HTTP logic minimal and fully async
(using httpx.AsyncClient) so that multiple media files can be processed in
parallel.
"""

import logging
from typing import List, Optional
from enum import Enum
from dataclasses import dataclass

import httpx
from pydantic import BaseModel

from backend.config import get_settings

logger = logging.getLogger("ai.media_describer_agent")

# ----------------------------------------------------------------------------
# Helper pydantic model to capture the raw response we expect from OpenRouter
# ----------------------------------------------------------------------------


class _OpenRouterChoice(BaseModel):
    message: dict  # {"role": "assistant", "content": str}


class _OpenRouterResponse(BaseModel):
    choices: List[_OpenRouterChoice]

    def first_message_content(self) -> str:
        try:
            return self.choices[0].message["content"]
        except Exception:  # pragma: no cover – defensive
            return ""


# ----------------------------------------------------------------------------
# Main agent class
# ----------------------------------------------------------------------------


class MediaDescriberAgent:
    """Convert raw media URLs into a structured textual timeline."""

    _PROMPT_FOR_VIDEO = (
        "You will be given a video URL.  Generate a detailed timeline of events "
        "happening in the video.  Use bullet points ordered chronologically. "
        "For each bullet, include visible UI elements, text on screen, and any "
        "notable user interactions (clicks, typing, scrolling, etc.).  Be as "
        "specific as possible while remaining concise."
    )

    _PROMPT_FOR_IMAGE = (
        "You will be given an image.  Describe it in detail: visible text, UI "
        "elements, their positions (e.g., top-left), and anything that looks "
        "like an error message or warning."
    )

    def __init__(self):
        self.settings = get_settings()
        if not self.settings.openrouter_api_key:
            logger.warning("OpenRouter API key is not configured – media describing might fail.")

        self._headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            # Leaving HTTP-Referer / X-Title optional – configurable via env later.
        }

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    async def describe_media(self, original_query: str, urls: List[MediaUrl]) -> MediaTimelinePayload:
        """Return a MediaTimelinePayload for the given URLs."""

        # Perform a single multimodal call with **all** media URLs to reduce latency
        # and LLM invocation cost. The model is instructed to return descriptions
        # grouped by URL so we can split them back into individual timeline events.
        try:
            bulk_response = await self._describe_bulk(original_query, urls)
        except Exception as exc:
            logger.exception("Bulk media description call failed: %s", exc)
            bulk_response = ""

        # Parse the bulk response and map each URL to its description.
        url_to_desc = self._parse_bulk_response(bulk_response, urls)

        timeline_events: List[MediaTimelineEvent] = []
        for media in urls:
            desc = url_to_desc.get(media.url, "(No description returned)")
            timeline_events.append(
                MediaTimelineEvent(
                    image_identifier=media.url,
                    description=desc.strip(),
                    code_references=[],
                )
            )

        # High-level hypothesis – simple heuristic for now.
        hypothesis_text = (
            "Potential UI / functional issues may exist; refer to detailed timeline for context."
            if timeline_events
            else "No media descriptions were successfully generated."
        )

        return MediaTimelinePayload(
            hypothesis=hypothesis_text,
            timeline_events=timeline_events,
            original_query=original_query,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _describe_single(self, media: MediaUrl, original_query: str) -> str:
        """Call OpenRouter and return the raw assistant content."""

        # Compose a prompt that includes the high-level issue context provided by the user
        # followed by the modality-specific instructions.
        base_prompt = (
            self._PROMPT_FOR_VIDEO if media.type == UrlType.VIDEO else self._PROMPT_FOR_IMAGE
        )
        prompt = f"Issue context: {original_query}\n\n{base_prompt}"

        if media.type == UrlType.VIDEO:
            media_block = {"type": "video_url", "video_url": {"url": media.url}}
        else:
            media_block = {"type": "image_url", "image_url": {"url": media.url}}

        message_content = [
            {"type": "text", "text": prompt},
            media_block,
        ]

        payload = {
            "model": "google/gemini-2.5-pro-preview",
            "messages": [{"role": "user", "content": message_content}],
            # Temperature / other params could be made configurable.
            "max_tokens": 1024,
        }

        logger.info("Requesting media description for %s", media.url)

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=self._headers,
                json=payload,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"OpenRouter request failed (status {response.status_code}): {response.text}"
                )

            # Validate / extract.
            parsed = _OpenRouterResponse.model_validate_json(response.text)
            content = parsed.first_message_content()
            logger.info("Received description for %s (chars=%d)", media.url, len(content))
            return content

    # ------------------------------------------------------------------
    # Bulk helper – new implementation making a SINGLE LLM call
    # ------------------------------------------------------------------

    async def _describe_bulk(self, original_query: str, medias: List[MediaUrl]) -> str:
        """Describe a list of media objects with a single OpenRouter call."""

        # Craft a comprehensive prompt that tells the model exactly how we
        # expect the output so we can map it back deterministically.
        modality_instructions = []
        for m in medias:
            if m.type == UrlType.VIDEO:
                modality_instructions.append(f"- {m.url} → video – generate detailed timeline with timestamps")
            else:
                modality_instructions.append(f"- {m.url} → image – analyze all visible elements")
        joined_instructions = "\n".join(modality_instructions)
        prompt_text = (
            f"# Bug Analysis Context\n"
            f"Original issue: {original_query}\n\n"
            "You are a debugging assistant analyzing visual evidence of software bugs. Your task is to extract "
            "all information from the provided media that could help identify code responsible for the bug.\n\n"
            "You have to do a detailed RCA of the bug and provide a detailed timeline of the events that happened.\n\n"
            "## Analysis Instructions\n"
            "For each media item, create a structured description following these guidelines:\n\n"
            "### For Images:\n"
            "1. **UI Components**: Identify all visible UI elements (buttons, forms, panels, etc.)\n"
            "   - Note exact text on elements (labels, titles, button text)\n"
            "   - Look for component identifiers (class names, IDs, data attributes visible in DOM)\n"
            "   - Describe component states (active, disabled, loading, error states)\n"
            "2. **Error Messages**: Capture full text of any errors, warnings, or notifications\n"
            "3. **Data Content**: Describe visible data structures, lists, tables and their contents\n"
            "4. **Console/Logs**: Transcribe any visible terminal output, console logs, or debug text\n"
            "5. **Context Clues**: Note file names, paths, URLs or other identifying information\n\n"
            "### For Videos:\n"
            "1. **Chronological Timeline**: List key events with timestamps\n"
            "   - User interactions (clicks, typing, navigation)\n"
            "   - System responses (loading states, transitions, errors)\n"
            "   - State changes (before/after conditions)\n"
            "2. **Error Sequence**: Describe exact steps leading to and following any error\n"
            "3. **UI Changes**: Note appearing/disappearing elements and content changes\n"
            "4. **Performance Issues**: Identify lags, freezes, or unexpected behaviors\n"
            "5. **Error Details**: Capture complete text of any error messages that appear\n\n"
            "## Output Format\n"
            "For each URL, create a Markdown section with this structure:\n\n"
            "```\n"
            "<URL>:\n"
            "# Summary (1-2 sentences describing what's shown/happening)\n\n"
            "## Key Elements\n"
            "- Element 1: [description with exact text and identifiable details]\n"
            "- Element 2: [description with exact text and identifiable details]\n"
            "...\n\n"
            "## Error Information (if present)\n"
            "- Error message: [exact text]\n"
            "- Context: [when/where it appeared]\n\n"
            "## Timeline (for videos only)\n"
            "- [00:01] Action: [description]\n"
            "- [00:03] Result: [description]\n"
            "...\n"
            "```\n\n"
            "Be extremely precise with text transcription - use exact wording, preserve case, spacing, and punctuation.\n\n"
            "Analyze these media items:\n\n"
            f"{joined_instructions}\n\n"
            "Begin your detailed analysis now."
        )

        # Compose the multimodal message content list: first text, then each block.
        message_content = [{"type": "text", "text": prompt_text}]
        for m in medias:
            if m.type == UrlType.VIDEO:
                block = {"type": "video_url", "video_url": {"url": m.url}}
            else:
                block = {"type": "image_url", "image_url": {"url": m.url}}
            message_content.append(block)

        payload = {
            "model": "google/gemini-2.5-pro-preview",
            "messages": [{"role": "user", "content": message_content}],
            "max_tokens": 2048,
        }

        logger.info("Requesting bulk media description for %d items", len(medias))

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=self._headers,
                json=payload,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"OpenRouter bulk request failed (status {response.status_code}): {response.text}"
                )

            parsed = _OpenRouterResponse.model_validate_json(response.text)
            content = parsed.first_message_content()
            logger.info("Received bulk description (chars=%d)", len(content))
            return content

    # ------------------------------------------------------------------
    # Parsing helper
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_bulk_response(content: str, medias: List[MediaUrl]) -> dict[str, str]:
        """Best-effort extraction of descriptions per URL from the LLM response."""

        if not content:
            return {}

        lines = content.splitlines()
        url_set = {m.url for m in medias}
        current_url: Optional[str] = None
        accum: dict[str, list[str]] = {u: [] for u in url_set}

        for line in lines:
            stripped = line.strip()
            # Detect a new section starting with a URL followed by a colon
            for url in url_set:
                if stripped.startswith(url):
                    current_url = url
                    # Remove the leading "<url>:" part if exists
                    remainder = stripped[len(url):].lstrip(" :")
                    if remainder:
                        accum[current_url].append(remainder)
                    break
            else:  # not a new URL line
                if current_url:
                    accum[current_url].append(stripped)

        # Join accumulated lines into single strings
        return {u: "\n".join(segs).strip() for u, segs in accum.items() if segs}

# --------------------------------------------------------------------
# Simple data models (replace dependency on legacy media_agent)
# --------------------------------------------------------------------

class UrlType(str, Enum):
    VIDEO = "video"
    IMAGE = "image"

@dataclass
class MediaUrl:
    url: str
    type: UrlType

class MediaTimelineEvent(BaseModel):
    image_identifier: str
    description: str
    code_references: List[str] = []

class MediaTimelinePayload(BaseModel):
    hypothesis: str
    timeline_events: List[MediaTimelineEvent]
    original_query: str 