// Export Patrol: one-tap PDF of the Patrol history (on-device render, shared via the system sheet).
// Full links are included only because this is the user's own device export, generated locally.
// Includes both PatrolEvents and the unified ActivityLog.

import * as Print from "expo-print";
import * as Sharing from "expo-sharing";
import { Platform } from "react-native";

import { STATE_LABEL, type PatrolEvent } from "@/src/domain/types";
import { exportActivities, type ActivityEntry } from "@/src/store/activityLog";

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
const COLOR: Record<PatrolEvent["state"], string> = { sniffing: "#52606D", resting: "#4FAF83", ears_up: "#F4B942", growling: "#E8943A", barking: "#D9534F", biting: "#D9534F" };

const OUTCOME_COLOR: Record<string, string> = { success: "#4FAF83", concern: "#D9534F", failure: "#D9534F", blocked: "#4FAF83", change: "#D4780A", baseline: "#52606D", restored: "#4FAF83" };

function activityRows(activities: ActivityEntry[]): string {
  return activities.map((a) => `
    <tr>
      <td style="white-space:nowrap">${esc(new Date(a.timestamp).toLocaleString())}</td>
      <td><span style="color:${OUTCOME_COLOR[a.outcome] ?? "#52606D"};font-weight:600">${esc(a.outcome)}</span><br><small>${esc(a.type)} · ${esc(a.actor)}</small></td>
      <td><strong>${esc(a.title)}</strong><br>${esc(a.detail)}${a.beforeValue && a.afterValue ? `<br><small>Changed: ${esc(a.beforeValue)} → ${esc(a.afterValue)}</small>` : ""}${a.expandedDetail ? `<br><small>${esc(a.expandedDetail)}</small>` : ""}</td>
      <td>${a.limitations?.length ? a.limitations.map(esc).join("<br>") : "—"}</td>
    </tr>`).join("");
}

export function patrolHtml(events: PatrolEvent[], deviceId: string | null, activities?: ActivityEntry[]): string {
  const rows = events.map((e) => `
    <tr>
      <td style="white-space:nowrap">${esc(new Date(e.occurred_at).toLocaleString())}</td>
      <td><span style="color:${COLOR[e.state]};font-weight:600">${esc(STATE_LABEL[e.state])}</span><br><small>${esc(e.status)}${e.verified_block ? " · block verified" : ""}</small></td>
      <td><strong>${esc(e.headline)}</strong><br>${esc(e.what_happened)}<br><small>${e.why.map(esc).join(" · ")}</small>${e.local_indicator ? `<br><code style="font-size:10px">${esc(e.local_indicator)}</code>` : e.indicator_host ? `<br><code>${esc(e.indicator_host)}</code>` : ""}</td>
      <td>${esc(e.what_to_do)}</td>
    </tr>`).join("");

  const actRows = activities?.length ? activityRows(activities) : "";
  const actSection = actRows ? `
    <h2 style="margin-top:24px">Activity Log</h2>
    <p class="meta">${activities!.length} activity record${activities!.length === 1 ? "" : "s"} (device changes, protection events, background checks).</p>
    <table><thead><tr><th>When</th><th>Outcome</th><th>What happened</th><th>Limitations</th></tr></thead><tbody>${actRows}</tbody></table>` : "";

  return `<html><head><meta charset="utf-8"><style>
    body{font-family:-apple-system,Helvetica,Arial,sans-serif;color:#111;padding:24px;font-size:12px}
    h1{margin:0 0 4px;font-size:22px} h2{margin:0 0 4px;font-size:18px} .meta{color:#666;margin-bottom:16px}
    table{width:100%;border-collapse:collapse} th,td{border-top:1px solid #ddd;padding:8px;vertical-align:top;text-align:left} th{background:#f3f5f8;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
    .legend{margin:12px 0 16px;color:#444}
  </style></head><body>
    <h1>Apollo Patrol history</h1>
    <div class="meta">Exported ${esc(new Date().toLocaleString())} · ${events.length} event${events.length === 1 ? "" : "s"}${activities?.length ? ` + ${activities.length} activity record${activities.length === 1 ? "" : "s"}` : ""} · Anonymous device ${esc(deviceId ? deviceId.slice(0, 8) : "n/a")}…</div>
    <div class="legend"><b>Patrolling</b> = no concern identified within completed checks · <b>Growling</b> = possible concern needing caution · <b>Barking</b> = significant concern needing attention · <b>Biting</b> = actual protective block confirmed. Protection availability is separate: use Gates to see what is automatic, manual or unavailable.</div>
    <table><thead><tr><th>When</th><th>Apollo state</th><th>What happened / why</th><th>What to do</th></tr></thead><tbody>${rows || "<tr><td colspan=4>No events.</td></tr>"}</tbody></table>
    ${actSection}
    <p class="meta" style="margin-top:16px">Generated on-device by ApolloSG. This document is a record of the app's observations and is not a forensic report.</p>
  </body></html>`;
}

export async function exportPatrolPdf(events: PatrolEvent[], deviceId: string | null): Promise<"shared" | "printed"> {
  const activities = await exportActivities();
  const html = patrolHtml(events, deviceId, activities);
  if (Platform.OS === "web") { await Print.printAsync({ html }); return "printed"; }
  const { uri } = await Print.printToFileAsync({ html });
  if (await Sharing.isAvailableAsync()) { await Sharing.shareAsync(uri, { mimeType: "application/pdf", dialogTitle: "Apollo Patrol history", UTI: "com.adobe.pdf" }); return "shared"; }
  await Print.printAsync({ uri }); return "printed";
}
