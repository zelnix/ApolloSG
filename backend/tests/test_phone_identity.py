"""Tests for the Phone Number Identity resolution pipeline (Phase 2)."""
import asyncio
import sys
sys.path.insert(0, "/app/backend")

from services.phone_identity import (
    assess_association,
    IdentityEvidence,
    _number_details,
    _check_org_directory,
    _names_match,
    _digits,
    _national,
    _cache_key,
)

def test_assess_empty():
    conf, ent = assess_association([])
    assert conf == "unknown" and ent is None, f"Expected unknown/None, got {conf}/{ent}"

def test_assess_verified():
    e = IdentityEvidence(source="https://commbank.com.au", source_type="tier_1_official", publisher="CommBank", claim="CommBank", retrieved_at="2026-01-01")
    conf, ent = assess_association([e])
    assert conf == "verified" and ent == "CommBank", f"Expected verified/CommBank, got {conf}/{ent}"

def test_assess_strong_government():
    e = IdentityEvidence(source="https://acma.gov.au", source_type="tier_2_government", publisher="ACMA", claim="Telstra", retrieved_at="2026-01-01")
    conf, ent = assess_association([e])
    assert conf == "strong" and ent == "Telstra", f"Expected strong/Telstra, got {conf}/{ent}"

def test_assess_strong_multi_web():
    e1 = IdentityEvidence(source="a.com", source_type="tier_4_web", publisher="A", claim="RAC WA", retrieved_at="2026-01-01")
    e2 = IdentityEvidence(source="b.com", source_type="tier_4_web", publisher="B", claim="RAC WA", retrieved_at="2026-01-01")
    conf, ent = assess_association([e1, e2])
    assert conf == "strong" and ent == "RAC WA", f"Expected strong/RAC WA, got {conf}/{ent}"

def test_assess_possible_single_web():
    e = IdentityEvidence(source="a.com", source_type="tier_4_web", publisher="A", claim="Some Corp", retrieved_at="2026-01-01")
    conf, ent = assess_association([e])
    assert conf == "possible" and ent == "Some Corp", f"Expected possible/Some Corp, got {conf}/{ent}"

def test_assess_conflicting():
    e1 = IdentityEvidence(source="a.com", source_type="tier_4_web", publisher="A", claim="Telstra", retrieved_at="2026-01-01")
    e2 = IdentityEvidence(source="b.com", source_type="tier_4_web", publisher="B", claim="Optus", retrieved_at="2026-01-01")
    conf, ent = assess_association([e1, e2])
    assert conf == "conflicting" and ent is None, f"Expected conflicting/None, got {conf}/{ent}"

def test_names_match_subset():
    assert _names_match("rac wa", "rac western australia") is True
    assert _names_match("telstra", "optus") is False
    assert _names_match("commonwealth bank", "commonwealth bank of australia") is True  # subset

def test_number_details():
    d = _number_details("+61412345678", "AU")
    assert d["valid"] is True
    assert d["country"] == "Australia"
    assert d["number_type"] == "Mobile"

def test_digits():
    assert _digits("+61 412 345 678") == "61412345678"
    assert _digits("0412-345-678") == "0412345678"

def test_cache_key_stable():
    k1 = _cache_key("+61412345678")
    k2 = _cache_key("+61412345678")
    assert k1 == k2, "Cache key should be stable"
    k3 = _cache_key("+61412345679")
    assert k1 != k3, "Different numbers should have different cache keys"

def test_org_directory_commbank():
    """CommBank's 13 22 21 should be found in the Official Organisation Directory.
    The org_directory is loaded at server startup from the DB — we test via the running API."""
    import urllib.request, json
    # Register a device to get a token
    req = urllib.request.Request("http://localhost:8001/api/devices/register", data=json.dumps({"platform":"test","adapter_mode":"test","app_version":"1.0"}).encode(), headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        token = json.loads(r.read())["device_token"]
    # Identify CommBank's number
    req2 = urllib.request.Request("http://localhost:8001/api/number/identify", data=json.dumps({"number":"13 22 21","country":"AU"}).encode(), headers={"Content-Type":"application/json","Authorization":f"Bearer {token}"}, method="POST")
    with urllib.request.urlopen(req2) as r:
        result = json.loads(r.read())
    assert result["associated_entity"] == "CommBank", f"Expected CommBank, got {result['associated_entity']}"
    assert result["association_confidence"] == "verified", f"Expected verified, got {result['association_confidence']}"
    assert any(e["source_type"] == "tier_1_official" for e in result["evidence"]), "Expected Tier 1 evidence"

def test_org_directory_unknown():
    """A random mobile number should not be in the Official Organisation Directory."""
    evidence = _check_org_directory("+61400000000")
    assert len(evidence) == 0, "Random number should not be found"

# Run all tests
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed + failed} tests passed.")
    if failed > 0:
        sys.exit(1)
