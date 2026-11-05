// One line under a finished result: when the pictures and files sent for it left Apollo's server. Read from this
// phone's saved record, or from the live case before it is saved.
import React, { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { serverCopyNote, serverLeavesBy } from "@/src/domain/serverCopyNote";
import { getInvestigation, subscribeDeviceInvestigations, type DeviceInvestigation } from "@/src/investigation/deviceStore";
import type { InvestigationCase } from "@/src/investigation/types";
import { fonts, makeStyles, spacing } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  wrap: { minHeight: 44, justifyContent: "center", paddingVertical: spacing.xs },
  text: { fontFamily: fonts.text, fontSize: 13, lineHeight: 19, color: c.onSurfaceSecondary },
}));

export function ServerCopyNote({ caseId, live, testID = "server-copy-note" }: {
  caseId: string | null | undefined;
  /** The live case, used until the result is saved on this device. */
  live?: InvestigationCase | null;
  testID?: string;
}) {
  const s = useStyles();
  const [saved, setSaved] = useState<DeviceInvestigation | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!caseId) return;
    let active = true;
    const load = () => {
      void getInvestigation(caseId).then((record) => { if (active) { setSaved(record); setNow(Date.now()); } }).catch(() => undefined);
    };
    load();
    const unsubscribe = subscribeDeviceInvestigations(load);
    return () => { active = false; unsubscribe(); };
  }, [caseId]);

  const note = saved ? serverCopyNote(saved.serverCopy, saved.completedAt, now)
    // A result reopened from this phone carries no server deadline of its own, so only a live case is used.
    : live && live.retentionClass !== "device_local" ? serverCopyNote({ removedAt: null, leavesBy: serverLeavesBy(live) }, live.updatedAt, now)
    : null;
  if (!note) return null;
  return (
    <View accessibilityRole="text" testID={testID} style={s.wrap}>
      <Text style={s.text}>{note}</Text>
    </View>
  );
}
