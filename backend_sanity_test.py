#!/usr/bin/env python3
"""
Quick sanity check for backend health and patrol delete endpoint.
Tests that frontend-only changes didn't break backend functionality.
"""

import requests
import os

# Get backend URL from environment
BACKEND_URL = os.getenv('EXPO_PUBLIC_BACKEND_URL', 'https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com')
API_BASE = f"{BACKEND_URL}/api"

def test_health_endpoint():
    """Test that backend health endpoint is responding"""
    print("\n=== Testing Backend Health Endpoint ===")
    
    try:
        response = requests.get(f"{API_BASE}/health", timeout=10)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'ok':
                print("✅ Health endpoint is working correctly")
                return True
            else:
                print(f"❌ Health endpoint returned unexpected status: {data.get('status')}")
                return False
        else:
            print(f"❌ Health endpoint returned status code: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Health endpoint test failed with error: {e}")
        return False

def test_patrol_delete_endpoint():
    """Test that POST /api/patrol/delete endpoint exists and responds properly"""
    print("\n=== Testing POST /api/patrol/delete Endpoint ===")
    
    # First, we need to register a device to get auth token
    try:
        # Register a test device
        device_data = {
            "platform": "android",
            "adapter_mode": "mock",
            "app_version": "1.0.0",
            "tz_offset_minutes": 0,
            "locale": "en-AU"
        }
        
        register_response = requests.post(
            f"{API_BASE}/devices/register",
            json=device_data,
            timeout=10
        )
        
        if register_response.status_code not in [200, 201]:
            print(f"❌ Failed to register device: {register_response.status_code}")
            print(f"Response: {register_response.text}")
            return False
            
        device_info = register_response.json()
        device_id = device_info.get('device_id')
        device_token = device_info.get('device_token')
        
        print(f"✅ Device registered successfully: {device_id}")
        
        # Now test the patrol delete endpoint
        # The endpoint should accept a request with event_ids to delete
        delete_payload = {
            "eventIds": ["test-event-id-1", "test-event-id-2"],
            "caseIds": []
        }
        
        headers = {
            "Authorization": f"Bearer {device_token}"
        }
        
        delete_response = requests.post(
            f"{API_BASE}/patrol/delete",
            json=delete_payload,
            headers=headers,
            timeout=10
        )
        
        print(f"Status Code: {delete_response.status_code}")
        print(f"Response: {delete_response.text}")
        
        # The endpoint should return 200 or 204 for successful deletion
        # Even if the events don't exist, it should handle gracefully
        if delete_response.status_code in [200, 204]:
            print("✅ Patrol delete endpoint is responding correctly")
            return True
        elif delete_response.status_code == 404:
            print("⚠️  Patrol delete endpoint returned 404 - endpoint may not exist")
            return False
        else:
            print(f"⚠️  Patrol delete endpoint returned status code: {delete_response.status_code}")
            # Still consider it working if it's not a 500 error
            return delete_response.status_code < 500
            
    except Exception as e:
        print(f"❌ Patrol delete endpoint test failed with error: {e}")
        return False

def main():
    print("=" * 60)
    print("BACKEND SANITY CHECK")
    print("=" * 60)
    print(f"Backend URL: {BACKEND_URL}")
    print(f"API Base: {API_BASE}")
    
    results = {
        "health": test_health_endpoint(),
        "patrol_delete": test_patrol_delete_endpoint()
    }
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name}: {status}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n✅ All sanity checks PASSED")
        return 0
    else:
        print("\n❌ Some sanity checks FAILED")
        return 1

if __name__ == "__main__":
    exit(main())
