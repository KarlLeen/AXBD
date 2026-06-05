"""Unit tests for Nouns-affiliated lead exclusion."""
import pytest
from athenax.filters import is_excluded, filter_leads


class TestIsExcluded:
    def test_excludes_known_twitter_handle(self):
        # 'lilnounsdao' is in the exclusion list
        excl, reason = is_excluded({"twitter_handle": "lilnounsdao", "name": "Lil Nouns"})
        assert excl
        assert "Twitter" in reason or "keyword" in reason

    def test_excludes_handle_with_at_prefix(self):
        excl, _ = is_excluded({"twitter_handle": "@nounsdao", "name": "X"})
        assert excl

    def test_excludes_by_name_keyword(self):
        excl, reason = is_excluded({"name": "Prop House (by Nouns DAO)", "twitter_handle": ""})
        assert excl

    def test_excludes_by_url_handle(self):
        excl, _ = is_excluded({"name": "Some Project", "url": "https://x.com/lilnounsdao"})
        assert excl

    def test_excludes_funded_by_nouns_phrase(self):
        excl, reason = is_excluded({
            "name": "Mystery Project",
            "description": "A simple way to award builders. Born in and funded by Nouns DAO.",
            "twitter_handle": "mysteryxyz",
        })
        assert excl

    def test_excludes_nounish_keyword(self):
        excl, _ = is_excluded({"name": "Gnars DAO", "twitter_handle": "somethingelse"})
        assert excl

    def test_keeps_unrelated_project(self):
        excl, reason = is_excluded({
            "name": "unionlabs/union",
            "description": "Trust-minimized zkIBC bridging protocol",
            "twitter_handle": "union_build",
            "url": "https://github.com/unionlabs/union",
        })
        assert not excl
        assert reason == ""

    def test_keeps_generic_crypto_project(self):
        excl, _ = is_excluded({
            "name": "pk910/PoWFaucet",
            "description": "Proof-of-work faucet with Gitcoin Passport",
            "twitter_handle": "pk910",
        })
        assert not excl


class TestFilterLeads:
    def test_splits_kept_and_excluded(self):
        leads = [
            {"name": "Lil Nouns", "twitter_handle": "lilnounsdao"},
            {"name": "unionlabs/union", "twitter_handle": "union_build",
             "url": "https://github.com/unionlabs/union"},
            {"name": "Prop House (by Nouns DAO)", "twitter_handle": ""},
        ]
        kept, excluded = filter_leads(leads)
        assert len(kept) == 1
        assert len(excluded) == 2
        assert kept[0]["name"] == "unionlabs/union"
        assert all("_exclusion_reason" in e for e in excluded)

    def test_empty_list(self):
        kept, excluded = filter_leads([])
        assert kept == []
        assert excluded == []

    def test_all_kept(self):
        leads = [{"name": "promptfoo/promptfoo", "twitter_handle": "promptfoo"}]
        kept, excluded = filter_leads(leads)
        assert len(kept) == 1
        assert len(excluded) == 0
