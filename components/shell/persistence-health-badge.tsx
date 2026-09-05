"use client";

import { useEffect, useState } from "react";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

const POLL_INTERVAL_MS = 15_000;

interface HealthResponse {
  status: string;
  db: string;
  persisted: number;
  dropped: number;
  queued: number;
  dbError: string | null;
}

function healthUrlFromHubUrl(hubUrl: string): string {
  return `${hubUrl.replace(/\/hub\/cockpit\/?$/, "")}/health`;
}

/**
 * Polls the backend's /health for the persistence-writer counters (ADR 0003:
 * HTTP is the sanctioned surface for health/admin, not for trading flow).
 *
 * Why this exists: CockpitHub.PublishEvent broadcasts to every dashboard
 * BEFORE the write is even enqueued — a full queue or a down database drops
 * the write with zero effect on the broadcast. A published fact (e.g. a T04
 * ticket) can therefore echo back to the sender — proving the broadcast
 * happened — while never reaching the database. Only /health's `dropped`
 * counter can catch that case.
 */
export function PersistenceHealthBadge() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    if (process.env.NEXT_PUBLIC_REALTIME_SOURCE !== "backend") {
      return;
    }
    const hubUrl = process.env.NEXT_PUBLIC_BACKEND_HUB_URL ?? "http://localhost:5080/hub/cockpit";
    const url = healthUrlFromHubUrl(hubUrl);
    let cancelled = false;

    async function poll() {
      try {
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok) {
          throw new Error(String(res.status));
        }
        const data = (await res.json()) as HealthResponse;
        if (!cancelled) {
          setHealth(data);
          setUnreachable(false);
        }
      } catch {
        if (!cancelled) {
          setUnreachable(true);
        }
      }
    }

    void poll();
    const timer = setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (process.env.NEXT_PUBLIC_REALTIME_SOURCE !== "backend") {
    return null; // nothing to poll in mock mode — no backend running
  }
  if (unreachable || !health) {
    return <StatusPill tone="muted">Persistance —</StatusPill>;
  }

  const hasIssue = health.dropped > 0 || health.db !== "ok";
  const tone: PillTone = hasIssue ? "loss" : "profit";
  return (
    <StatusPill tone={tone} pulse={hasIssue}>
      {health.dropped > 0 ? `${health.dropped} événements perdus` : "Persistance OK"}
    </StatusPill>
  );
}
