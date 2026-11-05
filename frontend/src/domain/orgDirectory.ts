// Australian Organisation Directory — scam reporting channels and official contact details.
// Used by the Luddish layer to generate organisation-specific recommended actions when an
// investigation identifies an impersonated organisation. Pure: no React, no native imports.

export interface OrgEntry {
  /** Canonical name as people know it. */
  name: string;
  /** Patterns that match this org in finding text (lowercase). */
  patterns: string[];
  /** Official website domains (lowercase, no protocol). */
  officialDomains: string[];
  /** Scam/phishing reporting channels. */
  reportScam: string;
  /** If the user already clicked or entered credentials. */
  ifCompromised: string;
  /** General customer service contact. */
  generalContact: string;
}

export const AU_ORG_DIRECTORY: readonly OrgEntry[] = [
  {
    name: "Commonwealth Bank (CommBank)",
    patterns: ["commbank", "commonwealth bank", "netbank", "cba.com"],
    officialDomains: ["commbank.com.au", "cba.com.au"],
    reportScam: "Forward the text to CommBank's phishing team at 0429 087 209 or email hoax@cba.com.au, then delete it.",
    ifCompromised: "Contact CommBank customer support immediately on 13 22 21 or through the official CommBank App to secure your account and reset your password.",
    generalContact: "13 22 21",
  },
  {
    name: "Westpac",
    patterns: ["westpac"],
    officialDomains: ["westpac.com.au"],
    reportScam: "Forward the message to Westpac at reportphishing@westpac.com.au, then delete it.",
    ifCompromised: "Call Westpac immediately on 13 20 32 to secure your account.",
    generalContact: "13 20 32",
  },
  {
    name: "ANZ",
    patterns: ["anz"],
    officialDomains: ["anz.com.au", "anz.com"],
    reportScam: "Forward the message to ANZ at hoax@anz.com, then delete it.",
    ifCompromised: "Call ANZ immediately on 13 13 14 to secure your account.",
    generalContact: "13 13 14",
  },
  {
    name: "NAB",
    patterns: ["nab", "national australia bank"],
    officialDomains: ["nab.com.au"],
    reportScam: "Forward the message to NAB at phish@nab.com.au, then delete it.",
    ifCompromised: "Call NAB immediately on 13 22 65 to secure your account.",
    generalContact: "13 22 65",
  },
  {
    name: "Australia Post",
    patterns: ["australia post", "auspost"],
    officialDomains: ["auspost.com.au"],
    reportScam: "Report to Australia Post at scams@auspost.com.au, then delete the message.",
    ifCompromised: "Call Australia Post on 13 13 18 if you entered any details.",
    generalContact: "13 13 18",
  },
  {
    name: "Telstra",
    patterns: ["telstra"],
    officialDomains: ["telstra.com.au", "telstra.com"],
    reportScam: "Forward the message to Telstra at report.phishing@telstra.com, then delete it.",
    ifCompromised: "Call Telstra on 13 22 00 to secure your account.",
    generalContact: "13 22 00",
  },
  {
    name: "Optus",
    patterns: ["optus"],
    officialDomains: ["optus.com.au"],
    reportScam: "Forward the message to Optus at report.phishing@optus.com.au, then delete it.",
    ifCompromised: "Call Optus on 13 39 37 to secure your account.",
    generalContact: "13 39 37",
  },
  {
    name: "ATO (Australian Taxation Office)",
    patterns: ["ato", "australian taxation office", "mygov", "my gov"],
    officialDomains: ["ato.gov.au", "my.gov.au"],
    reportScam: "Report to the ATO at ReportScams@ato.gov.au or call 1800 008 540.",
    ifCompromised: "Call the ATO immediately on 1800 008 540 to secure your myGov account.",
    generalContact: "13 28 61",
  },
  {
    name: "Linkt (Transurban)",
    patterns: ["linkt", "transurban"],
    officialDomains: ["linkt.com.au"],
    reportScam: "Report the message to Linkt via their website or call 13 33 31, then delete it.",
    ifCompromised: "Log in to your Linkt account via linkt.com.au and change your password, or call 13 33 31.",
    generalContact: "13 33 31",
  },
  {
    name: "PayPal",
    patterns: ["paypal"],
    officialDomains: ["paypal.com", "paypal.com.au"],
    reportScam: "Forward the message to PayPal at phishing@paypal.com, then delete it.",
    ifCompromised: "Log in to PayPal directly at paypal.com (not via any link) and change your password. Call PayPal on 1800 073 263.",
    generalContact: "1800 073 263",
  },
  {
    name: "RAC WA",
    patterns: ["rac wa", "rac western australia", "royal automobile club"],
    officialDomains: ["rac.com.au"],
    reportScam: "Contact RAC directly on 13 17 03 to verify the communication.",
    ifCompromised: "Call RAC on 13 17 03 to secure your membership account.",
    generalContact: "13 17 03",
  },
  {
    name: "Medicare / Services Australia",
    patterns: ["medicare", "centrelink", "services australia"],
    officialDomains: ["servicesaustralia.gov.au", "my.gov.au"],
    reportScam: "Report to Services Australia at scams@servicesaustralia.gov.au or call the Scams and Identity Theft helpdesk on 1800 941 126.",
    ifCompromised: "Call Services Australia on 1800 941 126 immediately to secure your account.",
    generalContact: "13 24 68",
  },
];

/** Find the organisation entry that matches the given text (finding text, overview, etc.). */
export function detectOrg(text: string): OrgEntry | null {
  const lower = text.toLowerCase();
  for (const org of AU_ORG_DIRECTORY) {
    for (const pattern of org.patterns) {
      if (lower.includes(pattern)) return org;
    }
  }
  return null;
}

/** Check if a URL domain is a known official domain for any org. */
export function isOfficialDomain(domain: string, org: OrgEntry): boolean {
  const d = domain.toLowerCase().replace(/^www\./, "");
  return org.officialDomains.some((od) => d === od || d.endsWith("." + od));
}
