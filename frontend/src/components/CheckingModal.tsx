/**
 * CheckingModal — Shared checking overlay for all Check screens.
 * Shows a centered modal with spinner, title, subject, and description.
 */
import React from "react";
import { ActivityIndicator, Modal, Text, View } from "react-native";
import { makeStyles, fonts, radius, spacing, useTheme } from "@/src/theme";

interface CheckingModalProps {
  visible: boolean;
  /** e.g. "Checking link", "Checking number", "Checking message", "Checking email" */
  title: string;
  /** The URL, phone number, sender, etc. being checked */
  subject?: string;
  /** Optional secondary description */
  description?: string;
}

const useStyles = makeStyles(() => ({
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.xl,
  },
  card: {
    backgroundColor: "#FFFFFF",
    borderRadius: radius.xl,
    padding: spacing.xl * 1.5,
    alignItems: "center",
    gap: spacing.lg,
    width: "90%",
    maxWidth: 340,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.15,
    shadowRadius: 24,
    elevation: 12,
  },
  title: {
    fontFamily: fonts.displayBold,
    fontSize: 20,
    color: "#1A1A2E",
    textAlign: "center",
  },
  subject: {
    fontFamily: fonts.textSemibold,
    fontSize: 15,
    color: "#4A5568",
    textAlign: "center",
    maxWidth: 280,
  },
  description: {
    fontFamily: fonts.text,
    fontSize: 14,
    color: "#718096",
    textAlign: "center",
    lineHeight: 20,
  },
}));

export function CheckingModal({ visible, title, subject, description }: CheckingModalProps) {
  const s = useStyles();
  const { colors } = useTheme();

  return (
    <Modal visible={visible} transparent animationType="fade" statusBarTranslucent>
      <View style={s.overlay}>
        <View style={s.card}>
          <ActivityIndicator size="large" color={colors.brand} />
          <Text style={s.title}>{title}</Text>
          {subject ? (
            <Text style={s.subject} numberOfLines={2}>{subject}</Text>
          ) : null}
          <Text style={s.description}>
            {description || "Higgins Triage and TC Hawkeye are checking\nreputation data and scam patterns.\nThis usually takes a few seconds."}
          </Text>
        </View>
      </View>
    </Modal>
  );
}
