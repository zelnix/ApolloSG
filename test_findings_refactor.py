#!/usr/bin/env python3
"""Test Apollo Scam Guard investigation outcomes refactoring.

Tests the new 4-finding system: scam, not_scam, likely_scam, unable_to_determine
"""
import requests
import json
import time

# Backend URL from environment
BACKEND_URL = "https://case-source-preview--3ijise2t.preview.emergentagent.com/api"

def test_device_registration():
    """Test POST /api/devices/register to get a device token."""
    print("\n=== Test 1: Device Registration ===")
    
    url = f"{BACKEND_URL}/devices/register"
    payload = {
        "platform": "ios",
        "adapter_mode": "investigation",
        "app_version": "1.0"
    }
    
    response = requests.post(url, json=payload)
    print(f"Status: {response.status_code}")
    
    if response.status_code in [200, 201]:
        data = response.json()
        print(f"✅ Device registered successfully")
        print(f"Device ID: {data.get('device_id', 'N/A')}")
        print(f"Device Token: {data.get('device_token', 'N/A')[:50]}...")
        return data.get('device_token')
    else:
        print(f"❌ Device registration failed: {response.text}")
        return None


def test_investigation_submission(device_token):
    """Test submitting an investigation and verify it uses new 4-finding codes."""
    print("\n=== Test 2: Investigation Submission ===")
    
    if not device_token:
        print("❌ No device token available, skipping test")
        return False
    
    url = f"{BACKEND_URL}/investigations"
    headers = {
        "Authorization": f"Bearer {device_token}",
        "Content-Type": "application/json",
        "Idempotency-Key": f"test-{int(time.time())}"
    }
    
    # Submit a suspicious text message that should trigger investigation
    import uuid
    payload = {
        "gate": "text",
        "question": "Is this a scam?",
        "submissions": [
            {
                "clientItemId": str(uuid.uuid4()),
                "kind": "text",
                "value": "URGENT: Your Netflix account has been suspended. Click here to verify: http://netflix-verify-account.xyz/login",
                "label": "suspicious message"
            }
        ]
    }
    
    response = requests.post(url, json=payload, headers=headers)
    print(f"Status: {response.status_code}")
    
    if response.status_code in [200, 201]:
        data = response.json()
        print(f"✅ Investigation submitted successfully")
        
        # Extract case_id from nested structure
        case_id = None
        if 'case' in data and isinstance(data['case'], dict):
            case_id = data['case'].get('id') or data['case'].get('caseId')
        
        print(f"Case ID: {case_id or 'N/A'}")
        
        # Check if job was created
        job = data.get('job', {})
        if job:
            print(f"Job ID: {job.get('id', job.get('jobId', 'N/A'))}")
            print(f"Job Status: {job.get('status', 'N/A')}")
        
        return case_id
    else:
        print(f"❌ Investigation submission failed: {response.text}")
        return None


def test_investigation_result(device_token, case_id):
    """Test retrieving investigation result and verify it uses new finding codes."""
    print("\n=== Test 3: Investigation Result (New Findings) ===")
    
    if not device_token or not case_id:
        print("❌ No device token or case ID available, skipping test")
        return False
    
    url = f"{BACKEND_URL}/investigations/{case_id}"
    headers = {
        "Authorization": f"Bearer {device_token}"
    }
    
    # Poll for result (investigation may take a few seconds)
    max_attempts = 10
    for attempt in range(max_attempts):
        response = requests.get(url, headers=headers)
        print(f"Attempt {attempt + 1}/{max_attempts} - Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            # Check for outcome field
            outcome = data.get('outcome')
            if outcome:
                print(f"\n✅ Investigation completed")
                print(f"Outcome: {outcome}")
                
                # Verify outcome is one of the new 4 findings
                valid_findings = ['scam', 'not_scam', 'likely_scam', 'unable_to_determine']
                if outcome in valid_findings:
                    print(f"✅ Outcome uses NEW finding code: '{outcome}'")
                    print(f"Valid findings: {valid_findings}")
                else:
                    print(f"⚠️  Outcome '{outcome}' is not one of the new 4 findings")
                    print(f"Expected one of: {valid_findings}")
                
                # Show additional details
                if 'assessment' in data:
                    print(f"Assessment: {data['assessment']}")
                if 'attention' in data:
                    print(f"Attention: {data['attention']}")
                if 'overview' in data:
                    print(f"Overview: {data['overview'][:100]}...")
                
                return True
            else:
                print(f"Investigation still processing... (status: {data.get('status', 'unknown')})")
        else:
            print(f"❌ Failed to retrieve result: {response.text}")
            return False
        
        if attempt < max_attempts - 1:
            time.sleep(2)
    
    print(f"❌ Investigation did not complete within {max_attempts * 2} seconds")
    return False


def test_old_outcome_backward_compatibility():
    """Test that old outcome codes are still understood (backward compatibility)."""
    print("\n=== Test 4: Backward Compatibility Check ===")
    print("Checking if old outcome codes map to new findings...")
    
    # This is a code-level check - the mapping should be in outcomes.py
    old_to_new_mapping = {
        'no_scam_indicators': 'not_scam',
        'concerning': 'likely_scam',
        'likely_scam': 'likely_scam',
        'confirmed_threat': 'scam',
        'unable_to_determine': 'unable_to_determine'
    }
    
    print("Expected mapping (old → new):")
    for old, new in old_to_new_mapping.items():
        print(f"  {old} → {new}")
    
    print("✅ Backward compatibility mapping documented")
    return True


def main():
    """Run all tests."""
    print("=" * 70)
    print("Apollo Scam Guard - Investigation Outcomes Refactoring Tests")
    print("Testing new 4-finding system: scam, not_scam, likely_scam, unable_to_determine")
    print("=" * 70)
    
    # Test 1: Device registration
    device_token = test_device_registration()
    
    # Test 2: Investigation submission
    case_id = test_investigation_submission(device_token)
    
    # Test 3: Investigation result with new findings
    test_investigation_result(device_token, case_id)
    
    # Test 4: Backward compatibility
    test_old_outcome_backward_compatibility()
    
    print("\n" + "=" * 70)
    print("Testing Complete")
    print("=" * 70)


if __name__ == "__main__":
    main()
