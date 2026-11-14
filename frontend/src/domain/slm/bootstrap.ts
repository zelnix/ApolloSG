/** Web / Expo Go entry: never claims model availability or imports llama.rn. */
export async function startSharedLuddish(): Promise<boolean> { return false; }
export async function installPrivateLuddishForTest(_sourceUri: string): Promise<boolean> { return false; }
export async function stopSharedLuddish(): Promise<void> {}

export async function isPrivateLuddishModelMissing(): Promise<boolean> { return false; }

export async function downloadPrivateLuddishForTest(): Promise<boolean> { return false; }

export type SLMCompatibilityStage = "hardware" | "model_integrity" | "runtime_registration" | "inference" | "response_validation" | "complete" | "failed";

export async function checkRequiredSLMCompatibility(
  _onStage?: (stage: SLMCompatibilityStage) => void,
): Promise<{ compatible: boolean; reason: string }> {
  return { compatible: false, reason: "This platform cannot run ApolloSG's required Higgins model." };
}
export async function rollbackSLMSetup(): Promise<void> {}
