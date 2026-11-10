/** Web / Expo Go entry: never claims model availability or imports llama.rn. */
export async function startSharedLuddish(): Promise<boolean> { return false; }
export async function installPrivateLuddishForTest(_sourceUri: string): Promise<boolean> { return false; }
export async function stopSharedLuddish(): Promise<void> {}

export async function isPrivateLuddishModelMissing(): Promise<boolean> { return false; }
