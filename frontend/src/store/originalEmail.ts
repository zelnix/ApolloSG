// The original email (.eml / original source) exactly as received — kept on THIS PHONE only, never uploaded.
// Higgins Triage reads it here; only the minimal structured findings travel with an investigation.
// Native: a file in the app's document folder. Web preview: browser storage, up to a size limit.
// Kept for 24 hours from when it was kept (domain/heldCopies.ts), then deleted — on access and by the clean-up sweep —
// and earlier with the case and on full data wipe.
import * as Crypto from "expo-crypto";
import * as DocumentPicker from "expo-document-picker";
import * as FS from "expo-file-system/legacy";
import { Platform } from "react-native";

import {
  MAX_ORIGINAL_BYTES, b64ToBinary, binaryToBase64, bytesToBinary, looksLikeRawEmail, parseOriginalEmail, utf8ToBinary, type ParsedOriginal,
} from "@/src/domain/triage/emailOriginal";
import { heldCopyExpired } from "@/src/domain/heldCopies";
import { storage } from "@/src/utils/storage";

export interface OriginalEmailRecord { caseKeys: string[]; sha256: string; bytes: number; uri: string | null; createdAt: string }

const INDEX = "apollo.original_email.v1";
const DIR = "apollo-originals";
const WEB_LIMIT = 2 * 1024 * 1024;
const dirUri = () => (FS.documentDirectory ?? "") + DIR + "/";
const webKey = (sha256: string) => `${INDEX}.${sha256}`;

async function readIndex(): Promise<OriginalEmailRecord[]> {
  try { const parsed = JSON.parse((await storage.getItem(INDEX, "[]")) ?? "[]"); return Array.isArray(parsed) ? parsed : []; }
  catch { return []; }
}
const writeIndex = (next: OriginalEmailRecord[]) => storage.setItem(INDEX, JSON.stringify(next));

export interface OriginalEmail { parsed: ParsedOriginal; binary: string }

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, bytes as unknown as BufferSource);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

const NOT_AN_EMAIL = "That file isn't an original email. Save the email as an .eml file (Gmail: ⋮ → Download message; Outlook: Save as) and choose it again.";

/** Parse an original message on this device. `binary` is its exact bytes, one char per byte. */
export async function readOriginal(binary: string): Promise<OriginalEmail> {
  if (!looksLikeRawEmail(binary.slice(0, 65536))) throw new Error(NOT_AN_EMAIL);
  return { parsed: await parseOriginalEmail(binary, sha256Hex), binary };
}

/** Pasted original source ("Show original") as UTF-8 bytes. */
export function readOriginalText(text: string): Promise<OriginalEmail> {
  return readOriginal(utf8ToBinary(text.replace(/^\s+/, "")));
}

/** Let the person choose an .eml file and read it on this device. Null when they cancel. */
export async function pickOriginalEmail(): Promise<OriginalEmail | null> {
  const res = await DocumentPicker.getDocumentAsync({ type: ["message/rfc822", "application/octet-stream", "text/plain", "*/*"], copyToCacheDirectory: true, multiple: false });
  if (res.canceled || !res.assets[0]) return null;
  const asset = res.assets[0];
  try { return await readOriginal(await readEmailFile(asset)); }
  finally {
    if (Platform.OS !== "web" && asset.uri.startsWith(FS.cacheDirectory ?? "\u0000")) { try { await FS.deleteAsync(asset.uri, { idempotent: true }); } catch { /* picker copy already gone */ } }
  }
}

/** Read a picked file's exact bytes as a binary string (one char per byte). */
export async function readEmailFile(asset: { uri: string; size?: number | null }): Promise<string> {
  if (asset.size != null && asset.size > MAX_ORIGINAL_BYTES) throw new Error(`This email is ${Math.round(asset.size / (1024 * 1024))} MB — ApolloSG reads originals up to ${MAX_ORIGINAL_BYTES / (1024 * 1024)} MB.`);
  if (Platform.OS === "web") {
    const bytes = new Uint8Array(await (await fetch(asset.uri)).arrayBuffer());
    if (!bytes.length || bytes.length > MAX_ORIGINAL_BYTES) throw new Error("That file is empty or larger than ApolloSG can read.");
    return bytesToBinary(bytes);
  }
  const info = await FS.getInfoAsync(asset.uri);
  if (!info.exists || info.isDirectory || !info.size || info.size > MAX_ORIGINAL_BYTES) throw new Error("That file is empty or larger than ApolloSG can read.");
  return b64ToBinary(await FS.readAsStringAsync(asset.uri, { encoding: FS.EncodingType.Base64 }));
}

/** Keep the original unaltered for these cases. Returns whether it is now kept on this device. */
export async function keepOriginalEmail(caseKeys: (string | null | undefined)[], binary: string, sha256: string): Promise<boolean> {
  const keys = caseKeys.filter((k): k is string => !!k);
  if (!keys.length) return false;
  try {
    await sweepOriginalEmails();
    const all = await readIndex();
    const existing = all.find((r) => r.sha256 === sha256);
    if (existing) {
      await writeIndex(all.map((r) => (r === existing ? { ...r, caseKeys: [...new Set([...r.caseKeys, ...keys])] } : r)));
      return true;
    }
    let uri: string | null = null;
    if (Platform.OS === "web") {
      if (binary.length > WEB_LIMIT) return false;
      await storage.setItem(webKey(sha256), binaryToBase64(binary));
    } else {
      const info = await FS.getInfoAsync(dirUri());
      if (!info.exists) await FS.makeDirectoryAsync(dirUri(), { intermediates: true });
      uri = `${dirUri()}${sha256}.eml`;
      await FS.writeAsStringAsync(uri, binaryToBase64(binary), { encoding: FS.EncodingType.Base64 });
    }
    await writeIndex([{ caseKeys: keys, sha256, bytes: binary.length, uri, createdAt: new Date().toISOString() }, ...all]);
    return true;
  } catch (e) {
    console.warn("[originalEmail] could not keep the original email:", e);
    return false;
  }
}

/** The exact bytes of the original email kept for any of these case keys (a binary string), or null when none is kept. */
export async function readKeptOriginalEmail(caseKeys: string[]): Promise<string | null> {
  await sweepOriginalEmails();
  const record = (await readIndex()).find((r) => r.caseKeys.some((k) => caseKeys.includes(k)));
  if (!record) return null;
  try {
    if (Platform.OS === "web") {
      const b64 = await storage.getItem<string | null>(webKey(record.sha256), null);
      return b64 ? b64ToBinary(b64) : null;
    }
    return record.uri ? b64ToBinary(await FS.readAsStringAsync(record.uri, { encoding: FS.EncodingType.Base64 })) : null;
  } catch { return null; }
}

export async function listOriginalEmails(caseKey: string): Promise<OriginalEmailRecord[]> {
  await sweepOriginalEmails();
  return (await readIndex()).filter((r) => r.caseKeys.includes(caseKey));
}

/** Deletes every original email kept for more than 24 hours. */
export async function sweepOriginalEmails(now: number = Date.now()): Promise<number> {
  const all = await readIndex();
  const due = all.filter((r) => heldCopyExpired(r.createdAt, now));
  if (!due.length) return 0;
  for (const r of due) await remove(r);
  await writeIndex(all.filter((r) => !due.includes(r)));
  return due.length;
}

async function remove(record: OriginalEmailRecord) {
  if (Platform.OS === "web") { await storage.removeItem(webKey(record.sha256)); return; }
  if (record.uri?.startsWith(dirUri())) { try { await FS.deleteAsync(record.uri, { idempotent: true }); } catch { /* already gone */ } }
}

export async function deleteOriginalEmailsFor(caseKey: string) {
  const all = await readIndex();
  const gone = all.filter((r) => r.caseKeys.includes(caseKey) && r.caseKeys.length === 1);
  if (!all.some((r) => r.caseKeys.includes(caseKey))) return;
  for (const r of gone) await remove(r);
  await writeIndex(all.filter((r) => !gone.includes(r)).map((r) => ({ ...r, caseKeys: r.caseKeys.filter((k) => k !== caseKey) })));
}

export async function clearAllOriginalEmails() {
  for (const r of await readIndex()) await remove(r);
  if (Platform.OS !== "web") { try { await FS.deleteAsync(dirUri(), { idempotent: true }); } catch { /* best effort */ } }
  await writeIndex([]);
}
