// Gate 6 — Check This File. Reads the file on this device: its signature and a text sample, and the whole file
// (at most 10 MB) to fingerprint it with SHA-256. Nothing is uploaded. URLs found inside are handed to Gate 3.
import * as DocumentPicker from "expo-document-picker";
import * as Crypto from "expo-crypto";
import * as FS from "expo-file-system/legacy";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import X from "lucide-react-native/icons/x";
import React, { useEffect, useRef, useState } from "react";
import { Platform, Pressable, Switch, Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { markCheckDone } from "@/src/store/checkCompletion";
import { CheckResultScreen } from "@/src/components/CheckResultScreen";
import { InvestigationCheckScreen } from "@/src/components/InvestigationCheckScreen";
import { RecoveryFlow } from "@/src/components/RecoveryFlow";
import { Body, Button, Card, SectionTitle } from "@/src/components/ui";
import { buildFileCheckResult } from "@/src/domain/fileCheckResultAdapter";
import { contextFromEvent, gateForCategory } from "@/src/domain/higginsHandoff";
import { analyseFile, FILE_SOURCES, type FileAnalysis, type FileSource } from "@/src/domain/fileAnalysis";
import { FILE_SIZE_LIMIT, FILE_SAMPLE_BYTES, inspectSample, type Inspection } from '@/src/domain/fileInspection';
import type { EvidenceProfile } from "@/src/domain/triage/evidenceProfile";
import { buildFileProfile, type FileVia } from "@/src/domain/triage/fileEvidence";
import { sha256Hex } from "@/src/store/originalEmail";
import { type PatrolEvent } from "@/src/domain/types";
import { SourceHero } from "@/src/components/SourceHero";
import { SourcePickerSheet } from "@/src/components/SourcePickerSheet";
import { findSampleFile } from "@/src/sampleChecks";
import { simulation } from "@/src/simulation";
import { useApollo } from "@/src/store/ApolloContext";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { goBackOrHome } from "@/src/utils/navigation";
import { InfoButton } from "@/src/components/InfoButton";
import { CheckToolHeader } from "@/src/components/CheckToolHeader";
import { getShareIntake } from "@/src/share/shareIntake";
import { disposePickerCopy, sweepPickerCopies } from '@/src/domain/fileCopyLifecycle';

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  top: { paddingHorizontal: spacing.xl, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 22, color: c.onSurface },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: c.surfaceTertiary },
  subtitle: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceSecondary, marginBottom: spacing.xs },
  content: { paddingHorizontal: spacing.xl, gap: spacing.lg },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { paddingVertical: spacing.sm, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1, borderColor: c.border },
  chipOn: { borderColor: c.brandPrimary, backgroundColor: c.restingTint },
  chipText: { fontFamily: fonts.textMedium, fontSize: 14, color: c.onSurface },
  input: { minHeight: 48, backgroundColor: c.surfaceTertiary, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, fontFamily: fonts.text, fontSize: 15, color: c.onSurface },
  verdict: { fontFamily: fonts.displayBold, fontSize: 20, lineHeight: 26, color: c.onSurface },
  why: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.md },
  passwordRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md },
}));

type FileAsset = { uri: string; name: string; mimeType?: string | null; size?: number };
/** What the check could read of the file — the file's evidence profile is built from it. */
type FileRead = { via: FileVia; simulated?: boolean; inspected: boolean; inspectionError?: string | null; sha256?: string | null; origin?: "sample_check" };
type PendingFile = { asset: FileAsset; inspected: Inspection; needsSource: boolean; needsPassword: boolean; sourceAnswered: boolean; owned: boolean; read: FileRead };

export default function CheckFile() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { ready, setupDone, upsertEvent, deviceId, adapterLabel } = useApollo();
  const [source, setSource] = useState<FileSource>("unknown");
  const [pw, setPw] = useState<boolean | null>(null);
  const [nameOnly, setNameOnly] = useState("");
  const [result, setResult] = useState<{ submissionId: string; a: FileAnalysis; event: PatrolEvent | null; profile: EvidenceProfile } | null>(null);
  const [busy, setBusy] = useState(false);
  const [pickerError, setPickerError] = useState<string | null>(null);
  const [filePicker, setFilePicker] = useState(false);
  const [selected, setSelected] = useState<{ asset: FileAsset; inspected: Inspection; realType: string; owned: boolean } | null>(null);
  const [pending, setPending] = useState<PendingFile | null>(null);
  // The temporary handle (an app-owned picker copy, or a shared-in URI we never own) is kept alive for the whole
  // screen visit — a later "Ask Higgins" upload needs the SAME bytes local inspection just read. It is disposed only
  // after durable publication, explicit reset, or the 15-minute expiry below. Never the user's original.
  const disposeSelection = (uri: string | null, owned: boolean) => { if (uri) disposePickerCopy(uri, owned); };
  useEffect(() => { sweepPickerCopies(); const timer = setInterval(sweepPickerCopies, 60000); return () => clearInterval(timer); }, []);
  useEffect(() => {
    if (!selected) return;
    const timer = setTimeout(() => { disposeSelection(selected.asset.uri, selected.owned); setSelected(null); setPending(null); setResult(null); setNameOnly(''); setPickerError('Temporary file evidence expired. Select the file again to continue.'); }, 15 * 60 * 1000);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.asset.uri]);
  // Navigation into Ask/Higgins intentionally does not dispose the picker copy. The shared case upload owns it until
  // durable publication (or the bounded expiry sweep), making backgrounding/navigation safe.

  const finish = async (a: FileAnalysis, file: { name: string; size?: number; mime?: string | null; passwordInMessage?: boolean }, read: FileRead) => {
    // Higgins Triage's classification of what ApolloSG could read of the file (name only → fingerprinted).
    const profile = buildFileProfile({ via: read.via, simulated: read.simulated, name: file.name, size: file.size ?? null, mime: file.mime ?? null, analysis: a,
      inspected: read.inspected, inspectionError: read.inspectionError ?? null, sha256: read.sha256 ?? null, passwordInMessage: file.passwordInMessage });
    let event: PatrolEvent | null = null;
    if (a.state !== "resting") {
      event = await upsertEvent({ event_id: Math.random().toString(36).slice(2) + Date.now().toString(36), origin: read.origin ?? "user", device_id: deviceId ?? "local", category: "known_threat", state: a.state, status: "active", headline: `File: ${a.title}`, what_happened: a.verdict, why: a.why, what_to_do: a.recommendation, indicator_host: a.urls[0] ? a.urls[0].replace(/^https?:\/\//i, "").split("/")[0] : null, indicator_digest: null, local_indicator: a.technical[0], verified_block: false, adapter_label: adapterLabel, occurred_at: new Date().toISOString(), resolved_at: null, trust_allowed: false, claimed_brand: null, scenario: a.scenario, evidence_profile: profile });
    }
    setResult({ submissionId: event?.event_id ?? Crypto.randomUUID(), a, event, profile });
    void markCheckDone("file");
  };
  const params = useLocalSearchParams<{ uri?: string; name?: string; mime?: string; size?: string; source?: string; sharedIntakeId?: string; sample?: string }>();
  const shared = getShareIntake(params.sharedIntakeId);
  const sharedFile = shared?.files?.[0];
  const incomingUri = sharedFile?.path || params.uri;
  useEffect(() => { if (!incomingUri && FILE_SOURCES.some((item) => item.id === params.source)) setSource(params.source as FileSource); }, [params.source, incomingUri]);
  // Preview only: a simulated file is written to a REAL temporary file so Apollo's own inspection
  // reads real bytes and runs the same check a picked file runs — no preview-only analysis path.
  const checkSimulatedFile = async (sim: { name: string; mime: string; content: string }) => {
    setPickerError(null);
    try {
      const size = sim.content.length;
      if (Platform.OS === "web") {
        const blob = new Blob([sim.content], { type: sim.mime });
        await analyseAsset({ uri: URL.createObjectURL(blob), name: sim.name, mimeType: sim.mime, size }, "unknown", false, "picked", true);
        return;
      }
      const targetUri = (FS.cacheDirectory ?? "") + sim.name;
      await FS.writeAsStringAsync(targetUri, sim.content, { encoding: FS.EncodingType.UTF8 });
      await analyseAsset({ uri: targetUri, name: sim.name, mimeType: sim.mime, size }, "unknown", true, "picked", true);
    } catch (error) {
      setPickerError(error instanceof Error ? error.message : "ApolloSG could not prepare the simulated file.");
    }
  };

  /** Sample Check: constructs controlled sample bytes and feeds them through the real file inspection.
   *  Provenance is "sample_check" — the file is not represented as genuinely selected from the device. */
  const checkSampleFile = async (sample: { name: string; mime: string; content: string }) => {
    setPickerError(null);
    try {
      const size = sample.content.length;
      if (Platform.OS === "web") {
        const blob = new Blob([sample.content], { type: sample.mime });
        await analyseAsset({ uri: URL.createObjectURL(blob), name: sample.name, mimeType: sample.mime, size }, "unknown", false, "picked", false, "sample_check");
        return;
      }
      const targetUri = (FS.cacheDirectory ?? "") + sample.name;
      await FS.writeAsStringAsync(targetUri, sample.content, { encoding: FS.EncodingType.UTF8 });
      await analyseAsset({ uri: targetUri, name: sample.name, mimeType: sample.mime, size }, "unknown", true, "picked", false, "sample_check");
    } catch (error) {
      setPickerError(error instanceof Error ? error.message : "ApolloSG could not prepare the sample file.");
    }
  };

  const pick = async () => {
    setPickerError(null);
    try {
      const res = await DocumentPicker.getDocumentAsync({ copyToCacheDirectory: true, multiple: false });
      if (res.canceled || !res.assets[0]) return;
      // The picker copy is owned by Apollo (it lives under our own cache directory) and stays alive past this local
      // check — an "Ask Higgins" upload for THIS same submission may still need it. It is disposed by the reset/
      // unmount/expiry handlers above, or by the 15-minute crash-recovery sweep, never eagerly right here.
      await analyseAsset(res.assets[0], "unknown", true);
    } catch (error) { setPickerError(error instanceof Error ? error.message : "ApolloSG could not open the file picker. Try again."); }
  };
  // Shared from another app (Share → Apollo): analyse the shared file straight away. This URI is never ours to delete.
  useEffect(() => { if (incomingUri && !result) { const incoming = FILE_SOURCES.some((item) => item.id === params.source) ? params.source as FileSource : "unknown"; setSource(incoming); void analyseAsset({ uri: incomingUri, name: sharedFile?.fileName ?? params.name ?? incomingUri.split("/").pop() ?? "shared file", mimeType: sharedFile?.mimeType ?? params.mime ?? null, size: sharedFile?.size ?? (params.size ? Number(params.size) : undefined) }, incoming, false, "shared"); } }, [incomingUri]); // eslint-disable-line react-hooks/exhaustive-deps
  // Sample Check: constructs sample bytes and feeds through the real file inspection pipeline.
  const sampleRan = useRef(false);
  useEffect(() => {
    if (!params.sample || !ready || !setupDone || sampleRan.current) return;
    const prodSample = findSampleFile(params.sample);
    if (!prodSample) return;
    sampleRan.current = true;
    void checkSampleFile(prodSample);
  }, [params.sample, ready, setupDone]); // eslint-disable-line react-hooks/exhaustive-deps
  const analyseAsset = async (asset: { uri: string; name: string; mimeType?: string | null; size?: number }, assetSource: FileSource = source, owned: boolean = false, via: FileVia = "picked", simulated = false, origin?: "sample_check") => {
    setBusy(true);
    try {
      // ── Hard size gate: reject oversized files BEFORE inspection ──
      if (asset.size != null && asset.size > FILE_SIZE_LIMIT) {
        throw new Error(`This file is ${Math.round(asset.size / (1024 * 1024))} MB — ApolloSG's limit is ${FILE_SIZE_LIMIT / (1024 * 1024)} MB. Choose a smaller file.`);
      }
      let inspected: Inspection = { headBytes: null, textSample: null };
      // The whole file is read on this device (at most 10 MB) so it can be fingerprinted (SHA-256); nothing is uploaded.
      let sha256: string | null = null;
      try {
        if (Platform.OS === "web") {
          const response = await fetch(asset.uri);
          const bytes = new Uint8Array(await response.arrayBuffer());
          if (!bytes.length || bytes.length > FILE_SIZE_LIMIT) throw new Error(`File is empty or exceeds the ${FILE_SIZE_LIMIT / (1024 * 1024)} MB limit.`);
          inspected = inspectSample(bytes);
          sha256 = await sha256Hex(bytes).catch(() => null);
        } else {
          // Native: read bytes via legacy expo-file-system
          const info = await FS.getInfoAsync(asset.uri);
          const fileSize = info.exists && !info.isDirectory ? (info.size ?? 0) : 0;
          if (fileSize <= 0 || fileSize > FILE_SIZE_LIMIT) throw new Error(`File is empty or exceeds the ${FILE_SIZE_LIMIT / (1024 * 1024)} MB limit.`);
          const b64 = await FS.readAsStringAsync(asset.uri, { encoding: FS.EncodingType.Base64 });
          const bin = atob(b64);
          const bytes = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          inspected = inspectSample(bytes.subarray(0, FILE_SAMPLE_BYTES));
          sha256 = await sha256Hex(bytes).catch(() => null);
        }
      } catch (innerErr) {
        // Re-throw size limit errors so they surface to the user
        if (innerErr instanceof Error && innerErr.message.includes("limit")) throw innerErr;
        inspected.inspectionError = 'This build could not read the file contents.';
      }
      const read: FileRead = { via, simulated, inspected: !!inspected.headBytes && inspected.headBytes.length >= 4 && !inspected.inspectionError, inspectionError: inspected.inspectionError ?? null, sha256, origin };
      const preliminary = analyseFile({ name: asset.name, size: asset.size ?? undefined, mime: asset.mimeType ?? null, ...inspected, source: assetSource, passwordInMessage: false });
      // The real, still-live handle is kept (never blanked) — Higgins needs it if the person later asks for a deeper,
      // explicitly-authorised cloud check. Filenames/size/mime travel as METADATA describing the file, never as a
      // substitute for its contents.
      const metadata: FileAsset = { name: asset.name, size: asset.size, mimeType: asset.mimeType, uri: asset.uri };
      setSelected({ asset: metadata, inspected, realType: preliminary.realType, owned });
      const extension = asset.name.toLowerCase().split(".").pop() ?? "";
      const needsPassword = ["zip", "rar", "7z"].includes(preliminary.realType) || ["zip", "rar", "7z"].includes(extension);
      const needsSource = (preliminary.state === "barking" || ["F01", "F03", "F04", "F13"].includes(preliminary.scenario)) && assetSource === "unknown";
      if (needsPassword || needsSource) setPending({ asset: metadata, inspected, needsSource, needsPassword, sourceAnswered: assetSource !== "unknown", owned, read });
      else await finish(preliminary, { name: asset.name, size: asset.size, mime: asset.mimeType ?? null }, read);
    } catch (e) { setPickerError(e instanceof Error ? e.message : "ApolloSG couldn't read that file. Choose it again or try another file."); } finally { setBusy(false); }
  };
  const completePending = async () => {
    if (!pending || (pending.needsSource && !pending.sourceAnswered) || (pending.needsPassword && pw === null)) return;
    setBusy(true);
    try { await finish(analyseFile({ name: pending.asset.name, size: pending.asset.size, mime: pending.asset.mimeType ?? null, ...pending.inspected, source, passwordInMessage: pw === true }), { name: pending.asset.name, size: pending.asset.size, mime: pending.asset.mimeType ?? null, passwordInMessage: pw === true }, pending.read); setPending(null); }
    catch (error) { setPickerError(error instanceof Error ? error.message : "ApolloSG couldn't finish this file check. Retry."); }
    finally { setBusy(false); }
  };
  const checkAnother = () => { disposeSelection(selected?.asset.uri ?? null, selected?.owned ?? false); setResult(null); setNameOnly(""); setSelected(null); setPending(null); setPickerError(null); setPw(null); setSource("unknown"); };

  if (ready && !setupDone) return <Redirect href="/" />;
  const a = result?.a;

  // UNIVERSAL CHECK RESULT — when the file check has produced an outcome, the entire screen
  // becomes the shared Check Result. ONE Higgins paragraph, ONE items list, ONE actions row.
  if (result && a) {
    const model = { ...buildFileCheckResult({ analysis: a, event: result.event, fileName: selected?.asset.name ?? (nameOnly || "file"), submissionId: result.submissionId }), evidenceProfile: result.event?.evidence_profile ?? result.profile };
    const askPrompt = `About the file I just checked (${model.subject}). ${model.headline} Can you walk me through what Apollo found and what I should do?`;
    const fileActions: { label: string; onPress: () => void; testID: string; variant?: "primary" | "secondary" | "ghost" }[] = [];
    if (a.handoff === "app") {
      fileActions.push({ testID: "file-check-app", variant: "secondary", label: "I installed it — check the app", onPress: () => router.push({ pathname: "/app-check", params: { name: a.technical[0].replace(/^Name: /, "").replace(/\.[^.]+$/, ""), source: source === "browser" ? "browser" : "message", scent: result.event?.scent_id ?? result.event?.event_id ?? "" } }) });
    }
    if (a.handoff === "network") {
      fileActions.push({ testID: "file-check-device", variant: "secondary", label: "I installed it — check my device", onPress: () => router.push("/device") });
    }
    if (a.urls.length) {
      a.urls.forEach((u, i) => {
        fileActions.push({ testID: `file-check-link-${i}`, variant: "ghost", label: `Check link: ${u.length > 40 ? u.slice(0, 40) + "\u2026" : u}`, onPress: () => router.push({ pathname: "/check", params: { url: u, source: "file" } }) });
      });
    }
    fileActions.push({ testID: "file-again", variant: "ghost", label: "Check another file", onPress: checkAnother });

    return (
      <>
        {result.event ? (
          <InvestigationCheckScreen
            result={model}
            investigationContext={contextFromEvent(result.event, gateForCategory(result.event.category))}
            investigationQuestion={askPrompt}
            submissionId={result.event.event_id}
            eventId={result.event.event_id}
            caseId={result.event.investigation_case_id ?? null}
            actions={fileActions}
          />
        ) : (
          <CheckResultScreen result={model} actions={fileActions} />
        )}
        {result.event ? (
          <RecoveryFlow event={result.event} kinds={["clicked", "app", "password", "card", "money", "download"]} testID="file-recovery" />
        ) : null}
      </>
    );
  }

  return (
    <View style={s.root}>
      <View style={[s.top, { paddingTop: insets.top + spacing.md }]}>
        <CheckToolHeader
          title="Check a file"
          info={{ title: "About file checking", body: ["Choose or describe a file and Apollo will check it for disguised programs, risky formats, macros and links inside.", "ApolloSG reads the file on this device — its real type from its first bytes, a sample of its contents, and a SHA-256 fingerprint of the whole file. Nothing is uploaded."] }}
          testID="file"
        />
      </View>
      <KeyboardAwareScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + spacing.xl }]} bottomOffset={24} testID="file-scroll">
        <SourceHero
          testID="file-hero"
          title="Pick a file from this device"
          caption="Apollo reads the file on this device — its signature, a sample of its contents and a fingerprint of the whole file. Nothing is uploaded."
          actions={[{
            testID: "file-pick",
            label: busy ? "Inspecting file…" : "Choose a file",
            disabled: busy,
            onPress: () => { if (simulation.included) { setFilePicker(true); return; } void pick(); },
          }]}
        />
        {pickerError ? <Card testID="file-picker-error" style={{ gap: spacing.sm }}><Body>{pickerError}</Body><Button testID="file-picker-retry" variant="secondary" label="Try choosing again" onPress={() => { if (simulation.included) { setFilePicker(true); return; } void pick(); }} disabled={busy} /></Card> : null}
        {selected ? <Card testID="file-evidence" style={{ gap: spacing.xs }}><SectionTitle>What Apollo inspected</SectionTitle><Body testID="file-evidence-name">Filename: {selected.asset.name}</Body><Body testID="file-evidence-size">Size: {selected.asset.size == null ? "not supplied" : `${selected.asset.size} bytes`}</Body><Body testID="file-evidence-mime">Supplied type: {selected.asset.mimeType || "unknown"}</Body><Body testID="file-evidence-signature">Signature result: {selected.realType}</Body><Body testID="file-evidence-sample">Content sample: {selected.inspected.inspectionError ? selected.inspected.inspectionError : selected.inspected.textSample ? "supported text was read locally" : "not readable or not present"}</Body></Card> : null}
        <Card testID="file-higgins-explanation" style={{ gap: spacing.xs }}><Body>Cloud hosting is not proof of safety — a harmful file hosted on a well-known service is still harmful. Apollo checks the file itself, not where it lives.</Body></Card>
            {pending?.needsSource && !pending.sourceAnswered ? <Card testID="file-source-followup" style={{ gap: spacing.sm }}><SectionTitle>One detail could change the advice</SectionTitle><Body>Where did this file come from? Choose “Not sure” if the source is unknown.</Body><View style={s.chips}>{FILE_SOURCES.map((o) => <Pressable key={o.id} testID={`file-source-${o.id}`} accessibilityRole="radio" accessibilityState={{ checked: source === o.id && pending.sourceAnswered }} aria-checked={source === o.id && pending.sourceAnswered} onPress={() => { setSource(o.id); setPending((current) => current ? { ...current, sourceAnswered: true } : current); }} style={[s.chip, source === o.id && pending.sourceAnswered && s.chipOn]}><Text style={s.chipText}>{o.label}</Text></Pressable>)}</View></Card> : null}
            {pending?.needsPassword && (!pending.needsSource || pending.sourceAnswered) ? <Card testID="file-password-followup" style={{ gap: spacing.sm }}><SectionTitle>One more detail</SectionTitle><View style={s.passwordRow}><Text style={[s.why, { flex: 1, flexShrink: 1 }]}>A password for this archive was supplied with it</Text><Switch style={{ flexShrink: 0 }} testID="file-pw" value={pw === true} onValueChange={(value) => setPw(value)} trackColor={{ true: colors.growling, false: colors.borderStrong }} thumbColor={colors.onSurface} /></View><Body testID="file-password-answer">{pw === null ? "Not answered yet" : pw ? "You reported that a password was supplied." : "You reported that no password was supplied."}</Body>{pw === null ? <Button testID="file-pw-no" variant="secondary" label="No password was supplied" onPress={() => setPw(false)} /> : null}</Card> : null}
            {pending ? <Button testID="file-finish-check" label={busy ? "Finishing check…" : "Finish file check"} onPress={() => void completePending()} disabled={busy || (pending.needsSource && !pending.sourceAnswered) || (pending.needsPassword && pw === null)} /> : null}
        {!pending && !selected ? <><SectionTitle>Limited alternative: filename only</SectionTitle><Body>A filename-only check cannot read the signature or content and cannot establish safety.</Body><TextInput testID="file-name" style={s.input} value={nameOnly} onChangeText={setNameOnly} placeholder="e.g. Statement.pdf.exe" placeholderTextColor={colors.muted} autoCapitalize="none" autoCorrect={false} /><Button testID="file-name-check" variant="secondary" label="Check filename only" onPress={() => void finish(analyseFile({ name: nameOnly.trim(), source: "unknown", passwordInMessage: false }), { name: nameOnly.trim() }, { via: "name_only", inspected: false })} disabled={!nameOnly.trim()} /></> : null}
      </KeyboardAwareScrollView>
      <SourcePickerSheet
        visible={filePicker}
        title="Your files"
        note="Each one is written to a real temporary file, so Apollo's inspection reads real bytes and runs the real file check."
        preview
        items={simulation.files.map((f) => ({ id: f.id, primary: f.name, secondary: f.mime, meta: f.probes }))}
        emptyText="There are no files to choose from here."
        onSelect={(id) => { setFilePicker(false); const f = simulation.files.find((x) => x.id === id); if (f) void checkSimulatedFile(f); }}
        onClose={() => setFilePicker(false)}
        testID="file-source-picker"
      />
    </View>
  );
}
