"""
Comprehensive Push Notification Robustness Audit for Apollo Backend
Backend runs on port 8001 with all routes under /api prefix
Push is CONFIGURED: EXPO_PUSH_ENABLED=true, EXPO_PUSH_ACCESS_TOKEN set, EXPO_PROJECT_ID set
"""
import os
import time
import requests
from datetime import datetime, timezone

# Load environment variables
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
EXPO_PROJECT_ID = os.environ.get("EXPO_PROJECT_ID", "47cd97c4-e5a6-41fa-9fde-257a5de031af")

print(f"Testing against: {API}")
print(f"Expo Project ID: {EXPO_PROJECT_ID}")
print("=" * 80)

# Helper functions
def register_device(platform="android", adapter_mode="web", app_version="1.1.0"):
    """Register a new test device and return device_id and token"""
    resp = requests.post(f"{API}/devices/register", json={
        "platform": platform,
        "adapter_mode": adapter_mode,
        "app_version": app_version
    })
    if resp.status_code != 201:
        print(f"❌ Device registration failed: {resp.status_code} - {resp.text}")
        return None, None
    data = resp.json()
    return data["device_id"], data["device_token"]

def test_category(name):
    """Decorator to print test category headers"""
    print(f"\n{'=' * 80}")
    print(f"TEST CATEGORY: {name}")
    print(f"{'=' * 80}")

# Setup: Register two test devices
print("\n🔧 SETUP: Registering two test devices...")
device1_id, device1_token = register_device(platform="android")
device2_id, device2_token = register_device(platform="ios")

if not device1_id or not device2_id:
    print("❌ FATAL: Could not register test devices. Aborting.")
    exit(1)

print(f"✅ Device 1 (Android): {device1_id}")
print(f"✅ Device 2 (iOS): {device2_id}")

# Create session with auth headers
session1 = requests.Session()
session1.headers.update({
    "Content-Type": "application/json",
    "Authorization": f"Bearer {device1_token}"
})

session2 = requests.Session()
session2.headers.update({
    "Content-Type": "application/json",
    "Authorization": f"Bearer {device2_token}"
})

# ============================================================================
# TEST CATEGORY 1: Push Registration Robustness
# ============================================================================
test_category("1. Push Registration Robustness")

# Test 1.1: Register push token with valid Expo format (Android)
print("\n📝 Test 1.1: Register push token with valid Expo format (Android)")
resp = session1.post(f"{API}/register-push", json={
    "platform": "android",
    "provider": "expo",
    "projectId": EXPO_PROJECT_ID,
    "device_token": "ExponentPushToken[test_android_token_abc123]"
})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json()}")
if resp.status_code == 201:
    print("✅ PASS: Push token registered successfully")
else:
    print(f"❌ FAIL: Expected 201, got {resp.status_code}")

# Test 1.2: Verify GET /push/registration returns configured: true, registered: true
print("\n📝 Test 1.2: Verify GET /push/registration shows registered: true")
resp = session1.get(f"{API}/push/registration")
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Response: {data}")
if data.get("configured") and data.get("registered"):
    print("✅ PASS: Push is configured and registered")
else:
    print(f"❌ FAIL: Expected configured=true and registered=true")

# Test 1.3: Re-register same device with a NEW token (token rotation)
print("\n📝 Test 1.3: Re-register same device with NEW token (token rotation)")
old_registration_id = data.get("registrationId")
resp = session1.post(f"{API}/register-push", json={
    "platform": "android",
    "provider": "expo",
    "projectId": EXPO_PROJECT_ID,
    "device_token": "ExponentPushToken[test_android_token_NEW_xyz789]"
})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json()}")
if resp.status_code == 201:
    print("✅ PASS: Token rotation accepted")
else:
    print(f"❌ FAIL: Expected 201, got {resp.status_code}")

# Test 1.4: Verify old token is replaced
print("\n📝 Test 1.4: Verify old token is replaced by checking /push/registration")
resp = session1.get(f"{API}/push/registration")
data = resp.json()
print(f"Response: {data}")
new_registration_id = data.get("registrationId")
if new_registration_id == old_registration_id:
    print("✅ PASS: Registration ID preserved (upsert, not duplicate)")
else:
    print(f"⚠️  WARNING: Registration ID changed (old: {old_registration_id}, new: {new_registration_id})")

# ============================================================================
# TEST CATEGORY 2: Push Registration Validation (negative tests)
# ============================================================================
test_category("2. Push Registration Validation (negative tests)")

# Test 2.1: Invalid token format (raw FCM token)
print("\n📝 Test 2.1: Invalid token format (raw FCM token) → expect 422")
resp = session1.post(f"{API}/register-push", json={
    "platform": "android",
    "provider": "expo",
    "projectId": EXPO_PROJECT_ID,
    "device_token": "dGVzdC1mY20tdG9rZW4"  # raw FCM token
})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text}")
if resp.status_code == 422:
    print("✅ PASS: Invalid token format rejected with 422")
else:
    print(f"❌ FAIL: Expected 422, got {resp.status_code}")

# Test 2.2: Wrong project ID
print("\n📝 Test 2.2: Wrong project ID → expect 422")
resp = session1.post(f"{API}/register-push", json={
    "platform": "android",
    "provider": "expo",
    "projectId": "wrong-project-id-12345678",
    "device_token": "ExponentPushToken[valid_format]"
})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text}")
if resp.status_code == 422:
    print("✅ PASS: Wrong project ID rejected with 422")
else:
    print(f"❌ FAIL: Expected 422, got {resp.status_code}")

# Test 2.3: Missing fields
print("\n📝 Test 2.3: Missing fields → expect 422")
resp = session1.post(f"{API}/register-push", json={
    "platform": "android"
})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text}")
if resp.status_code == 422:
    print("✅ PASS: Missing fields rejected with 422")
else:
    print(f"❌ FAIL: Expected 422, got {resp.status_code}")

# Test 2.4: Empty token
print("\n📝 Test 2.4: Empty token → expect 422")
resp = session1.post(f"{API}/register-push", json={
    "platform": "android",
    "provider": "expo",
    "projectId": EXPO_PROJECT_ID,
    "device_token": ""
})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text}")
if resp.status_code == 422:
    print("✅ PASS: Empty token rejected with 422")
else:
    print(f"❌ FAIL: Expected 422, got {resp.status_code}")

# Test 2.5: Token too short
print("\n📝 Test 2.5: Token too short → expect 422")
resp = session1.post(f"{API}/register-push", json={
    "platform": "android",
    "provider": "expo",
    "projectId": EXPO_PROJECT_ID,
    "device_token": "Ex"
})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text}")
if resp.status_code == 422:
    print("✅ PASS: Token too short rejected with 422")
else:
    print(f"❌ FAIL: Expected 422, got {resp.status_code}")

# ============================================================================
# TEST CATEGORY 3: Push Delivery Test
# ============================================================================
test_category("3. Push Delivery Test")

# Test 3.1: POST /push/test with registered device
print("\n📝 Test 3.1: POST /push/test with registered android device")
resp = session1.post(f"{API}/push/test", json={})
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Response: {data}")
if resp.status_code == 202:
    print("✅ PASS: Push test accepted with 202")
    delivery_id = data.get("deliveryId")
    if delivery_id:
        print(f"   Delivery ID: {delivery_id}")
        
        # Test 3.2: Check GET /push/deliveries/{delivery_id}
        print("\n📝 Test 3.2: Check GET /push/deliveries/{delivery_id}")
        time.sleep(1)  # Brief wait for processing
        resp = session1.get(f"{API}/push/deliveries/{delivery_id}")
        print(f"Status: {resp.status_code}")
        delivery_data = resp.json()
        print(f"Response: {delivery_data}")
        if resp.status_code == 200:
            state = delivery_data.get("state")
            print(f"   Delivery state: {state}")
            if state in ["submitted", "failed", "provider_accepted", "outcome_unknown"]:
                print("✅ PASS: Delivery state is valid (not unhandled exception)")
            else:
                print(f"❌ FAIL: Unexpected delivery state: {state}")
        else:
            print(f"❌ FAIL: Expected 200, got {resp.status_code}")
    else:
        print("⚠️  WARNING: No delivery_id returned")
else:
    print(f"❌ FAIL: Expected 202, got {resp.status_code}")

# ============================================================================
# TEST CATEGORY 4: Push Registration State Management
# ============================================================================
test_category("4. Push Registration State Management")

# Test 4.1: Register push for device 1, check device 2 is NOT registered
print("\n📝 Test 4.1: Device 1 registered, check device 2 is NOT registered")
resp = session2.get(f"{API}/push/registration")
data = resp.json()
print(f"Device 2 registration status: {data}")
if not data.get("registered"):
    print("✅ PASS: Device 2 shows registered: false")
else:
    print(f"❌ FAIL: Device 2 should not be registered yet")

# Test 4.2: Register device 2 with iOS token
print("\n📝 Test 4.2: Register device 2 with iOS token")
resp = session2.post(f"{API}/register-push", json={
    "platform": "ios",
    "provider": "expo",
    "projectId": EXPO_PROJECT_ID,
    "device_token": "ExponentPushToken[test_ios_token_def456]"
})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json()}")
if resp.status_code == 201:
    print("✅ PASS: Device 2 registered successfully")
else:
    print(f"❌ FAIL: Expected 201, got {resp.status_code}")

# Test 4.3: Both devices now show registered: true
print("\n📝 Test 4.3: Both devices now show registered: true")
resp1 = session1.get(f"{API}/push/registration")
resp2 = session2.get(f"{API}/push/registration")
data1 = resp1.json()
data2 = resp2.json()
print(f"Device 1: registered={data1.get('registered')}")
print(f"Device 2: registered={data2.get('registered')}")
if data1.get("registered") and data2.get("registered"):
    print("✅ PASS: Both devices registered")
else:
    print(f"❌ FAIL: Both devices should be registered")

# ============================================================================
# TEST CATEGORY 5: Idempotency & Deduplication
# ============================================================================
test_category("5. Idempotency & Deduplication")

# Test 5.1: Send POST /push/test twice rapidly
print("\n📝 Test 5.1: Send POST /push/test twice rapidly for same device")
resp1 = session1.post(f"{API}/push/test", json={})
time.sleep(0.1)  # Very brief delay
resp2 = session1.post(f"{API}/push/test", json={})
print(f"First request: {resp1.status_code}")
print(f"Second request: {resp2.status_code}")
data1 = resp1.json()
data2 = resp2.json()
print(f"First delivery_id: {data1.get('deliveryId')}")
print(f"Second delivery_id: {data2.get('deliveryId')}")
if data1.get('deliveryId') and data2.get('deliveryId'):
    if data1.get('deliveryId') == data2.get('deliveryId'):
        print("✅ PASS: Same delivery_id (deduplicated)")
    else:
        print("⚠️  INFO: Different delivery_ids (may be expected due to different idempotency keys)")
else:
    print("⚠️  WARNING: Could not verify deduplication")

# ============================================================================
# TEST CATEGORY 6: Cross-feature Push Integration (Family alerts)
# ============================================================================
test_category("6. Cross-feature Push Integration (Family alerts)")

# Test 6.1: Add a guardian email
print("\n📝 Test 6.1: Add guardian email for device 1")
resp = session1.post(f"{API}/family/guardians", json={
    "device_id": device1_id,
    "email": "test-push-guardian@example.com",
    "name": "Test Guardian",
    "owner_name": "Test Owner"
})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json()}")
if resp.status_code == 200:
    print("✅ PASS: Guardian added successfully")
else:
    print(f"❌ FAIL: Expected 200, got {resp.status_code}")

# Test 6.2: Pair device 1 and device 2
print("\n📝 Test 6.2: Pair device 1 and device 2")
print("   Step 1: Device 1 creates pair code")
resp = session1.post(f"{API}/family/pair", json={
    "device_id": device1_id,
    "owner_name": "Test Owner"
})
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Response: {data}")
if resp.status_code == 200:
    pair_code = data.get("code")
    print(f"   Pair code: {pair_code}")
    
    print("\n   Step 2: Device 2 links using pair code")
    resp = session2.post(f"{API}/family/link", json={
        "device_id": device2_id,
        "code": pair_code
    })
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}")
    if resp.status_code == 200:
        print("✅ PASS: Devices paired successfully")
    else:
        print(f"❌ FAIL: Expected 200, got {resp.status_code}")
else:
    print(f"❌ FAIL: Could not create pair code")

# Test 6.3: Verify the pairing
print("\n📝 Test 6.3: Verify pairing - GET /family/links")
resp = session1.get(f"{API}/family/links", params={"device_id": device1_id})
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Response: {data}")
if resp.status_code == 200:
    i_watch = data.get("i_watch", [])
    if any(link.get("protected_device_id") == device2_id for link in i_watch):
        print("✅ PASS: Device 2 found in device 1's watch list")
    else:
        print(f"❌ FAIL: Device 2 not found in watch list")
else:
    print(f"❌ FAIL: Expected 200, got {resp.status_code}")

# ============================================================================
# TEST CATEGORY 7: Weekly Check-in Push Config
# ============================================================================
test_category("7. Weekly Check-in Push Config")

# Test 7.1: GET /family/weekly/notify (default preferences)
print("\n📝 Test 7.1: GET /family/weekly/notify (default preferences)")
resp = session1.get(f"{API}/family/weekly/notify", params={"device_id": device1_id})
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Response: {data}")
if resp.status_code == 200:
    print("✅ PASS: Weekly notify preferences retrieved")
else:
    print(f"❌ FAIL: Expected 200, got {resp.status_code}")

# Test 7.2: PUT /family/weekly/notify - opt out
print("\n📝 Test 7.2: PUT /family/weekly/notify - opt out (enabled: false)")
resp = session1.put(f"{API}/family/weekly/notify", json={
    "device_id": device1_id,
    "enabled": False
})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json()}")
if resp.status_code == 200:
    print("✅ PASS: Opted out successfully")
else:
    print(f"❌ FAIL: Expected 200, got {resp.status_code}")

# Test 7.3: GET /family/weekly/notify - verify enabled: false
print("\n📝 Test 7.3: GET /family/weekly/notify - verify enabled: false")
resp = session1.get(f"{API}/family/weekly/notify", params={"device_id": device1_id})
data = resp.json()
print(f"Response: {data}")
if data.get("enabled") == False:
    print("✅ PASS: Opt-out confirmed (enabled: false)")
else:
    print(f"❌ FAIL: Expected enabled=false, got {data.get('enabled')}")

# Test 7.4: PUT /family/weekly/notify - opt back in
print("\n📝 Test 7.4: PUT /family/weekly/notify - opt back in (enabled: true)")
resp = session1.put(f"{API}/family/weekly/notify", json={
    "device_id": device1_id,
    "enabled": True
})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json()}")
if resp.status_code == 200:
    print("✅ PASS: Opted back in successfully")
else:
    print(f"❌ FAIL: Expected 200, got {resp.status_code}")

# ============================================================================
# TEST CATEGORY 8: Error Handling & Edge Cases
# ============================================================================
test_category("8. Error Handling & Edge Cases")

# Test 8.1: POST /push/test for device with NO push token
print("\n📝 Test 8.1: POST /push/test for device with NO push token")
# Register a new device without push token
device3_id, device3_token = register_device(platform="android")
session3 = requests.Session()
session3.headers.update({
    "Content-Type": "application/json",
    "Authorization": f"Bearer {device3_token}"
})
resp = session3.post(f"{API}/push/test", json={})
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json()}")
if resp.status_code == 409:
    print("✅ PASS: Proper error (409) for unregistered device")
elif resp.status_code == 500:
    print(f"❌ FAIL: Got 500 (should be proper error, not crash)")
else:
    print(f"⚠️  INFO: Got {resp.status_code} (expected 409 or similar)")

# Test 8.2: GET /push/deliveries/nonexistent-id → expect 404
print("\n📝 Test 8.2: GET /push/deliveries/nonexistent-id → expect 404")
resp = session1.get(f"{API}/push/deliveries/nonexistent-delivery-id-12345")
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text}")
if resp.status_code == 404:
    print("✅ PASS: Nonexistent delivery returns 404")
else:
    print(f"❌ FAIL: Expected 404, got {resp.status_code}")

# Test 8.3: Call endpoints without auth → expect 401/403
print("\n📝 Test 8.3: Call /push/registration without auth → expect 401/403")
resp = requests.get(f"{API}/push/registration")
print(f"Status: {resp.status_code}")
if resp.status_code in [401, 403]:
    print("✅ PASS: Unauthorized request rejected")
else:
    print(f"❌ FAIL: Expected 401/403, got {resp.status_code}")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "=" * 80)
print("PUSH NOTIFICATION ROBUSTNESS AUDIT COMPLETE")
print("=" * 80)
print("\nNote: Some tests may show provider errors (e.g., DeviceNotRegistered)")
print("since test tokens are fake. The key is that the backend handles them")
print("gracefully with proper error states, no 500s, and no crashes.")
print("\nNext steps:")
print("1. Review frontend TypeScript compilation")
print("2. Verify egress policy includes push_register")
print("3. Run backend pytest suite: cd /app/backend && python -m pytest tests/test_iter6_push.py -v")
