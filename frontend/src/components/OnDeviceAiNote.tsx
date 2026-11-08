/**
 * "On this phone" note under a message result: the on-device SLM's plain-language re-wording of Apollo's settled
 * result, and any request in the message the fixed rules didn't name (each with the message's own words).
 *
 * Shows nothing unless the person turned On-device AI on and the phone's model is ready. Never changes the result
 * above it, and says so. If the model fails or its answer is rejected, nothing is shown — Apollo's own wording above
 * is already complete.
 */
import React, { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { Body, Card } from "@/src/components/ui";
import { hintLine, slmModelLabel, type FixedSignalsView, type SettledResult, type SlmAdvisory, type SlmModelInfo } from "@/src/slm/core";
import { explainSettledResult, isSlmEnabled, preScreenMessage } from "@/src/slm/onDeviceSlm";
import { fonts, makeStyles, spacing } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  label: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.muted, marginBottom: spacing.xs },
  line: { marginTop: spacing.xs },
  foot: { fontFamily: fonts.text, fontSize: 12, color: c.muted, marginTop: spacing.sm },
  link: { fontFamily: fonts.textSemibold, color: c.resting, marginTop: spacing.sm },
}));

export function OnDeviceAiNote({ text, signals, settled, onFullCheck, testID = "on-device-ai-note" }: {
  text: string; signals: FixedSignalsView; settled: SettledResult; onFullCheck?: () => void; testID?: string;
}) {
  const s = useStyles();
  const [explanation, setExplanation] = useState<string | null>(null);
  const [advisory, setAdvisory] = useState<SlmAdvisory | null>(null);
  const [model, setModel] = useState<SlmModelInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (!(await isSlmEnabled())) return;
      // One call each, one after the other: the phone's model runs a single session at a time.
      const ex = await explainSettledResult(settled);
      if (!cancelled && ex.ok) { setExplanation(ex.value); setModel(ex.model); }
      const pre = await preScreenMessage(text, signals);
      if (!cancelled && pre.ok) { setAdvisory(pre.value); setModel(pre.model); }
    })();
    return () => { cancelled = true; };
    // Run once per checked message.
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!explanation && !advisory?.extra.length) return null;
  return (
    <Card testID={testID}>
      <Text style={s.label}>On this phone</Text>
      {explanation ? <Body testID={`${testID}-explanation`}>{explanation}</Body> : null}
      {advisory?.extra.length ? (
        <View testID={`${testID}-noticed`}>
          <Body style={s.line}>Also noticed in the message:</Body>
          {advisory.extra.map((h, i) => <Body key={i} style={s.line}>{`• ${hintLine(h)}`}</Body>)}
          {advisory.suggestFullCheck && onFullCheck ? (
            <Pressable accessibilityRole="button" onPress={onFullCheck} testID={`${testID}-full-check`}>
              <Text style={s.link}>Ask Higgins to look into this</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
      <Text style={s.foot}>Written by the AI built into this phone{model ? ` (${slmModelLabel(model)})` : ""}. Nothing left the phone, and Apollo&apos;s result above is unchanged.</Text>
    </Card>
  );
}
