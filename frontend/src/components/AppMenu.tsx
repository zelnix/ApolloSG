// The hamburger menu: always the last (far-right) icon in a full screen's header. It hides itself on
// pop-up routes (see src/navigation/modalRoutes), and screens closed with an X don't include it.
import { useRouter, useSegments } from "expo-router";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import FlaskConical from "lucide-react-native/icons/flask-conical";
import HelpCircle from "lucide-react-native/icons/life-buoy";
import Info from "lucide-react-native/icons/info";
import ListChecks from "lucide-react-native/icons/list-checks";
import Lock from "lucide-react-native/icons/lock";
import Menu from "lucide-react-native/icons/menu";
import Settings from "lucide-react-native/icons/settings";
import X from "lucide-react-native/icons/x";
import React, { useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { isPopupRoute } from "@/src/navigation/modalRoutes";
import { fonts, makeStyles, spacing, useTheme } from "@/src/theme";

const ITEMS = [
  { label: "Sample checks", icon: FlaskConical, route: "/sample-checks", testID: "menu-sample-checks" },
  { label: "Settings", icon: Settings, route: "/(tabs)/settings", testID: "menu-settings" },
  { label: "About ApolloSG", icon: Info, route: "/about", testID: "menu-about" },
  { label: "How Apollo checks", icon: ListChecks, route: "/how-apollo-checks", testID: "menu-how-apollo-checks" },
  { label: "Privacy", icon: Lock, route: "/privacy", testID: "menu-privacy" },
  { label: "Support", icon: HelpCircle, route: "/support", testID: "menu-support" },
] as const;

const useStyles = makeStyles((c) => ({
  // Same visible size as the bell and info icons beside it; hitSlop keeps the tap area 44pt.
  // marginLeft "auto" keeps it at the far right of whatever header row it sits in.
  button: { width: 34, height: 44, alignItems: "center", justifyContent: "center", marginLeft: "auto" },
  overlay: { flex: 1, backgroundColor: c.scrim },
  sheet: { position: "absolute", top: 0, right: 0, width: 280, height: "100%", backgroundColor: c.surface, shadowColor: c.onSurface, shadowOpacity: 0.2, shadowRadius: 16, shadowOffset: { width: -4, height: 0 }, elevation: 16 },
  closeRow: { flexDirection: "row", justifyContent: "flex-end", paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  item: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.lg, paddingHorizontal: spacing.lg, borderBottomWidth: 0.5, borderBottomColor: c.divider },
  label: { flex: 1, fontFamily: fonts.textMedium, fontSize: 15, color: c.onSurface },
}));

export function AppMenuButton({ testID }: { testID: string }) {
  const s = useStyles(); const { colors } = useTheme(); const insets = useSafeAreaInsets(); const router = useRouter();
  const segments = useSegments() as string[];
  const [open, setOpen] = useState(false);
  if (isPopupRoute(segments)) return null;
  return (
    <>
      <Pressable testID={testID} accessibilityRole="button" accessibilityLabel="Menu" onPress={() => setOpen(true)} style={s.button} hitSlop={{ left: 5, right: 5 }}>
        <Menu size={22} color={colors.onSurface} />
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={s.overlay} onPress={() => setOpen(false)} testID="menu-overlay">
          <View style={[s.sheet, { paddingTop: insets.top + spacing.sm }]}>
            <View style={s.closeRow}>
              <Pressable onPress={() => setOpen(false)} style={s.close} accessibilityRole="button" accessibilityLabel="Close menu" testID="menu-close">
                <X size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            {ITEMS.map((item) => (
              <Pressable
                key={item.testID}
                testID={item.testID}
                accessibilityRole="button"
                accessibilityLabel={item.label}
                onPress={() => { setOpen(false); router.push(item.route as never); }}
                style={({ pressed }) => [s.item, { opacity: pressed ? 0.7 : 1 }]}
              >
                <item.icon size={20} color={colors.onSurface} />
                <Text style={s.label}>{item.label}</Text>
                <ChevronRight size={16} color={colors.onSurfaceSecondary} />
              </Pressable>
            ))}
          </View>
        </Pressable>
      </Modal>
    </>
  );
}
