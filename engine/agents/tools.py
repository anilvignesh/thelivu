import requests
from shared.config import BRAVE_API_KEY, SKILLS_DIR

# --- Tool schemas (Claude API format) ---

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the web for information. Use for verification, finding primary records "
        "(court filings, govt data, ECI/RBI/CAG, company disclosures), and cross-checking "
        "claims. Each result includes title, URL, and snippet."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default 5, max 10)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}

CREATE_SKILL_TOOL = {
    "name": "create_skill",
    "description": (
        "Create a new skill SKILL.md file for a capability that recurs often enough "
        "to be worth codifying. Only use this when you have identified a clear, reusable "
        "editorial pattern. Follow the existing SKILL.md format exactly."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name in kebab-case (e.g. 'financial-doc-analyst')",
            },
            "content": {
                "type": "string",
                "description": "Full SKILL.md content including YAML frontmatter, method, output format, and guardrails",
            },
        },
        "required": ["name", "content"],
    },
}

READ_SKILL_TOOL = {
    "name": "read_skill",
    "description": "Read an existing skill's SKILL.md to understand its method or output format.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name in kebab-case",
            },
        },
        "required": ["name"],
    },
}


# --- Tool execution ---

def execute_tool(tool_name, tool_input):
    if tool_name == "web_search":
        return web_search(tool_input["query"], tool_input.get("num_results", 5))
    if tool_name == "create_skill":
        return create_skill(tool_input["name"], tool_input["content"])
    if tool_name == "read_skill":
        return read_skill(tool_input["name"])
    raise ValueError(f"Unknown tool: {tool_name}")


def web_search(query, num_results=5):
    if BRAVE_API_KEY:
        return _brave_search(query, num_results)
    return _ddg_search(query)


def _brave_search(query, num_results):
    r = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": num_results},
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": BRAVE_API_KEY,
        },
        timeout=10,
    )
    r.raise_for_status()
    results = r.json().get("web", {}).get("results", [])
    if not results:
        return "No results found."
    return "\n\n".join(
        f"**{item['title']}**\n{item['url']}\n{item.get('description', '')}"
        for item in results
    )


def _ddg_search(query):
    try:
        from duckduckgo_search import DDGS
        results = list(DDGS().text(query, max_results=5))
        if not results:
            return "No results found."
        return "\n\n".join(
            f"**{r['title']}**\n{r['href']}\n{r['body']}" for r in results
        )
    except Exception as e:
        return f"Search unavailable: {e}. The web search tool is not working. Document this failure and output HOLD (not KILL) — absence of search results is not evidence against the story."


def create_skill(name, content):
    skill_dir = SKILLS_DIR / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return f"Skill '{name}' created at engine/skills/{name}/SKILL.md"


def read_skill(name):
    skill_file = SKILLS_DIR / name / "SKILL.md"
    if not skill_file.exists():
        return f"Skill '{name}' not found. Available skills: {[p.name for p in SKILLS_DIR.iterdir() if p.is_dir()]}"
    return skill_file.read_text(encoding="utf-8")
