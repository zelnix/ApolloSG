import { requireOptionalNativeModule } from "expo-modules-core";

import type { SlmGenerateInput, SlmNativeResult, SlmNativeStatus } from "./src/ApolloSlm.types";

interface NativeModule {
  getStatus(): Promise<SlmNativeStatus>;
  /** Android only: asks the OS to fetch its on-device model. iOS manages its model itself. */
  requestDownload(): Promise<SlmNativeStatus>;
  generate(input: SlmGenerateInput): Promise<SlmNativeResult>;
  /** Streamed SHA-256 (lower-case hex) of a local file, or null if it can't be read. */
  sha256File(path: string): Promise<string | null>;
}

const notInstalled = async (): Promise<never> => { throw new Error("On-device AI needs an installed ApolloSG mobile build."); };
const absent: NativeModule = {
  getStatus: async () => ({ availability: "unavailable", engine: "none", reason: "not_in_this_build", modelName: null, osVersion: null, observedAt: new Date().toISOString() }),
  requestDownload: async () => ({ availability: "unavailable", engine: "none", reason: "not_in_this_build", modelName: null, osVersion: null, observedAt: new Date().toISOString() }),
  generate: notInstalled,
  sha256File: async () => null,
};

export const ApolloSlm: NativeModule = requireOptionalNativeModule<NativeModule>("ApolloSlm") ?? absent;
export type * from "./src/ApolloSlm.types";
