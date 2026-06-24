"""Tests for the in-memory employee roster cache with TTL."""
from bot import get_roster_cache, RosterCache

TEMP_ROSTER = {"fatou manneh": {"id": "f1", "name": "Fatou Manneh"}}


class TestRosterCache:
    """Roster cache stores and refreshes employee listings."""

    def test_cache_miss_calls_fetch(self):
        """On cache miss, fetch is called and result is cached."""
        cache = RosterCache(ttl_seconds=1800)

        def fake_fetch():
            return dict(TEMP_ROSTER)

        result = cache.get("drive_123", fake_fetch)
        assert result == TEMP_ROSTER

    def test_cache_hit_returns_stored(self):
        """On cache hit (within TTL), stored value is returned without calling fetch."""
        cache = RosterCache(ttl_seconds=1800)
        call_count = 0

        def fake_fetch():
            nonlocal call_count
            call_count += 1
            return dict(TEMP_ROSTER)

        # First call — miss, calls fetch
        result1 = cache.get("drive_123", fake_fetch)
        assert call_count == 1

        # Second call — hit, no fetch
        result2 = cache.get("drive_123", fake_fetch)
        assert call_count == 1
        assert result2 == TEMP_ROSTER

    def test_cache_expiry_triggers_refetch(self):
        """After TTL expires, cache miss triggers a new fetch."""
        cache = RosterCache(ttl_seconds=0)  # Immediate expiry
        call_count = 0

        def fake_fetch():
            nonlocal call_count
            call_count += 1
            return dict(TEMP_ROSTER)

        cache.get("drive_123", fake_fetch)
        cache.get("drive_123", fake_fetch)
        assert call_count == 2, "Both calls should trigger fetch when TTL=0"

    def test_separate_drive_ids_separate_caches(self):
        """Different drive_root_ids have independent cache entries."""
        cache = RosterCache(ttl_seconds=1800)

        def fetch_a():
            return {"emp a": {"id": "a1", "name": "Emp A"}}

        def fetch_b():
            return {"emp b": {"id": "b1", "name": "Emp B"}}

        result_a = cache.get("drive_a", fetch_a)
        result_b = cache.get("drive_b", fetch_b)

        assert result_a == {"emp a": {"id": "a1", "name": "Emp A"}}
        assert result_b == {"emp b": {"id": "b1", "name": "Emp B"}}

    def test_get_roster_cache_function(self):
        """get_roster_cache integrates with list_employee_folders."""
        cache = RosterCache(ttl_seconds=1800)

        def fake_list():
            return dict(TEMP_ROSTER)

        result = get_roster_cache(cache, "drive_123", fake_list)
        assert result == TEMP_ROSTER
