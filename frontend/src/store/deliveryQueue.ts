// Durable single-writer outbox. Pending evidence is never evicted; overflow is explicit.
type Payload = Record<string, unknown>;
type Item = { payload: Payload; version: string; attempts: number; nextAt: number; error: string | null; blocked: boolean; enqueuedAt?: number };
type Receipt = { version: string; ackAt: number };
type Journal = { pending: Record<string, Item>; receipts: Record<string, Receipt | string>; cleared?: Record<string, true>; overflow?: { count: number; lastAt: number } };
type IO = { read(): Promise<string | null>; write(value: string): Promise<void>; send(body: Payload): Promise<Payload>; changed(status: DeliveryStatus): void; now?: () => number };
export type DeliveryStatus = { pending: number; blocked: number; overflow: number; error: string | null };
export type DeliveryQueueOptions = { maxPending: number; maxReceipts: number; receiptTtlMs: number };

export const DELIVERY_QUEUE_LIMITS: DeliveryQueueOptions = {
  maxPending: 256,
  maxReceipts: 1024,
  receiptTtlMs: 30 * 24 * 60 * 60 * 1000,
};

export class DeliveryQueueOverflow extends Error {
  constructor() { super("Delivery queue is full. Pending evidence was retained; this event remains in local Patrol for retry."); this.name = "DeliveryQueueOverflow"; }
}

export class DeliveryQueue {
  private chain: Promise<unknown> = Promise.resolve();
  private running = false;
  private journal: Journal | null = null;
  private paused = new Set<string>();
  private activeSend: Promise<Payload> | null = null;
  private io: IO;
  private limits: DeliveryQueueOptions;
  constructor(io: IO, limits: DeliveryQueueOptions = DELIVERY_QUEUE_LIMITS) { this.io = io; this.limits = limits; }
  private now() { return this.io.now?.() ?? Date.now(); }
  private serial<T>(fn: () => Promise<T>): Promise<T> { const next = this.chain.then(fn); this.chain = next.catch(() => undefined); return next; }
  private pruneReceipts(j: Journal) {
    const now = this.now();
    const retained = Object.entries(j.receipts).map(([key, raw]) => [key, typeof raw === "string" ? { version: raw, ackAt: now } : raw] as const)
      .filter(([, receipt]) => now - receipt.ackAt <= this.limits.receiptTtlMs)
      .sort((a, b) => b[1].ackAt - a[1].ackAt).slice(0, this.limits.maxReceipts);
    j.receipts = Object.fromEntries(retained);
  }
  private async load() {
    if (!this.journal) {
      const raw = await this.io.read(); this.journal = raw ? JSON.parse(raw) : { pending: {}, receipts: {} };
      if (!this.journal?.pending || !this.journal.receipts) { this.journal = null; throw new Error("Delivery journal is unreadable"); }
      const priorReceipts = JSON.stringify(this.journal.receipts);
      this.pruneReceipts(this.journal);
      if (JSON.stringify(this.journal.receipts) !== priorReceipts) await this.io.write(JSON.stringify(this.journal));
      this.publish(this.journal);
    }
    return this.journal;
  }
  private async save(j: Journal) {
    this.pruneReceipts(j);
    try { await this.io.write(JSON.stringify(j)); }
    catch (error) { this.journal = null; throw error; }
    this.publish(j);
  }
  private publish(j: Journal) {
    const rows = Object.values(j.pending);
    const overflow = Math.max(j.overflow?.count ?? 0, Math.max(0, rows.length - this.limits.maxPending));
    this.io.changed({ pending: rows.length, blocked: rows.filter(x => x.blocked).length, overflow,
      error: overflow ? "Delivery queue capacity was reached. Pending evidence was kept; newer local events will retry as space becomes available." : rows.find(x => x.error)?.error ?? null });
  }
  async enqueue(payload: Payload) {
    return this.serial(async () => {
      if (this.paused.has(String(payload.device_id))) return;
      const j = await this.load(), key = `${payload.device_id}:${payload.event_id}`, version = JSON.stringify(payload);
      if (j.cleared?.[key]) return;
      const receipt = j.receipts[key];
      if ((typeof receipt === "string" ? receipt : receipt?.version) === version || j.pending[key]?.version === version) return;
      if (!j.pending[key] && Object.keys(j.pending).length >= this.limits.maxPending) {
        j.overflow = { count: (j.overflow?.count ?? 0) + 1, lastAt: this.now() };
        await this.save(j); throw new DeliveryQueueOverflow();
      }
      j.pending[key] = { payload, version, attempts: 0, nextAt: 0, error: null, blocked: false, enqueuedAt: this.now() };
      delete j.overflow; await this.save(j);
    });
  }
  async flush(deviceId: string, manual = false) {
    if (this.running) return;
    this.running = true;
    try {
      const entries = await this.serial(async () => Object.entries((await this.load()).pending));
      for (const [key, item] of entries) {
        if (this.paused.has(deviceId) || item.payload.device_id !== deviceId || (!manual && (item.blocked || item.nextAt > this.now()))) continue;
        try {
          this.activeSend = this.io.send(item.payload); const ack = await this.activeSend;
          if (!ackMatches(item.payload, ack, deviceId)) throw new Error("Server acknowledgement did not match the event");
          await this.serial(async () => {
            const j = await this.load(); if (j.pending[key]?.version !== item.version) return;
            j.receipts[key] = { version: item.version, ackAt: this.now() }; delete j.pending[key]; await this.save(j);
          });
        } catch (error) {
          await this.serial(async () => {
            const j = await this.load(); if (j.pending[key]?.version !== item.version) return;
            const e = error as { name?: string; status?: number };
            item.blocked = e.name === "EgressViolation" || (!!e.status && e.status >= 400 && e.status < 500 && e.status !== 429);
            item.attempts += 1; item.nextAt = this.now() + Math.min(300_000, 2000 * 2 ** Math.min(item.attempts, 7));
            item.error = item.blocked ? "Delivery blocked by policy or server validation. The event remains on this device." : "Delivery not acknowledged. ApolloSG will retry.";
            j.pending[key] = item; await this.save(j);
          });
        } finally { this.activeSend = null; }
      }
    } finally { this.running = false; }
  }
  async pauseForClear(deviceId: string) { this.paused.add(deviceId); try { await this.activeSend; } catch { /* reconcile below */ } }
  async clearPaused(deviceId: string, eventIds: string[]) {
    await this.serial(async () => {
      const j = await this.load(); j.cleared ??= {};
      for (const id of eventIds) { const key = `${deviceId}:${id}`; j.cleared[key] = true; delete j.receipts[key]; }
      for (const [key, item] of Object.entries(j.pending)) if (item.payload.device_id === deviceId) { j.cleared[key] = true; delete j.pending[key]; }
      delete j.overflow; await this.save(j);
    });
  }
  resume(deviceId: string) { this.paused.delete(deviceId); }
  /** The person deleted these events: nothing pending for them is sent, and they are never queued again. */
  async forget(deviceId: string, eventIds: string[]) {
    await this.serial(async () => {
      const j = await this.load(); j.cleared ??= {};
      for (const id of eventIds) { const key = `${deviceId}:${id}`; j.cleared[key] = true; delete j.receipts[key]; delete j.pending[key]; }
      await this.save(j);
    });
  }
}

function ackMatches(payload: Payload, ack: Payload, deviceId: string) {
  if (ack.event_id !== payload.event_id || ack.device_id !== deviceId) return false;
  const evidence = payload.enforcement_evidence as Payload | undefined;
  if (evidence) return (ack.enforcement_evidence as Payload | undefined)?.evidence_id === evidence.evidence_id;
  return ack.state === payload.state && ack.verified_block === payload.verified_block && ack.status === payload.status && sameTime(ack.resolved_at, payload.resolved_at);
}
function sameTime(a: unknown, b: unknown) { return a == null && b == null || typeof a === "string" && typeof b === "string" && Date.parse(a) === Date.parse(b); }