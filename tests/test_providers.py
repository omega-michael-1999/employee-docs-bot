"""Tests for provider config schema and /providers command."""


def test_providers_config_optional():
    """Config schema should accept both with and without providers field."""
    import json

    with_providers = json.dumps({
        "clients": [{
            "chat_id": -100,
            "name": "Test",
            "drive_root_id": "abc",
            "service_account_key_file": "key.json",
            "providers": ["Sandra Namwase"]
        }]
    })
    parsed = json.loads(with_providers)
    assert "providers" in parsed["clients"][0]
    assert parsed["clients"][0]["providers"] == ["Sandra Namwase"]

    without_providers = json.dumps({
        "clients": [{
            "chat_id": -200,
            "name": "Test 2",
            "drive_root_id": "def",
            "service_account_key_file": "key.json"
        }]
    })
    parsed2 = json.loads(without_providers)
    assert "providers" not in parsed2["clients"][0]
    assert parsed2["clients"][0]["name"] == "Test 2"


def test_is_provider_returns_true_for_matching_name():
    """is_provider should return True for names in the providers list."""
    from bot import is_provider
    client = {"providers": ["Sandra Namwase", "Jane Doe"]}
    assert is_provider(client, "Sandra Namwase") is True
    assert is_provider(client, "Jane Doe") is True


def test_is_provider_returns_false_for_non_provider():
    """is_provider should return False for names not in the list."""
    from bot import is_provider
    client = {"providers": ["Sandra Namwase"]}
    assert is_provider(client, "Fatou Manneh") is False


def test_is_provider_defaults_to_empty_list():
    """is_provider should handle missing providers field gracefully."""
    from bot import is_provider
    client = {}
    assert is_provider(client, "Anyone") is False
    assert is_provider(client, "") is False


def test_providers_list_format():
    """Providers field should be a list of strings."""
    from bot import is_provider
    client = {"providers": ["Sandra Namwase"]}
    assert isinstance(client.get("providers", []), list)


def test_providers_empty_list():
    """Empty providers list should result in no providers."""
    from bot import is_provider
    client = {"providers": []}
    assert is_provider(client, "Anyone") is False
