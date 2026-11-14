import { createInvestigationAudit } from "../domain/investigationAudit";
import { storage } from "../utils/storage";
import { getDeviceIdentity } from "../auth/deviceIdentity";
export const investigationAudit = createInvestigationAudit(storage, async () => (await getDeviceIdentity())?.deviceId ?? null);
