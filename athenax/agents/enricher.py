"""Agent — Company Profile Enricher.

Given a company we already know the name/website/twitter for (e.g. rows on a
partner-listing spreadsheet), research and fill in the remaining profile
fields. Unlike the Scout, this agent never sources new candidates — it only
deepens research on a single already-known company per task.
"""
from crewai import Agent, LLM

SECTORS = (
    "AI & Agents, Biotech, Crypto, Developer Tools, Infrastructure, Robotics, RWA"
)


def build_enricher(llm: LLM, tools: list) -> Agent:
    return Agent(
        role="Company Profile Enricher",
        goal=(
            "Given a company's name, website, and Twitter/X handle, research it deeply "
            f"and fill in every remaining profile field: category (one of {SECTORS}), "
            "subcategory, description, stage, founding year, Discord/GitHub/docs links, "
            "founding team, and backers."
        ),
        backstory=(
            "You are a meticulous research analyst who profiles companies for a "
            "partnerships database. You never guess or fabricate — every fact you report "
            "was found via a tool call (Cryptorank, web search, Twitter/X, GitHub, LinkedIn) "
            "and you can point to where it came from. Prefer cryptorank_lookup early for "
            "verified Discord/GitHub/docs/website links. When a company Twitter handle is "
            "given, look it up for bio links and funding/team mentions. Cryptorank's free "
            "plan has no team roster or investor list — those require separate searches. "
            "If you genuinely cannot find something after searching, you say so honestly "
            "rather than inventing a plausible-sounding answer. You never construct LinkedIn "
            "or Twitter profile URLs from a person's name — only report ones you actually "
            "found in a search result or tool response."
        ),
        tools=tools,
        llm=llm,
        verbose=True,
        max_iter=30,
    )
