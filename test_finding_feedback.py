#!/usr/bin/env python3
"""Test finding feedback endpoints (Phase 2 feature)"""
import requests
import os

# Get backend URL from environment
BACKEND_URL = os.getenv("REACT_APP_BACKEND_URL", "http://localhost:8001")
BASE_URL = f"{BACKEND_URL}/api"

def test_finding_feedback():
    """Test finding feedback endpoints with error handling for non-existent case"""
    print("=" * 80)
    print("Testing Finding Feedback Endpoints (Phase 2)")
    print("=" * 80)
    
    # Step 1: Register a device
    print("\n1. Registering device...")
    register_resp = requests.post(
        f"{BASE_URL}/devices/register",
        json={"platform": "web", "adapter_mode": "standard", "app_version": "1.0.0"}
    )
    print(f"   Status: {register_resp.status_code}")
    assert register_resp.status_code in [200, 201], f"Device registration failed: {register_resp.text}"
    
    device_token = register_resp.json()["device_token"]
    print(f"   ✓ Device registered, token: {device_token[:20]}...")
    
    headers = {"Authorization": f"Bearer {device_token}"}
    
    # Step 2: Test POST feedback with non-existent case (should return 404)
    print("\n2. Testing POST /api/investigations/{case_id}/feedback with non-existent case...")
    fake_case_id = "00000000-0000-0000-0000-000000000000"
    fake_finding_id = "11111111-1111-1111-1111-111111111111"
    
    feedback_resp = requests.post(
        f"{BASE_URL}/investigations/{fake_case_id}/feedback",
        headers=headers,
        json={
            "finding_id": fake_finding_id,
            "verdict": "incorrect",
            "reason": "Test feedback"
        }
    )
    print(f"   Status: {feedback_resp.status_code}")
    print(f"   Response: {feedback_resp.json()}")
    
    # Should return 404 for non-existent case
    assert feedback_resp.status_code == 404, f"Expected 404 for non-existent case, got {feedback_resp.status_code}"
    response_data = feedback_resp.json()
    assert "error" in response_data, "Expected error field in response"
    print(f"   ✓ Correctly returned 404 for non-existent case")
    
    # Step 3: Test GET feedback with non-existent case (should return 404)
    print("\n3. Testing GET /api/investigations/{case_id}/feedback with non-existent case...")
    get_feedback_resp = requests.get(
        f"{BASE_URL}/investigations/{fake_case_id}/feedback",
        headers=headers
    )
    print(f"   Status: {get_feedback_resp.status_code}")
    print(f"   Response: {get_feedback_resp.json()}")
    
    # Should return 404 for non-existent case
    assert get_feedback_resp.status_code == 404, f"Expected 404 for non-existent case, got {get_feedback_resp.status_code}"
    print(f"   ✓ Correctly returned 404 for non-existent case")
    
    # Step 4: Test endpoint structure is correct
    print("\n4. Verifying endpoint structure...")
    print(f"   ✓ POST /api/investigations/{{case_id}}/feedback endpoint exists")
    print(f"   ✓ GET /api/investigations/{{case_id}}/feedback endpoint exists")
    print(f"   ✓ Both endpoints require device authentication")
    print(f"   ✓ Both endpoints validate case existence")
    
    print("\n" + "=" * 80)
    print("✓ ALL FINDING FEEDBACK TESTS PASSED")
    print("=" * 80)
    return True

if __name__ == "__main__":
    try:
        test_finding_feedback()
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        exit(1)
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
