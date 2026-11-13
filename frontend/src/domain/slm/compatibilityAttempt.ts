export type SLMAdmissionResult = { compatible: boolean; reason: string; diagnosticCode?: string };

export class SLMCompatibilityTimeout extends Error {
  constructor() { super("On-device AI verification timed out"); this.name = "SLMCompatibilityTimeout"; }
}

/** Installation is not a boot-time check. Only native verification gets a deadline.
 * Keep `work` separate: a timeout cannot cancel a native operation or permit overlap.
 */
export function createCompatibilityAttempt(options: {
  install?: () => Promise<boolean>;
  installFailure?: () => SLMAdmissionResult;
  check: () => Promise<SLMAdmissionResult>;
  verificationTimeoutMs?: number;
}): { work: Promise<SLMAdmissionResult>; result: Promise<SLMAdmissionResult> } {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let rejectTimeout!: (error: Error) => void;
  const timeout = new Promise<never>((_, reject) => { rejectTimeout = reject; });
  const work = (async (): Promise<SLMAdmissionResult> => {
    if (options.install && !await options.install()) {
      return options.installFailure?.() ?? { compatible: false, reason: "On-device AI installation was not completed." };
    }
    timer = setTimeout(() => rejectTimeout(new SLMCompatibilityTimeout()), options.verificationTimeoutMs ?? 45000);
    return options.check();
  })();
  const result = Promise.race([work, timeout]).finally(() => { if (timer) clearTimeout(timer); });
  return { work, result };
}
