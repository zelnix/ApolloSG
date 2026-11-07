// Renders ApolloSG's own confirmation dialog (title + message + buttons), fed by confirmDialog()
// (src/utils/confirmDialog.ts) via the confirmDialogStore pub/sub. Mounted once at the root
// (app/_layout.tsx) alongside ToastHost, so it floats above whatever screen is on top — identical
// look on native and web, never the OS's own Alert box or the browser's window.confirm (which shows
// the raw preview URL).
import React from "react";
import { Modal, Pressable, Text, View } from "react-native";

import { dismissConfirmDialog, type ConfirmButton, useConfirmDialog } from "@/src/store/confirmDialogStore";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  backdrop: { flex: 1, backgroundColor: c.scrim, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  card: { width: "100%", maxWidth: 360, backgroundColor: c.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.xl, gap: spacing.sm },
  title: { fontFamily: fonts.display, fontSize: 18, color: c.onSurface },
  message: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceSecondary },
  actions: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.lg, marginTop: spacing.md },
  btn: { minHeight: 44, minWidth: 44, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.sm },
  btnText: { fontFamily: fonts.textMedium, fontSize: 15 },
}));

export function ConfirmDialogHost() {
  const s = useStyles();
  const { colors } = useTheme();
  const request = useConfirmDialog();
  if (!request) return null;

  const colorFor = (style: ConfirmButton["style"]) => {
    if (style === "destructive") return colors.barkingText;
    if (style === "cancel") return colors.onSurfaceSecondary;
    return colors.brand;
  };
  const run = (button: ConfirmButton) => { dismissConfirmDialog(); button.onPress?.(); };

  return (
    <Modal visible transparent animationType="fade" onRequestClose={() => dismissConfirmDialog()} testID="confirm-dialog">
      <View style={s.backdrop}>
        <View style={s.card}>
          <Text style={s.title}>{request.title}</Text>
          <Text style={s.message}>{request.message}</Text>
          <View style={s.actions}>
            {request.buttons.map((button, i) => (
              <Pressable
                key={`${button.text}-${i}`}
                onPress={() => run(button)}
                style={s.btn}
                testID={`confirm-dialog-${button.style === "cancel" ? "cancel" : "action"}`}
                accessibilityRole="button"
                accessibilityLabel={button.text}
              >
                <Text style={[s.btnText, { color: colorFor(button.style), fontFamily: button.style === "cancel" ? fonts.text : fonts.textMedium }]}>{button.text}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      </View>
    </Modal>
  );
}
