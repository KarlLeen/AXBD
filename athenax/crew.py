"""CrewAI Crew — Scout → Evaluator → Writer pipeline."""
import os
from crewai import Crew, LLM, Task

from athenax.agents.scout import build_scout
from athenax.agents.evaluator import build_evaluator
from athenax.agents.verifier import build_verifier
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

PIPELINE_MIX = "Target mix: 70% new/early-stage + 30% established projects across all evaluated leads."


def build_llm() -> LLM:
    return LLM(
        model=MODEL,
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com/v1",
        temperature=0.3,
        max_tokens=8192,  # DeepSeek's ceiling — maximize complete leads per response
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

    # ── Task 1: Scout ────────────────────────────────────────────────────────

    scout_task = Task(
        description=f"""
You are sourcing project listing candidates for the AthenaX Launchpad.

AthenaX covers seven sectors:
{SECTORS}

Use ALL your tools to discover and fully profile EXACTLY 5 high-quality leads. Cast wide — cover multiple sectors.

HARD CAP — 5 leads: each lead carries a large profile (team, backers, voices, bounties, signals).
More than ~5 full profiles overflow the model's 8192-token output limit; the JSON then gets
truncated mid-array and EVERY lead is lost. A complete, well-closed 5-lead array beats a longer
one that gets cut off. Pick the 5 strongest candidates and profile each one deeply and completely.

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

FOR EACH LEAD — COLLECT ALL OF THE FOLLOWING:

━━━ PLATFORM ENRICHMENT (search all platforms for every lead) ━━━

① GitHub — find the repo. Extract: stars, forks, commits_last_30d, commits_last_90d,
            archived (bool), tech_stack (languages/frameworks), homepage URL.
② Twitter/X — find the official handle, follower count, most recent tweet.
              ALSO find BD/partnerships team members:
              Search "[project name] head of BD site:twitter.com",
              "[project name] partnerships site:twitter.com".
              Record as bd_twitter_handles: array of {{handle, name, role, followers}}.
              Include the main project handle (role: "official"). 2–4 entries preferred.
③ LinkedIn — find linkedin_profile URL and most recent post/announcement.
④ Web (Serper) — search "[project name] funding" and "[project name] team founders"
                 to surface backers, founding date, and team info.
⑤ Contact email — search for bd@, partnerships@, hello@ at the project's domain.
                  Only record a real address you found evidence for; otherwise "not found".

━━━ PROFILE FIELDS — EVERY field below is MANDATORY in each lead object ━━━
RULE: collect all of these first. Never omit a field and never leave one blank. If, after
genuinely searching with all your tools, you cannot find a value, set that field to the exact
string "not found". Exceptions:
  (a) url / website must ALWAYS be a real URL — it is the project's identity and dedup key, so
      only output projects that actually have one (never "not found" here).
  (b) list fields (other_links, backers, grants, team, voices, bounties, bd_twitter_handles)
      use an empty array [] when nothing is found.
  (c) numeric signals (github_stars, github_forks, commits_last_30d/90d, twitter_followers)
      stay numbers, or null if unknown — do NOT write "not found" for numbers.
  (d) link fields (github_url, twitter_url, discord_url, docs_url) — OMIT or set to null
      if not found. NEVER write "not found" for these fields.

NAME & DESCRIPTIONS
• name — official project/company name
• short_description — HARD LIMIT: 60 characters total (including the final period).
                      Must end with a period. One sharp phrase saying what it does.
                      Example: "Autonomous AI agents for enterprise ops." (42 chars ✓)
                      Count characters before outputting — never exceed 60.
• description — 3–5 sentences, 550–650 characters total. Never shorter than 500 or
                longer than 650 characters. Cover: what it builds, how it works,
                why it matters, and any key traction or differentiation.

CLASSIFICATION
• category — MUST be exactly one of:
    "AI & Agents" | "Biotech" | "Crypto" | "Developer Tools" |
    "Infrastructure" | "Robotics" | "RWA"
• subcategory — free-form niche tag within the category.
    Examples: "Foundation Models", "Drug Discovery", "ZK Proofs", "Humanoid Robots",
    "Tokenized Real Estate", "CI/CD", "Edge Computing". Be specific.

STAGE — pick the best match:
• "Active" — live product, actively operating
• "Active Development" — building, not yet live
• "Beta" — live but in beta / limited access
• "Seed" — raised or actively raising seed round
• "Series A" — raised or raising Series A
• "Series B" — raised or raising Series B+
• "Acquired" — acquired by another company
• "Not Active" — dormant / shut down (exclude these from output)

FOUNDING
• founded — year the project was founded (e.g. "2023"). Search LinkedIn, Crunchbase,
             website footer. "not found" if no founding year can be found.

LINKS (collect every link you can find)
CRITICAL RULE: If you cannot find a real URL for a link field, OMIT THAT FIELD ENTIRELY
from the JSON. NEVER set a link field to "not found" or any placeholder string.
Only output link fields where you have a verified, working URL.
• website — main product/company URL
• github_url — GitHub repo or org URL (only if found)
• twitter_url — full Twitter/X profile URL, e.g. https://x.com/handle (only if found)
• discord_url — Discord server invite link (only if found)
• docs_url — documentation URL: docs., gitbook., notion., etc. (only if found)
• other_links — array of any other relevant links (blog, whitepaper, token page, etc.)

BACKERS & GRANTS
• backers — JSON array of strings: VCs, angel investors, and accelerators ONLY.
  Do NOT include grants, prizes, or protocol incentive programs here.
  Search "[project name] investors", "[project name] backed by", "[project name] raised from".
  Examples: ["a16z", "Paradigm", "YC W26", "Sequoia"]. Empty array [] if none found.
• grants — JSON array of strings: grant programs, prizes, hackathon wins, and protocol
  incentives ONLY (not VCs). Examples: ["NSF SBIR Phase I", "ETHGlobal Best DeFi Prize",
  "Filecoin Foundation Grant"]. Empty array [] if none found.

TEAM (search LinkedIn, the website /team or /about page, Crunchbase, and Twitter bios)
• team — JSON array of the FOUNDERS + key leadership. Get EVERY co-founder you can find
  (most projects have 2–3); aim for 2–5 people. Do not stop at one person.
  Each member MUST have all four parts at this granularity:
  - name    — full name (e.g. "Amjad Masad")
  - title   — job title / role (e.g. "Co founder and CEO", "Executive Chair")
  - bio     — Short background bio as 2–3 bullet points (use "• " prefix).
              Focus ONLY on PREVIOUS EXPERIENCE — NOT current role (title covers that).
              Each bullet covers one signal: prior employer, company founded/exited,
              funding raised, acquisition, or top-university credential.
              Be specific and concrete. Total under 300 characters.
              BAD: "• Leads Polsia's AI platform"  (current role — wrong)
              GOOD: "• Early operator at CloudKitchens (Travis Kalanick)\n
                      • Founded prior startup, raised $17M\n
                      • MIT Computer Science"
  - linkedin — FULL LinkedIn profile URL. STRICT RULES:
               (1) NEVER construct a URL from a person's name. A URL like
                   linkedin.com/in/john-smith assembled from the name is a GUESS, not a fact.
               (2) You MUST find the URL in a search result, the project's /team page,
                   a Crunchbase profile, or the person's own Twitter bio before including it.
               (3) If your only "source" is your own pattern-matching, write "not found".
               HOW TO VERIFY: run web_search("[name] [company] LinkedIn") and confirm
               a result explicitly shows this URL or a LinkedIn page matching this person.
  - twitter  — FULL X/Twitter URL. Same strict rules as linkedin above:
               found in a search result or the person's own page → include.
               Guessed from the person's name → "not found".

  Reference granularity — this is the depth expected for ONE project's team (Replit):
    Amjad Masad | Co founder and CEO | Ex-Facebook engineer; previously co-founded JSRepl (acquired); raised $97M+ across multiple rounds. | https://www.linkedin.com/in/amjadmasad | https://x.com/amasad
    Haya Odeh | Co founder | Former software engineer at Facebook; Computer Science graduate of Hebrew University of Jerusalem. | https://www.linkedin.com/in/haya-odeh-b0725928/
    Faris Masad | Co founder | Previously software engineer at Facebook; Computer Science background from the University of Jordan. | https://www.linkedin.com/in/faris-masad-219b0515b/

  Empty array [] only if the project genuinely has no discoverable team.

VOICES (external mentions — NOT the project's own posts)
• voices — JSON array of third-party coverage. Aim for 4–6 entries; include only real,
  findable items. Prioritise: popular/high-engagement tweets from notable accounts (VCs,
  founders, influencers), press articles, and podcasts. Each entry:
  - url     — direct link to the article, tweet, or post (must be a real URL)
  - source  — who said it (e.g. "TechCrunch", "a16z blog", "@naval on X")
  - summary — one sentence on what was said
  Search "[project name] site:x.com", "[project name] mentioned by VC",
  "[project name] news 2025 2026". Only include entries with a verifiable URL.
  Empty array [] if genuinely none found — do NOT fabricate URLs.

BOUNTIES (reward programs the project runs)
• bounties — JSON array. For each:
  - title
  - description (what the bounty asks for)
  - reward (e.g. "$5,000 USDC")
  - url
  Search "[project name] bounty" or "[project name] grants program".
  Empty array [] if none found.

GITHUB SIGNALS (already covered in ① but include in output)
• github_stars, github_forks, commits_last_30d, commits_last_90d, tech_stack

SOCIAL SIGNALS
• twitter_handle, twitter_followers, twitter_recent_tweet
• linkedin_profile, linkedin_recent_post
• bd_twitter_handles, contact_email

VELOCITY
• velocity_notes — one sentence on any evidence of rapid recent growth.
• conference_origin — e.g. "ETHGlobal Bangkok winner", "YC W26", "not found" if none.

━━━ ACTIVITY CHECK ━━━
• Set status = "inactive" if: repo archived, commits_last_90d == 0, or project announced shutdown.
• Exclude inactive projects from output entirely.

━━━ MANDATORY VERIFICATION PASS (do this BEFORE writing the final JSON) ━━━
For every team member across all 5 leads, go through their linkedin and twitter fields:
  1. Ask yourself: "Did I find this URL in a search result, a /team page, a Crunchbase
     entry, or the person's own bio — or did I construct it from their name?"
  2. If constructed → replace with "not found".
  3. If found in a source → use web_search to confirm the page exists and the profile
     matches this person (right name, right company). If it doesn't match → "not found".
This pass is NOT optional. Hallucinated URLs waste admin time and damage trust.

Return a single, COMPLETE JSON array of EXACTLY 5 ACTIVE leads — never more than 5, and make sure
the array is fully closed (ends with `]`). A truncated array loses every lead.
""",
        expected_output=(
            "A JSON array of EXACTLY 5 active leads. Every field below is present on every "
            "object; any scalar value that could not be found is the string \"not found\" "
            "(except url/website which is always a real URL, list fields which are [] when "
            "empty, and numeric signals which stay numbers or null). Each object has: "
            "source, name, url, status ('active'), "
            "short_description, description, "
            "category (one of the 7 exact category names), subcategory (free-form niche tag), "
            "stage ('Active'|'Active Development'|'Beta'|'Seed'|'Series A'|'Series B'|'Acquired'), "
            "founded (year string or 'not found'), "
            "website (URL), github_url, twitter_url, discord_url, docs_url, "
            "other_links (array of URLs), "
            "backers (array of strings — VC/angel/accelerator names), "
            "team (array of {name, title, bio, linkedin, twitter}), "
            "voices (array of {url, source, summary}), "
            "bounties (array of {title, description, reward, url}), "
            "github_stars, github_forks, commits_last_30d, commits_last_90d, "
            "tech_stack (array), archived (bool), "
            "linkedin_profile, linkedin_recent_post, "
            "twitter_handle, twitter_followers, twitter_recent_tweet, "
            "bd_twitter_handles (array of {handle, name, role, followers}), "
            "contact_email, "
            "velocity_notes, conference_origin."
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

━━━ STEP 4 — EVALUATE ALL LEADS ━━━
{PIPELINE_MIX}
Evaluate EVERY lead that passes the disqualifier check. Do NOT limit to a subset.
Discard only leads that score below 55 — include everything else in your output.

━━━ STEP 5 — PRODUCE DETAILED EVALUATION ━━━
For EVERY surviving lead, produce a full criteria breakdown so the reviewer can
see exactly why it scored the way it did. If the Scout did not provide a field
(e.g. github_stars is null) and you need it to evaluate, call the github_search
or coingecko_search tool to fetch it. Do not leave a criterion unevaluated.

For each criterion record:
• met: true / false / null (null = data unavailable after attempting to fetch)
• note: short factual note (the actual data or why it's missing)

Return your results as a JSON array.
""",
        expected_output=(
            "A JSON array of ALL evaluated leads that scored ≥ 55 (no upper limit on count), each with: "
            "lead_name, lead_url, sector (one of the 7 sectors), "
            "project_type ('new' or 'established'), "
            "compatibility_score (int 0–100), "
            "disqualifiers_checked (bool — true means passed all checks), "
            "minimum_requirements_met (bool, new projects only), "
            "signal_boosters (string array — e.g. ['YC W25', 'a16z portfolio']), "
            "velocity_assessment (1 sentence on growth trajectory), "
            "nounish_traits (string array — keep for Nouns DAO context), "
            "reason_for_partnership (1–2 sentences — why AthenaX incubation/distribution fits this project), "
            "listing_fit_notes (1 sentence — which AthenaX value prop is most relevant: capital alignment, distribution, narrative, or ecosystem access), "
            "score_breakdown (object): { "
            "  base_score (int — 40 for new if minimums met, or tier-based for established), "
            "  booster_points (int — sum of signal booster points awarded), "
            "  velocity_multiplier (float — 1.0–1.3), "
            "  boosters_detail (array of {signal, points, note}) "
            "}, "
            "criteria_detail (object with per-criterion result): { "
            "  working_product: {met, note}, "
            "  website: {met, note}, "
            "  github: {met, stars, commits_last_30d, note}, "
            "  twitter: {met, followers, note}, "
            "  team: {met, note}, "
            "  sector_fit: {met, note}, "
            "  active_development: {met, note}, "
            "  market_presence: {met, note} "
            "}."
        ),
        agent=evaluator,
        context=[scout_task],
    )

    return Crew(
        agents=[scout, evaluator],
        tasks=[scout_task, evaluator_task],
        verbose=True,
    )


def build_scout_crew() -> Crew:
    """Scout-only crew (discovery, no evaluation) for the decoupled Scout step.

    Reuses build_crew()'s scout agent + task (which has no context dependency)
    and drops the evaluator, so the Scout step can run on its own.
    """
    full = build_crew()
    return Crew(agents=[full.agents[0]], tasks=[full.tasks[0]], verbose=True)


def build_evaluator_crew(leads_json: str) -> Crew:
    """Evaluator-only crew for the decoupled Evaluate step.

    Scores leads passed in as JSON (loaded from the DB) rather than via the
    Scout's in-memory context, so evaluation can run independently of scouting.
    Single source of truth for the standalone evaluator (dashboard + script).
    """
    llm = build_llm()
    evaluator = build_evaluator(llm=llm, tools=[CoinGeckoTool()])

    eval_task = Task(
        description=f"""
You have received raw leads from the Scout. Apply the AthenaX selection criteria rigorously.

━━━ LEADS TO EVALUATE ━━━
{leads_json}

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

━━━ STEP 4 — EVALUATE ALL LEADS ━━━
{PIPELINE_MIX}
Evaluate EVERY lead that passes the disqualifier check. Do NOT limit to a subset.
Discard only leads that score below 55 — include everything else in your output.

━━━ STEP 5 — PRODUCE DETAILED EVALUATION ━━━
For EVERY surviving lead, produce a full criteria breakdown so the reviewer can
see exactly why it scored the way it did. If the Scout did not provide a field
(e.g. github_stars is null) and you need it to evaluate, call the github_search
or coingecko_search tool to fetch it. Do not leave a criterion unevaluated.

For each criterion record:
• met: true / false / null (null = data unavailable after attempting to fetch)
• note: short factual note (the actual data or why it's missing)

Return your results as a JSON array.
""",
        expected_output=(
            "A JSON array of ALL evaluated leads that scored ≥ 55 (no upper limit on count), each with: "
            "lead_name, lead_url, sector (one of the 7 sectors), "
            "project_type ('new' or 'established'), "
            "compatibility_score (int 0–100), "
            "disqualifiers_checked (bool — true means passed all checks), "
            "minimum_requirements_met (bool, new projects only), "
            "signal_boosters (string array — e.g. ['YC W25', 'a16z portfolio']), "
            "velocity_assessment (1 sentence on growth trajectory), "
            "nounish_traits (string array — keep for Nouns DAO context), "
            "reason_for_partnership (1–2 sentences — why AthenaX incubation/distribution fits this project), "
            "listing_fit_notes (1 sentence — which AthenaX value prop is most relevant: capital alignment, distribution, narrative, or ecosystem access), "
            "score_breakdown (object): { "
            "  base_score (int — 40 for new if minimums met, or tier-based for established), "
            "  booster_points (int — sum of signal booster points awarded), "
            "  velocity_multiplier (float — 1.0–1.3), "
            "  boosters_detail (array of {signal, points, note}) "
            "}, "
            "criteria_detail (object with per-criterion result): { "
            "  working_product: {met, note}, "
            "  website: {met, note}, "
            "  github: {met, stars, commits_last_30d, note}, "
            "  twitter: {met, followers, note}, "
            "  team: {met, note}, "
            "  sector_fit: {met, note}, "
            "  active_development: {met, note}, "
            "  market_presence: {met, note} "
            "}."
        ),
        agent=evaluator,
    )

    return Crew(agents=[evaluator], tasks=[eval_task], verbose=True)


def build_verifier_crew(leads_json: str) -> Crew:
    """Verifier-only crew. Takes leads JSON from the DB, checks every team member
    URL and project link with web_search, and assigns a certainty score per lead."""
    llm = build_llm()
    verifier = build_verifier(
        llm=llm,
        tools=[SerperTool(), LinkedInProfileTool(), LinkedInPeopleSearchTool()],
    )

    verify_task = Task(
        description=f"""
You are given a list of scouted projects. Score each lead 0–100 based on TWO dimensions:
data completeness (50 pts) and URL verification (50 pts).

━━━ LEADS TO VERIFY ━━━
{leads_json}

━━━ PART A — DATA COMPLETENESS (50 pts total, 5 pts each) ━━━
Check whether each of the following 10 fields is properly filled. Award 5 pts per field:

  1. name              — present and not "not found"
  2. short_description — present, ≤ 60 characters, ends with a period
  3. description       — present, between 500 and 650 characters
  4. category (sector) — one of exactly: AI & Agents, Crypto, Biotech, Robotics,
                         RWA, Developer Tools, Infrastructure
  5. subcategory       — present, specific niche tag (not "not found")
  6. stage             — one of: Active, Active Development, Beta, Seed, Series A,
                         Series B, Acquired (not "not found")
  7. founded           — year present (not "not found")
  8. links             — at least one of github_url / twitter_url / discord_url / docs_url is present
  9. backers           — array has at least 1 entry
 10. team              — at least 1 member with name + title + bio all filled

━━━ PART B — URL VERIFICATION (50 pts total) ━━━

① Verify project exists on the web (+20 pts)
   web_search("[project name] official site") — confirm the project is real and the URL matches.

② Verify team member social URLs (up to +20 pts, +10 per verified URL, max 2)
   For each team member linkedin / twitter URL:
   - web_search("[person name] [company] LinkedIn") — confirm profile matches this person.
   - web_search("[person name] [company] site:x.com OR site:twitter.com") — same for Twitter.
   If confirmed → keep URL. If unconfirmed or wrong person → set to null.
   NEVER construct a URL from a name — only keep ones you verified.

③ Verify project links (up to +10 pts)
   github_url  → web_search("[project name] github"):   +5 if confirmed, else null
   twitter_url → web_search("[project name] twitter"):  +5 if confirmed, else null
   discord_url → web_search("[project name] discord"):  unconfirmed → null (no pts)
   docs_url    → web_search("[project name] docs"):     unconfirmed → null (no pts)

━━━ SCORING ━━━
  total = Part A score + Part B score  (max 100)
  70–100 → certainty = "high"
  40–69  → certainty = "medium"
  0–39   → certainty = "low"

━━━ certainty_note ━━━
Write ONE sentence that covers BOTH dimensions. Mention:
- which completeness fields are missing (e.g. "no backers, description too short")
- how many team URLs were verified and which project links were confirmed
Example: "Missing backers and subcategory; 1 of 2 team LinkedIn URLs verified; GitHub confirmed, Discord not found."

━━━ OUTPUT FORMAT ━━━
Return a JSON array — one object per lead — with exactly these fields:
  name             — project name (unchanged)
  certainty        — "high" | "medium" | "low"
  certainty_score  — integer 0–100
  certainty_note   — 1 sentence (completeness gaps + URL verification summary)
  team             — array, each member: {{name, linkedin (URL or null), twitter (URL or null)}}
  github_url       — verified URL or null
  twitter_url      — verified URL or null
  discord_url      — verified URL or null
  docs_url         — verified URL or null

Keep the array fully closed (ends with `]`).
""",
        expected_output=(
            "A JSON array — one object per lead — each with: "
            "name (string), certainty ('high'|'medium'|'low'), "
            "certainty_score (integer 0–100, sum of completeness + URL verification), "
            "certainty_note (1 sentence: missing fields + URL verification summary), "
            "team (array of {name, linkedin, twitter} — URLs verified or null), "
            "github_url (string or null), twitter_url (string or null), "
            "discord_url (string or null), docs_url (string or null)."
        ),
        agent=verifier,
    )

    return Crew(agents=[verifier], tasks=[verify_task], verbose=True)
