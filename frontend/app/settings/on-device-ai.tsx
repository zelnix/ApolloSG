// Settings > App > On-device AI models — the phone's built-in model, the downloadable fallback models for phones
// without one, and the model comparison testers use to choose between Qwen and Llama.
import { useRouter } from "expo-router";
import ChevronLeft from "lucide-react-native/icons/chevron-left";
import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import type { SlmNativeStatus } from "@/modules/apollo-slm";
import { InfoButton, type ScreenInfo } from "@/src/components/InfoButton";
import { Sheet } from "@/src/components/Sheet";
import { Body, Button, Card, SectionTitle } from "@/src/components/ui";
import { summaryLine } from "@/src/slm/benchmark";
import { runBenchmark, savedBenchmarks, type StoredBenchmark } from "@/src/slm/benchmarkRunner";
import { slmModelLabel } from "@/src/slm/core";
import { cancelFallbackDownload, deleteFallback, downloadFallback, fallbackOptions, installedFallback } from "@/src/slm/fallbackModel";
import { FIT_TEXT, formatBytes, MODEL_SOURCES, type FallbackModel, type ModelFit } from "@/src/slm/models";
import { APACHE_2_0_LICENSE, BUILT_WITH_LLAMA, LLAMA_3_2_LICENSE, LLAMA_3_2_NOTICE } from "@/src/slm/licences";
import { getSlmStatus } from "@/src/slm/onDeviceSlm";
import { fonts, makeStyles, spacing, useTheme } from "@/src/theme";
import { goBackOrHome } from "@/src/utils/navigation";

const INFO: ScreenInfo = { title: "About on-device AI models", body: [
  "Some newer phones have an AI model built in. ApolloSG uses it when it's there.",
  "Other phones can download a small model instead. It runs only on this phone: nothing you receive is sent anywhere, and it never changes Apollo's result.",
  "Downloads need Wi-Fi. Only one model is kept, and you can delete it at any time.",
] };

const FAIL_TEXT: Record<string, string> = {
  needs_wifi: "Connect to Wi-Fi to download this model.",
  checksum_mismatch: "The download didn't match the expected file, so it was deleted. Try again later.",
  download_failed: "The download didn't finish. Try again on a steady Wi-Fi connection.",
  ...FIT_TEXT,
};

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  top: { paddingHorizontal: spacing.xl, flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingBottom: spacing.md },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center", marginLeft: -spacing.sm },
  title: { flex: 1, fontFamily: fonts.displayBold, fontSize: 24, color: c.onSurface },
  content: { paddingHorizontal: spacing.xl, gap: spacing.lg },
  name: { fontFamily: fonts.textSemibold, fontSize: 16, color: c.onSurface },
  meta: { fontFamily: fonts.text, fontSize: 12, color: c.muted, marginTop: spacing.xs },
  credit: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface, marginTop: spacing.xs },
  licence: { fontFamily: fonts.text, fontSize: 12, color: c.onSurface, lineHeight: 18 },
  licenceLink: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.resting, marginTop: spacing.sm },
}));

export default function OnDeviceAiScreen() {
  const s = useStyles(); const insets = useSafeAreaInsets(); const router = useRouter(); const { colors } = useTheme();
  const [status, setStatus] = useState<SlmNativeStatus | null>(null);
  const [options, setOptions] = useState<Array<{ model: FallbackModel; fit: ModelFit }>>([]);
  const [installed, setInstalled] = useState<FallbackModel | null>(null);
  const [downloading, setDownloading] = useState<{ id: string; progress: number } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [bench, setBench] = useState<StoredBenchmark[]>([]);
  const [benchProgress, setBenchProgress] = useState<string | null>(null);
  const [licenceFor, setLicenceFor] = useState<FallbackModel | null>(null);

  const load = useCallback(async () => {
    setStatus(await getSlmStatus());
    setOptions(await fallbackOptions());
    setInstalled(await installedFallback());
    setBench(await savedBenchmarks());
  }, []);
  useEffect(() => { void load(); }, [load]);

  const download = async (m: FallbackModel) => {
    setMessage(null);
    setDownloading({ id: m.id, progress: 0 });
    const r = await downloadFallback(m.id, (p) => setDownloading({ id: m.id, progress: p }));
    setDownloading(null);
    if (r.kind === "failed") setMessage(FAIL_TEXT[r.reason] ?? "The model couldn't be downloaded.");
    await load();
  };

  const compare = async () => {
    setMessage(null);
    setBenchProgress("Starting…");
    const r = await runBenchmark((done, total) => setBenchProgress(`Running test ${done} of ${total}…`));
    setBenchProgress(null);
    if ("error" in r) setMessage(r.error);
    await load();
  };

  const builtInReady = status?.availability === "available";

  return <View style={s.root} testID="on-device-ai-screen">
    <View style={[s.top, { paddingTop: insets.top + spacing.md }]}>
      <Pressable accessibilityRole="button" accessibilityLabel="Back" testID="on-device-ai-back" onPress={() => goBackOrHome(router)} style={s.back}>
        <ChevronLeft size={24} color={colors.onSurface} />
      </Pressable>
      <Text style={s.title}>On-device AI models</Text>
      <InfoButton info={INFO} testID="on-device-ai-info" />
    </View>
    <ScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + spacing.xl }]} testID="on-device-ai-scroll">
      {message ? <Card testID="on-device-ai-message"><Body>{message}</Body></Card> : null}

      <SectionTitle>Built into this phone</SectionTitle>
      <Card testID="on-device-ai-builtin">
        {status ? <>
          <Text style={s.name}>{builtInReady ? slmModelLabel(status) : "None ready"}</Text>
          <Text style={s.meta}>{builtInReady ? "ApolloSG uses this one first." : "This phone has no built-in model ApolloSG can use. You can download one below."}</Text>
        </> : <ActivityIndicator />}
      </Card>

      <SectionTitle>Download a model</SectionTitle>
      {options.map(({ model, fit }) => {
        const source = MODEL_SOURCES[model.id];
        const isInstalled = installed?.id === model.id;
        const isDownloading = downloading?.id === model.id;
        return <Card key={model.id} testID={`on-device-ai-model-${model.id}`}>
          <Text style={s.name}>{model.label}</Text>
          <Text style={s.meta}>{`${formatBytes(source?.bytes ?? model.approxBytes)} · ${model.licence}`}</Text>
          {model.licenceText === "llama_3_2" ? <Text style={s.credit} testID={`on-device-ai-credit-${model.id}`}>{BUILT_WITH_LLAMA}</Text> : null}
          <Pressable accessibilityRole="button" onPress={() => setLicenceFor(model)} testID={`on-device-ai-licence-${model.id}`}>
            <Text style={s.licenceLink}>Read the licence</Text>
          </Pressable>
          {isInstalled ? <>
            <Body style={{ marginTop: spacing.sm }}>{builtInReady ? "Downloaded. The built-in model is used while it's ready." : "Downloaded and in use."}</Body>
            <Button testID={`on-device-ai-delete-${model.id}`} variant="ghost" label="Delete this model" onPress={() => void deleteFallback().then(load)} />
          </> : isDownloading ? <>
            <Body style={{ marginTop: spacing.sm }}>{`Downloading… ${Math.round((downloading?.progress ?? 0) * 100)}%`}</Body>
            <Button testID={`on-device-ai-cancel-${model.id}`} variant="ghost" label="Cancel" onPress={() => void cancelFallbackDownload().then(() => { setDownloading(null); return load(); })} />
          </> : fit.ok ? (
            <Button testID={`on-device-ai-download-${model.id}`} variant="secondary" label={installed ? "Download instead (replaces the current one)" : "Download (Wi-Fi)"} disabled={!!downloading} onPress={() => void download(model)} />
          ) : <Body style={{ marginTop: spacing.sm }}>{FIT_TEXT[fit.reason]}</Body>}
        </Card>;
      })}

      <SectionTitle>Compare models</SectionTitle>
      <Card testID="on-device-ai-compare">
        <Body>Runs the same made-up test messages through the model in use now and keeps its score here. Download another model and run it again to compare.</Body>
        {benchProgress ? <Body style={{ marginTop: spacing.sm }}>{benchProgress}</Body> : (
          <Button testID="on-device-ai-run-compare" variant="secondary" label="Run the comparison" disabled={!!downloading || (!builtInReady && !installed)} onPress={() => void compare()} />
        )}
        {bench.map((b) => <View key={b.model} style={{ marginTop: spacing.md }} testID="on-device-ai-score">
          <Text style={s.name}>{b.model}</Text>
          <Text style={s.meta}>{summaryLine(b)}</Text>
        </View>)}
      </Card>
    </ScrollView>
    <Sheet visible={!!licenceFor} onClose={() => setLicenceFor(null)} title={licenceFor ? `${licenceFor.label} licence` : "Licence"} testID="on-device-ai-licence-sheet">
      {licenceFor?.licenceText === "llama_3_2" ? <>
        <Text style={s.credit}>{BUILT_WITH_LLAMA}</Text>
        <Text style={[s.licence, { marginVertical: spacing.sm }]}>{LLAMA_3_2_NOTICE}</Text>
        <Text style={s.licence} selectable>{LLAMA_3_2_LICENSE}</Text>
      </> : <Text style={s.licence} selectable>{APACHE_2_0_LICENSE}</Text>}
    </Sheet>
  </View>;
}
