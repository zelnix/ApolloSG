// About Apollo — a scrollable popup describing Apollo, the 10 Gates, Higgins, privacy and the free-forever promise.
// Opened from Settings → Help & about → About Apollo. Pure presentation; copy is provided by Harmony Wellness Group.
import { Image } from "expo-image";
import React from "react";
import { Text, View } from "react-native";

import { HigginsAvatar } from "@/src/components/HigginsAvatar";
import { fonts, makeStyles, radius, spacing } from "@/src/theme";
import { Sheet } from "./Sheet";
import { BUILT_WITH_LLAMA } from "@/src/slm/licences";

const GATES = ["Website", "Link", "Message", "Call", "Email", "File", "App", "Device", "Internet", "Account"];

const useStyles = makeStyles((c) => ({
  hero: { width: "100%", aspectRatio: 900 / 1124, borderRadius: radius.lg, backgroundColor: c.navyTint, marginBottom: spacing.xs },
  tagline: { fontFamily: fonts.displayBold, fontSize: 20, color: c.onSurface, textAlign: "center" },
  taglineSub: { fontFamily: fonts.textMedium, fontSize: 15, color: c.onSurfaceSecondary, textAlign: "center", marginBottom: spacing.sm },
  heading: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface, marginTop: spacing.md },
  subHeading: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface, marginTop: spacing.sm },
  body: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceSecondary },
  bullet: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceSecondary, paddingLeft: spacing.md },
  gatesWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginTop: spacing.xs },
  gateChip: { paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: c.navyTint, borderWidth: 1, borderColor: c.navyBorder },
  gateChipText: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurface },
  higginsRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginTop: spacing.sm },
  higginsFace: { borderWidth: 2, borderColor: c.goldBorder },
  higginsName: { fontFamily: fonts.displayBold, fontSize: 16, color: c.onSurface },
  higginsRole: { fontFamily: fonts.text, fontSize: 13, color: c.onSurfaceSecondary },
  portrait: { width: "100%", aspectRatio: 900 / 1080, borderRadius: radius.lg, backgroundColor: c.navyTint, marginTop: spacing.sm },
  divider: { height: 1, backgroundColor: c.divider, marginVertical: spacing.sm },
  closing: { fontFamily: fonts.displayBold, fontSize: 15, color: c.onSurface, textAlign: "center", marginTop: spacing.md },
  credit: { fontFamily: fonts.text, fontSize: 13, color: c.muted, textAlign: "center" },
}));

export function AboutApolloSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const s = useStyles();
  return (
    <Sheet visible={visible} onClose={onClose} title="About ApolloSG" testID="about-apollo-sheet">
      <Image source={require("../../assets/images/higgins-apollo-full.png")} style={s.hero} contentFit="cover" accessibilityLabel="Apollo with Higgins" />
      <Text style={s.tagline}>Meet Apollo 🐾</Text>
      <Text style={s.taglineSub}>ApolloSG</Text>
      <Text style={s.body}>Apollo helps protect you from online scams, suspicious activity and cyber threats.</Text>

      <Text style={s.heading}>🛡️ Apollo&apos;s 10 Protections</Text>
      <View style={s.gatesWrap}>
        {GATES.map((g) => <View key={g} style={s.gateChip}><Text style={s.gateChipText}>{g}</Text></View>)}
      </View>
      <Text style={[s.body, { marginTop: spacing.sm }]}>Each protection helps guard a different part of your digital life, with automatic monitoring or manual checks depending on your device and its capabilities.</Text>

      <Text style={s.heading}>🚨 Scam Alerts &amp; Education</Text>
      <Text style={s.body}>Stay informed about emerging scams and learn how to recognise warning signs, avoid common tricks and protect yourself and your family.</Text>

      <Text style={s.heading}>💬 Social Media &amp; Messaging Protection</Text>
      <Text style={s.body}>Apollo helps protect you from online scams, phishing links and known malicious websites encountered through social media and messaging platforms, including Facebook, Instagram, TikTok, X, Messenger, WhatsApp, Snapchat and others.</Text>
      <Text style={[s.body, { marginTop: spacing.sm }]}>Protection is provided through ApolloSG&apos;s existing security capabilities, depending on your device and its capabilities.</Text>

      <Text style={s.heading}>👨‍💼 Meet Higgins</Text>
      <View style={s.higginsRow}>
        <HigginsAvatar size={72} style={s.higginsFace} />
        <View style={{ flex: 1 }}>
          <Text style={s.higginsName}>Albert Higginstien (Higgins)</Text>
          <Text style={s.higginsRole}>Apollo&apos;s trusted handler</Text>
        </View>
      </View>
      <Text style={[s.body, { marginTop: spacing.sm }]}>Higgins explains what Apollo discovers in everyday language and guides you through anything that needs your attention.</Text>
      <Image source={require("../../assets/images/higgins-apollo-portrait.png")} style={s.portrait} contentFit="cover" accessibilityLabel="Higgins with Apollo" />
      <Text style={[s.body, { marginTop: spacing.sm }]}>Together, Apollo and Higgins make cyber security easier to understand and manage on all your devices.</Text>

      <View style={s.divider} />
      <Text style={s.heading}>🔒 Your Privacy &amp; Data</Text>
      <Text style={[s.body, { fontFamily: fonts.textSemibold, color: undefined }]}>No account. No login. No passwords required.</Text>
      <Text style={s.body}>ApolloSG uses a randomly generated device identifier rather than requiring you to create an account.</Text>

      <Text style={s.subHeading}>Where is information stored?</Text>
      <Text style={s.body}>Routine protection information and preferences can be kept on your device. Some security checks and Higgins conversations require secure online processing.</Text>

      <Text style={s.subHeading}>How long is information kept?</Text>
      <Text style={s.bullet}>• Security investigations: Temporary copies are cleared when processing finishes, with a maximum lifetime of 15 minutes in Apollo-controlled temporary storage.</Text>
      <Text style={s.bullet}>• Higgins conversations: The defined policy is encrypted storage on your device, cleared after one hour of inactivity. Server-side conversation content is limited to processing and a five-minute recovery period.</Text>
      <Text style={s.bullet}>• Patrol history and reports: Limited security findings and summaries may be stored for later reference. Original submitted material is not intended to form part of these records.</Text>
      <Text style={s.bullet}>• Deletion: You can clear your history. However, some server records may remain after being hidden or marked deleted. A guaranteed permanent-deletion timeframe has not yet been established.</Text>

      <Text style={s.subHeading}>What about external services?</Text>
      <Text style={s.body}>When required, approved analysis and security services may process submitted information. Their data handling and retention periods are governed by their own applicable terms and may differ from ApolloSG&apos;s limits.</Text>
      <Text style={[s.body, { marginTop: spacing.xs }]}>For more information, see Privacy Disclosure in Settings.</Text>

      <Text style={s.subHeading}>On-device AI</Text>
      <Text style={s.body}>Optional, and off unless you turn it on. It runs on your phone only. Phones without a built-in model can download Qwen 2.5 (Apache License 2.0) or Llama 3.2 ({BUILT_WITH_LLAMA}). Licences are in Settings → On-device AI models.</Text>

      <View style={s.divider} />
      <Text style={s.heading}>💙 Free Forever</Text>
      <Text style={s.body}>ApolloSG is 100% free, with no subscriptions, advertising or hidden costs.</Text>
      <Text style={s.body}>Voluntary donations help keep ApolloSG free and accessible to everyone.</Text>

      <Text style={s.closing}>Smart protection. Simple explanations. Peace of mind.</Text>
      <Text style={s.credit}>Created by Harmony Wellness Group.</Text>
    </Sheet>
  );
}
