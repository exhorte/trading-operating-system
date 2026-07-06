import type { Envelope, EventType } from "@/lib/contracts/envelope";

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `mock-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function makeEnvelope<TPayload>(
  type: EventType,
  source: string,
  payload: TPayload,
  correlationId?: string,
): Envelope<TPayload> {
  return {
    messageId: uuid(),
    correlationId: correlationId ?? uuid(),
    causationId: null,
    type,
    schemaVersion: 1,
    source,
    target: "dashboard",
    sentAt: new Date().toISOString(),
    payload,
  };
}

export { uuid };
