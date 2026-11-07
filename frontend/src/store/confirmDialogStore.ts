// A tiny pub/sub store behind confirmDialog() (src/utils/confirmDialog.ts), so any plain function —
// not just components — can raise ApolloSG's own confirmation dialog. Mirrors Alert.alert's
// (title, message, buttons) shape but is rendered by ConfirmDialogHost using the app's own theme on
// every platform, including web (where Alert.alert is a no-op and window.confirm shows the page's
// raw URL — neither is "in keeping with ApolloSG's" look).
import { useEffect, useState } from "react";

export interface ConfirmButton {
  text: string;
  style?: "default" | "cancel" | "destructive";
  onPress?: () => void;
}
export interface ConfirmRequest {
  title: string;
  message: string;
  buttons: ConfirmButton[];
}

let current: ConfirmRequest | null = null;
const listeners = new Set<(r: ConfirmRequest | null) => void>();
const emit = () => listeners.forEach((l) => l(current));

export function showConfirmDialog(title: string, message: string, buttons: ConfirmButton[]): void {
  current = { title, message, buttons };
  emit();
}

export function dismissConfirmDialog(): void {
  current = null;
  emit();
}

export function useConfirmDialog(): ConfirmRequest | null {
  const [state, setState] = useState(current);
  useEffect(() => {
    listeners.add(setState);
    return () => { listeners.delete(setState); };
  }, []);
  return state;
}
