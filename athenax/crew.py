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

# ── AthenaX Selection Criteria (embedded for agent context) ──────────────────

SECTORS = """
AI & Agents      — foundation models, agents, AI infra, MLOps, AI-native apps
Biotech          — drug discovery, genomics, longevity, lab automation, computational bio
Crypto           — L1/L2, DEXs, wallets, ZK, bridges, DePIN, stablecoins, DAOs
Developer Tools  — SDKs, APIs, editors, CI/CD, testing, monitoring, DB tooling
Infrastructure   — cloud, compute, networking, storage, security, edge, data pipelines
Robotics         — autonomous vehicles, drones, industrial robots, humanoids, sim-to-real
RWA              — tokenized real estate, commodities, treasuries, private credit, carbon credits
"""

DISQUALIFIERS = """
IMMEDIATE REJECTION — any one of these disqualifies a lead entirely:
• No working product (whitepaper-only, "coming soon", landing page with email capture only)
• Obvious scam signals (copied whitepaper, fake team photos, plagiarized code)
• Token-only project with no underlying product or protocol utility
• Inactive for 3+ months (no commits, no posts, no updates)
• Already widely known household name → move to established (30%) bucket instead
"""

NEW_PROJECT_CRITERIA = """
MINIMUM REQUIREMENTS for new/early-stage projects (the 70% bucket):
✓ Working product — functional prototype, beta, or live product (verify via URL, demo, or GitHub activity)
✓ Live website — functional site with clear product description
✓ GitHub OR Twitter presence (at least one):
    - GitHub: public repo with meaningful commit history (not empty, not a stale fork)
    - Twitter/X: active account, ≥1,000 followers minimum (≥3,000 preferred)
✓ Team identifiability — at least one founder publicly identifiable (real name, LinkedIn, prior work)
✓ Sector fit — clearly falls within one of the seven sectors above

SIGNAL BOOSTERS (not required, raise priority score):
+15  YC-backed (current or recent batch)
+12  a16z portfolio or public radar (blog, podcast, partner tweets)
+10  Other top-tier VC: Sequoia, Paradigm, Polychain, Founders Fund, Lux Capital,
     Multicoin, Pantera, Coatue, Radical Ventures, Khosla, Heavybit, ParaFi, etc.
+8   Active fundraising (currently raising or just closed a round)
+6   Accelerator alumni (Techstars, Neo, Entrepreneur First, On Deck, Station F)
+5   Academic spin-out (MIT, Stanford, CMU, etc. with published research)
+8   Open-source traction: GitHub stars > 500, growing contributor base
+5   Active community (Discord/Telegram with real conversation)

VELOCITY WEIGHTING (applies to all numeric signals):
  Weight growth RATE more than absolute numbers.
  - Went from 200→2,000 GitHub stars in 30 days > project with 5,000 stagnant stars
  - Same logic for Twitter followers, commit frequency, community size
"""

ESTABLISHED_PROJECT_CRITERIA = """
ESTABLISHED PROJECT requirements (the 30% bucket — trust anchors):
✓ Market presence: listed on CoinMarketCap/CoinGecko (crypto) OR major industry reports/press (non-crypto)
✓ Tier 1 or Tier 2 in their sector:
    Tier 1 = household name in the industry
    Tier 2 = well-known among practitioners, top 20 in their niche
✓ Sector leadership: demonstrably a leader in at least one sub-vertical
✓ Active development: still shipping (GitHub activity, changelogs, announcements)
✓ Brand fit: frontier tech — NOT consumer social, lifestyle brands, or low-tech SaaS

Sector anchor examples:
  Crypto: Ethereum, Solana, Arbitrum, Uniswap, MetaMask, zkSync, Aave, Lido, EigenLayer
  AI & Agents: Anthropic, Mistral, LangChain, CrewAI, Cohere
  Dev Tools: category leaders that developers discuss on Hacker News
  RWA: Ondo Finance, Centrifuge, Maple Finance, Securitize, Backed Finance
"""

PIPELINE_MIX = "Target mix: 70% new/early-stage + 30% established projects across the top 5 leads."


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

    # ── Task 1: Scout ────────────────────────────────────────────────────────

    scout_task = Task(
        description=f"""
You are sourcing project listing candidates for the AthenaX Launchpad.

AthenaX covers seven sectors:
{SECTORS}

Use ALL your tools to discover 15–20 raw leads. Cast wide — cover multiple sectors.

SEARCH STRATEGY:
1. GitHub — search repos per sector:
   • AI/Agents: "AI agent framework", "LLM infrastructure", "autonomous agent"
   • Crypto: "L2 protocol", "ZK proof", "DePIN", "DAO tooling"
   • Dev Tools: "developer SDK", "CI/CD", "code intelligence"
   • Infrastructure: "cloud native", "edge computing", "data pipeline"
   • RWA: "tokenized assets", "real world assets", "on-chain credit"
   • Robotics: "autonomous robot", "drone software", "humanoid"
   • Biotech: "drug discovery", "genomics", "computational biology"

2. LinkedIn — search companies and posts with sector-specific keywords.

3. Twitter/X — hashtags: #AI #Web3 #DePIN #RWA #BuildInPublic #ZKProof #Robotics #Biotech

4. Web search (Serper) — YC batch announcements, a16z portfolio updates,
   Paradigm/Multicoin/Polychain investments, ETHGlobal hackathon winners,
   NeurIPS demo days, recent seed/Series A announcements in these sectors.

FOR EACH LEAD COLLECT:
• Basic: name, URL, source, description, sector (your best guess)
• GitHub: stars, forks, last commit date, contributor count (if available)
• Twitter: handle, follower count, recent tweet (if available)
• LinkedIn: profile URL, recent post (if available)
• Signals: any VC/accelerator mentions, funding news, launch dates
• Velocity clue: any evidence of rapid recent growth (e.g. "just launched", "trending", recent funding)

Return a single JSON array.
""",
        expected_output=(
            "A JSON array of 15–20 lead objects, each with: "
            "source, name, url, description, sector, "
            "github_stars, github_forks, tech_stack (array or null), "
            "linkedin_profile, linkedin_recent_post, "
            "twitter_handle, twitter_followers, twitter_recent_tweet, "
            "vc_backing (string or null), funding_stage (string or null), "
            "velocity_notes (string or null — any evidence of rapid recent growth)."
        ),
        agent=scout,
    )

    # ── Task 2: Evaluator ────────────────────────────────────────────────────

    evaluator_task = Task(
        description=f"""
You have received raw leads from the Scout. Apply the AthenaX selection criteria rigorously.

━━━ STEP 1 — HARD DISQUALIFIERS (check first, reject immediately if any apply) ━━━
{DISQUALIFIERS}

━━━ STEP 2 — CLASSIFY each surviving lead ━━━
• "new"         → pre-PMF, early GTM, or actively fundraising (70% bucket)
• "established" → recognized market leader or Tier 1/2 player (30% bucket)

━━━ STEP 3 — SCORE 0–100 ━━━

For NEW projects:
{NEW_PROJECT_CRITERIA}

Base score starts at 40 if all minimum requirements are met.
Add signal booster points as listed above.
Apply velocity multiplier: if growth rate is exceptional, multiply total by up to 1.3×.
Cap at 100.

For ESTABLISHED projects:
{ESTABLISHED_PROJECT_CRITERIA}

Score based on tier (Tier 1 = 85–100, Tier 2 = 70–84), sector leadership, and active development.

━━━ STEP 4 — SELECT TOP 5 ━━━
{PIPELINE_MIX}
Aim for ~3–4 new projects and ~1–2 established anchors in your top 5.
Rank by score. Discard anything below 55.

Return your results as a JSON array.
""",
        expected_output=(
            "A JSON array of exactly 5 objects, each with: "
            "lead_name, lead_url, sector (one of the 7 sectors), "
            "project_type ('new' or 'established'), "
            "compatibility_score (int 0–100), "
            "disqualifiers_checked (bool — true means passed all checks), "
            "minimum_requirements_met (bool, new projects only), "
            "signal_boosters (string array — e.g. ['YC W25', 'a16z portfolio']), "
            "velocity_assessment (1 sentence on growth trajectory), "
            "nounish_traits (string array — keep for Nouns DAO context), "
            "reason_for_partnership (1–2 sentences), "
            "listing_fit_notes (1 sentence on AthenaX fit)."
        ),
        agent=evaluator,
        context=[scout_task],
    )

    # ── Task 3: Writer ───────────────────────────────────────────────────────

    writer_task = Task(
        description="""
You have the top 5 evaluated leads. Draft one outreach message per lead.

RULES:
• NO generic copy-paste. Every message must reference something SPECIFIC —
  a recent tweet, a GitHub commit, a LinkedIn post, a product launch, a funding round,
  a conference talk, or a hackathon win.
• Choose channel: Twitter DM if they have an active Twitter presence (≥1k followers);
  email if LinkedIn is stronger or no Twitter.
• Twitter DMs: max 280 characters, punchy, peer-to-peer.
• Emails: subject line required. Body under 150 words. Mention AthenaX naturally
  (positioning: curated frontier tech launchpad, not a generic directory).
• Tone: builder-to-builder, curious, direct. Never corporate or salesy.
• For established projects, lead with mutual credibility — reference their sector standing.
• For new projects, lead with what you noticed specifically about their momentum.

Return 5 draft objects in JSON.
""",
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
