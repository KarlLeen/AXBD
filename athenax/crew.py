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
from athenax.tools.coingecko_tool import CoinGeckoTool

MODEL = "deepseek/deepseek-chat"   # DeepSeek-V3 via official API

# ── AthenaX Selection Criteria (embedded for agent context) ──────────────────

SECTORS = """
AI & Agents      — foundation models, fine-tuning platforms, autonomous agents, AI infrastructure,
                   MLOps, AI-native applications
Biotech          — drug discovery, synthetic biology, genomics, longevity, diagnostics,
                   lab automation, computational biology
Crypto           — L1/L2 protocols, DEXs, CEXs, wallets, ZK-proofs, bridges, DePIN,
                   stablecoins, on-chain credit, DAOs
Developer Tools  — SDKs, APIs, code editors, CI/CD, testing, monitoring, database tooling,
                   developer platforms
Infrastructure   — cloud, compute, networking, storage, security, edge, data pipelines,
                   orchestration
Robotics         — autonomous vehicles, drones, industrial robots, humanoids, manipulation
                   hardware, ROS tooling, sim-to-real
RWA              — tokenized real estate, commodities, treasuries, private credit, carbon credits,
                   trade finance, asset-backed lending, fractionalization platforms, compliance
                   and oracle infrastructure for off-chain asset verification
"""

DISQUALIFIERS = """
IMMEDIATE REJECTION — any one of these disqualifies a lead entirely:
• No working product (whitepaper-only, "coming soon", landing page with email capture only)
• Obvious scam signals (copied whitepaper, fake team photos, plagiarized code)
• Token-only project with no underlying product or protocol utility
• Inactive for 3+ months (no commits, no posts, no updates)
• Already widely known household name → move to established (30%) bucket instead
• NOUNS DAO'S OWN / AFFILIATED PROJECT — we do NOT pitch Nouns to itself.
  Reject anything that is: a Nouns sub-DAO, Nouns-funded, "by Nouns DAO",
  a Nouns proliferation pod, or whose primary identity is Nounish
  (e.g. Prop House, Lil Nouns, Gnars, Nouns Esports, Nouns Deli, etc.).
• SHUT DOWN / DISCONTINUED — the project must STILL BE OPERATING TODAY.
  Reject if it has wound down, sunset, archived its repo, announced shutdown,
  or shows no activity in the last 3 months. Example: Prop House ceased
  operations — it must be rejected even though it was once prominent.
  Verify recent activity (commits_last_30d, recent tweets/posts) before scoring.
"""

NEW_PROJECT_CRITERIA = """
MINIMUM REQUIREMENTS for new/early-stage projects (the 70% bucket):
✓ Working product — functional prototype, beta, or live product
    Verify: visit product URL, check for demo, or confirm GitHub activity shows real code
✓ Live website — functional site with clear product description (not just a landing page)
✓ GitHub OR Twitter/X presence (at least one is sufficient):
    - GitHub: public repo with meaningful commit history (not empty, not a stale fork)
    - Twitter/X: active account, ≥1,000 followers minimum; ≥3,000 preferred
✓ Team identifiability — at least one founder publicly identifiable (real name, LinkedIn, prior work)
✓ Sector fit — clearly falls within one of the seven sectors above

SIGNAL BOOSTERS (not required, raise priority score):
+15  YC-backed — Y Combinator acceptance is a strong quality filter; track current and recent batches
+12  a16z portfolio or radar — a16z investment OR public interest (blog, podcast, partner tweets)
+10  Other top-tier VC: Sequoia, Founders Fund, Index Ventures, Accel, Lightspeed (generalist);
     Paradigm, Polychain, Pantera, Multicoin, Framework Ventures, Dragonfly (crypto);
     Coatue, Tiger Global, Radical Ventures, Conviction Partners (AI);
     Lux Capital, a16z Bio, Flagship Pioneering, GV, DCVC (deep tech/bio);
     Khosla Ventures, Eclipse Ventures, Toyota Ventures (robotics);
     Heavybit, Redpoint, Unusual Ventures, Greylock (dev tools);
     ParaFi Capital, Superstate, Galaxy Digital, Brevan Howard Digital, Hamilton Lane (RWA)
+8   Active fundraising — currently raising or just closed a round (urgency + newsworthiness)
+6   Accelerator alumni — Techstars, Neo, Entrepreneur First, On Deck, Station F, or sector programs
+5   Academic origin — spun out of university lab (MIT, Stanford, CMU etc.) with published research
+8   Open-source traction — GitHub stars > 500, growing contributor base, active issues/PRs
+5   Active community — Discord/Telegram with real conversation (not bot-filled)

VELOCITY WEIGHTING (applies to all numeric signals):
  Weight growth RATE more than absolute numbers.
  - Went from 200→2,000 GitHub stars in 30 days > project with 5,000 stagnant stars
  - Same logic for Twitter followers, commit frequency, community size
"""

ESTABLISHED_PROJECT_CRITERIA = """
ESTABLISHED PROJECT requirements (the 30% bucket — trust anchors):
✓ Market presence: listed on CoinMarketCap/CoinGecko (crypto) OR recognized in major
    industry reports, press, or analyst coverage (non-crypto)
✓ Tier 1 or Tier 2 in their sector:
    Tier 1 = household name in the industry (market cap rank, dominant user base)
    Tier 2 = well-known among practitioners, top 20 in their niche
✓ Sector leadership: demonstrably a leader in at least one sub-vertical
    (e.g. leading L2 by TVL, top DEX by volume, dominant CI/CD tool by dev surveys)
✓ Active development: still actively shipping — NOT legacy or stagnant
✓ Brand fit: frontier tech — NOT consumer social, lifestyle brands, or low-tech SaaS

Sector anchor targets:
  Crypto:    L1/L2 leaders (Ethereum, Solana, Arbitrum, Optimism, Base);
             top DEXs (Uniswap, Jupiter); major wallets (MetaMask, Phantom, Rabby);
             ZK pioneers (zkSync, Starknet, Aztec); DeFi anchors (Aave, Lido, EigenLayer)
  AI/Agents: Foundation model companies (Anthropic, Mistral, Cohere);
             agent frameworks (LangChain, CrewAI); MLOps leaders with significant adoption
  Dev Tools: Category leaders — tools developers actually use and discuss on Hacker News
  Infra:     Cloud-native leaders, major open-source infra projects, compute/networking innovators
  Biotech:   Well-funded startups with published research + clinical/regulatory milestones;
             companies featured in Nature, Science, or STAT News
  Robotics:  Companies with demonstrated hardware + real-world deployments, or significant
             backing from robotics-focused funds (Khosla, Eclipse, Toyota Ventures)
  RWA:       Tokenization leaders (Ondo Finance, Centrifuge, Maple Finance);
             infrastructure (Chainlink CCIP, Goldfinch); institutional platforms (Securitize, Backed);
             projects with real AUM or TVL — NOT just tokenization concepts
"""

PIPELINE_MIX = "Target mix: 70% new/early-stage + 30% established projects across the top 5 leads."


def build_llm() -> LLM:
    return LLM(
        model=MODEL,
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com/v1",
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
    evaluator = build_evaluator(llm=llm, tools=[CoinGeckoTool()])
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

4. Web search (Serper) — run ALL of the following targeted queries:

   VC PORTFOLIO MONITORING (run each separately, all with "after:2025-06-01"):
   Generalist tier 1:
   • "Sequoia new investment 2026 AI crypto after:2025-06-01"
   • "Founders Fund portfolio company 2026 after:2025-06-01"
   • "Accel Index Ventures Lightspeed new investment 2026 after:2025-06-01"
   YC:
   • "YC W26 batch companies list after:2025-06-01"
   • "YC Demo Day W26 AI startup after:2025-06-01"
   a16z:
   • "a16z new investment announcement 2026 crypto AI after:2025-06-01"
   • "a16z Bio portfolio company 2026 after:2025-06-01"
   Crypto-focused:
   • "Paradigm portfolio company 2026 after:2025-06-01"
   • "Polychain new investment 2026 after:2025-06-01"
   • "Multicoin Capital Dragonfly Framework Ventures portfolio 2026 after:2025-06-01"
   AI-focused:
   • "Coatue Tiger Global Radical Ventures AI investment 2026 after:2025-06-01"
   Deep tech / Bio:
   • "Lux Capital Flagship Pioneering DCVC GV new investment 2026 after:2025-06-01"
   Robotics:
   • "Khosla Ventures Eclipse Ventures Toyota Ventures robotics investment 2026 after:2025-06-01"
   RWA / TradFi:
   • "ParaFi Capital Galaxy Digital Hamilton Lane tokenization investment 2026 after:2025-06-01"

   CONFERENCE & HACKATHON WINNERS (all with "after:2025-06-01"):
   AI:
   • "NeurIPS ICML 2026 demo day startup winner after:2025-06-01"
   • "AI Grant Cerebral Valley startup 2026 after:2025-06-01"
   Crypto:
   • "ETHGlobal hackathon winner 2026 after:2025-06-01"
   • "ETHDenver Devconnect Consensus 2026 winner project after:2025-06-01"
   • "Token2049 2026 featured project after:2025-06-01"
   Biotech:
   • "JP Morgan Healthcare Conference BIO 2026 startup after:2025-06-01"
   Robotics:
   • "IROS CoRL CES robotics startup 2026 after:2025-06-01"
   Dev Tools:
   • "KubeCon GitHub Universe DevRelCon 2026 startup after:2025-06-01"

FOR EACH LEAD COLLECT:
• Basic: name, URL, source, description, sector (your best guess)
• GitHub: stars, forks, last commit date, contributor count (if available)
• Twitter: handle, follower count, recent tweet (if available)
• LinkedIn: profile URL, recent post (if available)
• Signals: any VC/accelerator mentions, funding news, launch dates
• Velocity clue: any evidence of rapid recent growth (e.g. "just launched", "trending", recent funding)
• commits_last_30d and commits_last_90d: the GitHub tool returns these automatically — include both
• archived: the GitHub tool returns this — include it

HARD ACTIVITY CHECK — set status field for EVERY lead:
• status = "inactive" if ANY of the following is true:
  - GitHub repo is archived (archived == true)
  - commits_last_90d == 0 (no commits in 90 days; treat null as unknown, not inactive)
  - Project has publicly announced shutdown, sunset, or wind-down
• status = "active" otherwise
Do NOT pass inactive leads to the Evaluator — exclude them from the output array.

Return a single JSON array of ACTIVE leads only.
""",
        expected_output=(
            "A JSON array of active leads only (inactive leads excluded). Each object has: "
            "source, name, url, description, sector, status ('active'), "
            "github_stars, github_forks, archived (bool), "
            "commits_last_30d (int or null), commits_last_90d (int or null), "
            "tech_stack (array or null), "
            "linkedin_profile, linkedin_recent_post, "
            "twitter_handle, twitter_followers, twitter_recent_tweet, "
            "vc_backing (string or null), funding_stage (string or null), "
            "velocity_notes (string or null — any evidence of rapid recent growth), "
            "conference_origin (string or null — e.g. 'ETHGlobal winner', 'YC W26')."
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
For GitHub repos: use commits_last_30d as velocity signal (>50 commits/month = strong).
Cap at 100.

For ESTABLISHED crypto projects: use the coingecko_search tool to verify they are
actually listed. A Tier 1 project must have a CoinGecko market_cap_rank ≤ 50.

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
            "reason_for_partnership (1–2 sentences — why AthenaX incubation/distribution fits this project), "
            "listing_fit_notes (1 sentence — which AthenaX value prop is most relevant: capital alignment, distribution, narrative, or ecosystem access)."
        ),
        agent=evaluator,
        context=[scout_task],
    )

    # ── Task 3: Writer ───────────────────────────────────────────────────────

    writer_task = Task(
        description="""
You have the top 5 evaluated leads. Draft one outreach message per lead.

━━━ WHO YOU ARE ━━━
You represent AthenaX — NounsDAO's decentralized incubation and distribution layer.
AthenaX operates upstream of grants and incentives. It is NOT an accelerator, grant
provider, mentorship program, or marketing agency.

What AthenaX actually offers a partner:
• Capital alignment: equity, tokens, or revenue share — zero-cost model, no treasury drain
• Distribution: 6M+ monthly ecosystem reach via AthenaX Media (long-form, live streams)
• Narrative shaping and market signaling — early GTM clarity before dilution
• Institutional access: NounsDAO treasury ($100M+ deployed, 33rd largest ETH holder),
  partner ecosystems across BNB Chain, Solana, Ethereum, Mantle, Sui, Base, Aptos
• Track record: co-built with Pudgy Penguins, Lido, Gitcoin, Parcl, Sui, and more

AthenaX backs builders with infrastructure and alignment — think YZi Labs, not YC.
Partnerships are based on alignment, not volume. AthenaX does NOT optimize for
speed of onboarding or short-term token launches.

━━━ MESSAGE RULES ━━━
• NO generic copy-paste. Every message must reference something SPECIFIC —
  a recent tweet, a GitHub commit, a LinkedIn post, a product launch, a funding round,
  a conference talk, or a hackathon win.
• Choose channel: Twitter DM if they have active Twitter presence (≥1k followers);
  email if LinkedIn is stronger or no Twitter.
• Twitter DMs: max 280 characters, punchy, peer-to-peer.
• Emails: subject line required. Body under 150 words.
• Tone: builder-to-builder, curious, direct. Never corporate or salesy.
• For established projects: lead with mutual credibility, reference their sector standing,
  and frame AthenaX as distribution + narrative infrastructure — not just another partner.
• For new/early projects: lead with what you noticed about their momentum, then offer
  the zero-cost incubation angle — capital alignment with no treasury drain.
• Never say "launchpad", "directory", or "accelerator". Say "incubation layer" or
  "distribution infrastructure" if you need a label. Preferably just be specific.
• Close with a low-friction ask: a 15-min call, or just "curious if aligned."
• Sign emails as "— Karl". Sign Twitter DMs without a signature (DMs have no sign-off).
• NEVER use placeholder text like "[Your name]", "[Name]", or "[Your Name]". Always use "Karl".

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
