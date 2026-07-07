"""Agent C — The URL Verifier."""
from crewai import Agent, LLM


def build_verifier(llm: LLM, tools: list) -> Agent:
    return Agent(
        role="URL Verifier & Data Quality Analyst",
        goal=(
            "Verify that every team member LinkedIn/Twitter URL and every project link "
            "in the provided leads actually exists and matches the expected person or project. "
            "Assign a certainty score to each lead based on how much of its data could be confirmed."
        ),
        backstory=(
            "You are a meticulous fact-checker. You never trust a URL just because it looks "
            "plausible — you always run a search to confirm the page exists and belongs to the "
            "right person or project. You know that AI systems hallucinate LinkedIn slugs by "
            "pattern-matching names, so you treat every unverified URL as guilty until proven "
            "innocent. Your goal is a clean dataset, not a full one: a null is always better "
            "than a wrong URL."
        ),
        tools=tools,
        llm=llm,
        verbose=True,
        max_iter=30,
    )
