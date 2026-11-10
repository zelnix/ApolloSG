/** Web / Expo Go entry: never claims model availability or imports llama.rn. */
export async function startSharedLuddish(): Promise<boolean> { return false; }
export async function installPrivateLuddishForTest(_sourceUri: string): Promise<boolean> { return false; }
export async function stopSharedLuddish(): Promise<void> {}

export async function isPrivateLuddishModelMissing(): Promise<boolean> { return false; }

export async function downloadPrivateLuddishForTest(): Promise<boolean> { return false; }

export async function checkRequiredSLMCompatibility(): Promise<{ compatible: boolean; reason: string }> {
  return { compatible: false, reason: "This platform cannot run ApolloSG's required On-device AI model." };
}
export async function rollbackSLMSetup(): Promise<void> {}
