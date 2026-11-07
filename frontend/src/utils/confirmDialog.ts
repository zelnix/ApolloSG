// Cross-platform confirmation dialog. react-native-web's Alert.alert() is a no-op stub (it never
// shows anything and never calls a button's onPress), so any confirm-then-act flow built on
// Alert.alert silently does nothing in the web preview. This wraps the exact same call shape —
// confirmDialog(title, message, buttons) — and on web falls back to window.confirm, matching the
// cancel button to "Cancel" and the primary action button to "OK". On native it is Alert.alert,
// unchanged.
import { Alert, Platform } from "react-native";

export interface ConfirmButton {
  text: string;
  style?: "default" | "cancel" | "destructive";
  onPress?: () => void;
}

export function confirmDialog(title: string, message: string, buttons: ConfirmButton[]): void {
  if (Platform.OS === "web") {
    const cancel = buttons.find((b) => b.style === "cancel");
    // The button a person would reach for to proceed — the first non-cancel one.
    const action = buttons.find((b) => b !== cancel);
    const proceed = typeof window !== "undefined" && typeof window.confirm === "function"
      ? window.confirm(`${title}\n\n${message}`)
      : false;
    if (proceed) action?.onPress?.();
    else cancel?.onPress?.();
    return;
  }
  Alert.alert(title, message, buttons);
}
