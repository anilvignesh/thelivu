import logging

import anthropic
from shared.config import CLAUDE_MODEL, GEMINI_MODEL, ANTHROPIC_API_KEY, GEMINI_API_KEY, SKILLS_DIR
from engine.agents.tools import (
    WEB_SEARCH_TOOL,
    CREATE_SKILL_TOOL,
    READ_SKILL_TOOL,
    execute_tool,
)

log = logging.getLogger("skill_runner")

_claude_client = None
_gemini_client = None


def _get_claude():
    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _claude_client


def _get_gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


# Skills that use Gemini + Google Search grounding (research-heavy)
_GEMINI_SKILLS = {
    "news-investigator",
    "source-verifier",
    "beat-monitor",
    "source-scout",
    "story-scout",
}

# Which Claude tools each skill gets (only for Claude-routed skills)
_CLAUDE_SKILL_TOOLS = {
    "news-monitor":       [],
    "pattern-synthesizer": [],
    "article-writer":     [],
    "editorial-reviewer": [],
    "topic-intake":       [WEB_SEARCH_TOOL],
    "publisher":          [],
    "source-ingestor":    [],
}


def _load_skill(skill_name):
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(
            f"Skill not found: {skill_name}. "
            f"Available: {[p.name for p in SKILLS_DIR.iterdir() if p.is_dir()]}"
        )
    return skill_path.read_text(encoding="utf-8")


def _run_gemini_skill(skill_name, input_text, system_prompt, max_tokens, run_id=None):
    """Run a skill using Gemini with Google Search grounding."""
    from google.genai import types
    from shared.db import record_usage

    client = _get_gemini()

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[types.Tool(google_search=types.GoogleSearch())],
        max_output_tokens=max_tokens,
    )

    log.info("Running %s via Gemini + Google Search", skill_name)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=input_text,
        config=config,
    )

    # Record token usage
    try:
        usage = response.usage_metadata
        record_usage(
            skill=skill_name, model=GEMINI_MODEL,
            input_tokens=getattr(usage, "prompt_token_count", 0),
            output_tokens=getattr(usage, "candidates_token_count", 0),
            run_id=run_id,
        )
    except Exception:
        pass

    return response.text.strip()


def _run_claude_skill(skill_name, input_text, system_prompt, extra_tools, max_tokens, run_id=None):
    """Run a skill using Claude with the configured tool set."""
    from shared.db import record_usage

    tools = _CLAUDE_SKILL_TOOLS.get(skill_name, []) + (extra_tools or [])
    messages = [{"role": "user", "content": input_text}]
    client = _get_claude()
    total_in, total_out = 0, 0

    log.info("Running %s via Claude", skill_name)

    while True:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            system=system_prompt,
            tools=tools,
            messages=messages,
            max_tokens=max_tokens,
        )

        total_in  += response.usage.input_tokens
        total_out += response.usage.output_tokens

        if response.stop_reason == "end_turn":
            try:
                record_usage(skill=skill_name, model=CLAUDE_MODEL,
                             input_tokens=total_in, output_tokens=total_out, run_id=run_id)
            except Exception:
                pass
            return _extract_claude_text(response)

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    try:
                        result = execute_tool(block.name, block.input)
                    except Exception as e:
                        result = f"Tool error: {e}"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        try:
            record_usage(skill=skill_name, model=CLAUDE_MODEL,
                         input_tokens=total_in, output_tokens=total_out, run_id=run_id)
        except Exception:
            pass
        return _extract_claude_text(response)


def run_skill(skill_name, input_text, extra_tools=None, max_tokens=4096):
    """
    Load engine/skills/{skill_name}/SKILL.md as system prompt and run.
    Research skills → Gemini + Google Search grounding.
    Editorial skills → Claude agentic loop.
    Falls back to Claude if GEMINI_API_KEY is not set.
    """
    system_prompt = _load_skill(skill_name)

    if skill_name in _GEMINI_SKILLS and GEMINI_API_KEY:
        try:
            return _run_gemini_skill(skill_name, input_text, system_prompt, max_tokens, run_id=None)
        except Exception as e:
            log.warning("Gemini failed for %s (%s) — falling back to Claude", skill_name, e)

    return _run_claude_skill(skill_name, input_text, system_prompt, extra_tools, max_tokens, run_id=None)


def _extract_claude_text(response):
    parts = []
    for block in response.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts).strip()
