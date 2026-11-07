// Confirmation dialog with ApolloSG's own look, on every platform. Kept as a drop-in for
// Alert.alert's (title, message, buttons) shape so call sites barely change, but it is rendered by
// ConfirmDialogHost (mounted once in app/_layout.tsx) instead of the OS alert — Alert.alert is a
// no-op on web, and the alternative, window.confirm, shows the raw preview URL and isn't styled.
import { showConfirmDialog, type ConfirmButton } from "@/src/store/confirmDialogStore";

export type { ConfirmButton };

export function confirmDialog(title: string, message: string, buttons: ConfirmButton[]): void {
  showConfirmDialog(title, message, buttons);
}
