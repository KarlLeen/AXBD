from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass
class Lead:
    name: str
    url: str
    source: str
    id: str = field(default_factory=_uuid)
    description: str | None = None
    github_stars: int | None = None
    github_forks: int | None = None
    github_contributors: int | None = None
    tech_stack: list[str] | None = None
    linkedin_profile: str | None = None
    linkedin_recent_post: str | None = None
    twitter_handle: str | None = None
    twitter_followers: int | None = None
    twitter_recent_tweet: str | None = None
    created_at: str = field(default_factory=_now)

    def to_db_row(self) -> dict:
        d = self.__dict__.copy()
        if d["tech_stack"] is not None:
            d["tech_stack"] = json.dumps(d["tech_stack"])
        return d


@dataclass
class Evaluation:
    lead_id: str
    compatibility_score: int
    reason_for_partnership: str
    id: str = field(default_factory=_uuid)
    nounish_traits: list[str] | None = None
    listing_fit_notes: str | None = None
    created_at: str = field(default_factory=_now)

    def to_db_row(self) -> dict:
        d = self.__dict__.copy()
        if d["nounish_traits"] is not None:
            d["nounish_traits"] = json.dumps(d["nounish_traits"])
        return d


@dataclass
class OutreachDraft:
    lead_id: str
    evaluation_id: str
    channel: str
    body: str
    id: str = field(default_factory=_uuid)
    subject: str | None = None
    status: str = "pending"
    approved_at: str | None = None
    created_at: str = field(default_factory=_now)
