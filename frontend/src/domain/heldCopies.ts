// ApolloSG's own copy of what was checked on this phone — the copied text, an email's body and headers, an .eml file and
// pictures — is kept until the person deletes it, the check, or all their data: no clock deletes it on the phone
// (owner's rule, 2026-11-01). The 24-hour rule is the server's only (backend services/held_copies.py), and the server
// waits for this phone to confirm it saved its own complete copy first (investigation/pickup.ts). This is ApolloSG's
// copy only: the message in Gmail, Messages or any other app is never touched. Pure: no React, unit-tested in node.

/** What the Evidence tab says where an earlier version of ApolloSG deleted this phone's copy of the original after 24
 *  hours (a rule since removed): when, why it can't be recovered, and where the person can still find the message.
 *  `when`: the deletion time, already worded for display. */
export function heldCopyDeletedNote(when: string | null): string {
  return `This phone's copy of the original was deleted${when ? ` on ${when}` : ""} by an earlier version of ApolloSG, under a `
    + "24-hour rule that has since been removed. ApolloSG's server no longer holds a copy either, so it can't be recovered. "
    + "The message in your own Messages or email app was never touched: you can check it again from there. "
    + "What Apollo found is kept above.";
}
