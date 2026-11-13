import { fetchEvidenceContent } from "@/src/investigation/evidenceContent";
// EvidencePopup — Full-screen modal for the Evidentiary Chain.
// Two sections: A. Evidence (display actual content) · B. Evidence Details (metadata).
// Supports images, text, URLs, documents. Mobile-friendly, accessible, dismissable.

import React, { useEffect, useState } from "react";
import X from "lucide-react-native/icons/x";
import { ActivityIndicator, Image, Modal, Pressable, ScrollView, Text, View } from "react-native";
import Animated, { FadeIn, SlideInUp } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { Body, Button, Pill } from "@/src/components/ui";
import type { EvidenceItem } from "@/src/investigation/types";
import * as investigationApi from "@/src/investigation/client";
import { getDeviceToken } from "@/src/auth/deviceIdentity";

const useStyles = makeStyles((c) => ({
  backdrop: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, backgroundColor: c.surfaceSecondary, borderBottomWidth: 1, borderBottomColor: c.border },
  headerTitle: { fontFamily: fonts.display, fontSize: 18, color: c.onSurface, flex: 1 },
  closeBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  content: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg, gap: spacing.lg },
  sectionTitle: { fontFamily: fonts.textMedium, fontSize: 16, color: c.onSurface, marginBottom: spacing.xs },
  sectionSubtitle: { fontFamily: fonts.text, fontSize: 13, color: c.muted, marginBottom: spacing.sm },
  card: { backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, borderWidth: 0.25, borderColor: c.border, gap: spacing.sm },
  imageContainer: { borderRadius: radius.sm, overflow: "hidden", alignItems: "center", backgroundColor: c.surfaceTertiary },
  evidenceImage: { width: "100%", aspectRatio: 4 / 3 },
  textContent: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurface },
  metaRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: c.border },
  metaLabel: { fontFamily: fonts.textMedium, fontSize: 13, color: c.muted, flex: 1 },
  metaValue: { fontFamily: fonts.text, fontSize: 13, color: c.onSurface, flex: 2, textAlign: "right" },
  hashText: { fontFamily: fonts.text, fontSize: 11, color: c.muted, flex: 2, textAlign: "right" },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  transformationRow: { paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: c.border },
  transformLabel: { fontFamily: fonts.textMedium, fontSize: 12, color: c.onSurfaceSecondary },
  transformDesc: { fontFamily: fonts.text, fontSize: 12, color: c.muted },
  unavailable: { alignItems: "center", justifyContent: "center", padding: spacing.xl, backgroundColor: c.surfaceTertiary, borderRadius: radius.md },
  unavailableText: { fontFamily: fonts.text, fontSize: 14, color: c.muted, textAlign: "center" },
}));

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

function kindLabel(kind: string): string {
  const labels: Record<string, string> = {
    text: "Text", url: "URL / Website", image: "Image", document: "Document",
    observation: "Device Observation", audio: "Audio", attachment: "Attachment", file: "File",
  };
  return labels[kind] || kind;
}

function originLabel(origin: string): string {
  const labels: Record<string, string> = {
    user_submission: "User submitted", device_observation: "Device observation",
    external_source: "External source", apollo_inference: "Apollo analysis",
  };
  return labels[origin] || origin;
}

interface Props {
  visible: boolean;
  onClose: () => void;
  caseId: string;
  /** Show a specific item, or null for the full evidence list */
  focusEvidenceId: string | null;
  /** Pre-loaded evidence items (optional — will fetch if not provided) */
  items?: EvidenceItem[];
}

export function EvidencePopup({ visible, onClose, caseId, focusEvidenceId, items: propItems }: Props) {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [items, setItems] = useState<EvidenceItem[]>(propItems || []);
  const [loading, setLoading] = useState(!propItems);
  const [imageUri, setImageUri] = useState<string | null>(null);
  const [imageLoading, setImageLoading] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(focusEvidenceId);

  useEffect(() => { setSelectedId(focusEvidenceId); }, [focusEvidenceId]);

  useEffect(() => {
    if (!visible) return;
    if (propItems) { setItems(propItems); setLoading(false); return; }
    setLoading(true);
    investigationApi.listEvidence(caseId)
      .then((res) => { setItems(res.items); setLoading(false); })
      .catch(() => setLoading(false));
  }, [visible, caseId, propItems]);

  // Load content for selected evidence item with proper authentication
  useEffect(() => {
    if (!selectedId || !visible) return;
    const item = items.find((i) => i.id === selectedId);
    if (!item) return;
    setImageUri(null);
    setImageError(null);
    setImageLoading(false);
    setTextContent(null);

    if (item.availability !== "available" && item.availability !== "content_expired") return;
    if (item.kind === "image") {
      // Fetch image bytes with auth token, convert to base64 data URI
      setImageLoading(true);
      getDeviceToken().then(async (token) => {
        if (!token) { setImageError("Authentication required"); setImageLoading(false); return; }
        try {
          const res = await fetchEvidenceContent(caseId, item.id);
          if (!res.ok) {
            if (res.status === 410) { setImageError("This evidence has expired and is no longer available."); }
            else if (res.status === 404) { setImageError("Evidence not found. It may belong to a different investigation."); }
            else { setImageError(`Could not load evidence image (${res.status}).`); }
            setImageLoading(false);
            return;
          }
          const blob = await res.blob();
          const reader = new FileReader();
          reader.onloadend = () => {
            const dataUri = reader.result as string;
            setImageUri(dataUri);
            setImageLoading(false);
          };
          reader.onerror = () => { setImageError("Failed to process the evidence image."); setImageLoading(false); };
          reader.readAsDataURL(blob);
        } catch {
          setImageError("Could not connect to load evidence. Check your connection.");
          setImageLoading(false);
        }
      });
    } else if (item.kind === "text" || item.kind === "url") {
      getDeviceToken().then((token) => {
        if (!token) return;
        fetchEvidenceContent(caseId, item.id)
          .then((r) => {
            if (!r.ok) throw new Error(`${r.status}`);
            return r.text();
          })
          .then((text) => setTextContent(text))
          .catch(() => setTextContent("[Content could not be loaded]"));
      });
    }
  }, [selectedId, items, visible, caseId]);

  const selected = selectedId ? items.find((i) => i.id === selectedId) : null;
  const title = selected ? `Evidence ${selected.displayId || selected.id.slice(0, 8)}` : "Evidentiary Chain";

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="fullScreen" onRequestClose={onClose}>
      <Animated.View entering={FadeIn} style={[s.backdrop, { paddingTop: insets.top }]} testID="evidence-popup">
        {/* Header */}
        <View style={s.header}>
          <Text style={s.headerTitle}>{title}</Text>
          <Pressable onPress={onClose} hitSlop={16} style={s.closeBtn} testID="evidence-popup-close" accessibilityRole="button" accessibilityLabel="Close evidence">
            <X size={22} color={colors.onSurface} />
          </Pressable>
        </View>

        {loading ? (
          <View style={{ flex: 1, justifyContent: "center", alignItems: "center" }}>
            <ActivityIndicator color={colors.gold} size="large" />
            <Body style={{ marginTop: spacing.md }}>Loading evidence…</Body>
          </View>
        ) : selected ? (
          /* Single evidence item view */
          <ScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + spacing.xl }]} keyboardShouldPersistTaps="handled">
            {/* Navigation back to list */}
            {items.length > 1 && (
              <Button variant="ghost" label={`← All evidence (${items.length})`}
                onPress={() => setSelectedId(null)} testID="evidence-back-to-list" />
            )}

            {/* Section A: Evidence */}
            <Text style={s.sectionTitle}>Evidence</Text>
            <View style={s.card}>
              <View style={s.pillRow}>
                <Pill tone="neutral" label={kindLabel(selected.kind)} />
                {selected.displayId ? <Pill tone="neutral" label={selected.displayId} /> : null}
              </View>
              {selected.label ? <Text style={s.textContent}>{selected.label}</Text> : null}

              {/* Image evidence — authenticated fetch → base64 data URI */}
              {selected.kind === "image" && imageLoading ? (
                <View style={[s.imageContainer, { padding: spacing.xl }]}>
                  <ActivityIndicator color={colors.gold} size="large" />
                  <Body style={{ marginTop: spacing.sm }}>Loading evidence image…</Body>
                </View>
              ) : selected.kind === "image" && imageError ? (
                <View style={[s.unavailable, { backgroundColor: colors.surfaceTertiary }]}>
                  <Text style={s.unavailableText}>{imageError}</Text>
                </View>
              ) : selected.kind === "image" && imageUri ? (
                <View style={s.imageContainer}>
                  <Image source={{ uri: imageUri }} style={s.evidenceImage} resizeMode="contain" testID="evidence-image"
                    accessibilityLabel={`Evidence ${selected.displayId || selected.id}: ${selected.label || "Investigated image"}`} />
                </View>
              ) : null}

              {/* Text / URL evidence */}
              {(selected.kind === "text" || selected.kind === "url") && textContent ? (
                <View style={{ backgroundColor: colors.surfaceTertiary, borderRadius: radius.sm, padding: spacing.md }}>
                  <Text style={[s.textContent, { fontSize: 13 }]} selectable testID="evidence-text-content">{textContent}</Text>
                </View>
              ) : null}

              {/* Unavailable or expired evidence */}
              {selected.availability === "content_expired" ? (
                <View style={[s.unavailable, { backgroundColor: colors.surfaceTertiary }]}>
                  <Text style={[s.unavailableText, { fontFamily: fonts.textMedium }]}>Server copy deleted</Text>
                  <Text style={[s.unavailableText, { marginTop: spacing.xs }]}>
                    ApolloSG&apos;s server copy of this evidence was deleted after 24 hours to protect your privacy.
                    Your copy on this device is kept until you delete it, and the investigation findings remain in your saved report.
                  </Text>
                  {selected.collectedAt ? (
                    <Text style={[s.unavailableText, { marginTop: spacing.xs, fontSize: 12 }]}>
                      Acquired: {formatDate(selected.collectedAt)} · Server copy deleted: {formatDate(selected.expiresAt)}
                    </Text>
                  ) : null}
                </View>
              ) : selected.availability !== "available" ? (
                <View style={s.unavailable}>
                  <Text style={s.unavailableText}>
                    {selected.availability === "purged" ? "ApolloSG's server copy was deleted after its retention period. Your copy on this device is kept until you delete it."
                      : selected.availability === "permission_required" ? "Access to this evidence requires additional permissions."
                      : "Evidence content is not currently available."}
                  </Text>
                </View>
              ) : null}
            </View>

            {/* Section B: Evidence Details */}
            <Text style={s.sectionTitle}>Evidence Details</Text>
            <View style={s.card}>
              <MetaRow label="Evidence ID" value={selected.displayId || selected.id.slice(0, 12)} s={s} />
              <MetaRow label="Case ID" value={selected.caseId.slice(0, 12)} s={s} />
              <MetaRow label="Type" value={kindLabel(selected.kind)} s={s} />
              <MetaRow label="Source" value={originLabel(selected.origin)} s={s} />
              {selected.provenance?.sourceDescription ? (
                <MetaRow label="Acquisition" value={selected.provenance.sourceDescription} s={s} />
              ) : null}
              {selected.provenance?.acquisitionMethod ? (
                <MetaRow label="Method" value={selected.provenance.acquisitionMethod.replace(/_/g, " ")} s={s} />
              ) : null}
              <MetaRow label="Collected" value={selected.collectedAt ? formatDate(selected.collectedAt) : formatDate(selected.expiresAt)} s={s} />
              {selected.expiresAt ? <MetaRow label="Server copy deleted" value={formatDate(selected.expiresAt)} s={s} /> : null}
              {selected.availability === "content_expired" ? <MetaRow label="Status" value="Server copy deleted (24h). Device copy kept." s={s} /> : null}
              {selected.mediaType ? <MetaRow label="Media type" value={selected.mediaType} s={s} /> : null}
              {selected.byteLength ? <MetaRow label="Size" value={formatBytes(selected.byteLength)} s={s} /> : null}

              {/* Integrity hash */}
              {selected.integrityHash ? (
                <View style={s.metaRow}>
                  <Text style={s.metaLabel}>Integrity (SHA-256)</Text>
                  <Text style={s.hashText} selectable numberOfLines={2}>{selected.integrityHash}</Text>
                </View>
              ) : null}

              {/* Coverage */}
              <MetaRow label="Examination"
                value={`${selected.coverage.examined} of ${selected.coverage.total} ${selected.coverage.unit} examined`} s={s} />

              {/* Transformations */}
              {selected.transformations && selected.transformations.length > 0 ? (
                <>
                  <Text style={[s.metaLabel, { marginTop: spacing.xs }]}>Processing history</Text>
                  {selected.transformations.map((t, i) => (
                    <View key={i} style={s.transformationRow}>
                      <Text style={s.transformLabel}>{t.kind.replace(/_/g, " ")}</Text>
                      <Text style={s.transformDesc}>{t.description}</Text>
                    </View>
                  ))}
                </>
              ) : null}
            </View>
          </ScrollView>
        ) : (
          /* Evidence list view */
          <ScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + spacing.xl }]} keyboardShouldPersistTaps="handled">
            <Text style={s.sectionTitle}>Evidentiary Chain</Text>
            <Text style={s.sectionSubtitle}>{items.length} evidence item{items.length !== 1 ? "s" : ""} in this investigation</Text>
            {items.map((item) => (
              <Pressable key={item.id} onPress={() => setSelectedId(item.id)}
                style={s.card} testID={`evidence-list-item-${item.displayId || item.id}`}
                accessibilityLabel={`View evidence ${item.displayId || item.id}`}>
                <View style={[s.pillRow, { marginBottom: spacing.xs }]}>
                  {item.displayId ? <Pill tone="neutral" label={item.displayId} /> : null}
                  <Pill tone="neutral" label={kindLabel(item.kind)} />
                  <Pill tone={item.availability === "available" ? "resting" : "growling"} label={item.availability} />
                </View>
                <Text style={s.textContent} numberOfLines={2}>{item.label || `${kindLabel(item.kind)} evidence`}</Text>
                <Text style={[s.metaLabel, { fontSize: 12 }]}>{originLabel(item.origin)}{item.integrityHash ? " · Integrity verified" : ""}</Text>
              </Pressable>
            ))}
            {items.length === 0 ? (
              <View style={s.unavailable}><Text style={s.unavailableText}>No evidence items found for this investigation.</Text></View>
            ) : null}
          </ScrollView>
        )}
      </Animated.View>
    </Modal>
  );
}

function MetaRow({ label, value, s }: { label: string; value: string; s: ReturnType<typeof useStyles> }) {
  return (
    <View style={s.metaRow}>
      <Text style={s.metaLabel}>{label}</Text>
      <Text style={s.metaValue}>{value}</Text>
    </View>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
