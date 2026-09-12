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
//| THIS BUILD CONTAINS NO OrderSend CALL. That is not an oversight —   |
//| it is EA-05 increment 6, and it is added only after a separate,     |
//| explicit approval (context/product/tools/EA-05-agent-mql5.md). A   |
//| command that passes every local barrier is acknowledged and        |
//| reported SIMULATED, exactly like the read-only Python observer's    |
//| own stub loop (tools/mt5-observer/mt5_observer.py) — validated       |
//| end-to-end, at zero financial risk, before a single line of order   |
//| code exists in this file.                                          |
//|                                                                     |
//| Mode is a physical barrier, not a switch (ADR 0010): this build     |
//| never sets any mode other than OBSERVE — there is no code path      |
//| that could. Reaching CONFIRM in a working system requires EA-07's   |
//| mode ladder, which does not exist yet either.                       |
//+------------------------------------------------------------------+
#property copyright "Trading Operating System — personal use only"
#property version   "1.00"
#property description "EA-05 execution agent — OBSERVE only, no OrderSend in this build."

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
input int    InpMaxOpenPositions  = 3;           // local barrier — counts ALL positions on this terminal; excluding external ones is EA-06
input int    InpMaxSpreadPoints   = 50;          // local barrier, re-checked at validation time, not just at proposal time
input string InpAllowedSymbolsCsv = "EURUSDm,GBPUSDm"; // local whitelist — broker-side names (context/domain/symbols-broker.md)

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
   int written = StringToCharArray(withNewline, data, 0, StringLen(withNewline), CP_UTF8);
   int len = written - 1; // StringToCharArray appends a trailing terminator; exclude it from the wire
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

void SendReport(const string commandId, const string status, const string symbol, const string side, const string detail)
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
   json += "\"brokerOrderId\":null,";
   json += "\"brokerPositionId\":null,";
   json += "\"filledVolume\":null,";
   json += "\"averagePrice\":null,";
   json += "\"brokerRetcode\":null,";
   json += "\"detail\":\"" + JsonEscape(detail) + "\"";
   json += "}";
   SendRawLine(json);
}

//+------------------------------------------------------------------+
//| The whole command path: receive -> idempotency -> account check -> |
//| expiry -> validate -> acknowledge -> report. NO EXECUTE STEP EXISTS |
//| — every accepted command reports SIMULATED. See the file header.   |
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
   string simDetail = "SIMULATED " + DoubleToString(volume, 2) + " lot " + side + " " + symbol +
                       " (observe-only build, no broker order — EA-05 increment 6 not yet approved)";
   CommandStoreRecord(commandId, "SIMULATED", simDetail);
   SendReport(commandId, "SIMULATED", symbol, side, simDetail);
}
