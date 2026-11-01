// ApolloSG's own copy of what was checked on this phone — the copied text, an email's body and headers, an .eml file and
// pictures — is kept until the person deletes it, the check, or all their data: no clock deletes it on the phone
// (owner's rule, 2026-11-01). The 24-hour rule is the server's only (backend services/held_copies.py), and the server
// waits for this phone to confirm it saved its own complete copy first (investigation/pickup.ts). This is ApolloSG's
// copy only: the message in Gmail, Messages or any other app is never touched. Pure: no React, unit-tested in node.

/** What the Evidence tab says where an earlier version of ApolloSG deleted its copy of the original after 24 hours. */
export const HELD_COPY_DELETED = "An earlier version of ApolloSG deleted its copy of the original 24 hours after it was checked. What Apollo found is kept above.";
