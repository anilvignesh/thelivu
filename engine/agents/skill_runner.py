import anthropic
from shared.config import CLAUDE_MODEL, ANTHROPIC_API_KEY, SKILLS_DIR
from engine.agents.tools import (
    WEB_SEARCH_TOOL,
    CREATE_SKILL_TOOL,
    READ_SKILL_TOOL,
    execute_tool,
)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# Which tools each skill gets access to
_SKILL_TOOLS = {
    "news-investigator": [WEB_SEARCH_TOOL, CREATE_SKILL_TOOL, READ_SKILL_TOOL],
    "source-verifier":   [WEB_SEARCH_TOOL],
    "beat-monitor":      [WEB_SEARCH_TOOL],
    "story-scout":       [WEB_SEARCH_TOOL, CREATE_SKILL_TOOL, READ_SKILL_TOOL],
    "source-scout":      [WEB_SEARCH_TOOL, READ_SKILL_TOOL],
    "news-monitor":      [],
    "pattern-synthesizer": [],
    "article-writer":    [],
    "editorial-reviewer": [],
    "topic-intake":      [WEB_SEARCH_TOOL],
}


def run_skill(skill_name, input_text, extra_tools=None, max_tokens=4096):
    """
    Load engine/skills/{skill_name}/SKILL.md as the system prompt and run a
    full Claude agentic loop — handles tool_use cycles until end_turn.
    Returns the final text output.
    """
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(
            f"Skill not found: {skill_name}. "
            f"Available: {[p.name for p in SKILLS_DIR.iterdir() if p.is_dir()]}"
        )

    system_prompt = skill_path.read_text(encoding="utf-8")
    tools = _SKILL_TOOLS.get(skill_name, []) + (extra_tools or [])
    messages = [{"role": "user", "content": input_text}]
    client = _get_client()

    while True:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            system=system_prompt,
            tools=tools,
            messages=messages,
            max_tokens=max_tokens,
        )

        if response.stop_reason == "end_turn":
            return _extract_text(response)

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

        # Unexpected stop reason — return whatever text we have
        return _extract_text(response)


def _extract_text(response):
    parts = []
    for block in response.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts).strip()
