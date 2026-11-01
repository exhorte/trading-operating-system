import { describe, expect, it } from "vitest";
import type { Account, AccountStatus } from "@/lib/api/generated";
import { connectedAccount, needsConnectedAccount, showsConnectGate, type CoreView } from "./connected";

function account(id: string, status: AccountStatus): Account {
  return { id, status } as Account;
}

const answered: CoreView = { connection: "connected", version: "0.2.0", accounts: [] };

describe("connectedAccount", () => {
  it("is the one account that is connected", () => {
    expect(connectedAccount([account("a", "DISCONNECTED"), account("b", "CONNECTED")])?.id).toBe("b");
  });

  it.each<AccountStatus>(["DISCONNECTED", "CONNECTING", "ERROR"])("is none when the only account is %s", (status) => {
    expect(connectedAccount([account("a", status)])).toBeNull();
    expect(connectedAccount([])).toBeNull();
  });
});

describe("needsConnectedAccount", () => {
  it.each(["/", "/positions", "/risk", "/journal", "/journal/123", "/analyse", "/market-context", "/preflight", "/setups", "/agents"])(
    "%s reads an account's figures",
    (path) => expect(needsConnectedAccount(path)).toBe(true),
  );

  it.each(["/account", "/settings", "/account/"])("%s is where an account is connected and set up", (path) => {
    expect(needsConnectedAccount(path)).toBe(false);
  });

  it("does not mistake a longer name for an open screen", () => {
    expect(needsConnectedAccount("/accounting")).toBe(true);
  });
});

describe("showsConnectGate", () => {
  it("replaces a screen that needs an account when the core answered and none is connected", () => {
    expect(showsConnectGate(answered, "/")).toBe(true);
    expect(showsConnectGate({ ...answered, accounts: [account("a", "DISCONNECTED")] }, "/risk")).toBe(true);
    expect(showsConnectGate({ ...answered, connection: "degraded" }, "/positions")).toBe(true);
  });

  it("leaves Account and Settings open — that is where the trader connects one", () => {
    expect(showsConnectGate(answered, "/account")).toBe(false);
    expect(showsConnectGate(answered, "/settings")).toBe(false);
  });

  it("stays out of the way once an account is connected", () => {
    expect(showsConnectGate({ ...answered, accounts: [account("a", "CONNECTED")] }, "/")).toBe(false);
  });

  it("never claims « no account » before the core's first snapshot has arrived", () => {
    expect(showsConnectGate({ ...answered, version: null }, "/")).toBe(false);
  });

  it.each<CoreView["connection"]>(["connecting", "reconnecting", "stale", "disconnected"])(
    "leaves the screen's own message when the link is %s",
    (connection) => expect(showsConnectGate({ ...answered, connection }, "/")).toBe(false),
  );
});
