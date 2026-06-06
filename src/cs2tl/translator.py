"""LLM-powered CS2 voice comm translation with esports terminology.

Groups voice segments by (steam_id, round_number), builds system prompts
with map-specific callout dictionaries, calls an LLM API with retry/fallback
logic, and validates translated output against the dictionary.

Key P1 constraints:
  - P1-5: 3x exponential backoff retry → "[翻译失败]" fallback prefix
  - P1-11: --dry-run cost estimation (no API call)
  - Customizable system prompt template
  - Incremental JSONL caching per round
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from cs2tl.errors import (
    llm_auth_failed,
    llm_rate_limited,
    llm_response_malformed,
)

logger = logging.getLogger(__name__)

# LLM pricing per 1K tokens (approximate, updated 2026)
COST_PER_1K_INPUT = {
    "gpt-4o": 0.0025,
    "gpt-4o-mini": 0.00015,
    "gpt-4-turbo": 0.01,
    "gpt-3.5-turbo": 0.0005,
    "claude-sonnet-4-6": 0.003,
    "claude-haiku-4-5": 0.0008,
    "deepseek-chat": 0.00027,
    "deepseek-reasoner": 0.00055,
}

COST_PER_1K_OUTPUT = {
    "gpt-4o": 0.01,
    "gpt-4o-mini": 0.0006,
    "gpt-4-turbo": 0.03,
    "gpt-3.5-turbo": 0.0015,
    "claude-sonnet-4-6": 0.015,
    "claude-haiku-4-5": 0.004,
    "deepseek-chat": 0.0011,
    "deepseek-reasoner": 0.0022,
}

DEFAULT_COST_INPUT = 0.005
DEFAULT_COST_OUTPUT = 0.015

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds, doubled each attempt
MAX_SEGMENTS_PER_BATCH = 50  # split large rounds to avoid LLM response truncation

FALLBACK_PREFIX = "[翻译失败]"

# Default system prompt template
DEFAULT_PROMPT_TEMPLATE = """\
You are a CS2 (Counter-Strike 2) esports translation expert.
Translate the following player voice communications into {target_language}.

Rules:
1. Use the provided callout dictionary for CS2 map terminology.
2. Translate game terms naturally — do NOT translate player names or map names.
3. Commands and callouts should be brief and urgent, matching the game pace.
4. If a phrase is unclear or whispered, include your best guess in brackets.

{term_table_section}

Output format: Return a JSON array of objects, one per voice line:
[{{"line": N, "translated": "...", "notes": "..."}}]

Voice lines to translate:
{voice_lines}
"""


@dataclass
class TranslationSegment:
    """A fully translated voice segment."""

    steam_id: str
    player_name: str
    team: str  # "T" | "CT" | "unknown"
    start_time: float
    end_time: float
    original_text: str
    translated_text: str
    round_number: int | None = None
    warnings: list[str] = field(default_factory=list)


# ---- pipeline entry point ----


def translate_all(
    segments: list,  # PartialSegment (with round_number attr)
    players: dict,  # str -> PlayerInfo
    rounds: list,  # RoundBoundary
    map_name: str | None,
    dictionary_manager,  # DictionaryManager | None
    llm_config,  # LLMConfig
    target_language: str = "Simplified Chinese (简体中文)",
    no_dictionary: bool = False,
    prompt_template: str | None = None,
    cache_path: Path | None = None,
    dry_run: bool = False,
) -> list[TranslationSegment]:
    """Translate all voice segments grouped by (steam_id, round_number).

    Args:
        segments: PartialSegments with .round_number and .team attributes set.
        players: steam_id -> PlayerInfo mapping.
        rounds: RoundBoundary list.
        map_name: Map name for dictionary lookup.
        dictionary_manager: Loaded DictionaryManager or None.
        llm_config: LLM configuration.
        target_language: Target language name (for prompt).
        no_dictionary: If True, skip dictionary injection.
        prompt_template: Custom system prompt template string.
        cache_path: Path to demo.translated.jsonl for incremental cache.
        dry_run: If True, estimate cost without calling the API.

    Returns:
        List of fully translated TranslationSegments.
    """
    # Group by round
    by_round: dict[int, list] = {}
    for seg in segments:
        rn = getattr(seg, "round_number", None)
        if rn is None:
            rn = -1  # unclassified
        by_round.setdefault(rn, []).append(seg)

    # Build term table
    term_table = ""
    if dictionary_manager and map_name and not no_dictionary:
        term_table = dictionary_manager.build_term_table(map_name)

    # Build prompt
    prompt = build_system_prompt(
        target_language=target_language,
        term_table=term_table,
        no_dictionary=no_dictionary or not term_table,
        custom_template=prompt_template,
    )

    translated: list[TranslationSegment] = []

    for rn in sorted(by_round.keys()):
        round_segs = by_round[rn]

        # Split large rounds into batches to avoid LLM response truncation
        total_batches = (len(round_segs) + MAX_SEGMENTS_PER_BATCH - 1) // MAX_SEGMENTS_PER_BATCH

        for batch_num in range(total_batches):
            batch_start = batch_num * MAX_SEGMENTS_PER_BATCH
            batch_end = min(batch_start + MAX_SEGMENTS_PER_BATCH, len(round_segs))
            batch_segs = round_segs[batch_start:batch_end]

            if total_batches > 1:
                logger.info(
                    "Round %d batch %d/%d: %d segments",
                    rn, batch_num + 1, total_batches, len(batch_segs),
                )

            voice_lines = _format_voice_lines(batch_segs)

            if dry_run:
                # P1-11: Estimate cost only
                estimated_input_tokens = _estimate_tokens(prompt + voice_lines)
                estimated_output_tokens = len(batch_segs) * 30  # ~30 tokens per line
                cost = _estimate_cost(
                    estimated_input_tokens, estimated_output_tokens, llm_config.model
                )
                logger.info(
                    "Round %d batch %d/%d: ~%d input + ~%d output tokens, est. cost $%.4f",
                    rn, batch_num + 1, total_batches,
                    estimated_input_tokens,
                    estimated_output_tokens,
                    cost,
                )
                continue

            # Call LLM
            response_text = call_llm(prompt, voice_lines, llm_config)

            # Parse and build TranslationSegments
            parsed = _parse_response(response_text, len(batch_segs))
            for i, seg in enumerate(batch_segs):
                pid = players.get(getattr(seg, "steam_id", ""), None)
                player_name = pid.player_name if pid else getattr(seg, "steam_id", "unknown")
                team = getattr(seg, "team", None) or (pid.team if pid else "unknown")

                translated_text = parsed[i] if i < len(parsed) else f"{FALLBACK_PREFIX} {getattr(seg, 'text', '')}"

                tseg = TranslationSegment(
                    steam_id=getattr(seg, "steam_id", ""),
                    player_name=player_name,
                    team=team,
                    start_time=getattr(seg, "start_time", 0.0),
                    end_time=getattr(seg, "end_time", 0.0),
                    original_text=getattr(seg, "text", ""),
                    translated_text=translated_text,
                    round_number=None if rn == -1 else rn,
                    warnings=[],
                )

                # Validate against dictionary
                if dictionary_manager and map_name and not no_dictionary:
                    tseg.warnings = dictionary_manager.validate_terms(translated_text, map_name)

                translated.append(tseg)

            # Incremental cache after each batch
            if cache_path:
                _append_translated(cache_path, translated[-len(batch_segs):])

    if dry_run:
        logger.info("Dry run complete — no API calls made. Run without --dry-run to translate.")

    return translated


# ---- LLM call with retry ----


def call_llm(
    system_prompt: str,
    user_content: str,
    llm_config,  # LLMConfig
    max_retries: int = MAX_RETRIES,
) -> str:
    """Call the LLM API with retry logic.

    Retry sequence: 1s, 2s, 4s delay.
    On final failure: returns the fallback prefix for each line.

    Args:
        system_prompt: System message content.
        user_content: User message content.
        llm_config: LLM configuration (provider, api_key, model, base_url).
        max_retries: Maximum retry attempts (default 3).

    Returns:
        LLM response text, or fallback prefix on final failure.
    """
    if not llm_config.api_key:
        return f"{FALLBACK_PREFIX} (no API key configured)"

    for attempt in range(max_retries + 1):
        try:
            if llm_config.provider in ("openai", "openrouter"):
                return _call_openai(system_prompt, user_content, llm_config)
            elif llm_config.provider == "anthropic":
                return _call_anthropic(system_prompt, user_content, llm_config)
            else:
                # Default: OpenAI-compatible
                return _call_openai(system_prompt, user_content, llm_config)
        except Exception as e:
            error_str = str(e).lower()
            if "401" in error_str or "unauthorized" in error_str:
                raise llm_auth_failed(str(e)) from e
            if "429" in error_str or "rate" in error_str:
                if attempt < max_retries:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning("Rate limited. Retrying in %.0fs (attempt %d/%d)", delay, attempt + 1, max_retries)
                    time.sleep(delay)
                    continue
                raise llm_rate_limited(str(attempt)) from e
            if attempt < max_retries:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning("LLM error: %s. Retrying in %.0fs (attempt %d/%d)", e, delay, attempt + 1, max_retries)
                time.sleep(delay)
                continue
            # Final failure
            logger.error("LLM call failed after %d retries: %s", max_retries, e)
            return f"{FALLBACK_PREFIX} (API error)"

    return f"{FALLBACK_PREFIX} (max retries exceeded)"


def _call_openai(system_prompt: str, user_content: str, llm_config) -> str:
    from openai import OpenAI

    client_kwargs = {"api_key": llm_config.api_key}
    if llm_config.base_url:
        client_kwargs["base_url"] = llm_config.base_url

    client = OpenAI(**client_kwargs)
    response = client.chat.completions.create(
        model=llm_config.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content or ""


def _call_anthropic(system_prompt: str, user_content: str, llm_config) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=llm_config.api_key)
    response = client.messages.create(
        model=llm_config.model,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
        max_tokens=4096,
        temperature=0.3,
    )
    content = response.content
    if isinstance(content, list):
        return "".join(
            b.text if hasattr(b, "text") else str(b) for b in content
        )
    return str(content)


# ---- prompt construction ----


def build_system_prompt(
    target_language: str = "Simplified Chinese (简体中文)",
    term_table: str = "",
    no_dictionary: bool = False,
    custom_template: str | None = None,
) -> str:
    """Build the final system prompt."""
    template = custom_template or DEFAULT_PROMPT_TEMPLATE

    if term_table and not no_dictionary:
        term_section = f"### CS2 Callout Dictionary\n\n{term_table}"
    else:
        term_section = "(No map-specific dictionary available. Translate using general gaming knowledge.)"

    prompt = template.replace("{target_language}", target_language)
    prompt = prompt.replace("{term_table_section}", term_section)

    # {voice_lines} placeholder is filled at call time
    return prompt


# ---- response parsing ----


def _parse_response(response_text: str, expected_count: int) -> list[str]:
    """Parse LLM JSON response into a list of translated strings.

    Handles: markdown-wrapped JSON, truncated/incomplete JSON arrays,
    line-by-line JSON objects, and raw text responses.
    """
    if not response_text or response_text.startswith(FALLBACK_PREFIX):
        return [FALLBACK_PREFIX] * expected_count

    # Step 1: Extract JSON from markdown code blocks
    # (DeepSeek often wraps responses in ```json ... ```)
    json_text = response_text
    backtick3 = "```"
    if backtick3 in response_text:
        code_lines = []
        in_block = False
        for line in response_text.split("\n"):
            stripped = line.strip()
            if stripped.startswith(backtick3):
                if in_block:
                    break  # end of code block
                in_block = True
                continue
            if in_block:
                code_lines.append(line)
        if code_lines:
            json_text = "\n".join(code_lines)

    # Step 2: Try full JSON array parse
    try:
        data = json.loads(json_text)
        if isinstance(data, list):
            results = []
            for item in data:
                if isinstance(item, dict):
                    results.append(item.get("translated", str(item)))
                else:
                    results.append(str(item))
            return results
    except json.JSONDecodeError:
        pass

    # Step 3: Line-by-line JSON object parsing
    # Works even when the full array is truncated: each line like
    #   {"line": 1, "translated": "...", "notes": "..."},
    results: list[str] = [""] * expected_count
    found_any = False
    for line in json_text.split("\n"):
        stripped = line.strip().rstrip(",")  # remove trailing comma
        if not stripped:
            continue
        # Must look like a JSON object with "line" and "translated" keys
        if not (stripped.startswith('{"line"') or stripped.startswith('{ "line"')):
            continue
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict) and "line" in obj and "translated" in obj:
                idx = int(obj["line"]) - 1  # lines are 1-indexed
                if 0 <= idx < expected_count:
                    results[idx] = str(obj["translated"])
                    found_any = True
        except (json.JSONDecodeError, ValueError, KeyError):
            continue

    if found_any:
        filled = sum(1 for r in results if r)
        logger.info(
            "Extracted %d/%d translations via line-by-line JSON parsing",
            filled, expected_count,
        )
        # Fill remaining slots with fallback
        for i in range(expected_count):
            if not results[i]:
                results[i] = f"{FALLBACK_PREFIX} (unparsed)"
        return results

    # Step 4: Regex-based extraction as last resort
    # Matches: {"line": <N>, "translated": "<text>"...}
    line_re = re.compile(
        r'\{\s*"line"\s*:\s*(\d+)\s*,\s*"translated"\s*:\s*"((?:[^"\\]|\\.)*)"'
    )
    matches = line_re.findall(json_text)
    if matches:
        results = [""] * expected_count
        for match in matches:
            try:
                idx = int(match[0]) - 1
                if 0 <= idx < expected_count:
                    # Unescape common JSON escapes
                    text = match[1].replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
                    results[idx] = text
                    found_any = True
            except (ValueError, IndexError):
                continue
        if found_any:
            filled = sum(1 for r in results if r)
            logger.info(
                "Extracted %d/%d translations via regex fallback",
                filled, expected_count,
            )
            for i in range(expected_count):
                if not results[i]:
                    results[i] = f"{FALLBACK_PREFIX} (unparsed)"
            return results

    # Step 5: Complete failure — return raw text
    logger.warning("Failed to parse LLM JSON response; using raw text fallback")
    return [response_text] * expected_count


def _format_voice_lines(segments: list) -> str:
    """Format voice segments as a numbered list for the LLM prompt."""
    lines = []
    for i, seg in enumerate(segments):
        player = getattr(seg, "steam_id", "unknown")
        text = getattr(seg, "text", "")
        lines.append(f"{i + 1}. [{player}] {text}")
    return "\n".join(lines)


def _estimate_tokens(text: str) -> int:
    """Quick token count estimate. ~4 chars per token for English, ~1.5 for Chinese."""
    chars = len(text)
    cjk_chars = sum(1 for c in text if "一" <= c <= "鿿")
    return int((chars - cjk_chars) / 4 + cjk_chars / 1.5)


def _estimate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    input_rate = COST_PER_1K_INPUT.get(model, DEFAULT_COST_INPUT)
    output_rate = COST_PER_1K_OUTPUT.get(model, DEFAULT_COST_OUTPUT)
    return (input_tokens * input_rate + output_tokens * output_rate) / 1000


def _append_translated(cache_path: Path, segments: list[TranslationSegment]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "a", encoding="utf-8") as f:
        for seg in segments:
            f.write(
                json.dumps(
                    {
                        "steam_id": seg.steam_id,
                        "player_name": seg.player_name,
                        "team": seg.team,
                        "start_time": seg.start_time,
                        "end_time": seg.end_time,
                        "original_text": seg.original_text,
                        "translated_text": seg.translated_text,
                        "round_number": seg.round_number,
                        "warnings": seg.warnings,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
