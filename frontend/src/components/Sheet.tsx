// Lightweight bottom sheet built on Modal (no extra native deps).

import React from "react";
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { fonts, makeStyles, radius, spacing } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  backdrop: { flex: 1, backgroundColor: c.scrim, justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surfaceSecondary, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, borderWidth: 1, borderColor: c.border, maxHeight: "88%" },
  handle: { alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: c.borderStrong, marginTop: spacing.md },
  title: { fontFamily: fonts.display, fontSize: 20, color: c.onSurface, paddingHorizontal: spacing.xl, paddingTop: spacing.lg },
  content: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, gap: spacing.md },
  // A pinned footer keeps the action that completes the sheet in view, however long the form is.
  footer: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, gap: spacing.sm, borderTopWidth: 1, borderTopColor: c.border, backgroundColor: c.surfaceSecondary },
}));

export function Sheet({ visible, onClose, title, children, testID, scrollRef, footer }: { visible: boolean; onClose: () => void; title: string; children: React.ReactNode; testID?: string; scrollRef?: React.RefObject<ScrollView | null>; footer?: React.ReactNode }) {
  const s = useStyles();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        keyboardVerticalOffset={Platform.OS === "ios" ? 0 : 0}
      >
        <View style={s.backdrop}>
          <Pressable style={{ flex: 1 }} onPress={onClose} testID="sheet-backdrop" accessibilityLabel="Close" />
          <View style={s.sheet} testID={testID}>
            <View style={s.handle} />
            <Text style={s.title}>{title}</Text>
            <ScrollView ref={scrollRef} contentContainerStyle={[s.content, { paddingBottom: footer ? spacing.lg : insets.bottom + spacing.xl }]} keyboardShouldPersistTaps="handled" nestedScrollEnabled>{children}</ScrollView>
            {footer ? <View style={[s.footer, { paddingBottom: insets.bottom + spacing.md }]} testID={testID ? `${testID}-footer` : undefined}>{footer}</View> : null}
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}
