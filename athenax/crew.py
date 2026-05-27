"""CrewAI Crew — Scout → Evaluator → Writer pipeline."""
import os
from crewai import Crew, LLM, Task

from athenax.agents.scout import build_scout
from athenax.agents.evaluator import build_evaluator
from athenax.agents.writer import build_writer
from athenax.tools.github_tool import GitHubTool
from athenax.tools.linkedin_tool import (
    LinkedInPeopleSearchTool,
    LinkedInCompanySearchTool,
    LinkedInPostSearchTool,
    LinkedInProfileTool,
)
from athenax.tools.twitter_tool import TwitterTool
from athenax.tools.serper_tool import SerperTool

MODEL = "openrouter/deepseek/deepseek-v4-pro"


def build_llm() -> LLM:
    return LLM(
        model=MODEL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        temperature=0.3,
    )


def build_crew() -> Crew:
    llm = build_llm()

    scout = build_scout(
        llm=llm,
        tools=[
            GitHubTool(),
            LinkedInPeopleSearchTool(),
            LinkedInCompanySearchTool(),
            LinkedInPostSearchTool(),
            LinkedInProfileTool(),
            TwitterTool(),
            SerperTool(),
        ],
    )
    evaluator = build_evaluator(llm=llm, tools=[])
    writer = build_writer(llm=llm, tools=[])

    scout_task = Task(
        description=(
            "You are discovering partnership candidates for Nouns DAO and listing candidates for AthenaX.\n\n"
            "Use your tools to collect at least 15–20 raw leads across three platforms:\n"
            "1. GitHub — search repos with keywords: 'DAO tooling', 'public goods', 'CC0', 'Web3 Infrastructure'\n"
            "2. LinkedIn — search people ('Web3 founder DAO builder') and companies ('DAO tooling Web3 infrastructure')\n"
            "   and posts ('DAO public goods CC0')\n"
            "3. Twitter/X — hashtags: #DAO, #Web3, #BuildInPublic, #PublicGoods\n\n"
            "For each lead collect: name, URL, source platform, description, GitHub stars/forks if applicable, "
            "LinkedIn profile if available, Twitter handle and followers if available, recent post/tweet.\n\n"
            "Return a single JSON array of lead objects."
        ),
        expected_output=(
            "A JSON array of 15–20 lead objects, each with: "
            "source, name, url, description, github_stars (or null), github_forks (or null), "
            "tech_stack (array or null), linkedin_profile (or null), linkedin_recent_post (or null), "
            "twitter_handle (or null), twitter_followers (or null), twitter_recent_tweet (or null)."
        ),
        agent=scout,
    )

    evaluator_task = Task(
        description=(
            "You have received a list of raw leads from the Scout.\n\n"
            "Evaluate each lead against two frameworks:\n\n"
            "**Nouns DAO fit** — Award points for:\n"
            "  • CC0 / open-source culture (+20)\n"
            "  • Public goods orientation (+20)\n"
            "  • Community-driven / DAO governance (+20)\n"
            "  • On-chain / decentralized architecture (+20)\n"
            "  • Builder ethos, transparent roadmap (+10)\n"
            "  • Nounish aesthetic or existing Nouns connection (+10)\n\n"
            "**AthenaX listing fit** — Also consider:\n"
            "  • Genuine traction (stars, followers, activity)\n"
            "  • Team quality and public credibility\n"
            "  • Market timing and narrative relevance\n\n"
            "Score each lead 0–100. Discard anything below 50.\n"
            "Return the TOP 5 leads ranked by score with full rationale."
        ),
        expected_output=(
            "A JSON array of exactly 5 objects, each with: "
            "lead_name, lead_url, compatibility_score (int 0–100), "
            "nounish_traits (string array), reason_for_partnership (1–2 sentences), "
            "listing_fit_notes (1 sentence)."
        ),
        agent=evaluator,
        context=[scout_task],
    )

    writer_task = Task(
        description=(
            "You have the top 5 evaluated leads. Draft one outreach message per lead.\n\n"
            "Rules:\n"
            "• NO generic copy-paste. Every message must reference something SPECIFIC — "
            "a recent tweet, a GitHub commit, a LinkedIn post, or a product launch.\n"
            "• Choose the channel: Twitter DM if they have an active Twitter presence; "
            "email if LinkedIn is stronger. State your choice.\n"
            "• Twitter DMs: max 280 characters, punchy, personal.\n"
            "• Emails: include a subject line. Keep body under 150 words. "
            "Mention Nouns DAO and AthenaX naturally.\n"
            "• Tone: peer-to-peer, builder-to-builder. Not corporate.\n\n"
            "Return 5 draft objects in JSON."
        ),
        expected_output=(
            "A JSON array of exactly 5 objects, each with: "
            "lead_name, channel ('twitter_dm' or 'email'), "
            "subject (string or null for DMs), body (the message text)."
        ),
        agent=writer,
        context=[evaluator_task],
    )

    return Crew(
        agents=[scout, evaluator, writer],
        tasks=[scout_task, evaluator_task, writer_task],
        verbose=True,
    )
