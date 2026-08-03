#!/usr/bin/env python3
"""Find Twitter handles for Aventus Community Map entries."""

import csv
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

BEARER_TOKEN = os.environ["TWITTER_BEARER_TOKEN"]
HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}"}
EXCEL_PATH = "/Users/karl4chill/Downloads/_Aventus Community Map.xlsx"
OUTPUT_PATH = "/Users/karl4chill/dev/axbd/aventus_twitter_handles.csv"

SKIP_PATTERNS = (
    r"^Community / Group$",
    r"^Twitter/X$",
    r"^\d+\.",
    r"^Aventus —",
    r"^Communities Aventus",
    r"^\(Future",
)

# High-confidence known official handles (verified manually / widely known)
KNOWN_HANDLES = {
    "Polkadot / Web3 Foundation": ("Polkadot", "high", "Official Polkadot account"),
    "Parity Technologies": ("ParityTech", "high", "Official Parity Technologies account"),
    "Ethereum": ("ethereum", "high", "Official Ethereum account"),
    "Moonbeam (GLMR)": ("MoonbeamNetwork", "high", "Official Moonbeam Network account"),
    "Astar (ASTR)": ("AstarNetwork", "high", "Official Astar Network account"),
    "Acala (ACA)": ("AcalaNetwork", "high", "Official Acala Network account"),
    "Hydration / HydraDX (HDX)": ("HydraDX", "high", "Rebranded to Hydration; handle @HydraDX"),
    "Bifrost (BNC)": ("BifrostFinance", "high", "Official Bifrost Finance account"),
    "Centrifuge (CFG)": ("centrifuge", "high", "Official Centrifuge account"),
    "Phala Network (PHA)": ("PhalaNetwork", "high", "Official Phala Network account"),
    "Unique Network (UNQ)": ("Unique_NFTchain", "high", "Official Unique Network account"),
    "Mythos (MYTH)": ("EnterTheMythos", "high", "Official Mythos gaming account"),
    "Energy Web X (EWT)": ("energywebx", "high", "Official Energy Web X account"),
    "Energy Web": ("energywebx", "high", "Energy Web / Energy Web X official account"),
    "Frequency (FRQCY)": ("onefrequency", "high", "Official Frequency (DSNP) account"),
    "Interlay (INTR)": ("interlayHQ", "high", "Official Interlay account"),
    "Manta (MANTA)": ("MantaNetwork", "high", "Official Manta Network account"),
    "KILT Protocol (KILT)": ("Kiltprotocol", "high", "Official KILT Protocol account"),
    "Nodle (NODL)": ("NodleNetwork", "high", "Official Nodle Network account"),
    "Parallel Finance (PARA)": ("ParallelFi", "high", "Official Parallel Finance account"),
    "Composable (LAYR)": ("ComposableFin", "high", "Official Composable Finance account"),
    "Integritee (TEER)": ("IntegriteeHQ", "high", "Official Integritee account"),
    "Darwinia (RING)": ("DarwiniaNetwork", "high", "Official Darwinia Network account"),
    "Crust Network (CRU)": ("CrustNetwork", "high", "Official Crust Network account"),
    "Zeitgeist (ZTG)": ("ZeitgeistPM", "high", "Official Zeitgeist account"),
    "Polkadex (PDEX)": ("Polkadex", "high", "Official Polkadex account"),
    "Ajuna Network (AJUN)": ("AjunaNetwork", "high", "Official Ajuna Network account"),
    "NeuroWeb (NEURO)": ("NeuroWebAI", "high", "Official NeuroWeb account"),
    "Pendulum (PEN)": ("Pendulum_chain", "high", "Official Pendulum chain account"),
    "peaq (PEAQ)": ("peaqnetwork", "high", "Official peaq network account"),
    "InvArch (VARCH)": ("InvArchNetwork", "high", "Official InvArch account"),
    "Litentry (LIT)": ("litentry", "high", "Official Litentry account"),
    "Polimec (PLMC)": ("PolimecProtocol", "high", "Official Polimec account"),
    "Robonomics (XRT)": ("AIRA_Robonomics", "high", "Official Robonomics account"),
    "Logion (LGNT)": ("LogionNetwork", "medium", "Likely official Logion account; verify"),
    "Equilibrium (EQ)": ("EquilibriumDeFi", "medium", "Likely official Equilibrium account; parachain status uncertain"),
    "Vodafone (DAB platform)": ("Vodafone", "high", "Official Vodafone corporate account"),
    "Beatport": ("beatport", "high", "Official Beatport account"),
    "NFL Alumni": ("NFLAlumni", "high", "Official NFL Alumni account"),
    "Imperial College London": ("imperialcollege", "high", "Official Imperial College London account"),
    "CoinShares": ("CoinSharesCo", "high", "Official CoinShares account"),
    "PayPal": ("PayPal", "high", "Listed in extended reach brands"),
    "Shell": ("Shell", "high", "Listed in extended reach brands"),
    "EDF": ("EDFofficiel", "medium", "EDF official account (French energy company)"),
    "Time Magazine": ("TIME", "high", "Official TIME account"),
    "Sports Illustrated": ("SInow", "high", "Official Sports Illustrated account"),
    "Truth Network (now Predictor Network)": ("PredictorNetwork", "medium", "Rebranded to Predictor Network"),
    "Truth Network appchain (TRUU)": ("PredictorNetwork", "medium", "Same ecosystem as Predictor Network / TRUU"),
    "Enigmatic Smile (Voucher Ledger)": ("EnigmaticSmile", "medium", "Company account; verify against Voucher Ledger"),
    "VOW / vCurrency (Cashbackapp)": ("vowcurrency", "medium", "VOW / vCurrency project account"),
    "Fruitlab (PIP token)": ("FruitlabOfficial", "low", "Historical project; account may be inactive"),
    "FanDragon Technologies": ("FanDragonTech", "low", "Historical ticketing partner; limited recent activity"),
    "Artos Systems": ("ArtosSystems", "low", "Historical partner; account may be inactive"),
    "Parity Sports (paritynow)": ("paritynow", "high", "Handle explicitly referenced in Excel entry name"),
    "Aventus Node Holders (retail)": ("AventusNetwork", "medium", "No dedicated retail-holder account; using @AventusNetwork"),
}


def should_skip(name: str) -> bool:
    name = name.strip()
    if not name:
        return True
    return any(re.search(p, name, re.I) for p in SKIP_PATTERNS)


def extract_entries() -> List[Dict]:
    df = pd.read_excel(EXCEL_PATH, sheet_name="Aventus Communities", header=None)
    entries = []
    current_section = ""

    for _, row in df.iterrows():
        name = str(row[0]).strip() if pd.notna(row[0]) else ""
        if not name:
            continue
        if re.match(r"^\d", name) and "Community / Group" not in name:
            current_section = name
            continue
        if should_skip(name):
            continue

        community_type = str(row[2]).strip() if pd.notna(row[2]) else ""
        entries.append(
            {
                "name": name,
                "section": current_section,
                "community_type": community_type,
            }
        )

    # Split extended reach brands row into individual names
    expanded = []
    for entry in entries:
        if entry["name"].startswith("Sports Illustrated, Time Magazine"):
            brands = [
                "Sports Illustrated",
                "Time Magazine",
                "PayPal",
                "Shell",
                "EDF",
                "Loyalty Key",
            ]
            for brand in brands:
                expanded.append({**entry, "name": brand, "parent_group": entry["name"]})
        else:
            expanded.append({**entry, "parent_group": ""})
    return expanded


def clean_search_name(name: str) -> str:
    name = re.sub(r"\s*\([^)]*\)", "", name)
    name = re.sub(r"\s*—.*$", "", name)
    name = re.sub(r"\s*/.*$", "", name)
    name = re.sub(r"\s+via\s+.*$", "", name, flags=re.I)
    return name.strip()


def lookup_by_username(username: str) -> Optional[Dict]:
    url = f"https://api.twitter.com/2/users/by/username/{urllib.parse.quote(username)}"
    try:
        resp = requests.get(
            url,
            headers=HEADERS,
            params={"user.fields": "name,description,verified,public_metrics"},
            timeout=20,
        )
        if resp.status_code == 429:
            time.sleep(60)
            resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            data = resp.json().get("data")
            return data
        return None
    except requests.RequestException:
        return None


def search_users(query: str, count: int = 10) -> List[Dict]:
    try:
        resp = requests.get(
            "https://api.twitter.com/1.1/users/search.json",
            headers=HEADERS,
            params={"q": query, "count": count},
            timeout=20,
        )
        if resp.status_code == 429:
            time.sleep(60)
            resp = requests.get(
                "https://api.twitter.com/1.1/users/search.json",
                headers=HEADERS,
                params={"q": query, "count": count},
                timeout=20,
            )
        if resp.status_code == 200:
            return resp.json()
        return []
    except requests.RequestException:
        return []


def score_match(name: str, community_type: str, user: dict) -> float:
    uname = (user.get("screen_name") or user.get("username") or "").lower()
    display = (user.get("name") or "").lower()
    desc = (user.get("description") or "").lower()
    search = clean_search_name(name).lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", search) if len(t) > 2]

    score = 0.0
    if search.replace(" ", "") in uname or uname in search.replace(" ", ""):
        score += 5
    for token in tokens:
        if token in uname:
            score += 2
        if token in display:
            score += 1.5
        if token in desc:
            score += 0.5

    type_tokens = [t for t in re.split(r"[^a-z0-9]+", community_type.lower()) if len(t) > 3]
    for token in type_tokens[:3]:
        if token in desc:
            score += 0.3

    if user.get("verified"):
        score += 0.5
    followers = 0
    if "followers_count" in user:
        followers = user["followers_count"]
    elif user.get("public_metrics", {}).get("follower_count"):
        followers = user["public_metrics"]["follower_count"]
    if followers > 10000:
        score += 1
    elif followers > 1000:
        score += 0.5

    return score


def find_handle(entry: dict) -> dict:
    name = entry["name"]
    community_type = entry["community_type"]

    if name in KNOWN_HANDLES:
        handle, confidence, notes = KNOWN_HANDLES[name]
        user = lookup_by_username(handle)
        time.sleep(0.5)
        if user:
            return {
                "name": name,
                "company": community_type or entry.get("parent_group", ""),
                "twitter_handle": f"@{user['username']}",
                "confidence": confidence,
                "notes": f"{notes}; API verified ({user.get('name', '')})",
            }
        return {
            "name": name,
            "company": community_type or entry.get("parent_group", ""),
            "twitter_handle": f"@{handle}",
            "confidence": confidence,
            "notes": f"{notes}; known mapping (API lookup failed)",
        }

    # Try direct username guesses from cleaned name
    clean = clean_search_name(name)
    guesses = []
    compact = re.sub(r"[^a-zA-Z0-9]", "", clean)
    guesses.extend([compact, compact + "HQ", compact + "Network", compact + "Tech"])
    if " " in clean:
        parts = clean.split()
        guesses.append("".join(parts))
        guesses.append(parts[0])

    for guess in guesses:
        if len(guess) < 3:
            continue
        user = lookup_by_username(guess)
        time.sleep(0.5)
        if user:
            score = score_match(name, community_type, {
                "screen_name": user["username"],
                "name": user.get("name", ""),
                "description": user.get("description", ""),
                "verified": user.get("verified", False),
                "public_metrics": user.get("public_metrics", {}),
            })
            if score >= 3:
                conf = "high" if score >= 6 else "medium"
                return {
                    "name": name,
                    "company": community_type,
                    "twitter_handle": f"@{user['username']}",
                    "confidence": conf,
                    "notes": f"Direct username lookup; score={score:.1f}; {user.get('name', '')}",
                }

    # Search API
    queries = [clean]
    if community_type:
        short_type = community_type.split("/")[0].split("—")[0].strip()
        if short_type and short_type.lower() not in clean.lower():
            queries.append(f"{clean} {short_type}")

    best = None
    best_score = 0
    for query in queries:
        results = search_users(query)
        time.sleep(1)
        for user in results:
            score = score_match(name, community_type, user)
            if score > best_score:
                best_score = score
                best = user

    if best and best_score >= 4:
        conf = "high" if best_score >= 7 else "medium"
        return {
            "name": name,
            "company": community_type,
            "twitter_handle": f"@{best['screen_name']}",
            "confidence": conf,
            "notes": f"Search match score={best_score:.1f}; {best.get('name', '')}",
        }
    if best and best_score >= 2.5:
        return {
            "name": name,
            "company": community_type,
            "twitter_handle": f"@{best['screen_name']}",
            "confidence": "low",
            "notes": f"Ambiguous search match score={best_score:.1f}; verify manually",
        }

    return {
        "name": name,
        "company": community_type,
        "twitter_handle": "",
        "confidence": "none",
        "notes": "No confident match found via API",
    }


def main():
    entries = extract_entries()
    print(f"Processing {len(entries)} entries...")
    results = []
    for i, entry in enumerate(entries, 1):
        print(f"[{i}/{len(entries)}] {entry['name']}")
        results.append(find_handle(entry))

    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["name", "company", "twitter_handle", "confidence", "notes"],
        )
        writer.writeheader()
        writer.writerows(results)

    found = sum(1 for r in results if r["twitter_handle"])
    print(f"\nDone: {found}/{len(results)} handles found")
    print(f"Saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
