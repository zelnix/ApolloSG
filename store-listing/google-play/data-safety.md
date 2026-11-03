# ApolloSG — Google Play Data Safety Declaration

> **Purpose:** Complete reference for filling out the Data Safety section in
> Google Play Console (Policy → App content → Data safety). Walk through each
> question below and select the indicated answer.
>
> Generated from the production codebase analysis on 2026-11-03.

---

## Section 1 — Overview questions

| Question | Answer | Notes |
|---|---|---|
| Does your app collect or share any of the required user data types? | **Yes** | See detailed breakdown below. |
| Is all of the user data collected by your app encrypted in transit? | **Yes** | All API calls use HTTPS/TLS. |
| Do you provide a way for users to request that their data is deleted? | **Yes** | Admin case-wipe and per-case delete available; device records are purged on device reset. Temporary AI content auto-expires (15 min). |

---

## Section 2 — Data types

### 2.1 Location

| Data type | Collected | Shared | Purpose | Optional |
|---|---|---|---|---|
| Approximate location | No | — | — | — |
| Precise location | No | — | — | — |

> ApolloSG requests `ACCESS_NETWORK_STATE` (not location). iOS `NSLocationWhenInUseUsageDescription`
> is used only for Wi-Fi security check (SSID); no coordinates are recorded or transmitted.

### 2.2 Personal info

| Data type | Collected | Shared | Purpose | Optional |
|---|---|---|---|---|
| Name | **Yes** | No | App functionality (Family Assist — display name for paired relatives) | Optional |
| Email address | **Yes** | No | App functionality (Gmail mailbox monitoring connection) | Optional |
| User IDs | **Yes** | No | App functionality (random device ID, not hardware ID) | Required |
| Address | No | — | — | — |
| Phone number | **Yes** | No | App functionality (caller-ID risk check) | Optional |
| Race and ethnicity | No | — | — | — |
| Political or religious beliefs | No | — | — | — |
| Sexual orientation | No | — | — | — |
| Other personal info | No | — | — | — |

### 2.3 Financial info

| Data type | Collected | Shared |
|---|---|---|
| User payment info | No | — |
| Purchase history | No | — |
| Credit score | No | — |
| Other financial info | No | — |

### 2.4 Health and fitness

| Data type | Collected | Shared |
|---|---|---|
| Health info | No | — |
| Fitness info | No | — |

### 2.5 Messages

| Data type | Collected | Shared | Purpose | Optional |
|---|---|---|---|---|
| Emails | **Yes** | No | App functionality (mailbox scanning for phishing/scam detection) | Optional |
| SMS or MMS | No | — | — | — |
| Other in-app messages | **Yes** | No | App functionality (user-submitted messages/text for threat analysis) | Optional |

> SMS/MMS: The app does NOT read SMS directly. Users manually share message text for checking.
> Email: Only collected when user explicitly connects their Gmail account via OAuth.

### 2.6 Photos and videos

| Data type | Collected | Shared | Purpose | Optional |
|---|---|---|---|---|
| Photos | **Yes** | No | App functionality (screenshots for device settings verification via Higgins AI) | Optional |
| Videos | No | — | — | — |

### 2.7 Audio files

| Data type | Collected | Shared |
|---|---|---|
| Voice or sound recordings | No | — |
| Music files | No | — |
| Other audio files | No | — |

### 2.8 Files and docs

| Data type | Collected | Shared |
|---|---|---|
| Files and docs | No | — |

### 2.9 Calendar

| Data type | Collected | Shared |
|---|---|---|
| Calendar events | No | — |

### 2.10 Contacts

| Data type | Collected | Shared |
|---|---|---|
| Contacts | No | — |

### 2.11 App activity

| Data type | Collected | Shared | Purpose | Optional |
|---|---|---|---|---|
| App interactions | **Yes** | No | App functionality & analytics (feature usage counts for admin device management) | Required |
| In-app search history | No | — | — | — |
| Installed apps | No | — | — | — |
| Other user-generated content | **Yes** | No | App functionality (URLs, links, and message text submitted for threat checking) | Optional |
| Other actions | No | — | — | — |

### 2.12 Web browsing

| Data type | Collected | Shared |
|---|---|---|
| Web browsing history | No | — |

> ApolloSG's VPN-based website filter intercepts DNS lookups locally; domain names
> checked against the blocklist never leave the device unless a match is found.

### 2.13 App info and performance

| Data type | Collected | Shared | Purpose | Optional |
|---|---|---|---|---|
| Crash logs | **Yes** | No | App functionality (error diagnostics) | Required |
| Diagnostics | **Yes** | No | App functionality (device posture auditing) | Required |
| Other app performance data | No | — | — | — |

### 2.14 Device or other IDs

| Data type | Collected | Shared | Purpose | Optional |
|---|---|---|---|---|
| Device or other IDs | **Yes** | No | App functionality (random UUID device identifier; not IMEI, Android ID, or GAID) | Required |

---

## Section 3 — Data handling for each collected type

For **every** data type marked "Collected" above, Play Console asks additional
questions. Use the answers below:

### Personal info — Name
- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** No (stored with family link record)
- **Is this data required or can the user choose whether it's collected?** Optional (only when using Family Assist)
- **Why is this user data collected?** App functionality

### Personal info — Email address
- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** No (stored for ongoing mailbox monitoring)
- **Is this data required or can the user choose whether it's collected?** Optional (only when connecting Gmail)
- **Why is this user data collected?** App functionality

### Personal info — User IDs
- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** No (persistent random device ID)
- **Is this data required or can the user choose whether it's collected?** Required
- **Why is this user data collected?** App functionality

### Personal info — Phone number
- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** No (cached for caller-ID risk lookups)
- **Is this data required or can the user choose whether it's collected?** Optional (only when user submits a number for checking)
- **Why is this user data collected?** App functionality

### Messages — Emails
- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** Yes (email content is scanned and only the verdict is stored; raw email body is not persisted)
- **Is this data required or can the user choose whether it's collected?** Optional
- **Why is this user data collected?** App functionality

### Messages — Other in-app messages
- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** Yes (message text submitted for analysis is attached to the threat case; temporary AI content auto-expires within 15 minutes)
- **Is this data required or can the user choose whether it's collected?** Optional
- **Why is this user data collected?** App functionality

### Photos — Photos
- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** Yes (screenshot is analysed by Higgins AI and not persisted; only the verdict is stored)
- **Is this data required or can the user choose whether it's collected?** Optional
- **Why is this user data collected?** App functionality

### App activity — App interactions
- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** No (stored as aggregate usage counts)
- **Is this data required or can the user choose whether it's collected?** Required
- **Why is this user data collected?** App functionality, Analytics

### App activity — Other user-generated content
- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** Partially (URLs and text are stored in investigation cases; temporary AI processing content expires within 15 minutes)
- **Is this data required or can the user choose whether it's collected?** Optional
- **Why is this user data collected?** App functionality

### App info and performance — Crash logs
- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** No
- **Is this data required or can the user choose whether it's collected?** Required
- **Why is this user data collected?** App functionality

### App info and performance — Diagnostics
- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** No (device posture snapshots are stored)
- **Is this data required or can the user choose whether it's collected?** Required
- **Why is this user data collected?** App functionality

### Device or other IDs
- **Is this data collected, shared, or both?** Collected
- **Is this data processed ephemerally?** No (persistent random identifier)
- **Is this data required or can the user choose whether it's collected?** Required
- **Why is this user data collected?** App functionality

---

## Section 4 — Data sharing

| Question | Answer |
|---|---|
| Does your app share user data with third parties? | **No** |

> **Clarification:** User-submitted content (messages, URLs) is sent to AI services
> (Claude, Gemini) for threat analysis. However, under Google Play's definition,
> this is "processing" on behalf of the app, not "sharing", because:
> 1. The data is sent only to provide the app's core functionality (threat verdicts)
> 2. Personal information is stripped before transmission
> 3. AI providers act as data processors, not independent controllers
> 4. No data is sold, shared for advertising, or made available for third-party purposes

---

## Section 5 — Security practices

| Question | Answer |
|---|---|
| Is all of the user data collected by your app encrypted in transit? | **Yes** (HTTPS/TLS) |
| Do you provide a way for users to request that their data is deleted? | **Yes** |
| Has your app been independently security reviewed? | Select based on your status |
| Does your app follow Google's Families Policy? | **No** (not a children's app) |

### Data deletion mechanisms:
1. **Per-case delete** — Users can delete individual threat cases (`services/case_delete.py`)
2. **Admin case wipe** — Full reset of all threat cases and patrol records (`services/case_wipe.py`)
3. **Automatic retention** — Temporary AI analysis content (Ask Higgins messages, handoffs) auto-expires and is purged after 15 minutes (`services/higgins/retention.py`)
4. **Device deregistration** — Removes the device record and associated data

---

## Section 6 — Quick-reference summary (for Play Console copy-paste)

```
DATA COLLECTED:
• Device ID (random UUID, required, app functionality)
• Email address (optional, app functionality — mailbox monitoring)
• Phone number (optional, app functionality — caller-ID risk check)
• Name (optional, app functionality — Family Assist display)
• Photos (optional, ephemeral — settings verification screenshots)
• Emails (optional, ephemeral — scanned for phishing, body not stored)
• User-submitted text/URLs (optional — threat investigation cases)
• App interactions (required — feature usage counts)
• Crash logs (required — diagnostics)
• Device diagnostics (required — security posture audit)

DATA NOT COLLECTED:
• Precise or approximate location
• Financial information
• Health/fitness data
• Contacts, calendar, files
• SMS/MMS (users share text manually)
• Web browsing history (VPN filtering is local-only)
• Advertising ID

DATA SHARED WITH THIRD PARTIES: None
ENCRYPTED IN TRANSIT: Yes (HTTPS/TLS)
DATA DELETION AVAILABLE: Yes
```

---

## Appendix — Permissions declared in AndroidManifest

| Permission | Why |
|---|---|
| `INTERNET` | API calls to backend for threat analysis |
| `ACCESS_NETWORK_STATE` | Check Wi-Fi security status |
| `POST_NOTIFICATIONS` | Push alerts for new threats and scam advisories |
| `CAMERA` | Scan QR codes, photograph suspicious items, capture screenshots for settings verification |
| `FOREGROUND_SERVICE_MEDIA_PROJECTION` | GuardDog VPN website filtering service |

**Blocked permissions:**
| Permission | Why blocked |
|---|---|
| `SYSTEM_ALERT_WINDOW` | ApolloSG checks whether OTHER apps hold this; it never uses it itself |
