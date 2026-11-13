export class ModelDownloadPaused extends Error {
  constructor() { super("Model download paused pending network consent"); this.name = "ModelDownloadPaused"; }
}

interface ResumableTransfer<T> {
  downloadAsync(): Promise<T | undefined>;
  pauseAsync(): Promise<unknown>;
  resumeAsync(): Promise<T | undefined>;
  cancelAsync(): Promise<void>;
}

/** Keep one transfer alive across native pause/resume promises. A pause resolves
 * Expo's original promise without a result; only a completed transfer is success.
 */
export function downloadWithNetworkConsent<T>(task: ResumableTransfer<T>, options: {
  approvedNetwork: string;
  readNetwork: () => Promise<string>;
  approveNetwork: () => Promise<string | null>;
}): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let done = false;
    let busy = false;
    let generation = 0;
    let approved = options.approvedNetwork;
    let current: Promise<T | undefined>;
    let monitor: ReturnType<typeof setInterval>;
    const fail = (error: unknown) => {
      if (done) return;
      done = true; clearInterval(monitor); reject(error);
    };
    const watch = (transfer: Promise<T | undefined>, token: number) => {
      current = transfer;
      void transfer.then(result => {
        if (done || token !== generation) return;
        if (result === undefined || result === null) { fail(new Error("Model transfer did not complete")); return; }
        done = true; clearInterval(monitor); resolve(result);
      }, error => { if (!done && token === generation) fail(error); });
    };
    monitor = setInterval(() => {
      if (done || busy) return;
      busy = true;
      void (async () => {
        try {
          const network = await options.readNetwork();
          if (done || network === approved) return;
          // Fence the old promise before pauseAsync resolves it with undefined.
          generation++;
          await task.pauseAsync();
          if (done) return;
          const consent = await options.approveNetwork();
          if (done) return;
          if (consent === null) { fail(new ModelDownloadPaused()); return; }
          approved = consent;
          watch(task.resumeAsync(), ++generation);
        } catch (error) {
          if (done) return;
          generation++;
          try { await task.cancelAsync(); }
          catch { await current?.catch(() => undefined); }
          fail(error);
        } finally { busy = false; }
      })();
    }, 1000);
    try { watch(task.downloadAsync(), ++generation); }
    catch (error) { fail(error); }
  });
}
