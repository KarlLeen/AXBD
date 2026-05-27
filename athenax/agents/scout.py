"""Agent A — The Multi-Platform Scout."""
from crewai import Agent, LLM


def build_scout(llm: LLM, tools: list) -> Agent:
    return Agent(
        role="Multi-Platform Scout",
        goal=(
            "Discover high-potential Web3 / DAO projects across GitHub, LinkedIn, and Twitter/X "
            "that may be strong partners for Nouns DAO or listing candidates for AthenaX."
        ),
        backstory=(
            "You are a tireless researcher with deep knowledge of the Web3 ecosystem. "
            "You scan trending repositories, founder profiles, and builder conversations to surface "
            "raw leads before they become mainstream. "
            "You always call your tools to fetch real data — you never make up leads."
        ),
        tools=tools,
        llm=llm,
        verbose=True,
        max_iter=15,
    )
