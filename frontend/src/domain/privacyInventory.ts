// Single maintained processing inventory; screen + Settings summaries must refer here.
// Governing principle: Transparent Data Use and Necessary Sharing.

// ─── Governing Principle ───────────────────────────────────────────────────────

export const GOVERNING_PRINCIPLE = {
  title: 'Transparent Data Use and Necessary Sharing',
  body: [
    'Apollo must clearly explain what information it examines on the user\u2019s device, what information is transmitted to ApolloSG\u2019s supporting services, and what information is shared with third-party providers.',
    'ApolloSG processes information locally wherever practical while using secure external services when necessary to deliver effective scam protection, threat detection, reputation checking and investigations.',
    'Personal information may be shared with an authorised service provider when necessary to perform a specific function, appropriately authorised and legally permitted.',
    'ApolloSG must minimise unnecessary disclosure without removing material security evidence or impairing the protection service.',
  ],
  credo: 'Protect the person. Preserve the evidence. Share only what is necessary.',
  accountability: 'Harmony Wellness Group remains accountable for ApolloSG\u2019s information handling and third-party arrangements.',
};

// ─── Three Processing Locations ────────────────────────────────────────────────

export const PROCESSING_LOCATIONS = {
  title: 'How ApolloSG processes your information',
  locations: [
    {
      label: 'On your device',
      icon: 'device' as const,
      summary: 'Apollo examines messages, caller information, links, security activity, screenshots and files locally on your device. Privacy screening, credential detection and image redaction all happen here before anything is sent externally.',
      detail: 'Information that stays local includes: passwords and verification codes detected in content, full messages and files after assessment, browsing history, precise location, hardware identifiers, and any content you choose to withhold. Some local processing may identify a security concern that leads to an authorised external investigation.',
    },
    {
      label: 'ApolloSG\u2019s services',
      icon: 'server' as const,
      summary: 'When a security investigation is needed, ApolloSG transmits privacy-processed evidence to its backend for investigation coordination, security checking, evidence management and alerts.',
      detail: 'Transmission is required because security investigations need access to threat intelligence, AI analysis and reputation databases that cannot run on-device. Protections include: one outbound privacy boundary before any AI tool that strips credentials and authentication secrets, removes your personal information and keeps only the security evidence the investigation needs; owner-scoped access control; Fernet encryption for investigation content, and automatic deletion within 15 minutes of completion.',
    },
    {
      label: 'Third-party services',
      icon: 'external' as const,
      summary: 'ApolloSG shares specific information with named external providers when necessary for a particular security function. Each provider receives only the information needed for its purpose.',
      detail: 'Some personal information must be shared for particular services to work. For example: your email address for breach checking, a phone number for caller reputation, a website address for malicious-site detection, and approved investigation evidence for AI analysis. These are necessary, authorised disclosures \u2014 not privacy violations. The full list of providers is in the Third-Party Service Register accessible from Settings.',
    },
  ],
};

// ─── Capability Data Use ───────────────────────────────────────────────────────

export const CAPABILITY_DATA_USE = [
  {
    capability: 'Message and email investigation',
    local: 'Apollo examines message text, sender details and embedded links on your device.',
    backend: 'Privacy-processed evidence (with credentials stripped) is sent to ApolloSG\u2019s backend for Higgins AI investigation.',
    thirdParty: 'AI tools receive approved investigation content, with your personal information removed. Safe Browsing checks embedded URLs. RDAP checks sender domains.',
    shared: 'Sanitised message content, sender indicators, embedded URLs',
    necessary: 'AI investigation requires the submitted content to assess the threat accurately.',
    activation: 'Manual: when you submit a message for investigation',
    withheld: 'Passwords, verification codes and authentication tokens (blacked out of images before sending)',
  },
  {
    capability: 'Gmail monitoring',
    local: 'ApolloSG does not store mailbox credentials. Gmail OAuth provides read-only access.',
    backend: 'Email content is processed through ApolloSG\u2019s backend investigation pipeline with the same credential stripping and privacy controls as manual investigations.',
    thirdParty: 'AI tools receive privacy-processed email evidence, with your personal information removed. VirusTotal receives file hashes (not file content) for attachment scanning. Safe Browsing checks URLs in emails.',
    shared: 'Email sender, subject, body content (privacy-processed), attachment hashes',
    necessary: 'Automated monitoring requires processing email content to detect scam patterns.',
    activation: 'User-enabled: only after you connect Gmail via OAuth and start monitoring',
    withheld: 'Mailbox credentials (never collected), attachment file content (only hashes sent to VirusTotal)',
  },
  {
    capability: 'Link and website investigation',
    local: 'ApolloSG sanitises URLs on your device, removing credentials, fragments and secret query parameters.',
    backend: 'Sanitised URL and domain are sent to ApolloSG\u2019s backend for reputation checking and web crawling.',
    thirdParty: 'Safe Browsing checks the URL. RDAP checks domain registration. Public websites are accessed for content analysis.',
    shared: 'Sanitised URL, domain name',
    necessary: 'Website safety checks require submitting the URL to reputation services.',
    activation: 'Manual: when you submit a link for investigation',
    withheld: 'URL credentials, authentication tokens, fragment identifiers, secret query values',
  },
  {
    capability: 'Phone number checking',
    local: 'ApolloSG processes the device number you submit.',
    backend: 'The phone number is sent to ApolloSG\u2019s backend for reputation lookup.',
    thirdParty: 'IPQualityScore receives the device number for fraud and reputation checking.',
    shared: 'The phone number being checked',
    necessary: 'Caller reputation checking requires submitting the device number to the reputation provider.',
    activation: 'Manual: when you submit a phone number for investigation',
    withheld: 'No additional personal information is sent',
  },
  {
    capability: 'Breach checking',
    local: 'ApolloSG processes the email address you submit.',
    backend: 'The email address is sent to ApolloSG\u2019s backend for breach lookup.',
    thirdParty: 'XposedOrNot (or Have I Been Pwned when configured) receives the email address to check against known data breaches.',
    shared: 'The email address submitted for the breach check',
    necessary: 'Breach checking requires submitting the email address to the breach database provider.',
    activation: 'Manual: when you request a breach check for an email address',
    withheld: 'No additional personal information is sent',
  },
  {
    capability: 'Image and screenshot investigation',
    local: 'When you submit an image, Apollo checks it on your device for passwords, PINs, one-time codes and similar secrets and blacks them out on the copy it sends. The scam evidence in the picture \u2014 the message wording, links, the sender\u2019s details, payment requests and layout \u2014 is kept, because that is what Apollo checks. If a detected secret can\u2019t be blacked out, the image isn\u2019t sent.',
    backend: 'The prepared copy is sent to ApolloSG\u2019s backend for the investigation. Your original stays on your device unchanged.',
    thirdParty: 'AI tools receive the prepared image (with any detected credentials blacked out) through ApolloSG\u2019s single AI gateway.',
    shared: 'The submitted image, with detected credentials blacked out',
    necessary: 'Visual content investigation requires transmitting the approved representation to AI analysis.',
    activation: 'Manual: when you submit an image',
    withheld: 'Detected credentials, and any image whose detected credentials can\u2019t be blacked out',
  },
  {
    capability: 'Push notifications and alerts',
    local: 'Apollo determines when a security alert should be sent.',
    backend: 'Notification content and this device\u2019s delivery token are passed to ApolloSG\u2019s managed push relay, which keeps the token; ApolloSG\u2019s own records never store it.',
    thirdParty: 'ApolloSG\u2019s managed push relay, Google FCM and Apple APNs deliver the notification to your device.',
    shared: 'Push delivery token and notification content',
    necessary: 'Push delivery requires sharing the delivery token and notification content with the platform push service.',
    activation: 'User-enabled: only when you enable notifications in Settings',
    withheld: 'Full investigation details; notifications contain minimal alert content',
  },
  {
    capability: 'Family support',
    local: 'You choose your name, what to share with paired family members, and (as the family member) a number to call them on.',
    backend: 'Chosen names, a call-back number if a family member adds one, alerts, weekly counts and replies are stored on ApolloSG\u2019s backend and shared with paired family members. A pairing code is 6 random digits that works once and expires after 15 minutes.',
    thirdParty: 'Push services deliver alerts. No email is sent.',
    shared: 'Names, a call-back number if added, alert content, text messages you choose to send',
    necessary: 'Family pairing requires sharing chosen information with paired members and using push delivery for alerts.',
    activation: 'Manual: when you pair with a code, share an incident or send a note',
    withheld: 'Full investigation evidence; family members receive alert summaries, not raw evidence',
  },
  {
    capability: 'Ask Higgins (text chat)',
    local: 'Questions are composed on your device. A state-only reading of your own ApolloSG app \u2014 protection statuses, permission states, settings values, counts and the headlines ApolloSG itself wrote \u2014 is assembled on the device to accompany the question.',
    backend: 'Questions, that state reading and requested speech are sent to ApolloSG\u2019s backend using the owner-managed key. Personal identifiers in research queries are removed within ApolloSG\u2019s backend before anything is sent to AI tools.',
    thirdParty: 'AI tools receive the privacy-processed question, with your personal information removed.',
    shared: 'Privacy-processed question or speech request, plus your Apollo protection state',
    necessary: 'AI responses and speech generation require transmitting your query to the AI provider. The state reading is what lets Higgins answer about your actual phone instead of guessing.',
    activation: 'Manual: when you send a question, tap read-aloud, or enable automatic read-aloud',
    withheld: 'Message bodies, screenshots, files, links you checked, personal details and secrets are never part of the state reading. Private messages or secrets you should not paste into the chat field',
  },
  {
    capability: 'On-device AI (optional)',
    local: 'When you turn it on, the text of a message you check is read by an AI model that runs on your phone: the one built into the phone (Gemini Nano on supported Android phones, Apple Intelligence on supported iPhones), or a small model ApolloSG downloads if you ask it to. Passwords and codes are removed before the model sees the text. It re-words Apollo\u2019s result and points out requests in the message; it never changes Apollo\u2019s result.',
    backend: 'Nothing. The model\u2019s input and output are not sent to ApolloSG\u2019s backend. If you download a model, ApolloSG\u2019s storage sends the model file to your phone; no message content goes with that request.',
    thirdParty: 'None. The built-in models are part of your phone\u2019s operating system and run on the phone.',
    shared: 'Nothing is shared',
    necessary: 'Not required for protection. Apollo\u2019s checks work the same with it off.',
    activation: 'Manual: off until you turn on On-device AI in Settings. A model is downloaded only when you tap Download, and only on Wi-Fi',
    withheld: 'Everything. A local record on your phone keeps only which model ran, when, how long it took and whether its answer was shown \u2014 never the message, the question or the answer',
  },
];

// ─── Existing Processing Flows ─────────────────────────────────────────────────

export const PRIVACY_FLOWS = [
  { what: 'Purpose-limited security assessments', when: 'When you submit a message, email, screenshot, account alert, phone number or link', detail: 'ApolloSG combines on-device detection with Higgins context and supported reputation sources. Raw submitted content is not kept in Patrol, logs or analytics. Request-scoped copies close immediately after completion or failure and never later than 15 minutes.' },
  { what: 'Optional ongoing access', when: 'Only after you enable notification access or connect Gmail with OAuth', detail: 'Notification checks (where your device allows them) and Gmail OAuth are opt-in. Disconnect or disable access to stop future checks. ApolloSG never asks for or stores a mailbox username or password. Gmail monitoring uses the same credential stripping and privacy controls as manual investigations, with AI investigation authorised for detected threats.' },
  { what: 'Links you investigate', when: 'When you manually check or share a link, message or email', detail: 'ApolloSG receives a sanitised URL for the requested investigation. Credentials, fragments and secret query values are removed first. Reputation, safe webpage and domain-registration services receive only the URL or hostname needed for their check. Cached reputation uses a digest; expired rows are ignored, not treated as current evidence.' },
  { what: 'Minimal Patrol summaries and packet evidence', when: 'After checks and native observations; retried until acknowledged', detail: 'ApolloSG stores category, state, timestamps, opaque event IDs and website domain. Packet evidence adds mechanism, protocol, rule ID, port and observed action. No caller numbers, app/process attribution or raw message narratives. Clear Patrol currently hides server rows (soft deletion), not physical erasure. Pending uploads are shown in Patrol.' },
  { what: 'Device and notification settings', when: 'Setup, heartbeat, notification enablement and settings changes', detail: 'A server-issued random device ID, platform/app version, coarse UTC offset and quiet-hour preferences go to ApolloSG, with the device\'s make, model, system version, region-setting country, install date and how many times each feature was used (never what was checked or read). Push delivery tokens go to the managed relay and Apple/Google delivery services. Disable notifications in Settings to stop notifications; this is not data erasure.' },
  { what: 'Ask Higgins and Hear Higgins', when: 'When you send a question, tap read-aloud, or explicitly enable automatic read-aloud', detail: 'Questions and requested speech go to Higgins using the owner-managed key; do not paste private messages or secrets. Automatic event context is replaced with a generic summary. ApolloSG retains conversation history and temporary cached speech under the stated case lifecycle. Turning off read-aloud stops future automatic speech requests. Personal information is removed within ApolloSG\u2019s backend before anything reaches AI tools.' },
  { what: 'Optional family support', when: 'You pair, invite, share an incident, reply or send a text note', detail: 'Chosen names, contact details, minimal alerts, weekly counts and replies go to ApolloSG and paired guardians. Invitations use an email delivery service; confirmed guardians also receive authorised automatic security alerts via email when Apollo is barking or biting. Alerts use the push relay. Remove a pairing to stop future sharing; it does not erase prior deliveries.' },
  { what: 'App reputation checks', when: 'You manually check an app', detail: 'The supplied app/developer names, source, permission labels and website hosts go to ApolloSG and optionally Higgins for explanation, not your full app inventory. Do not enter personal content in app-name fields.' },
  { what: 'Optional Gmail investigation', when: 'Only after you connect Gmail with Google OAuth and start a scan or monitor', detail: "ApolloSG uses Gmail read-only OAuth access. ApolloSG never asks for or stores a mailbox username or password. Disconnect removes ApolloSG's stored OAuth connection; revoke provider access as an additional control. Raw message content is not copied into Patrol. Email attachment hashes are checked against VirusTotal for known malware; file content is never sent." },
  { what: 'Optional on-device AI', when: 'Only after you turn on On-device AI in Settings', detail: "The text of a message you check is read by an AI model on your phone, after passwords and codes are removed. Nothing it reads or writes leaves the phone. A model download (only if your phone has no built-in model and you tap Download) fetches the model file from ApolloSG's storage over Wi-Fi; no message content is sent. A local record keeps which model ran and whether its answer was shown, never the content." },
];

export const AI_PROCESSING_DISCLOSURE = {
  title: 'How AI investigation works',
  sections: [
    {
      heading: 'Where your data goes',
      text: "When you submit content for AI investigation, ApolloSG removes your personal information and sends the privacy-processed evidence through its own service to the AI tools it uses. For Gmail monitoring, previously authorised automatic investigations use the same privacy controls. This uses a paid API tier managed by ApolloSG \u2014 it is not your personal account with any AI provider and does not connect to any account you own.",
    },
    {
      heading: 'What the AI tools receive',
      text: 'For manual investigations: the scam evidence in the messages, screenshots and images you submit (with detected credentials removed or blacked out, and your personal information removed), and minimal research queries. For Gmail monitoring: privacy-processed email evidence from your previously authorised connection. In all cases, detected credentials, passwords and your personal information are not transmitted.',
    },
    {
      heading: 'Data retention',
      text: "ApolloSG uses paid AI services. Under their published terms, data sent through the paid service is not used for model training. Request-scoped processing copies on ApolloSG's side are closed immediately after completion and never retained beyond 15 minutes. Each AI provider's own data retention and processing practices are governed by its published terms, which ApolloSG does not control or independently verify.",
    },
    {
      heading: 'Research queries',
      text: 'When Higgins researches a domain, phone number, or scam report, the outbound query is minimised. Personal identifiers detected in your evidence (emails, phone numbers, account numbers) are replaced with category labels within ApolloSG\u2019s backend before the query reaches any AI tool. Domain names and scam indicators are preserved because they are essential for the investigation.',
    },
    {
      heading: 'On-device AI (optional)',
      text: "If you turn on On-device AI, an AI model running on your phone also reads the message you check, after passwords and codes are removed. It can re-word Apollo's result in plainer language and point out requests in the message, quoting the message's own words. It never changes Apollo's result, and what it reads or writes is not sent anywhere. Its re-wording is checked first and isn't shown if it adds anything that wasn't in Apollo's result. Phones without a built-in model can download a small open model (Qwen or Llama) from ApolloSG over Wi-Fi; delete it at any time in Settings.",
    },
    {
      heading: 'On-device screening',
      text: "Submitting an image is your authorisation for Apollo to investigate it. Before sending, Apollo checks it on your device for credentials and blacks out any it finds on the copy it sends; everything else is kept as evidence. If a detected credential can't be blacked out, the image isn't sent. Detection depends on on-device text recognition, so a credential it can't read may not be caught.",
    },
  ],
};

export const LOCAL_ONLY_CONTENT = ['Passwords, verification codes and sensitive URL tokens', 'Full messages, screenshots and files after their submitted assessment completes', 'Browsing history, precise location, IMEI, serial number and advertising ID'];

export const PRIVACY_STANDARDS_DISCLOSURE = {
  title: 'Privacy standards',
  intro: "ApolloSG's privacy and security controls are designed to conform with the following recognised international standards. Adoption means ApolloSG maps its controls against these standards through internal conformity assessment. Independent certification is not currently claimed.",
  standards: [
    { name: 'ISO/IEC 27701:2025', role: 'Privacy Information Management System (PIMS)' },
    { name: 'ISO/IEC 29100:2024', role: 'Privacy terminology, definitions and principles' },
    { name: 'ISO/IEC 27001:2022', role: 'Information security management and controls' },
    { name: 'ISO/IEC 42001:2023', role: 'AI governance and accountability' },
    { name: 'Australian Privacy Act 1988', role: 'Applicable Australian legal requirements and Privacy Principles (APPs)' },
    { name: 'ISO/IEC 27559:2022', role: 'De-identification framework for personal data minimisation' },
    { name: 'ISO 31700-1:2023', role: 'Privacy-by-design requirements' },
  ],
};

export const THIRD_PARTY_SERVICES_DISCLOSURE = {
  title: 'Third-party services',
  intro: 'ApolloSG is a brand of Harmony Wellness Group (HWG), which is accountable for the selection, configuration and oversight of the external services ApolloSG uses. ApolloSG uses external services only where needed to provide security investigations, reputation checks, communications, storage or supporting functionality.',
  services: [
    { name: 'AI tools', purpose: 'AI-powered security investigations, explanations and research', shared: 'Privacy-processed investigation evidence, approved content, security indicators and minimised research queries. Your personal information and authentication secrets are removed before anything is sent.' },
    { name: 'Google Safe Browsing', purpose: 'Detect known unsafe websites', shared: 'Sanitised website addresses and domains. Credentials and secret query values are removed before lookup.' },
    { name: 'Google Gmail', purpose: 'Optional read-only email checking', shared: 'Google OAuth authorisation and access to email information within the approved read-only scope. Only active when you connect Gmail.' },
    { name: 'VirusTotal', purpose: 'Email attachment malware scanning', shared: 'SHA-256 file hashes only. File content is never sent. Active when Gmail monitoring is connected.' },
    { name: 'XposedOrNot / Have I Been Pwned', purpose: 'Check whether an email appears in known data breaches', shared: 'The email address submitted for the specific breach check.' },
    { name: 'IPQualityScore', purpose: 'Phone-number fraud and reputation checking', shared: 'The phone number being checked.' },
    { name: 'Push notifications (Expo, Google FCM, Apple APNs)', purpose: 'Deliver security and family alerts', shared: 'Push delivery tokens and notification content. Only active when you enable notifications.' },
    { name: 'Emergent-managed email delivery', purpose: 'Family invitations, guardian security alerts and service emails', shared: 'Recipient email address, subject and email content. Triggered by your actions (invitations) and by authorised automatic security alerts to confirmed family guardians.' },
    { name: 'Database hosting provider', purpose: 'Store authorised application and investigation records', shared: 'Records permitted by ApolloSG\u2019s storage and retention controls.' },
    { name: 'Domain registries and public websites', purpose: 'Domain registration research and website investigation', shared: 'Domain lookup requests and requested website access for URLs you submit.' },
  ],
  footer: 'Optional integrations operate only when you enable the relevant feature. ApolloSG applies purpose-based privacy controls to all information sent to external services. Some personal information (such as an email address for breach checking or a phone number for reputation checking) must be shared with the relevant provider for the service to work. These are necessary, authorised disclosures.',
  changes: 'Harmony Wellness Group may add, remove or replace third-party services to improve security, privacy, reliability or functionality. New or replacement services remain subject to ApolloSG\u2019s privacy and security controls. Where changes materially affect the handling of personal information, updated disclosures will be provided and additional consent obtained where legally required.',
};

export const THIRD_PARTY_REGISTER = {
  title: 'HWG Third-Party Service Register',
  accountable: 'Harmony Wellness Group (HWG)',
  intro: 'Harmony Wellness Group is accountable for the selection, configuration and oversight of the external services ApolloSG uses. This register reflects the verified deployment configuration.',
  active: [
    { name: 'AI tools', purpose: 'AI-powered security investigations, explanations and research', shared: 'Privacy-processed investigation evidence, approved content, security indicators and minimised research queries. Your personal information and authentication secrets are removed before anything is sent.', controls: 'Single gateway; credential stripping; personal-information removal; research-query minimisation; images only for authorised investigation purposes' },
    { name: 'Google Safe Browsing', purpose: 'Detect known unsafe websites', shared: 'Sanitised website addresses and domains', controls: 'URL sanitisation removes credentials and secret parameters' },
    { name: 'IPQualityScore', purpose: 'Phone-number fraud and reputation checking', shared: 'The phone number being checked', controls: 'Single-field transmission' },
    { name: 'VirusTotal', purpose: 'Email attachment malware scanning (hash-only)', shared: 'SHA-256 file hashes only; file content never sent', controls: 'Hash-only mode; free tier rate-limited' },
    { name: 'Push notifications (Expo, FCM, APNs)', purpose: 'Deliver security and family alerts', shared: 'Push delivery tokens and notification content', controls: 'Minimal notification content' },
    { name: 'Emergent-managed email delivery', purpose: 'Family invitations and guardian security alerts', shared: 'Recipient email, subject and content', controls: 'Triggered by user actions and authorised automatic alerts to confirmed guardians' },
    { name: 'MongoDB hosting provider', purpose: 'Store authorised application records', shared: 'Records permitted by retention controls', controls: 'Owner-scoped access; Fernet encryption; 15-minute scoped retention' },
  ],
  optional: [
    { name: 'Google Gmail', purpose: 'Optional read-only email checking', shared: 'OAuth authorisation and email within read-only scope', activation: 'User connects Gmail via OAuth in Settings' },
    { name: 'XposedOrNot', purpose: 'Check if an email appears in known breaches', shared: 'Email address submitted for the check', activation: 'Free API; default breach provider' },
    { name: 'IANA / RDAP registries', purpose: 'Domain registration research', shared: 'Domain name being investigated', activation: 'Public registries; no credentials required' },
    { name: 'Public websites', purpose: 'Investigation of submitted websites', shared: 'Requested website access', activation: 'Triggered by user-submitted URL investigation' },
  ],
  unconfigured: [
    { name: 'Have I Been Pwned', purpose: 'Breach checking (replaces XposedOrNot when configured)', activation: 'Requires HIBP API key' },
    { name: 'S3-compatible storage', purpose: 'Family shared content', activation: 'Requires storage credentials' },
  ],
};

export const COMPLIANCE_MATRIX_DISCLOSURE = {
  title: 'ApolloSG Compliance Matrix',
  version: '3.0',
  effective: 'June 2026',
  framework: 'Application technical compliance is assessed independently from operational and legal assurance. Passing code tests establishes application compliance. It does not automatically establish full ISO management-system conformity.',
  standards: [
    { name: 'ISO/IEC 27701:2025', role: 'Privacy Information Management' },
    { name: 'ISO/IEC 29100:2024', role: 'Privacy principles and definitions' },
    { name: 'ISO/IEC 27001:2022', role: 'Information security controls' },
    { name: 'ISO/IEC 42001:2023', role: 'AI governance and accountability' },
    { name: 'Australian Privacy Act 1988', role: 'Australian Privacy Principles (APPs)' },
    { name: 'ISO/IEC 27559:2022', role: 'De-identification framework' },
    { name: 'ISO 31700-1:2023', role: 'Privacy-by-design' },
  ],
  appControls: [
    { control: 'Privacy by default', detail: 'Local-first processing, minimum collection, automatic withholding', status: 'implemented' as const },
    { control: 'Personal information protection', detail: 'Identification, classification and redaction of unnecessary personal data', status: 'implemented' as const },
    { control: 'Credential protection', detail: 'Prevent passwords, tokens and authentication codes from reaching AI tools', status: 'implemented' as const },
    { control: 'Purpose limitation', detail: 'Restrict information to each service according to its authorised purpose', status: 'implemented' as const },
    { control: 'Security evidence preservation', detail: 'Preserve sender details, URLs, scam wording and essential indicators', status: 'implemented' as const },
    { control: 'Image privacy', detail: 'On-device credential detection and blackout before an image is sent; personal details kept as evidence', status: 'implemented' as const },
    { control: 'Encryption', detail: 'Protect information transmitted and stored by application components', status: 'implemented' as const },
    { control: 'Access control', detail: 'Authenticate devices, isolate records and protect administrative endpoints', status: 'implemented' as const },
    { control: 'Retention and deletion', detail: 'Enforce temporary retention, expiry and deletion of application-managed records', status: 'implemented' as const },
    { control: 'Investigative integrity', detail: 'Validate evidence references, recommendations, uncertainty and completion claims', status: 'implemented' as const },
    { control: 'User choice and consent', detail: 'Privacy notices, permission controls and approval before relevant disclosure', status: 'implemented' as const },
    { control: 'Technical auditability', detail: 'Privacy-safe records of relevant processing and security decisions', status: 'implemented' as const },
  ],
  operationalItems: [
    { requirement: 'Formal privacy policy', appDoes: 'Display notices, obtain acknowledgements, offer privacy controls', outsideApp: 'Determine and approve legally adequate policy wording' },
    { requirement: 'Cross-border disclosure', appDoes: 'Minimise and authorise data leaving the device', outsideApp: 'Assess overseas processing and applicable legal obligations' },
    { requirement: 'Supplier management', appDoes: 'Restrict AI requests through an audited gateway', outsideApp: 'Evaluate supplier commitments and contractual terms' },
    { requirement: 'Incident response', appDoes: 'Detect incidents, record evidence, revoke access, delete data', outsideApp: 'Assign responsibilities, evaluate breaches, handle notifications' },
    { requirement: 'Bias and fairness', appDoes: 'Implement evidence-based decisions, run fairness regression tests', outsideApp: 'Approve the assessment and periodically review outcomes' },
    { requirement: 'Formal access and correction', appDoes: 'Provide access, correction and deletion capabilities', outsideApp: 'Handle formal requests, identity verification and exceptions' },
    { requirement: 'Organisational accountability', appDoes: 'Produce audit evidence and compliance reports', outsideApp: 'Assign accountable people and maintain governance' },
  ],
  testSummary: '344 tests passing (254 backend + 90 frontend). 12-point acceptance checklist verified.',
};
