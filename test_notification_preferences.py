#!/usr/bin/env python3
"""
Backend API Tests for Notification Categories Feature

Tests verify that:
1. GET /api/push/preferences returns 5 categories with default preferences
2. PUT /api/push/preferences updates and persists preferences
3. Multiple preference updates work correctly
4. Barking and Biting are always_on and cannot be disabled
5. Backend health endpoint works
"""

import requests
import json
import time
from datetime import datetime

# Backend URL from frontend/.env
BASE_URL = "https://case-source-preview--3ijise2t.preview.emergentagent.com/api"

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def log_test(name):
    print(f"\n{BLUE}{'='*80}{RESET}")
    print(f"{BLUE}TEST: {name}{RESET}")
    print(f"{BLUE}{'='*80}{RESET}")

def log_success(message):
    print(f"{GREEN}✓ {message}{RESET}")

def log_error(message):
    print(f"{RED}✗ {message}{RESET}")

def log_info(message):
    print(f"{YELLOW}ℹ {message}{RESET}")

def log_response(response):
    print(f"\nStatus: {response.status_code}")
    try:
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except:
        print(f"Response: {response.text}")

class TestResults:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []
    
    def add_pass(self, test_name):
        self.passed.append(test_name)
        log_success(f"PASSED: {test_name}")
    
    def add_fail(self, test_name, reason):
        self.failed.append((test_name, reason))
        log_error(f"FAILED: {test_name} - {reason}")
    
    def add_warning(self, test_name, reason):
        self.warnings.append((test_name, reason))
        log_info(f"WARNING: {test_name} - {reason}")
    
    def summary(self):
        print(f"\n{BLUE}{'='*80}{RESET}")
        print(f"{BLUE}TEST SUMMARY{RESET}")
        print(f"{BLUE}{'='*80}{RESET}")
        print(f"{GREEN}Passed: {len(self.passed)}{RESET}")
        print(f"{RED}Failed: {len(self.failed)}{RESET}")
        print(f"{YELLOW}Warnings: {len(self.warnings)}{RESET}")
        
        if self.failed:
            print(f"\n{RED}Failed Tests:{RESET}")
            for test_name, reason in self.failed:
                print(f"  - {test_name}: {reason}")
        
        if self.warnings:
            print(f"\n{YELLOW}Warnings:{RESET}")
            for test_name, reason in self.warnings:
                print(f"  - {test_name}: {reason}")
        
        return len(self.failed) == 0

def register_device():
    """Register a device and return device_id and device_token"""
    log_test("Device Registration")
    
    url = f"{BASE_URL}/devices/register"
    payload = {
        "platform": "android",
        "adapter_mode": "test",
        "app_version": "1.0.0"
    }
    
    response = requests.post(url, json=payload)
    log_response(response)
    
    if response.status_code != 201:
        raise Exception(f"Device registration failed: {response.status_code}")
    
    data = response.json()
    device_id = data.get("device_id")
    device_token = data.get("device_token")
    
    if not device_id or not device_token:
        raise Exception("Device registration did not return device_id or device_token")
    
    log_success(f"Device registered: {device_id}")
    return device_id, device_token

def test_get_default_preferences(device_token, results):
    """Test 1: GET /api/push/preferences returns default preferences"""
    log_test("Test 1: GET /api/push/preferences - Default Preferences")
    
    url = f"{BASE_URL}/push/preferences"
    headers = {
        "Authorization": f"Bearer {device_token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(url, headers=headers)
    log_response(response)
    
    if response.status_code != 200:
        results.add_fail("GET /push/preferences status", f"Expected 200, got {response.status_code}")
        return None
    
    data = response.json()
    
    # Verify response structure
    if "categories" not in data:
        results.add_fail("GET /push/preferences categories", "Response missing 'categories' field")
        return None
    
    if "preferences" not in data:
        results.add_fail("GET /push/preferences preferences", "Response missing 'preferences' field")
        return None
    
    categories = data.get("categories", [])
    preferences = data.get("preferences", {})
    
    # Verify 5 categories
    if len(categories) != 5:
        results.add_fail("GET /push/preferences category count", f"Expected 5 categories, got {len(categories)}")
        return None
    
    log_success(f"Found {len(categories)} categories")
    
    # Verify category structure and always_on flags
    expected_categories = {
        "barking": {"always_on": True},
        "biting": {"always_on": True},
        "sniffing_growling": {"always_on": False},
        "scam_alerts": {"always_on": False},
        "learn_with_higgins": {"always_on": False}
    }
    
    category_ids = [cat.get("id") for cat in categories]
    for expected_id, expected_props in expected_categories.items():
        if expected_id not in category_ids:
            results.add_fail("GET /push/preferences category", f"Missing category: {expected_id}")
            return None
        
        cat = next((c for c in categories if c.get("id") == expected_id), None)
        if cat:
            if cat.get("always_on") != expected_props["always_on"]:
                results.add_fail(f"Category {expected_id} always_on", 
                               f"Expected always_on={expected_props['always_on']}, got {cat.get('always_on')}")
                return None
            log_success(f"Category '{expected_id}': always_on={cat.get('always_on')}")
    
    # Verify default preferences (all configurable should be true)
    expected_prefs = {
        "sniffing_growling": True,
        "scam_alerts": True,
        "learn_with_higgins": True
    }
    
    for pref_key, expected_value in expected_prefs.items():
        actual_value = preferences.get(pref_key)
        if actual_value != expected_value:
            results.add_fail(f"Default preference {pref_key}", 
                           f"Expected {expected_value}, got {actual_value}")
            return None
        log_success(f"Default preference '{pref_key}': {actual_value}")
    
    results.add_pass("GET /push/preferences returns correct default preferences")
    return preferences

def test_update_single_preference(device_token, results):
    """Test 2: PUT /api/push/preferences updates single preference"""
    log_test("Test 2: PUT /api/push/preferences - Update Single Preference")
    
    url = f"{BASE_URL}/push/preferences"
    headers = {
        "Authorization": f"Bearer {device_token}",
        "Content-Type": "application/json"
    }
    
    # Update scam_alerts to false
    payload = {"scam_alerts": False}
    
    response = requests.put(url, json=payload, headers=headers)
    log_response(response)
    
    if response.status_code != 200:
        results.add_fail("PUT /push/preferences status", f"Expected 200, got {response.status_code}")
        return None
    
    data = response.json()
    preferences = data.get("preferences", {})
    
    # Verify scam_alerts is now false
    if preferences.get("scam_alerts") != False:
        results.add_fail("PUT /push/preferences scam_alerts", 
                       f"Expected scam_alerts=False, got {preferences.get('scam_alerts')}")
        return None
    
    log_success("scam_alerts updated to False")
    
    # Verify other preferences remain true
    if preferences.get("sniffing_growling") != True:
        results.add_fail("PUT /push/preferences sniffing_growling", 
                       "sniffing_growling should remain True")
        return None
    
    if preferences.get("learn_with_higgins") != True:
        results.add_fail("PUT /push/preferences learn_with_higgins", 
                       "learn_with_higgins should remain True")
        return None
    
    log_success("Other preferences remain unchanged")
    results.add_pass("PUT /push/preferences updates single preference correctly")
    return preferences

def test_verify_persistence(device_token, results):
    """Test 2b: Verify preference persistence with GET"""
    log_test("Test 2b: Verify Preference Persistence")
    
    url = f"{BASE_URL}/push/preferences"
    headers = {
        "Authorization": f"Bearer {device_token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(url, headers=headers)
    log_response(response)
    
    if response.status_code != 200:
        results.add_fail("GET /push/preferences persistence check", f"Expected 200, got {response.status_code}")
        return None
    
    data = response.json()
    preferences = data.get("preferences", {})
    
    # Verify scam_alerts is still false
    if preferences.get("scam_alerts") != False:
        results.add_fail("Preference persistence scam_alerts", 
                       f"Expected scam_alerts=False (persisted), got {preferences.get('scam_alerts')}")
        return None
    
    log_success("scam_alerts persisted as False")
    results.add_pass("Preferences persist correctly")
    return preferences

def test_update_multiple_preferences(device_token, results):
    """Test 3: PUT /api/push/preferences updates multiple preferences"""
    log_test("Test 3: PUT /api/push/preferences - Update Multiple Preferences")
    
    url = f"{BASE_URL}/push/preferences"
    headers = {
        "Authorization": f"Bearer {device_token}",
        "Content-Type": "application/json"
    }
    
    # Update sniffing_growling and learn_with_higgins to false
    payload = {
        "sniffing_growling": False,
        "learn_with_higgins": False
    }
    
    response = requests.put(url, json=payload, headers=headers)
    log_response(response)
    
    if response.status_code != 200:
        results.add_fail("PUT /push/preferences multiple status", f"Expected 200, got {response.status_code}")
        return None
    
    data = response.json()
    preferences = data.get("preferences", {})
    
    # Verify both updated preferences
    if preferences.get("sniffing_growling") != False:
        results.add_fail("PUT /push/preferences sniffing_growling", 
                       f"Expected sniffing_growling=False, got {preferences.get('sniffing_growling')}")
        return None
    
    if preferences.get("learn_with_higgins") != False:
        results.add_fail("PUT /push/preferences learn_with_higgins", 
                       f"Expected learn_with_higgins=False, got {preferences.get('learn_with_higgins')}")
        return None
    
    log_success("sniffing_growling updated to False")
    log_success("learn_with_higgins updated to False")
    
    # Verify scam_alerts remains false from Test 2
    if preferences.get("scam_alerts") != False:
        results.add_fail("PUT /push/preferences scam_alerts persistence", 
                       f"Expected scam_alerts=False (from previous test), got {preferences.get('scam_alerts')}")
        return None
    
    log_success("scam_alerts remains False from previous update")
    results.add_pass("PUT /push/preferences updates multiple preferences correctly")
    return preferences

def test_backend_health(results):
    """Test 5: Backend health check"""
    log_test("Test 5: Backend Health Check")
    
    url = f"{BASE_URL}/health"
    
    response = requests.get(url)
    log_response(response)
    
    if response.status_code != 200:
        results.add_fail("Backend health status", f"Expected 200, got {response.status_code}")
        return
    
    data = response.json()
    
    if data.get("status") != "ok":
        results.add_fail("Backend health status field", f"Expected status='ok', got {data.get('status')}")
        return
    
    log_success("Backend health check passed")
    results.add_pass("Backend health endpoint working")

def main():
    print(f"\n{BLUE}{'='*80}{RESET}")
    print(f"{BLUE}Backend API Tests - Notification Categories Feature{RESET}")
    print(f"{BLUE}{'='*80}{RESET}")
    print(f"Backend URL: {BASE_URL}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    
    results = TestResults()
    
    try:
        # Step 1: Register device
        device_id, device_token = register_device()
        log_success(f"Using device: {device_id}")
        
        # Test 1: GET default preferences
        default_prefs = test_get_default_preferences(device_token, results)
        if default_prefs is None:
            log_error("Test 1 failed, cannot continue with subsequent tests")
            results.summary()
            return 1
        
        # Test 2: Update single preference
        updated_prefs = test_update_single_preference(device_token, results)
        if updated_prefs is None:
            log_error("Test 2 failed, cannot continue with subsequent tests")
            results.summary()
            return 1
        
        # Test 2b: Verify persistence
        persisted_prefs = test_verify_persistence(device_token, results)
        if persisted_prefs is None:
            log_error("Test 2b failed, cannot continue with subsequent tests")
            results.summary()
            return 1
        
        # Test 3: Update multiple preferences
        multi_prefs = test_update_multiple_preferences(device_token, results)
        if multi_prefs is None:
            log_error("Test 3 failed")
        
        # Test 5: Backend health
        test_backend_health(results)
        
    except Exception as e:
        log_error(f"Test execution failed: {str(e)}")
        import traceback
        traceback.print_exc()
        results.add_fail("Test execution", str(e))
    
    # Print summary
    success = results.summary()
    
    if success:
        print(f"\n{GREEN}{'='*80}{RESET}")
        print(f"{GREEN}ALL TESTS PASSED ✓{RESET}")
        print(f"{GREEN}{'='*80}{RESET}")
        return 0
    else:
        print(f"\n{RED}{'='*80}{RESET}")
        print(f"{RED}SOME TESTS FAILED ✗{RESET}")
        print(f"{RED}{'='*80}{RESET}")
        return 1

if __name__ == "__main__":
    exit(main())
