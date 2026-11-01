// This phone's copies of cases the person deleted (domain/caseDelete.ts): the original kept with each, its pictures,
// .eml files, report progress, the investigation result saved on this phone, its case link and email check entries.
// The Threats list itself is updated by ApolloContext.deleteCases; ApolloSG's server deletes its own copies.
import { forgetCase } from "@/src/investigation/caseIndex";
import { deleteInvestigation } from "@/src/investigation/deviceStore";
import { forgetEmailChecks } from "./emailCheckHistoryStore";
import { deleteImageEvidenceFor } from "./imageEvidence";
import { deleteOriginalEmailsFor } from "./originalEmail";
import { deleteOriginalSource } from "./originalSource";
import { deleteReportProgress } from "./reportProgress";

export async function deleteLocalCaseCopies(eventIds: string[], caseIds: string[]): Promise<void> {
  for (const key of [...eventIds, ...caseIds]) {
    await deleteOriginalSource(key).catch(() => undefined);
    await deleteImageEvidenceFor(key).catch(() => undefined);
    await deleteOriginalEmailsFor(key).catch(() => undefined);
    await deleteReportProgress(key).catch(() => undefined);
  }
  for (const caseId of caseIds) {
    await deleteInvestigation(caseId).catch(() => undefined);
    await forgetCase(caseId).catch(() => undefined);
  }
  await forgetEmailChecks(eventIds).catch(() => undefined);
}
