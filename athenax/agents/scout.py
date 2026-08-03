"""Agent A — The Multi-Platform Scout."""
from crewai import Agent, LLM

SECTORS = (
    "AI & Agents, Biotech, Crypto, Developer Tools, Infrastructure, Robotics, RWA"
)

def build_scout(llm: LLM, tools: list) -> Agent:
    return Agent(
        role="Multi-Platform Scout",
        goal=(
            "Discover high-potential projects across all AthenaX sectors "
            f"({SECTORS}) by mining GitHub, LinkedIn, Twitter/X, and the web. "
            "Collect every signal the Evaluator needs to score and classify each lead."
        ),
        backstory=(
            "You are an obsessive deal-sourcer with deep knowledge of frontier tech. "
            "You know that the best leads are found early — before the press picks them up. "
            "You always prefer velocity over vanity: a project that doubled its GitHub stars "
            "in 30 days is more interesting than one sitting on a large but stale count. "
            "You never fabricate data — if a field is unavailable you leave it null."
        ),
        tools=tools,
        llm=llm,
        verbose=True,
        max_iter=15,
    )


def build_listing_scout(llm: LLM, tools: list) -> Agent:
    """Lightweight scout: name / website / twitter only — no deep profiles."""
    return Agent(
        role="Listing Discovery Scout",
        goal=(
            "Find NEW frontier-tech projects across AthenaX sectors "
            f"({SECTORS}) and return ONLY name, website URL, Twitter/X, and optional "
            "category. Maximize coverage of real projects with working websites; "
            "do not deep-profile teams, backers, or bios."
        ),
        backstory=(
            "You are a fast deal-sourcer building a candidate list for later enrichment. "
            "Your job is breadth: many real projects with verified website URLs, not "
            "deep research. You never invent URLs or company names. If you cannot "
            "confirm a real website from a tool result, you skip the project. "
            "You ignore exclusion-list names and already-scouted duplicates."
        ),
        tools=tools,
        llm=llm,
        verbose=True,
        max_iter=12,
    )
