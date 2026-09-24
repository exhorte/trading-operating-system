/**
 * HTTP calls of the Settings screen (T12 incrément 2) — the backend's
 * `/api/account-settings` endpoints (AccountSettingsEndpoints.cs).
 *
 * The page never decides whether a change applies now or tomorrow: it sends
 * the change, the backend decides at the moment of writing and says so in
 * the response (AccountSettingsGuard). Every failure throws an Error whose
 * message can be shown as is.
 */

import { backendHttpBase } from "@/lib/realtime/backend-url";
import {
  parseLedger,
  parseSettingsVersion,
  type AccountSettingsLedger,
  type ExnessSettings,
  type FtmoSettings,
  type SettingsVersion,
} from "./settings";

async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { message?: unknown; detail?: unknown };
    if (typeof body.message === "string") {
      return body.message;
    }
    if (typeof body.detail === "string") {
      return `${fallback} (${body.detail})`;
    }
  } catch {
    // Not JSON — the status line is all there is.
  }
  return `${fallback} (HTTP ${res.status})`;
}

export async function fetchAccountSettings(): Promise<AccountSettingsLedger> {
  let res: Response;
  try {
    res = await fetch(`${backendHttpBase()}/api/account-settings`, { cache: "no-store" });
  } catch {
    throw new Error("Backend injoignable.");
  }
  if (!res.ok) {
    throw new Error(await errorMessage(res, "Lecture des paramètres impossible"));
  }
  const ledger = parseLedger(await res.json());
  if (!ledger) {
    throw new Error("Réponse du backend illisible.");
  }
  return ledger;
}

export type SettingsChange =
  | { firm: "ftmo"; settings: FtmoSettings }
  | { firm: "exness"; settings: ExnessSettings };

export async function requestSettingsChange(change: SettingsChange): Promise<SettingsVersion> {
  let res: Response;
  try {
    res = await fetch(`${backendHttpBase()}/api/account-settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(change),
    });
  } catch {
    throw new Error("Backend injoignable — rien n'a été enregistré.");
  }
  if (!res.ok) {
    throw new Error(await errorMessage(res, "Enregistrement refusé"));
  }
  const version = parseSettingsVersion(((await res.json()) as { version?: unknown }).version);
  if (!version) {
    throw new Error("Enregistré, mais la réponse du backend est illisible — recharge la page.");
  }
  return version;
}

export async function cancelSettingsChange(versionId: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(
      `${backendHttpBase()}/api/account-settings/${encodeURIComponent(versionId)}/cancel`,
      { method: "POST" },
    );
  } catch {
    throw new Error("Backend injoignable — rien n'a été annulé.");
  }
  if (!res.ok) {
    throw new Error(await errorMessage(res, "Annulation refusée"));
  }
}
