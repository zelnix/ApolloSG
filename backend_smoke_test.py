#!/usr/bin/env python3
"""
Quick smoke test after frontend-only changes.
Tests:
1. GET /api/health returns 200
2. POST /api/patrol/delete responds properly (401 for unauthenticated)
"""

import requests
import sys
import os

# Get backend URL from environment
BACKEND_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://case-source-preview--3ijise2t.preview.emergentagent.com')
BASE_URL = f"{BACKEND_URL}/api"

def test_health_endpoint():
    """Test GET /api/health returns 200"""
    print("\n1. Testing GET /api/health...")
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=10)
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   Response: {data}")
            
            # Verify expected schema
            if 'status' in data and data['status'] == 'ok':
                print("   ✅ PASS: Health endpoint returns 200 with status='ok'")
                return True
            else:
                print(f"   ❌ FAIL: Unexpected response schema: {data}")
                return False
        else:
            print(f"   ❌ FAIL: Expected 200, got {response.status_code}")
            return False
            
    except Exception as e:
        print(f"   ❌ FAIL: Exception occurred: {e}")
        return False


def test_patrol_delete_unauthenticated():
    """Test POST /api/patrol/delete returns 401 for unauthenticated request"""
    print("\n2. Testing POST /api/patrol/delete (unauthenticated)...")
    try:
        # Send request without Authorization header
        response = requests.post(
            f"{BASE_URL}/patrol/delete",
            json={"event_ids": ["test-event-id"]},
            timeout=10
        )
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 401:
            print("   ✅ PASS: Patrol delete endpoint returns 401 for unauthenticated request")
            return True
        else:
            print(f"   ❌ FAIL: Expected 401, got {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"   ❌ FAIL: Exception occurred: {e}")
        return False


def main():
    print("=" * 70)
    print("BACKEND SMOKE TEST - Frontend-only changes verification")
    print("=" * 70)
    print(f"Backend URL: {BACKEND_URL}")
    
    results = []
    
    # Run tests
    results.append(("Health endpoint", test_health_endpoint()))
    results.append(("Patrol delete auth", test_patrol_delete_unauthenticated()))
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ All smoke tests PASSED - Backend is healthy after frontend changes")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
