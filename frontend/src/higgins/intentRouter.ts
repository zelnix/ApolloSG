/**
 * HigginsLocalIntentRouter — classifies every user message into one of three paths:
 *
 * 1. LOCAL_DIAGNOSTIC  — Device/Apollo status questions answered from local state
 * 2. INVESTIGATION     — Suspicious content that needs Magnum DI external analysis
 * 3. LOCAL_KNOWLEDGE   — Help, navigation, explanations about Apollo
 *
 * Core rule: Apollo observes → Magnum DI investigates → Higgins communicates.
 *
 * Hard architectural guard:
 *   getProtectionStatus()  → Diagnostic Core only
 *   getGateStatus()        → Diagnostic Core only
 *   getCurrentIssues()     → Diagnostic Core only
 *   investigateThreat(ev)  → Magnum DI only
 *
 * Even if Higgins misclassifies a message, Magnum DI CANNOT invent
 * whether the VPN is running or whether a gate is active.
 */

import { askedTerm } from "../domain/luddish/terms.ts";

// ── Route types ──────────────────────────────────────────────────────────────

export type HigginsRoute = "local_diagnostic" | "investigation" | "local_knowledge" | "clarify" | "ask_higgins";

export type LocalDiagnosticIntent =
  | "protection_status"
  | "device_health"
  | "site_gate_status"
  | "call_gate_status"
  | "text_gate_status"
  | "app_gate_status"
  | "vpn_status"
  | "permission_status"
  | "notification_status"
  | "current_issues"
  | "last_check"
  | "help_navigation";

export type LocalKnowledgeIntent =
  | "how_apollo_works"
  | "what_is_higgins"
  | "what_is_magnum_di"
  | "explain_feature"
  | "help_navigation"
  | "explain_alert";

export interface RouteDecision {
  route: HigginsRoute;
  /** For local_diagnostic: which specific diagnostic to run. */
  diagnosticIntent?: LocalDiagnosticIntent;
  /** For local_knowledge: which knowledge topic. */
  knowledgeIntent?: LocalKnowledgeIntent;
  /** For local_knowledge: the dictionary word a "what is …?" question asks about (Higgins Luddish L1). */
  termId?: string;
  confidence: number;
  /** Short reason for the classification (for logging/debugging). */
  reason: string;
  /** If route === 'clarify', the clarification question Higgins should ask. */
  clarificationQuestion?: string;
}

// ── Deterministic keyword/pattern matching (Layer 1) ─────────────────────────

interface PatternRule {
  patterns: RegExp[];
  route: HigginsRoute;
  diagnosticIntent?: LocalDiagnosticIntent;
  knowledgeIntent?: LocalKnowledgeIntent;
  confidence: number;
  reason: string;
}

// "Where is it?" is not "Is it on?". A question about finding or turning something
// on goes to Higgins himself, who holds the whole app map and answers with a tap
// straight through to the screen. Checked before the status patterns, which would
// otherwise read "where do I turn on call screening" as "is call screening on".
const WAYFINDING_PATTERNS: PatternRule[] = [
  {
    patterns: [
      /\bwhere\s+(?:is|are|do i|can i|would i|should i|will i)\b/i,
      /\bhow\s+(?:do|can)\s+i\s+(?:turn|switch|set|enable|disable|connect|disconnect|add|remove|open|find|get to|reach|start|stop|check|change|clear|delete|share|send|submit|upload)\b/i,
      /\bhow\s+(?:do|can)\s+i\s+\w+\s+(?:it|this|that|them)\s+(?:on|off)\b/i,
      /\b(?:take|bring|send|get)\s+me\s+to\b/i,
      /\b(?:show|open)\s+(?:me\s+)?(?:my|the)\s+\w+/i,
      /\bwhich\s+screen\b/i,
      /\bhow\s+(?:do|can|to)\s+i?\s*(?:share|send|submit|add|upload|get|put)\s+(?:\w+\s+)?(?:into|to|in|for|with)\s+(?:apollo|the app)/i,
      /\b(?:apollo|it)(?:'s| is)\s+not\s+(?:in|on|showing)\s+(?:my\s+)?(?:share|sharing)\s+menu/i,
      /\bnot\s+in\s+(?:my\s+)?(?:share|sharing)\s+menu/i,
    ],
    route: "ask_higgins",
    confidence: 0.9,
    reason: "Wayfinding question — Higgins knows the app and can link straight to it",
  },
];

const DIAGNOSTIC_PATTERNS: PatternRule[] = [
  // Protection status
  {
    patterns: [
      /\b(?:am i|is (?:my|the|this))\s+(?:phone|device)?\s*(?:protected|safe|secure)\b/i,
      /\b(?:protection|security)\s+(?:status|state|health)\b/i,
      /\b(?:is|are)\s+(?:apollo(?:\s?sg)?|protection|security)\s+(?:on|running|active|working|enabled)\b/i,
      /\b(?:what(?:'s| is))\s+(?:my)?\s*(?:protection|security)\s+(?:status|state)\b/i,
    ],
    route: "local_diagnostic",
    diagnosticIntent: "protection_status",
    confidence: 0.95,
    reason: "Explicit protection status question",
  },
  // Device health
  {
    patterns: [
      /\b(?:device|phone)\s+(?:health|status|check|diagnostics?)\b/i,
      /\b(?:how is|what(?:'s| is))\s+(?:my)?\s*(?:device|phone)\b/i,
      /\b(?:is (?:my|the|this))\s+(?:device|phone)\s+(?:ok|fine|healthy|good)\b/i,
    ],
    route: "local_diagnostic",
    diagnosticIntent: "device_health",
    confidence: 0.9,
    reason: "Device health question",
  },
  // Site Gate / Website protection
  {
    patterns: [
      /\b(?:site|website|web)\s*(?:gate|guard|protection|blocker)\b/i,
      /\b(?:is|are)\s+(?:websites?|sites?|web)\s+(?:protected|blocked|filtered)\b/i,
      /\b(?:website|web|site)\s+(?:protection|filtering|blocking)\s+(?:status|on|off|active|running)\b/i,
    ],
    route: "local_diagnostic",
    diagnosticIntent: "site_gate_status",
    confidence: 0.9,
    reason: "Site Gate status question",
  },
  // Call Gate
  {
    patterns: [
      /\b(?:call|phone)\s*(?:gate|guard|protection|screening)\b/i,
      /\b(?:is|are)\s+(?:calls?|phone)\s+(?:protected|screened|filtered)\b/i,
    ],
    route: "local_diagnostic",
    diagnosticIntent: "call_gate_status",
    confidence: 0.9,
    reason: "Call Gate status question",
  },
  // Text Gate
  {
    patterns: [
      /\b(?:text|sms|message)s?\s*(?:gate|guard|protection|screening)\b/i,
      /\b(?:is|are)\s+(?:texts?|sms|messages?)\s+(?:protected|screened|filtered|monitored)\b/i,
      /\b(?:are\s+my)\s+(?:texts?|sms|messages?)\s+(?:protected|safe|monitored|screened)\b/i,
    ],
    route: "local_diagnostic",
    diagnosticIntent: "text_gate_status",
    confidence: 0.9,
    reason: "Text Gate status question",
  },
  // App Gate
  {
    patterns: [
      /\b(?:app)\s*(?:gate|guard|protection|screening)\b/i,
      /\b(?:is|are)\s+(?:apps?)\s+(?:protected|screened|monitored)\b/i,
    ],
    route: "local_diagnostic",
    diagnosticIntent: "app_gate_status",
    confidence: 0.9,
    reason: "App Gate status question",
  },
  // VPN
  {
    patterns: [
      /\bvpn\s*(?:status|on|off|active|running|connected|enabled|working)\b/i,
      /\b(?:is|are)\s+(?:the|my)?\s*vpn\s+(?:on|off|active|running|connected|enabled|working)\b/i,
      /\b(?:what(?:'s| is))\s+(?:the|my)?\s*vpn\s+(?:status|state)\b/i,
    ],
    route: "local_diagnostic",
    diagnosticIntent: "vpn_status",
    confidence: 0.95,
    reason: "VPN status question",
  },
  // Permissions
  {
    patterns: [
      /\b(?:permission|permissions)\s+(?:status|state|granted|missing|needed|required)\b/i,
      /\b(?:what|which)\s+permissions?\b/i,
      /\b(?:do i need|does (?:apollo(?:\s?sg)?|it) (?:need|require))\s+(?:any )?permissions?\b/i,
    ],
    route: "local_diagnostic",
    diagnosticIntent: "permission_status",
    confidence: 0.85,
    reason: "Permission status question",
  },
  // Current issues
  {
    patterns: [
      /\b(?:any|what|are there)\s+(?:issues?|problems?|warnings?|alerts?|errors?)\b/i,
      /\b(?:what(?:'s| is))\s+wrong\b/i,
      /\b(?:why is|why'?s)\s+(?:apollo(?:\s?sg)?|it)\s+(?:barking|growling|warning|alerting)\b/i,
      /\b(?:needs?|requires?|requiring)\s+attention\b/i,
    ],
    route: "local_diagnostic",
    diagnosticIntent: "current_issues",
    confidence: 0.9,
    reason: "Current issues question",
  },
  // Last check
  {
    patterns: [
      /\b(?:last|latest|recent|previous)\s+(?:check|scan|result|investigation)\b/i,
      /\b(?:when was|what was)\s+(?:the)?\s*(?:last|latest)\s+(?:check|scan)\b/i,
    ],
    route: "local_diagnostic",
    diagnosticIntent: "last_check",
    confidence: 0.85,
    reason: "Last check question",
  },
];

const INVESTIGATION_PATTERNS: PatternRule[] = [
  {
    patterns: [
      /\b(?:investigate|check|scan|analyse|analyze|look at|inspect|review)\s+(?:this|a|an|the|my)?\s*(?:email|message|call|link|url|screenshot|file|app|text|sms|number|website|attachment|download|pdf|document)\b/i,
      /\b(?:is this|is it|does this|could this be)\s+(?:a )?(?:scam|phishing|fraud|fake|suspicious|malware|dangerous|safe|legit|legitimate)\b/i,
      /\b(?:i (?:got|received|have|just got))\s+(?:a |an )?(?:suspicious|weird|strange|dodgy|unusual|scam)\b/i,
      /\b(?:this (?:looks|seems|appears?) )?(?:suspicious|dodgy|sketchy|scammy|phishing|fraudulent)\b/i,
      /\b(?:someone|caller|sender)\s+(?:called|texted|emailed|sent|messaged)\b/i,
      /\b(?:is (?:this|that|the))\s+(?:url|link|website|site|domain)\s+(?:safe|legit|legitimate|ok|dangerous)\b/i,
    ],
    route: "investigation",
    confidence: 0.9,
    reason: "Investigation request detected",
  },
];

const KNOWLEDGE_PATTERNS: PatternRule[] = [
  // Explain alert/warning — must be checked BEFORE generic knowledge patterns
  {
    patterns: [
      /\bexplain\s+(?:a\s+|an\s+|the\s+|this\s+|that\s+)?(?:scam|threat|phishing|fraud|warning|alert)\b/i,
      /\b(?:what does|what do)\s+(?:this|that|the)\s+(?:warning|alert|threat|scam)\s+mean\b/i,
      /\b(?:what is|what's)\s+(?:this|that|the)\s+(?:warning|alert|threat|scam)\b/i,
    ],
    route: "local_knowledge",
    knowledgeIntent: "explain_alert",
    confidence: 0.9,
    reason: "Alert/warning explanation request",
  },
  {
    patterns: [
      /\b(?:how (?:does|do)|what (?:is|are)|explain|tell me about)\s+(?:apollo(?:\s?sg)?|higgins|magnum|gates?|protection|screening)\b/i,
      /\b(?:where (?:is|do i find))\s+(?:the\s+)?(?:settings?|protections?|checks?|home|patrol)\b/i,
      /\b(?:what can (?:you|higgins|apollo(?:\s?sg)?) do)\b/i,
      /\b(?:who (?:is|are) (?:you|higgins|apollo(?:\s?sg)?|magnum))\b/i,
    ],
    route: "local_knowledge",
    knowledgeIntent: "how_apollo_works",
    confidence: 0.8,
    reason: "Knowledge/help question about ApolloSG",
  },
  // Navigation help — only explicit "help" or "how do I navigate" requests
  {
    patterns: [
      /\b(?:help)\b(?!\s+(?:me\s+)?(?:recogni[sz]e|spot|identify|avoid|prevent|understand|learn))/i,
      /\b(?:how (?:do i|to))\s+(?:navigate|use|find|open|access)\s+(?:apollo(?:\s?sg)?|the app|settings|features)\b/i,
    ],
    route: "local_knowledge",
    knowledgeIntent: "help_navigation",
    confidence: 0.75,
    reason: "Navigation help request",
  },
];

// ── Context-aware routing (Layer 2) ──────────────────────────────────────────

// Matched as whole words only, so "on" never matches inside "someone", "phone" or "money".
const CONTEXT_KEYWORDS_DIAGNOSTIC = [
  "working", "running", "active", "on", "off", "enabled", "disabled",
  "status", "state", "ok", "fine", "healthy", "broken", "down",
];

const CONTEXT_KEYWORDS_INVESTIGATION = [
  "scam", "scams", "scammed", "scammer", "scammers", "phishing", "fraud", "fraudulent",
  "suspicious", "malware", "virus", "viruses", "hacked", "hacker", "hackers",
  "compromised", "stolen", "unsafe", "dangerous",
];

const hasWord = (text: string, words: string[]) => words.some((word) => new RegExp(`\\b${word}\\b`, "i").test(text));

/** Short ambiguous questions that should be resolved via context. */
function resolveAmbiguous(
  message: string,
  conversationContext?: string[],
): RouteDecision | null {
  const lower = message.toLowerCase().trim();

  // Very short questions like "Is it working?", "Am I protected?", "What about the VPN?"
  if (lower.length < 60) {
    const hasDeviceContext = hasWord(lower, CONTEXT_KEYWORDS_DIAGNOSTIC);
    const hasThreatContext = hasWord(lower, CONTEXT_KEYWORDS_INVESTIGATION);

    if (hasDeviceContext && !hasThreatContext) {
      // Likely asking about Apollo/device — route to diagnostic
      return {
        route: "local_diagnostic",
        diagnosticIntent: "protection_status",
        confidence: 0.7,
        reason: "Ambiguous but context suggests device/ApolloSG question",
      };
    }

    if (hasThreatContext && !hasDeviceContext) {
      return {
        route: "investigation",
        confidence: 0.7,
        reason: "Ambiguous but context suggests threat investigation",
      };
    }
  }

  return null;
}

// ── Main router ──────────────────────────────────────────────────────────────

/**
 * Classify a user message into the correct Higgins route.
 *
 * Layered decision:
 * 1. Deterministic pattern matching (highest confidence)
 * 2. Context-aware routing for ambiguous short questions
 * 3. Magnum DI only when investigation is genuinely required
 * 4. If genuinely ambiguous, return 'clarify' with a question
 *
 * @param message            The user's raw message text
 * @param conversationContext Recent conversation messages (for context)
 * @param hasActiveInvestigation Whether an investigation is currently active
 */
export function classifyIntent(
  message: string,
  conversationContext?: string[],
  hasActiveInvestigation?: boolean,
): RouteDecision {
  const trimmed = message.trim();
  if (!trimmed) {
    return { route: "local_knowledge", knowledgeIntent: "help_navigation", confidence: 1, reason: "Empty message" };
  }

  // Layer 1: Deterministic pattern matching
  // Wayfinding first — "where is X" must never be answered as "is X on".
  for (const rule of WAYFINDING_PATTERNS) {
    for (const pattern of rule.patterns) {
      if (pattern.test(trimmed)) {
        return { route: rule.route, confidence: rule.confidence, reason: rule.reason };
      }
    }
  }

  // "What is phishing?" — a word Higgins' dictionary explains, answered on the device from the Luddish Dictionary and
  // Knowledge Library. Checked before the status and scam patterns, which would read "phishing" as a case to open.
  const term = askedTerm(trimmed);
  if (term) {
    return { route: "local_knowledge", termId: term.id, confidence: 0.9, reason: "A word Higgins' dictionary explains" };
  }

  // Check diagnostics next — these should NEVER reach Magnum DI
  for (const rule of DIAGNOSTIC_PATTERNS) {
    for (const pattern of rule.patterns) {
      if (pattern.test(trimmed)) {
        return {
          route: rule.route,
          diagnosticIntent: rule.diagnosticIntent,
          confidence: rule.confidence,
          reason: rule.reason,
        };
      }
    }
  }

  // Check investigation patterns
  for (const rule of INVESTIGATION_PATTERNS) {
    for (const pattern of rule.patterns) {
      if (pattern.test(trimmed)) {
        return {
          route: rule.route,
          confidence: rule.confidence,
          reason: rule.reason,
        };
      }
    }
  }

  // Check knowledge patterns
  for (const rule of KNOWLEDGE_PATTERNS) {
    for (const pattern of rule.patterns) {
      if (pattern.test(trimmed)) {
        return {
          route: rule.route,
          knowledgeIntent: rule.knowledgeIntent,
          confidence: rule.confidence,
          reason: rule.reason,
        };
      }
    }
  }

  // Layer 2: Context-aware resolution for ambiguous messages
  const contextResolution = resolveAmbiguous(trimmed, conversationContext);
  if (contextResolution) return contextResolution;

  // Layer 3: If there's an active investigation, assume follow-up
  if (hasActiveInvestigation) {
    return {
      route: "investigation",
      confidence: 0.6,
      reason: "Follow-up during active investigation",
    };
  }

  // Layer 4: Genuinely ambiguous — ask for clarification
  // But only for very short messages. Longer messages are more likely knowledge questions.
  if (trimmed.length < 40 && !trimmed.includes("?")) {
    return {
      route: "clarify",
      confidence: 0.3,
      reason: "Message too short and ambiguous to classify",
      clarificationQuestion: "Do you mean whether Apollo is protecting your device, or would you like me to investigate something specific?",
    };
  }

  // Default: anything with no strong local signal belongs to Higgins himself, who
  // answers from Apollo's product knowledge, this device's live state and his own
  // knowledge of scams. A canned local answer here would be a guess.
  return {
    route: "ask_higgins",
    confidence: 0.5,
    reason: "No strong local signal — Higgins answers it",
  };
}
