"""
Skill runner — four-tier model routing.

Tier 1 (Research)   : Gemini 2.5 Flash + Google Search grounding
Tier 2 (Reasoning)  : DeepSeek R1 (chain-of-thought, no search needed)
Tier 3 (Utility)    : Groq / Llama 3.3 70B (free, fast, structured tasks)
Tier 4 (Editorial)  : Claude Sonnet (judgment, nuance, instruction-following)

Falls back to Claude if the preferred provider is unconfigured or fails.
"""

import logging

import anthropic
from shared.config import (
    CLAUDE_MODEL, GEMINI_MODEL, GROQ_MODEL, DEEPSEEK_MODEL, MISTRAL_MODEL,
    ANTHROPIC_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, DEEPSEEK_API_KEY, MISTRAL_API_KEY,
    SKILLS_DIR,
)
from engine.agents.tools import WEB_SEARCH_TOOL, execute_tool

log = logging.getLogger("skill_runner")

# ── Lazy clients ──────────────────────────────────────────────────────────────
_claude_client  = None
_gemini_client  = None
_groq_client    = None
_deepseek_client = None
_mistral_client = None


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


def _get_groq():
    global _groq_client
    if _groq_client is None:
        from openai import OpenAI
        _groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    return _groq_client


def _get_deepseek():
    global _deepseek_client
    if _deepseek_client is None:
        from openai import OpenAI
        _deepseek_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    return _deepseek_client


def _get_mistral():
    global _mistral_client
    if _mistral_client is None:
        from openai import OpenAI
        _mistral_client = OpenAI(api_key=MISTRAL_API_KEY, base_url="https://api.mistral.ai/v1")
    return _mistral_client


# ── Skill → provider routing ──────────────────────────────────────────────────

# Tier 1: Gemini — needs Google Search grounding for research
_GEMINI_SKILLS = {
    "news-investigator",
    "source-verifier",
    "beat-monitor",
    "source-scout",
    "story-scout",
    "story-tracker",
}

# Tier 2: DeepSeek R1 — reasoning-heavy, no search needed
_DEEPSEEK_SKILLS = {
    "pattern-synthesizer",
    "meta-synthesizer",
}

# Tier 3: Groq/Llama — utility tasks (formatting, extraction, classification)
_GROQ_SKILLS = {
    "finance-manager",
    "publisher",
    "source-ingestor",
    "news-monitor",
}

# Tier 4 (default): Claude — editorial judgment, tone, complex instruction-following
# editorial-reviewer, article-writer, topic-intake, and any skill not in the above sets

# Claude tools for fallback / Claude-native skills
_CLAUDE_SKILL_TOOLS = {
    "topic-intake":        [WEB_SEARCH_TOOL],
    "news-investigator":   [WEB_SEARCH_TOOL],
    "source-verifier":     [WEB_SEARCH_TOOL],
    "beat-monitor":        [WEB_SEARCH_TOOL],
    "source-scout":        [WEB_SEARCH_TOOL],
    "story-scout":         [WEB_SEARCH_TOOL],
    "story-tracker":       [WEB_SEARCH_TOOL],
}

# Per-provider cost per 1M tokens (USD) — for spend tracking
_COSTS = {
    CLAUDE_MODEL:   {"in": 3.00,  "out": 15.00},
    GEMINI_MODEL:   {"in": 0.30,  "out": 1.00},
    GROQ_MODEL:     {"in": 0.00,  "out": 0.00},   # free tier
    DEEPSEEK_MODEL: {"in": 0.55,  "out": 2.19},
    MISTRAL_MODEL:  {"in": 0.20,  "out": 0.60},
}


# ── Skill loader ──────────────────────────────────────────────────────────────

def _load_skill(skill_name):
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(
            f"Skill not found: {skill_name}. "
            f"Available: {[p.name for p in SKILLS_DIR.iterdir() if p.is_dir()]}"
        )
    return skill_path.read_text(encoding="utf-8")


# ── Provider runners ──────────────────────────────────────────────────────────

def _run_gemini(skill_name, input_text, system_prompt, max_tokens, run_id=None):
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
        model=GEMINI_MODEL, contents=input_text, config=config,
    )
    try:
        u = response.usage_metadata
        record_usage(skill=skill_name, model=GEMINI_MODEL,
                     input_tokens=getattr(u, "prompt_token_count", 0),
                     output_tokens=getattr(u, "candidates_token_count", 0),
                     run_id=run_id)
    except Exception:
        pass
    return response.text.strip()


def _run_openai_compat(client, model, skill_name, input_text, system_prompt,
                        max_tokens, run_id=None):
    """Shared runner for Groq, DeepSeek, Mistral (all OpenAI-compatible)."""
    from shared.db import record_usage

    log.info("Running %s via %s", skill_name, model)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": input_text},
        ],
        max_tokens=max_tokens,
        temperature=0.3,
    )
    try:
        u = response.usage
        record_usage(skill=skill_name, model=model,
                     input_tokens=u.prompt_tokens,
                     output_tokens=u.completion_tokens,
                     run_id=run_id)
    except Exception:
        pass
    return response.choices[0].message.content.strip()


def _run_claude(skill_name, input_text, system_prompt, extra_tools, max_tokens, run_id=None):
    from shared.db import record_usage

    tools = _CLAUDE_SKILL_TOOLS.get(skill_name, []) + (extra_tools or [])
    messages = [{"role": "user", "content": input_text}]
    client = _get_claude()
    total_in = total_out = 0

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
            _record_claude(skill_name, total_in, total_out, run_id)
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

        _record_claude(skill_name, total_in, total_out, run_id)
        return _extract_claude_text(response)


def _record_claude(skill_name, total_in, total_out, run_id):
    try:
        from shared.db import record_usage
        record_usage(skill=skill_name, model=CLAUDE_MODEL,
                     input_tokens=total_in, output_tokens=total_out, run_id=run_id)
    except Exception:
        pass


def _extract_claude_text(response):
    return "\n".join(
        block.text for block in response.content if hasattr(block, "text")
    ).strip()


# ── Main entry point ──────────────────────────────────────────────────────────

def run_skill(skill_name, input_text, extra_tools=None, max_tokens=4096,
              run_id=None, topic=None):
    """
    Route skill to the right model tier, fall back to Claude on any failure.

    Routing:
      Gemini skills   → Gemini 2.5 Flash + Google Search
      DeepSeek skills → DeepSeek R1 (reasoning)
      Groq skills     → Llama 3.3 70B (free utility)
      Everything else → Claude Sonnet (editorial judgment)
    """
    from shared.db import agent_start, agent_done

    system_prompt = _load_skill(skill_name)

    # Determine preferred provider
    if skill_name in _GEMINI_SKILLS and GEMINI_API_KEY:
        preferred = "gemini"
        model_label = GEMINI_MODEL
    elif skill_name in _DEEPSEEK_SKILLS and DEEPSEEK_API_KEY:
        preferred = "deepseek"
        model_label = DEEPSEEK_MODEL
    elif skill_name in _GROQ_SKILLS and GROQ_API_KEY:
        preferred = "groq"
        model_label = GROQ_MODEL
    else:
        preferred = "claude"
        model_label = CLAUDE_MODEL

    aid = agent_start(skill_name, model_label, topic=topic, run_id=run_id)

    try:
        if preferred == "gemini":
            try:
                return _run_gemini(skill_name, input_text, system_prompt, max_tokens, run_id)
            except Exception as e:
                log.warning("Gemini failed for %s (%s) — falling back to Claude", skill_name, e)

        elif preferred == "deepseek":
            try:
                return _run_openai_compat(
                    _get_deepseek(), DEEPSEEK_MODEL, skill_name,
                    input_text, system_prompt, max_tokens, run_id,
                )
            except Exception as e:
                log.warning("DeepSeek failed for %s (%s) — falling back to Claude", skill_name, e)

        elif preferred == "groq":
            try:
                return _run_openai_compat(
                    _get_groq(), GROQ_MODEL, skill_name,
                    input_text, system_prompt, max_tokens, run_id,
                )
            except Exception as e:
                log.warning("Groq failed for %s (%s) — falling back to Claude", skill_name, e)

        # Claude — primary or fallback
        return _run_claude(skill_name, input_text, system_prompt, extra_tools, max_tokens, run_id)

    finally:
        agent_done(aid)
