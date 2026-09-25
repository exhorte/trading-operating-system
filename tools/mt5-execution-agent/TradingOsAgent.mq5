//+------------------------------------------------------------------+
//| TradingOsAgent.mq5 — EA-05                                        |
//|                                                                    |
//| Execution agent for the Trading Operating System (ADR 0010). It    |
//| connects to the Gateway over a local TCP socket, receives          |
//| commands, validates them against local safety barriers             |
//| (context/execution/safety.md), and reports the outcome. It decides |
//| NOTHING: no strategy, no signal, no market analysis, no decision    |
//| parameter. It does not know why it executes.                       |
//|                                                                     |
//| THIS FILE CONTAINS THE ONLY OrderSend CALL IN THE REPOSITORY        |
//| (EA-05 increment 6, added 2026-09-15 on the separate explicit       |
//| approval that ADR 0010 requires). It lives in exactly one function, |
//| ExecuteOrder, whose first statement returns unless the mode is      |
//| CONFIRM — grep OrderSend and read that function: there is no        |
//| execution path that reaches the broker without passing that test.   |
//|                                                                     |
//| Mode is a physical barrier, not a switch (ADR 0010): g_mode below   |
//| is a compile-time const set to MODE_OBSERVE, so in THIS build the   |
//| guard can never pass and the whole execution body is provably dead  |
//| code. Writing the path and being allowed to run it are two separate |
//| approvals — turning the mode ladder on is EA-07, which does not     |
//| exist. A command that passes every local barrier is still           |
//| acknowledged and reported SIMULATED today, exactly as before.       |
//|                                                                     |
//| It still decides NOTHING: no strategy, no signal, no market         |
//| analysis, no decision parameter. It does not know why it executes.  |
//+------------------------------------------------------------------+
#property copyright "Trading Operating System — personal use only"
#property version   "1.01"
#property description "EA-05 execution agent — OrderSend exists but is unreachable outside CONFIRM; this build is OBSERVE."

#include "Include/JsonLite.mqh"
#include "Include/CommandStore.mqh"

//--- Inputs: configuration and bounds only (ADR 0007/0010) — never a
//    decision parameter, and no default is a guess dressed as a fact.
input string InpGatewayHost       = "127.0.0.1"; // Gateway host — loopback only, this is a personal-use, single-machine system
input int    InpGatewayPort       = 9765;        // Must match Cockpit:AgentPort on the Gateway
input string InpAccountId         = "";          // REQUIRED: the Trading OS accountId this terminal serves — refuses to start if empty
input int    InpMagicNumber       = 0;           // REQUIRED: unique per environment (ADR 0010 isolation) — refuses to start if <= 0
input int    InpHeartbeatSeconds  = 5;
input double InpMaxVolumePerOrder = 1.0;         // lots — local barrier, last line of defense, never a decision
input int    InpMaxOpenPositions  = 3;           // local barrier — counts ALL positions on this terminal, deliberately including external ones (EA-06 fiche decision: attribute via EXTERNAL_POSITION/WARN, never loosen this count)
input int    InpMaxSpreadPoints   = 50;          // local barrier, re-checked at validation time, not just at proposal time
input string InpAllowedSymbolsCsv = "XAUUSDm,EURUSDm"; // local whitelist — broker-side names (context/domain/symbols-broker.md); XAUUSD + EURUSD since 2026-09-25, GBPUSD set aside
input int    InpMaxSlippagePoints = 10;          // EA-05 inc. 6: MqlTradeRequest.deviation — a bound on the fill, never a decision
input int    InpReconciliationLookbackDays = 7;  // EA-06: how far back HistorySelect searches to resolve an UNKNOWN commandId

//--- Execution mode ladder (ADR 0010): OBSERVE -> PAPER -> CONFIRM.
//    "AUTO" is not a value this enum can express — reaching it requires an
//    ADR that supersedes 0010, not a fourth value added here.
enum ExecutionMode
{
   MODE_OBSERVE,
   MODE_PAPER,
   MODE_CONFIRM
};

//--- Fixed at OBSERVE for the whole lifetime of this build. Not an input,
//    not settable by any message this file handles — control.set_mode is
//    logged and ignored (EA-07's job). This is the "physical barrier, not a
//    switch" requirement made literal: there is no variable anyone can flip.
const ExecutionMode g_mode = MODE_OBSERVE;

int      g_socket = INVALID_HANDLE;
bool     g_connected = false;
datetime g_last_heartbeat_sent = 0;
string   g_recv_buffer = "";

//--- EA-06: reconciliation attempt count per commandId, THIS AGENT RUN ONLY
//    — resets on restart. That is fine: the history search is idempotent
//    and cheap, and a restart is often the very reason reconciliation is
//    running in the first place. Not persisted — CommandStore.mqh stays a
//    plain idempotency ledger, not a database (its own header's own rule).
string g_reconciliation_ids[];
int    g_reconciliation_attempts[];

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpAccountId == "")
   {
      Print("TradingOsAgent: InpAccountId is empty. Set it to the Trading OS accountId this terminal serves before running. Refusing to start.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(InpMagicNumber <= 0)
   {
      Print("TradingOsAgent: InpMagicNumber must be a positive value, unique per environment (ADR 0010 isolation). Refusing to start.");
      return INIT_PARAMETERS_INCORRECT;
   }

   CommandStoreInit(InpMagicNumber);

   if(!ConnectToGateway())
   {
      Print("TradingOsAgent: initial connection to ", InpGatewayHost, ":", InpGatewayPort,
            " failed (error ", GetLastError(), ") — will retry on timer.");
   }

   EventSetTimer(1);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   if(g_socket != INVALID_HANDLE)
   {
      SocketClose(g_socket);
      g_socket = INVALID_HANDLE;
   }
}

//+------------------------------------------------------------------+
//| This agent is timer-driven, not tick-driven: no OnTick is defined. |
//| It never acts on a price move by itself — only on messages from    |
//| the Gateway and its own heartbeat clock (ADR 0010: orient event,   |
//| not tick; avoid the hyperactivity a prop firm's servers would flag |
//| if a stop were touched on every tick).                             |
//+------------------------------------------------------------------+
void OnTimer()
{
   if(g_socket == INVALID_HANDLE || !SocketIsConnected(g_socket))
   {
      g_connected = false;
      if(!ConnectToGateway())
      {
         return;
      }
   }

   PollIncoming();

   if(g_connected && (TimeGMT() - g_last_heartbeat_sent) >= InpHeartbeatSeconds)
   {
      SendHeartbeat();
      // EA-06: same cadence as the heartbeat (fiche decision) — cheap no-op
      // when nothing is UNKNOWN, which is the steady-state case.
      ReconcileUnknownCommands();
      ScanOpenPositions();
   }
}

//+------------------------------------------------------------------+
//| connect                                                            |
//+------------------------------------------------------------------+
bool ConnectToGateway()
{
   if(g_socket != INVALID_HANDLE)
   {
      SocketClose(g_socket);
      g_socket = INVALID_HANDLE;
   }

   g_socket = SocketCreate();
   if(g_socket == INVALID_HANDLE)
   {
      return false;
   }

   if(!SocketConnect(g_socket, InpGatewayHost, InpGatewayPort, 1000))
   {
      SocketClose(g_socket);
      g_socket = INVALID_HANDLE;
      return false;
   }

   g_connected = true;
   g_recv_buffer = "";
   SendHello();
   g_last_heartbeat_sent = TimeGMT();
   // EA-06: always on connect, including the first one after a restart —
   // that restart is exactly when an UNKNOWN left behind by a crash between
   // OrderSend and its ack most needs resolving (fiche decision).
   ReconcileUnknownCommands();
   ScanOpenPositions();
   return true;
}

string GetAgentId()
{
   return "mt5-execution-agent-" + IntegerToString(InpMagicNumber);
}

string ModeToWireString(ExecutionMode m)
{
   if(m == MODE_PAPER)   return "paper";
   if(m == MODE_CONFIRM) return "confirm";
   return "observe";
}

//--- Approximate server-vs-UTC offset (T02a's convention: resolved fresh at
//    every hello, never hardcoded, since it shifts with DST).
int ServerUtcOffsetMinutes()
{
   return (int)((TimeCurrent() - TimeGMT()) / 60);
}

string FirstAllowedSymbol()
{
   string parts[];
   int n = StringSplit(InpAllowedSymbolsCsv, ',', parts);
   if(n <= 0)
   {
      return "";
   }
   string s = parts[0];
   StringTrimLeft(s);
   StringTrimRight(s);
   return s;
}

bool IsAllowedSymbol(const string symbol)
{
   string parts[];
   int n = StringSplit(InpAllowedSymbolsCsv, ',', parts);
   for(int i = 0; i < n; i++)
   {
      string candidate = parts[i];
      StringTrimLeft(candidate);
      StringTrimRight(candidate);
      if(candidate == symbol)
      {
         return true;
      }
   }
   return false;
}

void SendHello()
{
   string symbol = FirstAllowedSymbol();
   long timeMs = (long)TimeGMT() * 1000;
   double minVol = symbol == "" ? 0.0 : SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxVol = symbol == "" ? 0.0 : SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double volStep = symbol == "" ? 0.0 : SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   int stopsLevel = symbol == "" ? 0 : (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);

   string json = "{";
   json += "\"version\":1,";
   json += "\"type\":\"agent.hello\",";
   json += "\"accountId\":\"" + JsonEscape(InpAccountId) + "\",";
   json += "\"time\":" + IntegerToString(timeMs) + ",";
   json += "\"agentId\":\"" + JsonEscape(GetAgentId()) + "\",";
   // NOTE: agent.hello carries a single `symbol` field (lib/contracts/mt5-wire.ts)
   // — a legacy of the single-symbol observer prototype. This agent's
   // whitelist may name several symbols; only the first is reported here.
   // Known limitation, not silently papered over — see EA-05 fiche journal.
   json += "\"symbol\":\"" + JsonEscape(symbol) + "\",";
   json += "\"broker\":\"" + JsonEscape(AccountInfoString(ACCOUNT_COMPANY)) + "\",";
   json += "\"server\":\"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\",";
   json += "\"orderTypes\":[\"market\"],";
   json += "\"minVolume\":" + DoubleToString(minVol, 2) + ",";
   json += "\"maxVolume\":" + DoubleToString(maxVol, 2) + ",";
   json += "\"volumeStep\":" + DoubleToString(volStep, 2) + ",";
   json += "\"fillingMode\":\"IOC\",";
   json += "\"stopsLevelPoints\":" + IntegerToString(stopsLevel) + ",";
   json += "\"mode\":\"" + ModeToWireString(g_mode) + "\",";
   json += "\"agentVersion\":\"1.00\",";
   json += "\"serverUtcOffsetMinutes\":" + IntegerToString(ServerUtcOffsetMinutes());
   json += "}";
   SendRawLine(json);
}

void SendHeartbeat()
{
   long timeMs = (long)TimeGMT() * 1000;
   string json = "{";
   json += "\"version\":1,";
   json += "\"type\":\"agent.heartbeat\",";
   json += "\"accountId\":\"" + JsonEscape(InpAccountId) + "\",";
   json += "\"time\":" + IntegerToString(timeMs) + ",";
   json += "\"agentId\":\"" + JsonEscape(GetAgentId()) + "\",";
   json += "\"latencyMs\":0";
   json += "}";
   if(SendRawLine(json))
   {
      g_last_heartbeat_sent = TimeGMT();
   }
}

//+------------------------------------------------------------------+
//| receive                                                            |
//+------------------------------------------------------------------+
bool SendRawLine(const string line)
{
   if(g_socket == INVALID_HANDLE)
   {
      return false;
   }
   string withNewline = line + "\n";
   uchar data[];
   // count -1: copies the terminating 0 and counts it, in UTF-8 bytes. An
   // explicit StringLen() count copies no terminator, so the "- 1" below
   // stripped the "\n" instead and the Gateway, which reads line by line,
   // never saw a single message (EA-05 fiche, 2026-09-24).
   int written = StringToCharArray(withNewline, data, 0, -1, CP_UTF8);
   int len = written - 1; // exclude the terminating 0 from the wire
   if(len <= 0)
   {
      return false;
   }
   int sent = SocketSend(g_socket, data, len);
   return sent == len;
}

void PollIncoming()
{
   if(g_socket == INVALID_HANDLE)
   {
      return;
   }

   uint available = SocketIsReadable(g_socket);
   if(available == 0)
   {
      return;
   }

   uchar buffer[];
   int received = SocketRead(g_socket, buffer, (int)available, 10);
   if(received <= 0)
   {
      return;
   }

   g_recv_buffer += CharArrayToString(buffer, 0, received, CP_UTF8);

   int newlinePos;
   while((newlinePos = StringFind(g_recv_buffer, "\n")) >= 0)
   {
      string line = StringSubstr(g_recv_buffer, 0, newlinePos);
      g_recv_buffer = StringSubstr(g_recv_buffer, newlinePos + 1);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) > 0)
      {
         HandleMessage(line);
      }
   }
}

void HandleMessage(const string json)
{
   string type = JsonGetString(json, "type");
   if(type == "execution.order")
   {
      HandleOrderCommand(json);
   }
   else if(type == "control.set_mode")
   {
      Print("TradingOsAgent: control.set_mode received but not implemented in this build (EA-07) — ignored.");
   }
   else if(type == "control.resync")
   {
      Print("TradingOsAgent: control.resync received but not implemented in this build (EA-06) — ignored.");
   }
   else
   {
      Print("TradingOsAgent: unhandled message type '", type, "' — ignored, never crashes on an unknown frame.");
   }
}

//+------------------------------------------------------------------+
//| validate                                                           |
//| Local barriers, last line of defense — never a decision (ADR 0007/ |
//| 0010); context/execution/safety.md documents the reasoning behind   |
//| each one. Empty return = no objection.                             |
//+------------------------------------------------------------------+
string ValidateOrderCommand(const string symbol, const string orderType, const double volume, const double sl)
{
   if(!IsAllowedSymbol(symbol))
   {
      return "symbol '" + symbol + "' is not in the local whitelist";
   }
   if(orderType != "MARKET")
   {
      return "orderType '" + orderType + "' is not supported in this build (market only)";
   }
   if(volume <= 0 || volume > InpMaxVolumePerOrder)
   {
      return "volume " + DoubleToString(volume, 2) + " exceeds the local per-order maximum " + DoubleToString(InpMaxVolumePerOrder, 2);
   }
   if(sl <= 0)
   {
      return "no stop-loss on this command — never executed without an explicit invalidation";
   }
   if(PositionsTotal() >= InpMaxOpenPositions)
   {
      return "open positions (" + IntegerToString(PositionsTotal()) + ") already at the local maximum (" + IntegerToString(InpMaxOpenPositions) + ")";
   }

   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(point <= 0)
   {
      return "symbol '" + symbol + "' has no valid point size on this terminal (not in Market Watch?)";
   }
   double spreadPoints = MathRound((SymbolInfoDouble(symbol, SYMBOL_ASK) - SymbolInfoDouble(symbol, SYMBOL_BID)) / point);
   if(spreadPoints > InpMaxSpreadPoints)
   {
      return "spread " + DoubleToString(spreadPoints, 0) + " points exceeds the local maximum " + IntegerToString(InpMaxSpreadPoints);
   }

   return "";
}

//+------------------------------------------------------------------+
//| acknowledge / report                                                |
//+------------------------------------------------------------------+
void SendAck(const string commandId, const string status, const string reason)
{
   long timeMs = (long)TimeGMT() * 1000;
   string json = "{";
   json += "\"version\":1,";
   json += "\"type\":\"execution.ack\",";
   json += "\"accountId\":\"" + JsonEscape(InpAccountId) + "\",";
   json += "\"time\":" + IntegerToString(timeMs) + ",";
   json += "\"commandId\":\"" + JsonEscape(commandId) + "\",";
   json += "\"status\":\"" + status + "\",";
   json += (reason == "" ? "\"reason\":null" : "\"reason\":\"" + JsonEscape(reason) + "\"");
   json += "}";
   SendRawLine(json);
}

//--- Broker fields default to 0, which serialises as JSON null: "not
//    applicable / unknown", never "zero". Same null-≠-zero convention the
//    rest of the repo runs on. Only a real fill (increment 6) passes them.
void SendReport(const string commandId, const string status, const string symbol, const string side,
                const string detail, const long brokerOrderId = 0, const long brokerPositionId = 0,
                const double filledVolume = 0.0, const double averagePrice = 0.0,
                const int brokerRetcode = 0)
{
   long timeMs = (long)TimeGMT() * 1000;
   string json = "{";
   json += "\"version\":1,";
   json += "\"type\":\"execution.report\",";
   json += "\"accountId\":\"" + JsonEscape(InpAccountId) + "\",";
   json += "\"time\":" + IntegerToString(timeMs) + ",";
   json += "\"commandId\":\"" + JsonEscape(commandId) + "\",";
   json += "\"status\":\"" + status + "\",";
   json += "\"symbol\":\"" + JsonEscape(symbol) + "\",";
   json += "\"side\":\"" + JsonEscape(side) + "\",";
   json += "\"brokerOrderId\":" + (brokerOrderId == 0 ? "null" : IntegerToString(brokerOrderId)) + ",";
   json += "\"brokerPositionId\":" + (brokerPositionId == 0 ? "null" : IntegerToString(brokerPositionId)) + ",";
   json += "\"filledVolume\":" + (filledVolume == 0.0 ? "null" : DoubleToString(filledVolume, 2)) + ",";
   json += "\"averagePrice\":" + (averagePrice == 0.0 ? "null" : DoubleToString(averagePrice, 5)) + ",";
   json += "\"brokerRetcode\":" + (brokerRetcode == 0 ? "null" : IntegerToString(brokerRetcode)) + ",";
   json += "\"detail\":\"" + JsonEscape(detail) + "\"";
   json += "}";
   SendRawLine(json);
}

//--- EA-06: the state machine's UNKNOWN state may only exit to RECONCILED
//    (context/execution/state-machine.md) — this message is that exit, kept
//    distinct from execution.report so a fill pieced together after the
//    fact from history is never presented as one watched live. symbol/side
//    are null for "not_found" — nothing was located to describe.
//    brokerRetcode is always null here: history never records the original
//    TRADE_RETCODE_*, and this function does not fabricate one.
void SendReconciled(const string commandId, const string outcome, const string symbol, const string side,
                     const long brokerOrderId, const long brokerPositionId,
                     const double filledVolume, const double averagePrice,
                     const int attempts, const string detail)
{
   long timeMs = (long)TimeGMT() * 1000;
   string json = "{";
   json += "\"version\":1,";
   json += "\"type\":\"execution.reconciled\",";
   json += "\"accountId\":\"" + JsonEscape(InpAccountId) + "\",";
   json += "\"time\":" + IntegerToString(timeMs) + ",";
   json += "\"commandId\":\"" + JsonEscape(commandId) + "\",";
   json += "\"outcome\":\"" + outcome + "\",";
   json += (symbol == "" ? "\"symbol\":null," : "\"symbol\":\"" + JsonEscape(symbol) + "\",");
   json += (side == "" ? "\"side\":null," : "\"side\":\"" + JsonEscape(side) + "\",");
   json += "\"brokerOrderId\":" + (brokerOrderId == 0 ? "null" : IntegerToString(brokerOrderId)) + ",";
   json += "\"brokerPositionId\":" + (brokerPositionId == 0 ? "null" : IntegerToString(brokerPositionId)) + ",";
   json += "\"filledVolume\":" + (filledVolume == 0.0 ? "null" : DoubleToString(filledVolume, 2)) + ",";
   json += "\"averagePrice\":" + (averagePrice == 0.0 ? "null" : DoubleToString(averagePrice, 5)) + ",";
   json += "\"brokerRetcode\":null,";
   json += "\"attempts\":" + IntegerToString(attempts) + ",";
   json += "\"detail\":\"" + JsonEscape(detail) + "\"";
   json += "}";
   SendRawLine(json);
}

//+------------------------------------------------------------------+
//| execute — EA-05 increment 6. THE ONLY OrderSend IN THE REPOSITORY. |
//|                                                                    |
//| Structural barrier, not a flag (ADR 0010): the mode test is this   |
//| function's first statement and its early return leaves the entire  |
//| rest of the body dead. The fiche's review question is "can any     |
//| execution path reach OrderSend without passing this test?" — there |
//| is exactly one call site of OrderSend, it is below this guard, and |
//| the answer is no. The caller checks the mode too; that is defence  |
//| in depth, not the barrier. This test is the barrier, and it stays  |
//| here even if a future caller forgets.                              |
//|                                                                    |
//| In this build g_mode is a compile-time const MODE_OBSERVE, so the  |
//| guard can never pass at all: everything below is provably          |
//| unreachable until EA-07 builds the mode ladder.                    |
//|                                                                    |
//| "Jamais deux positions" (ADR 0010): the command is written to disk |
//| as UNKNOWN BEFORE the broker call and rewritten with the real      |
//| outcome after. An agent that dies between the two leaves UNKNOWN   |
//| behind; replaying that commandId then returns DUPLICATE/UNKNOWN    |
//| from the store and never calls OrderSend a second time. Resolving  |
//| an UNKNOWN is EA-06's reconciliation — never a retry from here.    |
//+------------------------------------------------------------------+
void ExecuteOrder(const string commandId, const string symbol, const string side,
                  const double volume, const double sl, const double tp)
{
   if(g_mode != MODE_CONFIRM)
   {
      return;
   }

   CommandStoreRecord(commandId, "UNKNOWN", "OrderSend in flight — outcome not yet known");

   bool isBuy = (side == "BUY");
   MqlTradeRequest request;
   MqlTradeResult  result;
   ZeroMemory(request);
   ZeroMemory(result);
   request.action       = TRADE_ACTION_DEAL;
   request.symbol       = symbol;
   request.volume       = volume;
   request.type         = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   request.price        = isBuy ? SymbolInfoDouble(symbol, SYMBOL_ASK) : SymbolInfoDouble(symbol, SYMBOL_BID);
   request.sl           = sl;
   request.tp           = tp;
   request.deviation    = InpMaxSlippagePoints;
   request.magic        = InpMagicNumber;
   request.type_filling = ORDER_FILLING_IOC;
   request.comment      = "TradingOS " + commandId;

   bool sent = OrderSend(request, result);

   bool filled = sent && (result.retcode == TRADE_RETCODE_DONE || result.retcode == TRADE_RETCODE_DONE_PARTIAL);
   if(!filled)
   {
      // A refusal is a definite outcome, safe to record as final: the broker
      // rejected it, nothing is open. Only a crash mid-call leaves UNKNOWN.
      string failDetail = "OrderSend refused: retcode " + IntegerToString(result.retcode) +
                          (result.comment == "" ? "" : " (" + result.comment + ")");
      CommandStoreRecord(commandId, "FAILED", failDetail);
      SendReport(commandId, "FAILED", symbol, side, failDetail, 0, 0, 0.0, 0.0, (int)result.retcode);
      return;
   }

   // A fresh market entry's position identifier is its opening order ticket
   // (verified against this account's own history). That equivalence does NOT
   // hold for a deal that closes or reverses an existing position — this build
   // only ever sends fresh entries (max-positions barrier above), and the
   // general case is EA-06's reconciliation, not an assumption made here.
   string status = (result.retcode == TRADE_RETCODE_DONE_PARTIAL) ? "PARTIALLY_FILLED" : "FILLED";
   string detail = status + " " + DoubleToString(result.volume, 2) + " lot " + side + " " + symbol +
                   " @ " + DoubleToString(result.price, 5) + " (order " + IntegerToString((long)result.order) + ")";
   CommandStoreRecord(commandId, status, detail);
   SendReport(commandId, status, symbol, side, detail,
              (long)result.order, (long)result.order, result.volume, result.price, (int)result.retcode);
}

//+------------------------------------------------------------------+
//| The whole command path: receive -> idempotency -> account check -> |
//| expiry -> validate -> acknowledge -> execute (CONFIRM only) or     |
//| report SIMULATED. See ExecuteOrder above for the execution gate.   |
//+------------------------------------------------------------------+
void HandleOrderCommand(const string json)
{
   string commandId = JsonGetString(json, "id");
   string accountId = JsonGetString(json, "accountId");
   long   expiresAt = JsonGetLong(json, "expiresAt");
   string symbol    = JsonGetString(json, "symbol");
   string side      = JsonGetString(json, "side");
   string orderType = JsonGetString(json, "orderType");
   double volume    = JsonGetDouble(json, "volume");
   double sl        = JsonGetDouble(json, "sl");
   double tp        = JsonGetDouble(json, "tp");

   if(commandId == "")
   {
      Print("TradingOsAgent: execution.order missing 'id' — dropping (malformed frame, never crash).");
      return;
   }

   // Idempotency FIRST, before any other check: a replayed commandId
   // returns its prior result, no matter what (ADR 0010).
   string priorStatus, priorDetail;
   if(CommandStoreLookup(commandId, priorStatus, priorDetail))
   {
      SendAck(commandId, "DUPLICATE", "replayed commandId — returning the recorded result, never re-executing");
      SendReport(commandId, priorStatus, symbol, side, priorDetail);
      return;
   }

   // Account isolation (ADR 0010): never executed "at best" on the wrong account.
   if(accountId != InpAccountId)
   {
      string detail = "ACCOUNT_MISMATCH: command targets '" + accountId + "', this terminal serves '" + InpAccountId + "'";
      CommandStoreRecord(commandId, "REJECTED", detail);
      SendAck(commandId, "REJECTED", detail);
      SendReport(commandId, "REJECTED", symbol, side, detail);
      return;
   }

   long nowMs = (long)TimeGMT() * 1000;
   if(expiresAt > 0 && nowMs > expiresAt)
   {
      CommandStoreRecord(commandId, "EXPIRED", "command received after its expiresAt");
      SendAck(commandId, "EXPIRED", "command received after its expiresAt");
      return; // no execution.report for an expired command — it never reached validation
   }

   string rejectReason = ValidateOrderCommand(symbol, orderType, volume, sl);
   if(rejectReason != "")
   {
      CommandStoreRecord(commandId, "REJECTED", rejectReason);
      SendAck(commandId, "REJECTED", rejectReason);
      SendReport(commandId, "REJECTED", symbol, side, rejectReason);
      return;
   }

   SendAck(commandId, "ACCEPTED", "");

   // The fork. CONFIRM is the only branch that can reach a broker, and
   // ExecuteOrder re-checks the mode itself — this test is convenience, that
   // one is the barrier. In this build g_mode is const MODE_OBSERVE, so the
   // SIMULATED path below is the only one that ever runs.
   if(g_mode == MODE_CONFIRM)
   {
      ExecuteOrder(commandId, symbol, side, volume, sl, tp);
      return;
   }

   string simDetail = "SIMULATED " + DoubleToString(volume, 2) + " lot " + side + " " + symbol +
                       " (mode " + ModeToWireString(g_mode) + ", no broker order — CONFIRM is EA-07)";
   CommandStoreRecord(commandId, "SIMULATED", simDetail);
   SendReport(commandId, "SIMULATED", symbol, side, simDetail);
}

//+------------------------------------------------------------------+
//| reconcile — EA-06. Resolves every commandId this agent left UNKNOWN  |
//| (written by ExecuteOrder, before OrderSend, never rewritten if the   |
//| process dies before the broker answers). Runs on the heartbeat       |
//| cadence and on every connect, including the first one after a       |
//| restart (context/product/tools/EA-06-reconciliation.md).             |
//+------------------------------------------------------------------+
int ReconciliationAttemptsFor(const string commandId)
{
   for(int i = 0; i < ArraySize(g_reconciliation_ids); i++)
   {
      if(g_reconciliation_ids[i] == commandId)
      {
         return g_reconciliation_attempts[i];
      }
   }
   return 0;
}

void ReconciliationAttemptsBump(const string commandId)
{
   for(int i = 0; i < ArraySize(g_reconciliation_ids); i++)
   {
      if(g_reconciliation_ids[i] == commandId)
      {
         g_reconciliation_attempts[i]++;
         return;
      }
   }
   int n = ArraySize(g_reconciliation_ids);
   ArrayResize(g_reconciliation_ids, n + 1);
   ArrayResize(g_reconciliation_attempts, n + 1);
   g_reconciliation_ids[n] = commandId;
   g_reconciliation_attempts[n] = 1;
}

//--- Scans the ALREADY-SELECTED history (caller must HistorySelect first)
//    for commandId's trace: magic number == InpMagicNumber AND comment ==
//    "TradingOS "+commandId — the exact comment ExecuteOrder writes. Deals
//    are checked first (an opening deal proves a position exists); orders
//    are the fallback (a refused order can leave no deal at all). Position
//    identity ALWAYS comes from DEAL_POSITION_ID, never a ticket (ADR 0010;
//    the two diverge on broker service operations — 2026-09-05 incident,
//    session-log.md). Returns false — "not_found" — when neither history
//    carries this commandId's trace in the search window at all.
bool SearchHistoryForCommand(const string commandId, string &outcome, string &symbol, string &side,
                              long &brokerOrderId, long &brokerPositionId,
                              double &filledVolume, double &averagePrice)
{
   string needle = "TradingOS " + commandId;

   int totalDeals = HistoryDealsTotal();
   for(int i = 0; i < totalDeals; i++)
   {
      ulong dealTicket = HistoryDealGetTicket(i);
      if(dealTicket == 0)
      {
         continue;
      }
      if((int)HistoryDealGetInteger(dealTicket, DEAL_MAGIC) != InpMagicNumber)
      {
         continue;
      }
      if(HistoryDealGetString(dealTicket, DEAL_COMMENT) != needle)
      {
         continue;
      }
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(dealTicket, DEAL_ENTRY) != DEAL_ENTRY_IN)
      {
         continue; // an exit/reversal deal cannot originate a fresh position; not this commandId's opening deal
      }

      outcome = "executed";
      symbol = HistoryDealGetString(dealTicket, DEAL_SYMBOL);
      side = ((ENUM_DEAL_TYPE)HistoryDealGetInteger(dealTicket, DEAL_TYPE) == DEAL_TYPE_BUY) ? "BUY" : "SELL";
      brokerOrderId = (long)HistoryDealGetInteger(dealTicket, DEAL_ORDER);
      brokerPositionId = (long)HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID);
      filledVolume = HistoryDealGetDouble(dealTicket, DEAL_VOLUME);
      averagePrice = HistoryDealGetDouble(dealTicket, DEAL_PRICE);
      return true;
   }

   // No filled deal found. Check order history for a definite broker-side
   // refusal/cancel that never produced one — still a definite answer, just
   // a negative one. A FILLED order without a matching deal above would be
   // an inconsistent read; skip it rather than guess (stays not_found).
   int totalOrders = HistoryOrdersTotal();
   for(int i = 0; i < totalOrders; i++)
   {
      ulong orderTicket = HistoryOrderGetTicket(i);
      if(orderTicket == 0)
      {
         continue;
      }
      if((int)HistoryOrderGetInteger(orderTicket, ORDER_MAGIC) != InpMagicNumber)
      {
         continue;
      }
      if(HistoryOrderGetString(orderTicket, ORDER_COMMENT) != needle)
      {
         continue;
      }
      if((ENUM_ORDER_STATE)HistoryOrderGetInteger(orderTicket, ORDER_STATE) == ORDER_STATE_FILLED)
      {
         continue;
      }

      outcome = "rejected";
      symbol = HistoryOrderGetString(orderTicket, ORDER_SYMBOL);
      side = ((ENUM_ORDER_TYPE)HistoryOrderGetInteger(orderTicket, ORDER_TYPE) == ORDER_TYPE_BUY) ? "BUY" : "SELL";
      brokerOrderId = (long)orderTicket;
      brokerPositionId = 0;
      filledVolume = 0.0;
      averagePrice = 0.0;
      return true;
   }

   return false;
}

void ReconcileUnknownCommands()
{
   string unknownIds[];
   int count = CommandStoreFindUnknown(unknownIds);
   if(count == 0)
   {
      return;
   }

   datetime from = TimeCurrent() - InpReconciliationLookbackDays * 86400;
   if(!HistorySelect(from, TimeCurrent()))
   {
      Print("TradingOsAgent: HistorySelect failed for EA-06 reconciliation window, error ", GetLastError());
      return;
   }

   for(int i = 0; i < count; i++)
   {
      string commandId = unknownIds[i];
      ReconciliationAttemptsBump(commandId);
      int attempts = ReconciliationAttemptsFor(commandId);

      string outcome, symbol, side;
      long brokerOrderId, brokerPositionId;
      double filledVolume, averagePrice;
      bool found = SearchHistoryForCommand(commandId, outcome, symbol, side,
                                            brokerOrderId, brokerPositionId,
                                            filledVolume, averagePrice);

      if(!found)
      {
         // Stays UNKNOWN in the store — retried on the next heartbeat/connect.
         SendReconciled(commandId, "not_found", "", "", 0, 0, 0.0, 0.0, attempts,
                         "not found in the last " + IntegerToString(InpReconciliationLookbackDays) +
                         "d of history (attempt " + IntegerToString(attempts) + ") — will retry");
         continue;
      }

      // Reuses ExecuteOrder's own terminal vocabulary (FILLED/FAILED), not a
      // new one: a replayed commandId still goes through CommandStoreLookup
      // -> SendReport(priorStatus, ...), and priorStatus must stay one of
      // Mt5ReportMessage's valid statuses. The reconciled-vs-live distinction
      // lives in execution.reconciled below, sent either way, not in this
      // local string. FILLED covers a partial fill too (see EA-06 fiche
      // journal) — history does not by itself carry the originally requested
      // volume to tell the two apart, and nothing downstream currently reads
      // that distinction for an outcome this build can never yet produce.
      string detail = "EA-06 reconciliation: " + outcome + " (attempt " + IntegerToString(attempts) + ")";
      if(outcome == "executed")
      {
         CommandStoreRecord(commandId, "FILLED", detail);
      }
      else
      {
         CommandStoreRecord(commandId, "FAILED", detail);
      }
      SendReconciled(commandId, outcome, symbol, side, brokerOrderId, brokerPositionId,
                      filledVolume, averagePrice, attempts, detail);
   }
}

//+------------------------------------------------------------------+
//| scan — EA-06. Reports every currently open position exactly as the  |
//| terminal sees it right now, one message per position (JsonLite.mqh   |
//| parses flat objects only — no batching). Tags EXTERNAL_POSITION when  |
//| the magic number isn't ours (ADR 0010 isolation): WARN only, never a |
//| block — PositionsTotal() in ValidateOrderCommand already counts every|
//| position regardless of magic (fiche decision: attribute, don't       |
//| loosen). Same cadence as reconciliation (heartbeat + every connect). |
//+------------------------------------------------------------------+
void SendPositionScanned(const string brokerPositionId, const string symbol, const string side,
                          const double volume, const int magicNumber, const bool isExternal,
                          const string knownCommandId)
{
   long timeMs = (long)TimeGMT() * 1000;
   string json = "{";
   json += "\"version\":1,";
   json += "\"type\":\"execution.position.scan\",";
   json += "\"accountId\":\"" + JsonEscape(InpAccountId) + "\",";
   json += "\"time\":" + IntegerToString(timeMs) + ",";
   json += "\"brokerPositionId\":\"" + JsonEscape(brokerPositionId) + "\",";
   json += "\"symbol\":\"" + JsonEscape(symbol) + "\",";
   json += "\"side\":\"" + JsonEscape(side) + "\",";
   json += "\"volume\":" + DoubleToString(volume, 2) + ",";
   json += "\"magicNumber\":" + IntegerToString(magicNumber) + ",";
   json += "\"isExternal\":" + (isExternal ? "true" : "false") + ",";
   json += (knownCommandId == "" ? "\"knownCommandId\":null" : "\"knownCommandId\":\"" + JsonEscape(knownCommandId) + "\"");
   json += "}";
   SendRawLine(json);
}

void ScanOpenPositions()
{
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i); // selects the position by index — ticket itself is never sent as identity
      if(ticket == 0)
      {
         continue;
      }

      int magic = (int)PositionGetInteger(POSITION_MAGIC);
      bool isExternal = (magic != InpMagicNumber);

      string knownCommandId = "";
      if(!isExternal)
      {
         string comment = PositionGetString(POSITION_COMMENT);
         string prefix = "TradingOS ";
         if(StringFind(comment, prefix) == 0)
         {
            knownCommandId = StringSubstr(comment, StringLen(prefix));
         }
      }
      else
      {
         Print("TradingOsAgent: EXTERNAL_POSITION — identifier ",
               (long)PositionGetInteger(POSITION_IDENTIFIER), " on ", PositionGetString(POSITION_SYMBOL),
               ", magic ", magic, " (this agent's magic is ", InpMagicNumber,
               ") — already counted in PositionsTotal() exposure, WARN only (EA-06 fiche decision).");
      }

      // POSITION_IDENTIFIER only, never POSITION_TICKET — the two diverge on
      // broker service operations (2026-09-05 incident, session-log.md);
      // same rule as every other brokerPositionId on this wire.
      string identifier = IntegerToString((long)PositionGetInteger(POSITION_IDENTIFIER));
      string side = ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      SendPositionScanned(identifier, PositionGetString(POSITION_SYMBOL), side,
                           PositionGetDouble(POSITION_VOLUME), magic, isExternal, knownCommandId);
   }
}
