//+------------------------------------------------------------------+
//| TradingOsAgent.mq5 — EA-05                                        |
//|                                                                   |
//| Execution agent for the Trading Operating System (ADR 0010). It   |
//| connects to the core over a local TCP socket, receives            |
//| commands, validates them against local safety barriers            |
//| (context/execution/safety.md), and reports the outcome. It decides|
//| NOTHING: no strategy, no signal, no market analysis, no decision  |
//| parameter. It does not know why it executes.                      |
//|                                                                   |
//| THIS FILE CONTAINS THE ONLY OrderSend CALL IN THE REPOSITORY      |
//| (EA-05 increment 6, added 2026-09-15 on the separate explicit     |
//| approval that ADR 0010 requires). It lives in exactly one function,|
//| ExecuteOrder, whose first statement returns unless the mode is    |
//| CONFIRM — grep OrderSend and read that function: there is no      |
//| execution path that reaches the broker without passing that test. |
//|                                                                   |
//| Mode is a physical barrier, not a switch (ADR 0010): g_mode below |
//| is a compile-time const set to MODE_OBSERVE, so in THIS build the |
//| guard can never pass and the whole execution body is provably dead|
//| code. The approvals of 2026-09-25/26 (ADR 0014 arming, EA-07,     |
//| EA-08, ADR 0015) open that path increment by increment (study I4  |
//| to I8) — not in this build. A command that passes every local     |
//| barrier is still acknowledged and reported SIMULATED today.       |
//|                                                                   |
//| I1 (2026-09-26) hardens the agent without touching that barrier:  |
//|  - identity from the terminal (ACCOUNT_LOGIN / ACCOUNT_SERVER), not|
//|    from an input — InpAccountId is only an optional expectation, and|
//|    a mismatch keeps the agent loaded but refusing (never INIT_FAILED,|
//|    which would detach it on every account switch);                |
//|  - a local halt that works with the core off: chart button,    |
//|    control.halt (can only set it) or a file; persisted on disk;   |
//|  - one instance per terminal;                                     |
//|  - a per-symbol spread limit in price units (a single point limit |
//|    of 50 refused every XAUUSDm order, whose normal spread is ~260 |
//|    points at 3 digits);                                           |
//|  - the core's agent token (read from MQL5\Files, never an input); |
//|  - hello and heartbeat publish the mode ceiling and effective mode,|
//|    the build, margin mode and FIFO, the four trading permissions, |
//|    the halt, and every other EA attached to this terminal;        |
//|  - a short order trace (<= 31 chars), filling mode from the symbol,|
//|    a store per login whose write failure blocks an order, and final|
//|    reports sent again after a reconnection.                       |
//|                                                                   |
//| 1.12 (ADR 0029, 2026-11-01) gives the agent the handlers the core  |
//| already speaks: LIMIT (a pending order that always expires at the  |
//| broker), MODIFY (a stop that only tightens), CLOSE, PARTIAL_CLOSE  |
//| and CANCEL. Every handler builds a TradeCommand and goes through   |
//| the same chain; ExecuteOrder stays the ONE function that sends, and|
//| its first statement is unchanged. The mode is still a compiled     |
//| constant at OBSERVE: all of this answers SIMULATED in this build.  |
//| 1.13 (ADR 0033, 2026-11-02): the local halt no longer refuses a    |
//| command that only closes or cancels — it stops new risk, not the   |
//| way out. Openings and stop moves are still refused while halted.   |
//|                                                                   |
//| It still decides NOTHING: no strategy, no signal, no market       |
//| analysis, no decision parameter. It does not know why it executes.|
//+------------------------------------------------------------------+
#property copyright "Trading Operating System — personal use only"
#property version   "1.13"
#property description "EA-05 execution agent (ADR 0029) — OrderSend exists once, in ExecuteOrder, unreachable outside CONFIRM; this build is OBSERVE."

#include "Include/JsonLite.mqh"
#include "Include/CommandStore.mqh"
#include "Include/TradeRequest.mqh"

#define AGENT_VERSION      "1.13"
#define INSTANCE_LOCK      "TradingOsAgent.instance"
#define HALT_BUTTON        "TradingOsAgent.halt"
#define HALT_FILE_ALL      "tradingos_halt.flag"
#define CORE_TOKEN_FILE "tradingos_agent.token"

//--- Inputs: configuration and bounds only (ADR 0007/0010) — never a
//    decision parameter, and no default is a guess dressed as a fact.
input string InpCoreHost       = "127.0.0.1"; // The Python core's host — loopback only, this is a personal-use, single-machine system
input int    InpCorePort       = 9765;        // Must match EA_LINK_PORT of the Python core (default 9765)
input string InpAccountId         = "";          // OPTIONAL since I1: the login this terminal is expected to be on. Empty = serve whatever login it is on. Set and different = refuse every command (identity "mismatch")
input int    InpMagicNumber       = 0;           // REQUIRED: unique per environment (ADR 0010 isolation) — refuses to start if <= 0
input string InpTradableLogins    = "";          // I1: logins on which an order may EVER reach the broker (CONFIRM only, not in this build). CSV; empty = none
input string InpClosableLogins    = "";          // I1: logins on which a close may EVER reach the broker (EA-08, I5 — not in this build). CSV; empty = none
input int    InpHeartbeatSeconds  = 5;
input double InpMaxVolumePerOrder = 1.0;         // lots — local barrier, last line of defense, never a decision
input int    InpMaxOpenPositions  = 3;           // local barrier — counts ALL positions on this terminal, deliberately including external ones (EA-06 fiche decision: attribute via EXTERNAL_POSITION/WARN, never loosen this count)
input string InpMaxSpreadCsv      = "";          // I1: maximum spread per symbol in PRICE units, e.g. "EURUSDm=0.00025,XAUUSDm=0.40" (2.5 pips; 40 cents). A symbol without an entry refuses every order — fail closed
input string InpAllowedSymbolsCsv = "XAUUSDm,EURUSDm"; // local whitelist — broker-side names (context/domain/symbols-broker.md); XAUUSD + EURUSD since 2026-09-25, GBPUSD set aside
input int    InpMaxSlippagePoints = 10;          // EA-05 inc. 6: MqlTradeRequest.deviation — a bound on the fill, never a decision
input int    InpPendingMaxMinutes = 60;          // 1.12: a pending (LIMIT) order always expires at the broker after this many minutes. 1..1440; anything else is read as 60 — it can be shortened or lengthened, never removed
input int    InpReconciliationLookbackDays = 7;  // EA-06: how far back HistorySelect searches to resolve an UNKNOWN commandId
input int    InpReportReplayMinutes = 60;        // I1: final reports recorded this recently are sent again after a reconnection
input int    InpDeadManSeconds    = 30;          // Python-native core: a NEW order is refused (DEAD_MAN) when no control.ping has arrived from the core for this long. 5..600; anything lower is read as 30 — it can be loosened, never switched off. A received order is not proof the core is alive; only the ping is. Stops already at the broker stay.

//--- Execution mode ladder (ADR 0010): OBSERVE -> PAPER -> CONFIRM.
//    AUTO (ADR 0015) is not a value of this enum yet: it arrives with its
//    own increment (I8), not as a fourth value slipped in here.
enum ExecutionMode
{
   MODE_OBSERVE,
   MODE_PAPER,
   MODE_CONFIRM
};

//--- Fixed at OBSERVE for the whole lifetime of this build. Not an input,
//    not settable by any message this file handles — control.set_mode is
//    logged and ignored. This is the "physical barrier, not a switch"
//    requirement made literal: there is no variable anyone can flip.
const ExecutionMode g_mode = MODE_OBSERVE;

//--- I1: the highest mode this BUILD may ever run in, published in every
//    hello and heartbeat. Arming (ADR 0014, I4) will raise the effective
//    mode up to this ceiling and never above it; in this build the two are
//    the same constant.
const ExecutionMode g_mode_ceiling = MODE_OBSERVE;

int      g_socket = INVALID_HANDLE;
bool     g_connected = false;
datetime g_last_heartbeat_sent = 0;
string   g_recv_buffer = "";

//--- I1: identity, read from the terminal — never from an input.
long   g_login = 0;
string g_account_id = "";          // the Trading OS accountId: the login, as text (the core uses the same)
string g_server = "";
string g_identity = "no_account";  // "ok" | "mismatch" | "no_account"
bool   g_tradable = false;         // login listed in InpTradableLogins
bool   g_closable = false;         // login listed in InpClosableLogins

bool   g_owns_instance_lock = false;
ulong  g_last_core_seen_ms = 0; // GetTickCount64() of the last line from the core
ulong  g_last_ping_ms = 0;         // GetTickCount64() of the last control.ping — 0 until the first one on THIS connection (dead-man switch)
bool   g_token_missing_reported = false;
bool   g_connect_failure_reported = false;

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
   if(InpMagicNumber <= 0)
   {
      Print("TradingOsAgent: InpMagicNumber must be a positive value, unique per environment (ADR 0010 isolation). Refusing to start.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!AcquireInstanceLock())
   {
      Print("TradingOsAgent: another TradingOsAgent is already running in this terminal — one instance per terminal (ADR 0010). This one removes itself.");
      return INIT_FAILED;
   }

   ResolveIdentity();
   CommandStoreInit(g_login, InpMagicNumber);
   CreateHaltButton();
   if(g_identity == "mismatch")
   {
      Print("TradingOsAgent: terminal is on login ", g_account_id, " but InpAccountId expects '", InpAccountId,
            "' — staying loaded, refusing every command until they agree.");
   }

   if(g_login > 0 && !ConnectToCore())
   {
      g_connect_failure_reported = true;
      Print("TradingOsAgent: initial connection to ", InpCoreHost, ":", InpCorePort,
            " failed (error ", GetLastError(), ") — will retry on timer, silently.");
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
   g_connected = false;
   ObjectDelete(0, HALT_BUTTON);
   if(g_owns_instance_lock)
   {
      GlobalVariableSetOnCondition(INSTANCE_LOCK, 0.0, 1.0);
      g_owns_instance_lock = false;
   }
}

//+------------------------------------------------------------------+
//| This agent is timer-driven, not tick-driven: no OnTick is defined. |
//| It never acts on a price move by itself — only on messages from    |
//| the core and its own heartbeat clock (ADR 0010: orient event,   |
//| not tick; avoid the hyperactivity a prop firm's servers would flag |
//| if a stop were touched on every tick).                             |
//+------------------------------------------------------------------+
void OnTimer()
{
   // I1: the terminal can change accounts under us. OnInit runs again on
   // REASON_ACCOUNT; this check covers a change that arrives without it.
   if(AccountInfoInteger(ACCOUNT_LOGIN) != g_login)
   {
      Print("TradingOsAgent: terminal login changed (", g_account_id, " -> ",
            IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)), ") — re-identifying before anything else.");
      if(g_socket != INVALID_HANDLE)
      {
         SocketClose(g_socket);
         g_socket = INVALID_HANDLE;
      }
      g_connected = false;
      ResolveIdentity();
      CommandStoreInit(g_login, InpMagicNumber);
      RefreshHaltButton();
   }

   if(g_login <= 0)
   {
      return; // no account: nothing to serve, nothing to say to the core
   }

   if(g_socket == INVALID_HANDLE || !SocketIsConnected(g_socket))
   {
      g_connected = false;
      if(!ConnectToCore())
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
//| I1: the chart button is the local kill switch's human side.        |
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
   if(id != CHARTEVENT_OBJECT_CLICK || sparam != HALT_BUTTON)
   {
      return;
   }
   ObjectSetInteger(0, HALT_BUTTON, OBJPROP_STATE, false);
   if(!IsHalted())
   {
      SetHalt("chart button"); // stopping must be one click, never a dialog
   }
   else if(MessageBox("Lever le halt de l'agent Trading OS ?\n\nIl pourra de nouveau recevoir des ordres de la passerelle.",
                      "TradingOsAgent", MB_YESNO | MB_ICONQUESTION) == IDYES)
   {
      ClearHalt("chart button");
   }
   RefreshHaltButton();
   if(g_connected)
   {
      SendHeartbeat(); // the core learns it now, not in up to 5 s
   }
}

//+------------------------------------------------------------------+
//| identity                                                           |
//+------------------------------------------------------------------+
void ResolveIdentity()
{
   g_login = AccountInfoInteger(ACCOUNT_LOGIN);
   g_server = AccountInfoString(ACCOUNT_SERVER);
   g_account_id = g_login > 0 ? IntegerToString(g_login) : "";
   if(g_login <= 0)
   {
      g_identity = "no_account";
   }
   else if(InpAccountId != "" && InpAccountId != g_account_id)
   {
      g_identity = "mismatch";
   }
   else
   {
      g_identity = "ok";
   }
   g_tradable = g_login > 0 && CsvContains(InpTradableLogins, g_account_id);
   g_closable = g_login > 0 && CsvContains(InpClosableLogins, g_account_id);
}

bool CsvContains(const string csv, const string value)
{
   string parts[];
   int n = StringSplit(csv, ',', parts);
   for(int i = 0; i < n; i++)
   {
      string candidate = parts[i];
      StringTrimLeft(candidate);
      StringTrimRight(candidate);
      if(candidate != "" && candidate == value)
      {
         return true;
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| single instance                                                    |
//| A temporary terminal variable dies with the terminal, so a crash   |
//| never leaves a stale lock across a restart. Set-on-condition is    |
//| atomic: of two instances starting together, exactly one wins.      |
//+------------------------------------------------------------------+
bool AcquireInstanceLock()
{
   if(!GlobalVariableCheck(INSTANCE_LOCK))
   {
      GlobalVariableTemp(INSTANCE_LOCK); // created at 0
   }
   if(GlobalVariableSetOnCondition(INSTANCE_LOCK, 1.0, 0.0))
   {
      g_owns_instance_lock = true;
      return true;
   }
   // Held: by a live instance on another chart, or left behind by one that
   // stopped without OnDeinit (a critical runtime error). Only the first
   // is a reason to leave.
   if(OtherChartRunsThisAgent())
   {
      return false;
   }
   GlobalVariableSet(INSTANCE_LOCK, 1.0);
   g_owns_instance_lock = true;
   return true;
}

bool OtherChartRunsThisAgent()
{
   string self = MQLInfoString(MQL_PROGRAM_NAME);
   long me = ChartID();
   for(long chart = ChartFirst(); chart >= 0; chart = ChartNext(chart))
   {
      if(chart != me && ChartGetString(chart, CHART_EXPERT_NAME) == self)
      {
         return true;
      }
   }
   return false;
}

//--- I1: every OTHER expert attached in this terminal. The Algo Trading
//    button arms all of them at once, not just this one — the arming
//    pre-flight (I4) refuses while this list is not empty.
string AttachedExpertsJson()
{
   string json = "[";
   bool first = true;
   long me = ChartID();
   for(long chart = ChartFirst(); chart >= 0; chart = ChartNext(chart))
   {
      if(chart == me)
      {
         continue;
      }
      string name = ChartGetString(chart, CHART_EXPERT_NAME);
      if(name == "")
      {
         continue;
      }
      json += (first ? "" : ",") + "\"" + JsonEscape(name) + "\"";
      first = false;
   }
   return json + "]";
}

//+------------------------------------------------------------------+
//| local halt (context/execution/safety.md: "Kill switch local")      |
//| Source of truth: a file in MQL5\Files, so it survives a restart    |
//| and works with the core off. tradingos_halt.flag halts any      |
//| login (drop it by hand in an emergency); tradingos_halt_<login>.flag|
//| is what the button and control.halt write. Halting never closes a  |
//| position, and never stops a close (EA-08, I5).                     |
//+------------------------------------------------------------------+
string HaltFileForLogin()
{
   return "tradingos_halt_" + g_account_id + ".flag";
}

bool IsHalted()
{
   return FileIsExist(HALT_FILE_ALL) || (g_account_id != "" && FileIsExist(HaltFileForLogin()));
}

bool SetHalt(const string origin)
{
   string file = g_account_id != "" ? HaltFileForLogin() : HALT_FILE_ALL;
   int handle = FileOpen(file, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
   {
      Print("TradingOsAgent: could NOT write the halt file '", file, "' (error ", GetLastError(),
            ") — the halt is not persisted.");
      return false;
   }
   FileWrite(handle, "halted by " + origin + " at " + TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS) + " UTC");
   FileClose(handle);
   Print("TradingOsAgent: HALT set by ", origin, " — every new command is refused until a human lifts it on the chart.");
   RefreshHaltButton();
   return true;
}

void ClearHalt(const string origin)
{
   FileDelete(HALT_FILE_ALL);
   if(g_account_id != "")
   {
      FileDelete(HaltFileForLogin());
   }
   Print("TradingOsAgent: halt lifted by ", origin, ".");
}

void CreateHaltButton()
{
   if(ObjectFind(0, HALT_BUTTON) < 0)
   {
      ObjectCreate(0, HALT_BUTTON, OBJ_BUTTON, 0, 0, 0);
   }
   ObjectSetInteger(0, HALT_BUTTON, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
   ObjectSetInteger(0, HALT_BUTTON, OBJPROP_XDISTANCE, 190);
   ObjectSetInteger(0, HALT_BUTTON, OBJPROP_YDISTANCE, 24);
   ObjectSetInteger(0, HALT_BUTTON, OBJPROP_XSIZE, 180);
   ObjectSetInteger(0, HALT_BUTTON, OBJPROP_YSIZE, 28);
   ObjectSetInteger(0, HALT_BUTTON, OBJPROP_FONTSIZE, 9);
   ObjectSetString(0, HALT_BUTTON, OBJPROP_FONT, "Arial Bold");
   ObjectSetInteger(0, HALT_BUTTON, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, HALT_BUTTON, OBJPROP_HIDDEN, true);
   RefreshHaltButton();
}

void RefreshHaltButton()
{
   if(ObjectFind(0, HALT_BUTTON) < 0)
   {
      return;
   }
   bool halted = IsHalted();
   ObjectSetString(0, HALT_BUTTON, OBJPROP_TEXT, halted ? "AGENT HALTED - click to lift" : "HALT Trading OS agent");
   ObjectSetInteger(0, HALT_BUTTON, OBJPROP_BGCOLOR, halted ? clrDarkOrange : clrFireBrick);
   ObjectSetInteger(0, HALT_BUTTON, OBJPROP_COLOR, clrWhite);
   ObjectSetInteger(0, HALT_BUTTON, OBJPROP_BORDER_COLOR, clrBlack);
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| connect                                                            |
//+------------------------------------------------------------------+
bool ConnectToCore()
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

   if(!SocketConnect(g_socket, InpCoreHost, InpCorePort, 1000))
   {
      SocketClose(g_socket);
      g_socket = INVALID_HANDLE;
      return false;
   }

   g_connected = true;
   g_connect_failure_reported = false;
   g_recv_buffer = "";
   g_last_core_seen_ms = GetTickCount64();
   g_last_ping_ms = 0; // a new connection starts without proof of life: the core must ping before any order is accepted
   SendHello();
   g_last_heartbeat_sent = TimeGMT();
   // I1: outcomes recorded while the link was down (or just before it
   // dropped) reach the core now; it keeps one row per report.
   ReplayRecentReports();
   // EA-06: always on connect, including the first one after a restart —
   // that restart is exactly when an UNKNOWN left behind by a crash between
   // the broker call and its ack most needs resolving (fiche decision).
   ReconcileUnknownCommands();
   ScanOpenPositions();
   return true;
}

//--- I1: the core's agent token (TRADINGOS_AGENT_TOKEN), written by scripts/start.ps1 into this
//    terminal's MQL5\Files. Never an input: an input lands in the preset
//    file and in the chart's properties. Limit, written down in the study:
//    any MQL5 program running in this terminal can read MQL5\Files too.
string ReadCoreToken()
{
   int handle = FileOpen(CORE_TOKEN_FILE, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
   {
      if(!g_token_missing_reported)
      {
         g_token_missing_reported = true;
         Print("TradingOsAgent: ", CORE_TOKEN_FILE, " not found in MQL5\\Files — the core will refuse this agent. ",
               "Run scripts/start.ps1: it writes the file.");
      }
      return "";
   }
   string token = FileReadString(handle);
   FileClose(handle);
   StringTrimLeft(token);
   StringTrimRight(token);
   g_token_missing_reported = false;
   return token;
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
   return CsvContains(InpAllowedSymbolsCsv, symbol);
}

//--- I1: the maximum spread for `symbol`, in price units, from
//    InpMaxSpreadCsv — or -1 when the symbol has no entry (every order on
//    it is then refused: no limit is never "unlimited").
double MaxSpreadFor(const string symbol)
{
   string parts[];
   int n = StringSplit(InpMaxSpreadCsv, ',', parts);
   for(int i = 0; i < n; i++)
   {
      string entry = parts[i];
      int eq = StringFind(entry, "=");
      if(eq <= 0)
      {
         continue;
      }
      string name = StringSubstr(entry, 0, eq);
      string value = StringSubstr(entry, eq + 1);
      StringTrimLeft(name);
      StringTrimRight(name);
      StringTrimLeft(value);
      StringTrimRight(value);
      if(name == symbol)
      {
         double limit = StringToDouble(value);
         return limit > 0 ? limit : -1;
      }
   }
   return -1;
}

//--- I1: the filling mode this symbol accepts — IOC when allowed (partial
//    fills of a small market order are acceptable), else FOK, else RETURN.
ENUM_ORDER_TYPE_FILLING FillingModeFor(const string symbol)
{
   long filling = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
   {
      return ORDER_FILLING_IOC;
   }
   if((filling & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
   {
      return ORDER_FILLING_FOK;
   }
   return ORDER_FILLING_RETURN;
}

string FillingModeLabel(const string symbol)
{
   if(symbol == "")
   {
      return "IOC";
   }
   ENUM_ORDER_TYPE_FILLING filling = FillingModeFor(symbol);
   if(filling == ORDER_FILLING_IOC) return "IOC";
   if(filling == ORDER_FILLING_FOK) return "FOK";
   return "RETURN";
}

string TradeModeLabel()
{
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(mode == ACCOUNT_TRADE_MODE_DEMO)    return "demo";
   if(mode == ACCOUNT_TRADE_MODE_CONTEST) return "contest";
   if(mode == ACCOUNT_TRADE_MODE_REAL)    return "real";
   return "unknown";
}

string MarginModeLabel()
{
   long mode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(mode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING) return "hedging";
   if(mode == ACCOUNT_MARGIN_MODE_RETAIL_NETTING) return "netting";
   if(mode == ACCOUNT_MARGIN_MODE_EXCHANGE)       return "exchange";
   return "unknown";
}

string JsonBool(const bool value)
{
   return value ? "true" : "false";
}

//--- Broker ids and retcodes are STRINGS on the wire (lib/contracts/mt5-wire.ts:
//    a 64-bit ticket does not survive a JavaScript number). Until I1 they went
//    out as bare numbers, which the core's parser refused: the report of the
//    first real fill would have been dropped as a malformed frame. 0 = null.
string JsonIdOrNull(const long value)
{
   return value == 0 ? "null" : "\"" + IntegerToString(value) + "\"";
}

//--- I1: the four independent permissions an order needs (none of them
//    can be set by code): the terminal's Algo Trading button, this EA's
//    "Allow Algo Trading" box, and the account's two server-side flags —
//    trade_allowed is false with an investor password.
string PermissionsJsonFields()
{
   string json = "";
   json += "\"terminalTradeAllowed\":" + JsonBool(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) != 0) + ",";
   json += "\"expertTradeAllowed\":" + JsonBool(MQLInfoInteger(MQL_TRADE_ALLOWED) != 0) + ",";
   json += "\"accountTradeExpert\":" + JsonBool(AccountInfoInteger(ACCOUNT_TRADE_EXPERT) != 0) + ",";
   json += "\"accountTradeAllowed\":" + JsonBool(AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) != 0) + ",";
   return json;
}

string BuildId()
{
   return AGENT_VERSION + " " + TimeToString(__DATETIME__, TIME_DATE | TIME_MINUTES);
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
   json += "\"accountId\":\"" + JsonEscape(g_account_id) + "\",";
   json += "\"time\":" + IntegerToString(timeMs) + ",";
   json += "\"agentId\":\"" + JsonEscape(GetAgentId()) + "\",";
   // NOTE: agent.hello carries a single `symbol` field (python/trading_os/infrastructure/mt5/wire.py)
   // — a legacy of the single-symbol prototype. This agent's
   // whitelist may name several symbols; only the first is reported here.
   // Known limitation, not silently papered over — see EA-05 fiche journal.
   json += "\"symbol\":\"" + JsonEscape(symbol) + "\",";
   json += "\"broker\":\"" + JsonEscape(AccountInfoString(ACCOUNT_COMPANY)) + "\",";
   json += "\"server\":\"" + JsonEscape(g_server) + "\",";
   json += "\"orderTypes\":[\"market\",\"limit\"],";
   json += "\"minVolume\":" + DoubleToString(minVol, 2) + ",";
   json += "\"maxVolume\":" + DoubleToString(maxVol, 2) + ",";
   json += "\"volumeStep\":" + DoubleToString(volStep, 2) + ",";
   json += "\"fillingMode\":\"" + FillingModeLabel(symbol) + "\",";
   json += "\"stopsLevelPoints\":" + IntegerToString(stopsLevel) + ",";
   json += "\"mode\":\"" + ModeToWireString(g_mode) + "\",";
   json += "\"agentVersion\":\"" + AGENT_VERSION + "\",";
   json += "\"serverUtcOffsetMinutes\":" + IntegerToString(ServerUtcOffsetMinutes()) + ",";
   // I1 — everything below is new. The token is checked by the core and
   // never stored or logged there.
   json += "\"token\":\"" + JsonEscape(ReadCoreToken()) + "\",";
   // dead_man: refuses new orders when the core stops pinging (1.11). limit, modify, close, cancel (1.12, ADR 0029): the core sends
   // those commands only to an agent that says it has a handler for them — they are validated here whatever the mode.
   json += "\"capabilities\":[\"ping\",\"halt\",\"dead_man\",\"limit\",\"modify\",\"close\",\"cancel\"],";
   json += "\"buildId\":\"" + JsonEscape(BuildId()) + "\",";
   json += "\"modeCeiling\":\"" + ModeToWireString(g_mode_ceiling) + "\",";
   json += "\"identity\":\"" + g_identity + "\",";
   json += (InpAccountId == "" ? "\"expectedAccountId\":null," : "\"expectedAccountId\":\"" + JsonEscape(InpAccountId) + "\",");
   json += "\"tradeMode\":\"" + TradeModeLabel() + "\",";
   json += "\"marginMode\":\"" + MarginModeLabel() + "\",";
   json += "\"fifoClose\":" + JsonBool(AccountInfoInteger(ACCOUNT_FIFO_CLOSE) != 0) + ",";
   json += "\"leverage\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LEVERAGE)) + ",";
   json += "\"currency\":\"" + JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)) + "\",";
   json += PermissionsJsonFields();
   json += "\"tradable\":" + JsonBool(g_tradable) + ",";
   json += "\"closable\":" + JsonBool(g_closable) + ",";
   json += "\"halted\":" + JsonBool(IsHalted()) + ",";
   json += "\"attachedExperts\":" + AttachedExpertsJson();
   json += "}";
   SendRawLine(json);
}

void SendHeartbeat()
{
   long timeMs = (long)TimeGMT() * 1000;
   string json = "{";
   json += "\"version\":1,";
   json += "\"type\":\"agent.heartbeat\",";
   json += "\"accountId\":\"" + JsonEscape(g_account_id) + "\",";
   json += "\"time\":" + IntegerToString(timeMs) + ",";
   json += "\"agentId\":\"" + JsonEscape(GetAgentId()) + "\",";
   json += "\"latencyMs\":0,";
   // I1: what can change while connected — someone clicks Algo Trading,
   // attaches another EA, halts from the chart.
   json += "\"mode\":\"" + ModeToWireString(g_mode) + "\",";
   json += "\"identity\":\"" + g_identity + "\",";
   json += PermissionsJsonFields();
   json += "\"halted\":" + JsonBool(IsHalted()) + ",";
   json += "\"coreSilentMs\":" + IntegerToString((long)(GetTickCount64() - g_last_core_seen_ms)) + ",";
   json += "\"attachedExperts\":" + AttachedExpertsJson();
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
   // stripped the "\n" instead and the core, which reads line by line,
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
         g_last_core_seen_ms = GetTickCount64();
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
   else if(type == "execution.modify")
   {
      HandleModifyCommand(json);
   }
   else if(type == "execution.close")
   {
      HandleCloseCommand(json);
   }
   else if(type == "execution.cancel")
   {
      HandleCancelCommand(json);
   }
   else if(type == "control.ping")
   {
      // The core's liveness beat (every 5 s). It is the ONLY thing that feeds
      // the dead-man clock: g_last_core_seen_ms moves on every line, an
      // order included, and an order is not proof the core is alive.
      g_last_ping_ms = GetTickCount64();
   }
   else if(type == "control.halt")
   {
      // I1: the core may SET the halt, never lift it — only a human on
      // the chart does that (OnChartEvent).
      string reason = JsonGetString(json, "reason");
      SetHalt("the core" + (reason == "" ? "" : " (" + reason + ")"));
      SendHeartbeat(); // carries halted:true — the acknowledgement
   }
   else if(type == "control.set_mode")
   {
      Print("TradingOsAgent: control.set_mode received but not implemented in this build (arming is I4) — ignored.");
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
//| dead-man switch                                                    |
//| The agent refuses every NEW order while the core's liveness is in   |
//| doubt: no control.ping since the connection was made, or none for    |
//| DeadManSeconds(). A refusal only — it opens nothing and closes       |
//| nothing, and it never touches a stop already placed at the broker.   |
//| Empty return = the core is alive as far as this agent can tell.      |
//+------------------------------------------------------------------+
int DeadManSeconds()
{
   return (InpDeadManSeconds >= 5 && InpDeadManSeconds <= 600) ? InpDeadManSeconds : 30;
}

string DeadManReason()
{
   if(g_last_ping_ms == 0)
   {
      return "DEAD_MAN: no ping received yet on this connection — the core's liveness is not established";
   }
   ulong silentMs = GetTickCount64() - g_last_ping_ms;
   if(silentMs > (ulong)DeadManSeconds() * 1000)
   {
      return "DEAD_MAN: no ping for " + IntegerToString((long)(silentMs / 1000)) + "s (limit " + IntegerToString(DeadManSeconds()) + "s)";
   }
   return "";
}

//+------------------------------------------------------------------+
//| validate                                                           |
//| Local barriers, last line of defense — never a decision (ADR 0007/ |
//| 0010); context/execution/safety.md documents the reasoning behind   |
//| each one. Empty return = no objection. A typed code leads each      |
//| reason (protocol.md, CommandRejectCode).                            |
//+------------------------------------------------------------------+
string ValidateTradeCommand(TradeCommand &cmd)
{
   string dead = DeadManReason();
   if(dead != "")
   {
      return dead;
   }
   if(!IsAllowedSymbol(cmd.symbol))
   {
      return "SYMBOL_MISMATCH: symbol '" + cmd.symbol + "' is not in the local whitelist";
   }
   if(cmd.kind == "OPEN")
   {
      return ValidateOpenCommand(cmd);
   }
   if(cmd.kind == "MODIFY")
   {
      return ValidateModifyCommand(cmd);
   }
   if(cmd.kind == "CLOSE" || cmd.kind == "PARTIAL_CLOSE")
   {
      return ValidateCloseCommand(cmd);
   }
   if(cmd.kind == "CANCEL")
   {
      return ValidateCancelCommand(cmd);
   }
   return "INVALID_REQUEST: unknown command kind '" + cmd.kind + "'";
}

//--- OPEN, at the market or resting (LIMIT). The barriers of 1.11 are all here, in their order and with their codes; 1.12
//    adds the symbol's own volume rules, the side of the stop and the target, the broker's stops level and, for a LIMIT, the
//    price and the lifetime. Pending orders count with the positions: a resting order is a position that has not filled yet.
string ValidateOpenCommand(TradeCommand &cmd)
{
   if(cmd.orderType != "MARKET" && cmd.orderType != "LIMIT")
   {
      return "ORDER_TYPE_UNSUPPORTED: orderType '" + cmd.orderType + "' is not supported (market and limit only)";
   }
   if(cmd.side != "BUY" && cmd.side != "SELL")
   {
      return "INVALID_REQUEST: side '" + cmd.side + "' is neither BUY nor SELL";
   }
   if(cmd.volume <= 0 || cmd.volume > InpMaxVolumePerOrder)
   {
      return "VOLUME_LIMIT: volume " + DoubleToString(cmd.volume, 2) + " outside (0, " + DoubleToString(InpMaxVolumePerOrder, 2) + "], the local per-order maximum";
   }
   if(cmd.sl <= 0)
   {
      return "STOP_MISSING: no stop-loss on this command — never executed without an explicit invalidation";
   }
   int exposure = PositionsTotal() + OrdersTotal();
   if(exposure >= InpMaxOpenPositions)
   {
      return "POSITIONS_LIMIT: open positions and pending orders (" + IntegerToString(exposure) + ") already at the local maximum (" + IntegerToString(InpMaxOpenPositions) + ")";
   }

   double point = SymbolInfoDouble(cmd.symbol, SYMBOL_POINT);
   if(point <= 0)
   {
      return "SYMBOL_UNAVAILABLE: symbol '" + cmd.symbol + "' has no valid point size on this terminal (not in Market Watch?)";
   }
   string volumeProblem = TradeVolumeProblem(cmd.symbol, cmd.volume);
   if(volumeProblem != "")
   {
      return "VOLUME_INVALID: " + volumeProblem;
   }
   double maxSpread = MaxSpreadFor(cmd.symbol);
   int digits = (int)SymbolInfoInteger(cmd.symbol, SYMBOL_DIGITS);
   if(maxSpread <= 0)
   {
      return "SPREAD_LIMIT_MISSING: no maximum spread configured for '" + cmd.symbol + "' in InpMaxSpreadCsv — refused, never unlimited";
   }
   double bid = SymbolInfoDouble(cmd.symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(cmd.symbol, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0)
   {
      return "SYMBOL_UNAVAILABLE: symbol '" + cmd.symbol + "' has no quote on this terminal";
   }
   double spread = ask - bid;
   if(spread > maxSpread + point / 2)
   {
      return "SPREAD_TOO_WIDE: spread " + DoubleToString(spread, digits) + " exceeds the local maximum " +
             DoubleToString(maxSpread, digits) + " for " + cmd.symbol;
   }

   // Where the stop and the target must sit: behind and beyond the price the position will be measured from — the price it
   // would be closed at for an order at the market, the order's own price for a resting one — by at least the stops level.
   bool isBuy = (cmd.side == "BUY");
   double gap = TradeStopsDistance(cmd.symbol);
   double reference;
   if(cmd.orderType == "LIMIT")
   {
      if(cmd.price <= 0)
      {
         return "LIMIT_PRICE_INVALID: a LIMIT order needs a price";
      }
      if(isBuy && cmd.price > ask - gap + point / 2)
      {
         return "LIMIT_PRICE_INVALID: a buy limit at " + DoubleToString(cmd.price, digits) + " is not below the ask " + DoubleToString(ask, digits) + " by the stops level";
      }
      if(!isBuy && cmd.price < bid + gap - point / 2)
      {
         return "LIMIT_PRICE_INVALID: a sell limit at " + DoubleToString(cmd.price, digits) + " is not above the bid " + DoubleToString(bid, digits) + " by the stops level";
      }
      if((SymbolInfoInteger(cmd.symbol, SYMBOL_EXPIRATION_MODE) & SYMBOL_EXPIRATION_SPECIFIED) == 0)
      {
         return "ORDER_TYPE_UNSUPPORTED: '" + cmd.symbol + "' does not accept a pending order with an expiration, and a resting order is never left without one";
      }
      reference = cmd.price;
   }
   else
   {
      reference = isBuy ? bid : ask;
   }
   bool stopWrong = isBuy ? (cmd.sl > reference - gap + point / 2) : (cmd.sl < reference + gap - point / 2);
   if(stopWrong)
   {
      return "STOP_INVALID: stop " + DoubleToString(cmd.sl, digits) + " is not " + (isBuy ? "below " : "above ") +
             DoubleToString(reference, digits) + " by the broker's stops level (" + DoubleToString(gap, digits) + ")";
   }
   if(cmd.tp > 0)
   {
      bool targetWrong = isBuy ? (cmd.tp < reference + gap - point / 2) : (cmd.tp > reference - gap + point / 2);
      if(targetWrong)
      {
         return "STOP_INVALID: target " + DoubleToString(cmd.tp, digits) + " is not " + (isBuy ? "above " : "below ") +
                DoubleToString(reference, digits) + " by the broker's stops level (" + DoubleToString(gap, digits) + ")";
      }
   }
   return "";
}

//--- MODIFY: move the stop and/or the target of one of this agent's own positions. A stop only ever tightens and is never
//    removed; the core checked the same thing, and this agent has the last word. Fills cmd.side with the position's.
string ValidateModifyCommand(TradeCommand &cmd)
{
   if(!cmd.hasSl && !cmd.hasTp)
   {
      return "INVALID_REQUEST: MODIFY names neither a stop nor a target";
   }
   if(cmd.hasSl && cmd.sl <= 0)
   {
      return "STOP_MISSING: a stop is never removed — no position without an explicit invalidation";
   }
   if(cmd.hasTp && cmd.tp <= 0)
   {
      return "INVALID_REQUEST: a target must be a price above zero (this command does not remove one)";
   }
   ulong ticket = 0;
   if(!TradeSelectPosition(cmd.positionId, ticket))
   {
      return "POSITION_NOT_FOUND: no open position " + IntegerToString(cmd.positionId) + " on this terminal";
   }
   string notYours = TargetNotOurs((int)PositionGetInteger(POSITION_MAGIC), PositionGetString(POSITION_SYMBOL), cmd.symbol,
                                   "position " + IntegerToString(cmd.positionId));
   if(notYours != "")
   {
      return notYours;
   }
   bool isBuy = ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
   cmd.side = isBuy ? "BUY" : "SELL";
   double point = SymbolInfoDouble(cmd.symbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(cmd.symbol, SYMBOL_DIGITS);
   double bid = SymbolInfoDouble(cmd.symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(cmd.symbol, SYMBOL_ASK);
   if(point <= 0 || bid <= 0 || ask <= 0)
   {
      return "SYMBOL_UNAVAILABLE: symbol '" + cmd.symbol + "' has no quote on this terminal";
   }
   double gap = TradeStopsDistance(cmd.symbol);
   double reference = isBuy ? bid : ask; // the price the position would be closed at
   if(cmd.hasSl)
   {
      double current = PositionGetDouble(POSITION_SL);
      bool looser = (current > 0) && (isBuy ? (cmd.sl < current - point / 2) : (cmd.sl > current + point / 2));
      if(looser)
      {
         return "STOP_LOOSENED: stop " + DoubleToString(cmd.sl, digits) + " lets the position lose more than its current stop " +
                DoubleToString(current, digits);
      }
      bool wrongSide = isBuy ? (cmd.sl > reference - gap + point / 2) : (cmd.sl < reference + gap - point / 2);
      if(wrongSide)
      {
         return "STOP_INVALID: stop " + DoubleToString(cmd.sl, digits) + " is not " + (isBuy ? "below " : "above ") +
                DoubleToString(reference, digits) + " by the broker's stops level (" + DoubleToString(gap, digits) + ")";
      }
   }
   if(cmd.hasTp)
   {
      bool wrongSide = isBuy ? (cmd.tp < reference + gap - point / 2) : (cmd.tp > reference - gap + point / 2);
      if(wrongSide)
      {
         return "STOP_INVALID: target " + DoubleToString(cmd.tp, digits) + " is not " + (isBuy ? "above " : "below ") +
                DoubleToString(reference, digits) + " by the broker's stops level (" + DoubleToString(gap, digits) + ")";
      }
   }
   return "";
}

//--- CLOSE (all of one of this agent's positions) and PARTIAL_CLOSE (part of it, strictly less, leaving a volume the symbol can
//    hold). Closing never adds exposure: no spread, volume-per-order or position-count barrier applies to it, only the
//    identity of the target. Fills cmd.side (and, for a CLOSE, cmd.volume) from the position.
string ValidateCloseCommand(TradeCommand &cmd)
{
   ulong ticket = 0;
   if(!TradeSelectPosition(cmd.positionId, ticket))
   {
      return "POSITION_NOT_FOUND: no open position " + IntegerToString(cmd.positionId) + " on this terminal";
   }
   string notYours = TargetNotOurs((int)PositionGetInteger(POSITION_MAGIC), PositionGetString(POSITION_SYMBOL), cmd.symbol,
                                   "position " + IntegerToString(cmd.positionId));
   if(notYours != "")
   {
      return notYours;
   }
   cmd.side = ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
   double heldVolume = PositionGetDouble(POSITION_VOLUME);
   if(cmd.kind == "CLOSE")
   {
      cmd.volume = heldVolume;
      return "";
   }
   if(cmd.volume <= 0)
   {
      return "INVALID_REQUEST: PARTIAL_CLOSE needs a volume";
   }
   if(cmd.volume >= heldVolume - 1e-9)
   {
      return "VOLUME_INVALID: " + DoubleToString(cmd.volume, 2) + " lot(s) is not less than the " + DoubleToString(heldVolume, 2) + " open — that is a CLOSE";
   }
   string volumeProblem = TradeVolumeProblem(cmd.symbol, cmd.volume);
   if(volumeProblem != "")
   {
      return "VOLUME_INVALID: " + volumeProblem;
   }
   if(heldVolume - cmd.volume < SymbolInfoDouble(cmd.symbol, SYMBOL_VOLUME_MIN) - 1e-9)
   {
      return "VOLUME_INVALID: closing " + DoubleToString(cmd.volume, 2) + " of " + DoubleToString(heldVolume, 2) + " would leave less than the symbol's minimum volume";
   }
   return "";
}

//--- CANCEL: delete one of this agent's own pending orders. Fills cmd.side with the order's.
string ValidateCancelCommand(TradeCommand &cmd)
{
   if(!TradeSelectPendingOrder(cmd.orderId))
   {
      return "ORDER_NOT_FOUND: no pending order " + IntegerToString(cmd.orderId) + " on this terminal";
   }
   ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
   if(!TradeOrderTypeIsPending(type))
   {
      return "ORDER_NOT_FOUND: order " + IntegerToString(cmd.orderId) + " is not a pending order";
   }
   string notYours = TargetNotOurs((int)OrderGetInteger(ORDER_MAGIC), OrderGetString(ORDER_SYMBOL), cmd.symbol,
                                   "order " + IntegerToString(cmd.orderId));
   if(notYours != "")
   {
      return notYours;
   }
   cmd.side = TradeOrderTypeIsBuy(type) ? "BUY" : "SELL";
   return "";
}

//--- "" when a position or an order belongs to this agent (its magic number) and sits on the symbol the command names; else the
//    refusal. The agent never touches what the user opened by hand or what another program placed (ADR 0010 isolation).
string TargetNotOurs(const int magic, const string targetSymbol, const string commandSymbol, const string what)
{
   if(magic != InpMagicNumber)
   {
      return "TARGET_NOT_OURS: " + what + " carries magic " + IntegerToString(magic) + ", this agent's is " + IntegerToString(InpMagicNumber) +
             " — it only manages what it placed";
   }
   if(targetSymbol != commandSymbol)
   {
      return "SYMBOL_MISMATCH: " + what + " is on " + targetSymbol + ", the command says " + commandSymbol;
   }
   return "";
}

//--- 1.12: a pending order lives at most this long at the broker. Never removable: anything outside 1..1440 is read as 60.
int PendingMaxMinutes()
{
   return (InpPendingMaxMinutes >= 1 && InpPendingMaxMinutes <= 1440) ? InpPendingMaxMinutes : 60;
}

datetime PendingExpiration()
{
   return TimeCurrent() + PendingMaxMinutes() * 60; // broker (server) time, as MqlTradeRequest.expiration wants
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
   json += "\"accountId\":\"" + JsonEscape(g_account_id) + "\",";
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
//    I1: the report's time is the record's — a report sent again after a
//    reconnection carries its original time, which is what lets the
//    core recognise it (report id = commandId + status + time).
void SendReportRecord(const CommandRecord &rec, const bool replayed)
{
   string json = "{";
   json += "\"version\":1,";
   json += "\"type\":\"execution.report\",";
   json += "\"accountId\":\"" + JsonEscape(g_account_id) + "\",";
   json += "\"time\":" + IntegerToString(rec.timeMs) + ",";
   json += "\"commandId\":\"" + JsonEscape(rec.commandId) + "\",";
   json += "\"status\":\"" + rec.status + "\",";
   json += "\"symbol\":\"" + JsonEscape(rec.symbol) + "\",";
   // A report without a side says null: the core reads "BUY", "SELL" or nothing, and an empty string would drop the whole frame.
   json += (rec.side == "" ? "\"side\":null," : "\"side\":\"" + JsonEscape(rec.side) + "\",");
   json += "\"brokerOrderId\":" + JsonIdOrNull(rec.brokerOrderId) + ",";
   json += "\"brokerPositionId\":" + JsonIdOrNull(rec.brokerPositionId) + ",";
   json += "\"filledVolume\":" + (rec.filledVolume == 0.0 ? "null" : DoubleToString(rec.filledVolume, 2)) + ",";
   json += "\"averagePrice\":" + (rec.averagePrice == 0.0 ? "null" : DoubleToString(rec.averagePrice, 5)) + ",";
   json += "\"brokerRetcode\":" + JsonIdOrNull(rec.retcode) + ",";
   json += (replayed ? "\"replayed\":true," : "");
   json += "\"detail\":\"" + JsonEscape(rec.detail) + "\"";
   json += "}";
   SendRawLine(json);
}

//--- Records a final outcome, then reports it. Returns whether the record
//    was persisted (the report goes out either way: the core must know).
bool RecordAndReport(const string commandId, const string status, const string symbol, const string side,
                     const string detail)
{
   CommandRecord rec;
   CommandRecordInit(rec, commandId, status, detail, symbol, side, (long)TimeGMT() * 1000);
   bool persisted = CommandStoreRecord(rec);
   SendReportRecord(rec, false);
   return persisted;
}

//--- I1: final outcomes of the last InpReportReplayMinutes, sent again on
//    every connection — an outcome reported into a dropping link is not lost.
void ReplayRecentReports()
{
   CommandRecord records[];
   long sinceMs = ((long)TimeGMT() - (long)InpReportReplayMinutes * 60) * 1000;
   int count = CommandStoreRecentFinal(sinceMs, records);
   for(int i = 0; i < count; i++)
   {
      SendReportRecord(records[i], true);
   }
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
   json += "\"accountId\":\"" + JsonEscape(g_account_id) + "\",";
   json += "\"time\":" + IntegerToString(timeMs) + ",";
   json += "\"commandId\":\"" + JsonEscape(commandId) + "\",";
   json += "\"outcome\":\"" + outcome + "\",";
   json += (symbol == "" ? "\"symbol\":null," : "\"symbol\":\"" + JsonEscape(symbol) + "\",");
   json += (side == "" ? "\"side\":null," : "\"side\":\"" + JsonEscape(side) + "\",");
   json += "\"brokerOrderId\":" + JsonIdOrNull(brokerOrderId) + ",";
   json += "\"brokerPositionId\":" + JsonIdOrNull(brokerPositionId) + ",";
   json += "\"filledVolume\":" + (filledVolume == 0.0 ? "null" : DoubleToString(filledVolume, 2)) + ",";
   json += "\"averagePrice\":" + (averagePrice == 0.0 ? "null" : DoubleToString(averagePrice, 5)) + ",";
   json += "\"brokerRetcode\":null,";
   json += "\"attempts\":" + IntegerToString(attempts) + ",";
   json += "\"detail\":\"" + JsonEscape(detail) + "\"";
   json += "}";
   SendRawLine(json);
}

//+------------------------------------------------------------------+
//| execute — EA-05 increment 6, widened by ADR 0029 (1.12).           |
//| THE ONLY OrderSend IN THE REPOSITORY.                              |
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
//| Since 1.12 this is the single point every kind of command goes     |
//| through — an order at the market, a resting LIMIT, a stop move, a   |
//| full or partial close, a cancel. The handlers build a TradeCommand; |
//| this function validates it again (the same ValidateTradeCommand),   |
//| builds the request (BuildTradeRequest), has the server check it     |
//| where that is meaningful (OrderCheck sends nothing), writes the     |
//| UNKNOWN line, and only then calls OrderSend.                       |
//|                                                                    |
//| In this build g_mode is a compile-time const MODE_OBSERVE, so the  |
//| guard can never pass at all: everything below is provably          |
//| unreachable until the mode ladder is built (I4 to I6).             |
//|                                                                    |
//| "Jamais deux positions" (ADR 0010): the command is written to disk |
//| as UNKNOWN BEFORE the broker call and rewritten with the real      |
//| outcome after. An agent that dies between the two leaves UNKNOWN   |
//| behind; replaying that commandId then returns DUPLICATE/UNKNOWN    |
//| from the store and never reaches the broker a second time. An      |
//| UNKNOWN line that cannot be written stops the order. Resolving an  |
//| UNKNOWN is EA-06's reconciliation, which LOOKS at the terminal     |
//| (orders, deals, the stop now in force) — never a retry from here.  |
//+------------------------------------------------------------------+
void ExecuteOrder(const TradeCommand &command)
{
   if(g_mode != MODE_CONFIRM)
   {
      return;
   }

   // I1, defence in depth: the caller checked these too. Opening and moving a stop need the login to be tradable; closing and
   // cancelling, to be closable — two lists (InpTradableLogins, InpClosableLogins), both empty by default.
   bool allowed = TradeCommandReducesRiskOnly(command.kind) ? g_closable : g_tradable;
   // The halt (ADR 0033) refuses what is not a closing or a cancelling; those two still need the login to be closable.
   if(g_identity != "ok" || !allowed || (IsHalted() && !TradeCommandReducesRiskOnly(command.kind)))
   {
      RecordAndReport(command.commandId, "REJECTED", command.symbol, command.side,
                      "IDENTITY_REFUSED: login not allowed for this kind of command, identity not ok, or halted — no broker call");
      return;
   }

   // The same local barriers the handler ran, run again here: whatever calls this function, nothing reaches the broker unvalidated.
   TradeCommand cmd = command;
   string refusal = ValidateTradeCommand(cmd);
   if(refusal != "")
   {
      RecordAndReport(cmd.commandId, "REJECTED", cmd.symbol, cmd.side, refusal);
      return;
   }

   MqlTradeRequest     request;
   MqlTradeResult      result;
   MqlTradeCheckResult check;
   ZeroMemory(result);
   ZeroMemory(check);
   string unbuildable = BuildTradeRequest(cmd, InpMagicNumber, InpMaxSlippagePoints, FillingModeFor(cmd.symbol),
                                          PendingExpiration(), CommandTrace(cmd.commandId), request);
   if(unbuildable != "")
   {
      RecordAndReport(cmd.commandId, "REJECTED", cmd.symbol, cmd.side, unbuildable);
      return;
   }

   // OrderCheck sends nothing: it asks the server whether it would take the request (margin, volume, stops, fill mode). It is
   // applied to the requests that open, close or place — where those can fail; stop moves and removals have no margin to check
   // and keep their local barriers. A refusal here is a definite outcome, recorded final.
   bool checkable = (request.action == TRADE_ACTION_DEAL || request.action == TRADE_ACTION_PENDING);
   if(checkable)
   {
      bool checked = OrderCheck(request, check);
      if(!checked || (check.retcode != 0 && check.retcode != TRADE_RETCODE_DONE))
      {
         CommandRecord refused;
         CommandRecordInit(refused, cmd.commandId, "FAILED",
                           "OrderCheck refused: retcode " + IntegerToString(check.retcode) +
                           (check.comment == "" ? "" : " (" + check.comment + ")") + " — nothing was sent",
                           cmd.symbol, cmd.side, (long)TimeGMT() * 1000);
         refused.retcode = (int)check.retcode;
         refused.kind = cmd.kind;
         CommandStoreRecord(refused);
         SendReportRecord(refused, false);
         return;
      }
   }

   CommandRecord inFlight;
   CommandRecordInit(inFlight, cmd.commandId, "UNKNOWN", "broker call in flight - outcome not yet known",
                     cmd.symbol, cmd.side, (long)TimeGMT() * 1000);
   inFlight.kind             = cmd.kind;
   inFlight.brokerOrderId    = cmd.orderId;
   inFlight.brokerPositionId = cmd.positionId;
   inFlight.filledVolume     = cmd.volume;
   inFlight.averagePrice     = cmd.price;
   inFlight.sl               = (cmd.kind == "OPEN" || cmd.hasSl) ? cmd.sl : 0.0;
   inFlight.tp               = (cmd.kind == "OPEN" || cmd.hasTp) ? cmd.tp : 0.0;
   if(!CommandStoreRecord(inFlight))
   {
      RecordAndReport(cmd.commandId, "FAILED", cmd.symbol, cmd.side,
                      "STORE_UNWRITABLE: the UNKNOWN line could not be written — order NOT sent");
      return;
   }

   bool sent = OrderSend(request, result);

   long nowMs = (long)TimeGMT() * 1000;
   // A stop move to the levels the position already has is a no-op, not a failure: the position is where the command wanted it.
   bool noChange = sent && cmd.kind == "MODIFY" && result.retcode == TRADE_RETCODE_NO_CHANGES;
   bool done = sent && (result.retcode == TRADE_RETCODE_DONE || result.retcode == TRADE_RETCODE_DONE_PARTIAL || noChange);
   if(!done)
   {
      // A refusal is a definite outcome, safe to record as final: the broker rejected it, nothing was done. Only a crash
      // mid-call leaves UNKNOWN. (Ambiguous returns — timeout, no connection — go to the core as FAILED with their retcode,
      // which classifies them UNKNOWN there; the agent's line is final, so a replay of the commandId never reaches the broker.)
      string failDetail = "OrderSend refused: retcode " + IntegerToString(result.retcode) +
                          (result.comment == "" ? "" : " (" + result.comment + ")");
      CommandRecord failed;
      CommandRecordInit(failed, cmd.commandId, "FAILED", failDetail, cmd.symbol, cmd.side, nowMs);
      failed.retcode = (int)result.retcode;
      failed.kind = cmd.kind;
      CommandStoreRecord(failed);
      SendReportRecord(failed, false);
      return;
   }

   RecordSuccess(cmd, result, noChange, nowMs);
}

//--- The final record and report of a command the broker accepted. What each kind reports (ADR 0029):
//    MARKET -> FILLED | PARTIALLY_FILLED; LIMIT -> SUBMITTED (resting at the broker, nothing filled); MODIFY -> MODIFIED;
//    CLOSE / PARTIAL_CLOSE -> CLOSED; CANCEL -> CANCELLED. This function sends nothing to the broker.
void RecordSuccess(const TradeCommand &cmd, const MqlTradeResult &result, const bool noChange, const long nowMs)
{
   string status;
   string detail;
   CommandRecord done;
   if(cmd.kind == "OPEN" && cmd.orderType == "MARKET")
   {
      // A fresh market entry's position identifier is its opening order ticket (verified against this account's own history).
      // That equivalence does NOT hold for a deal that closes or reverses an existing position — closes below name the
      // identifier the core gave, and the general case is EA-06's reconciliation, not an assumption made here.
      status = (result.retcode == TRADE_RETCODE_DONE_PARTIAL) ? "PARTIALLY_FILLED" : "FILLED";
      detail = status + " " + DoubleToString(result.volume, 2) + " lot " + cmd.side + " " + cmd.symbol +
               " @ " + DoubleToString(result.price, 5) + " (order " + IntegerToString((long)result.order) + ")";
      CommandRecordInit(done, cmd.commandId, status, detail, cmd.symbol, cmd.side, nowMs);
      done.brokerOrderId = (long)result.order;
      done.brokerPositionId = (long)result.order;
      done.filledVolume = result.volume;
      done.averagePrice = result.price;
   }
   else if(cmd.kind == "OPEN")
   {
      status = "SUBMITTED";
      detail = status + " " + DoubleToString(cmd.volume, 2) + " lot " + cmd.side + " LIMIT " + cmd.symbol + " @ " +
               DoubleToString(cmd.price, 5) + " (order " + IntegerToString((long)result.order) + ", expires within " +
               IntegerToString(PendingMaxMinutes()) + " min at the broker)";
      CommandRecordInit(done, cmd.commandId, status, detail, cmd.symbol, cmd.side, nowMs);
      done.brokerOrderId = (long)result.order; // nothing is filled: no position, no volume, no price yet
   }
   else if(cmd.kind == "MODIFY")
   {
      status = "MODIFIED";
      detail = status + " position " + IntegerToString(cmd.positionId) + " " + cmd.symbol +
               (cmd.hasSl ? " stop " + DoubleToString(cmd.sl, 5) : "") + (cmd.hasTp ? " target " + DoubleToString(cmd.tp, 5) : "") +
               (noChange ? " (already at these levels)" : "");
      CommandRecordInit(done, cmd.commandId, status, detail, cmd.symbol, cmd.side, nowMs);
      done.brokerPositionId = cmd.positionId;
   }
   else if(cmd.kind == "CANCEL")
   {
      status = "CANCELLED";
      detail = status + " pending order " + IntegerToString(cmd.orderId) + " " + cmd.symbol;
      CommandRecordInit(done, cmd.commandId, status, detail, cmd.symbol, cmd.side, nowMs);
      done.brokerOrderId = cmd.orderId;
   }
   else
   {
      status = "CLOSED";
      detail = status + " " + DoubleToString(result.volume, 2) + " lot of position " + IntegerToString(cmd.positionId) + " " +
               cmd.symbol + " @ " + DoubleToString(result.price, 5) + " (order " + IntegerToString((long)result.order) + ")";
      CommandRecordInit(done, cmd.commandId, status, detail, cmd.symbol, cmd.side, nowMs);
      done.brokerOrderId = (long)result.order;
      done.brokerPositionId = cmd.positionId;
      done.filledVolume = result.volume;
      done.averagePrice = result.price;
   }
   done.retcode = (int)result.retcode;
   done.kind = cmd.kind;
   done.sl = (cmd.kind == "OPEN" || cmd.hasSl) ? cmd.sl : 0.0;
   done.tp = (cmd.kind == "OPEN" || cmd.hasTp) ? cmd.tp : 0.0;
   CommandStoreRecord(done);
   SendReportRecord(done, false);
}

//+------------------------------------------------------------------+
//| The whole command path, for every kind of command:                 |
//|   receive -> idempotency -> halt -> identity -> account check ->   |
//|   expiry (AdmitCommand) -> validate (ValidateTradeCommand) ->      |
//|   acknowledge -> ExecuteOrder (CONFIRM only) or report SIMULATED.  |
//| The handlers below only read their message into a TradeCommand;    |
//| none of them builds or sends a broker request.                     |
//+------------------------------------------------------------------+

//--- The chain every command goes through before its own checks. True when the command may go on; false when it has been
//    answered here (a replay, the halt, the identity, the wrong account, an expired command).
bool AdmitCommand(const string commandId, const string accountId, const long expiresAt, const string symbol, const string side,
                  const bool exitOnly)
{
   // Idempotency FIRST, before any other check: a replayed commandId
   // returns its prior result, no matter what (ADR 0010).
   CommandRecord prior;
   if(CommandStoreLookup(commandId, prior))
   {
      SendAck(commandId, "DUPLICATE", "replayed commandId — returning the recorded result, never re-executing");
      if(CommandStoreIsFinalStatus(prior.status))
      {
         CommandRecord again = prior;
         again.timeMs = (long)TimeGMT() * 1000; // a new report of the old result, as before I1
         if(again.symbol == "") again.symbol = symbol;
         if(again.side == "") again.side = side;
         SendReportRecord(again, false);
      }
      // A command still UNKNOWN has no report to give: reconciliation settles it by looking at the terminal, never by sending again.
      return false;
   }

   // I1: the local kill switch. Checked before anything that could lead to
   // the broker, and it needs no link to the core to hold.
   // 1.13 (ADR 0033): the halt stops new risk, not the way out — a command that only closes or cancels (exitOnly) is not refused for it.
   // Everything else (an opening, a stop move) still is, and the halt is still lifted only on the chart.
   if(IsHalted() && !exitOnly)
   {
      RefuseCommand(commandId, symbol, side, "HALTED: the local kill switch is set on this terminal — lifted only on the chart");
      return false;
   }

   // I1: who this terminal really is. A terminal logged into another login
   // than InpAccountId expects refuses everything, whatever it receives.
   if(g_identity != "ok")
   {
      RefuseCommand(commandId, symbol, side, "IDENTITY_REFUSED: terminal login '" + g_account_id + "', expected '" + InpAccountId +
                    "' (identity " + g_identity + ")");
      return false;
   }

   // Account isolation (ADR 0010): never executed "at best" on the wrong
   // account. Since I1 this compares with the terminal's real login.
   if(accountId != g_account_id)
   {
      RefuseCommand(commandId, symbol, side, "ACCOUNT_MISMATCH: command targets '" + accountId + "', this terminal is on '" + g_account_id + "'");
      return false;
   }

   long nowMs = (long)TimeGMT() * 1000;
   if(expiresAt > 0 && nowMs > expiresAt)
   {
      CommandRecord rec;
      CommandRecordInit(rec, commandId, "EXPIRED", "command received after its expiresAt", symbol, side, nowMs);
      CommandStoreRecord(rec);
      SendAck(commandId, "EXPIRED", "command received after its expiresAt");
      return false; // no execution.report for an expired command — it never reached validation
   }
   return true;
}

//--- A command refused before validation: recorded, acknowledged REJECTED, reported.
void RefuseCommand(const string commandId, const string symbol, const string side, const string detail)
{
   CommandRecord rec;
   CommandRecordInit(rec, commandId, "REJECTED", detail, symbol, side, (long)TimeGMT() * 1000);
   CommandStoreRecord(rec);
   SendAck(commandId, "REJECTED", detail);
   SendReportRecord(rec, false);
}

string DescribeCommand(const TradeCommand &cmd)
{
   if(cmd.kind == "OPEN")
   {
      return cmd.orderType + " " + DoubleToString(cmd.volume, 2) + " lot " + cmd.side + " " + cmd.symbol +
             (cmd.orderType == "LIMIT" ? " @ " + DoubleToString(cmd.price, 5) : "");
   }
   if(cmd.kind == "MODIFY")
   {
      return "MODIFY position " + IntegerToString(cmd.positionId) + " " + cmd.symbol +
             (cmd.hasSl ? " stop " + DoubleToString(cmd.sl, 5) : "") + (cmd.hasTp ? " target " + DoubleToString(cmd.tp, 5) : "");
   }
   if(cmd.kind == "CANCEL")
   {
      return "CANCEL pending order " + IntegerToString(cmd.orderId) + " " + cmd.symbol;
   }
   return cmd.kind + " " + DoubleToString(cmd.volume, 2) + " lot of position " + IntegerToString(cmd.positionId) + " " + cmd.symbol;
}

//--- From a command read off the wire to its outcome. The mode fork: CONFIRM is the only branch that can reach a broker, and
//    ExecuteOrder re-checks the mode itself — this test is convenience, that one is the barrier. In this build g_mode is
//    const MODE_OBSERVE, so the SIMULATED path below is the only one that ever runs.
void ProcessCommand(const string json, TradeCommand &cmd)
{
   if(cmd.commandId == "")
   {
      Print("TradingOsAgent: command missing 'id' — dropping (malformed frame, never crash).");
      return;
   }
   if(!AdmitCommand(cmd.commandId, JsonGetString(json, "accountId"), JsonGetLong(json, "expiresAt"), cmd.symbol, cmd.side,
                    TradeCommandReducesRiskOnly(cmd.kind)))
   {
      return;
   }

   string rejectReason = ValidateTradeCommand(cmd);
   if(rejectReason != "")
   {
      RefuseCommand(cmd.commandId, cmd.symbol, cmd.side, rejectReason);
      return;
   }

   SendAck(cmd.commandId, "ACCEPTED", "");

   if(g_mode == MODE_CONFIRM)
   {
      bool reduceOnly = TradeCommandReducesRiskOnly(cmd.kind);
      if(!(reduceOnly ? g_closable : g_tradable))
      {
         RecordAndReport(cmd.commandId, "REJECTED", cmd.symbol, cmd.side,
                         (reduceOnly ? "LOGIN_NOT_CLOSABLE: login " + g_account_id + " is not in InpClosableLogins"
                                     : "LOGIN_NOT_TRADABLE: login " + g_account_id + " is not in InpTradableLogins"));
         return;
      }
      ExecuteOrder(cmd);
      return;
   }

   RecordAndReport(cmd.commandId, "SIMULATED", cmd.symbol, cmd.side,
                   "SIMULATED " + DescribeCommand(cmd) + " (mode " + ModeToWireString(g_mode) + ", no broker order)");
}

//--- execution.order: OPEN, at the market or resting (LIMIT).
void HandleOrderCommand(const string json)
{
   TradeCommand cmd;
   TradeCommandInit(cmd, "OPEN", JsonGetString(json, "id"), JsonGetString(json, "symbol"));
   cmd.side      = JsonGetString(json, "side");
   cmd.orderType = JsonGetString(json, "orderType");
   cmd.volume    = JsonGetDouble(json, "volume");
   cmd.price     = JsonGetDouble(json, "limitPrice");
   cmd.sl        = JsonGetDouble(json, "sl");
   cmd.tp        = JsonGetDouble(json, "tp");
   ProcessCommand(json, cmd);
}

//--- execution.modify: move the stop and/or the target of an open position. A null level is left as it is.
void HandleModifyCommand(const string json)
{
   TradeCommand cmd;
   TradeCommandInit(cmd, "MODIFY", JsonGetString(json, "id"), JsonGetString(json, "symbol"));
   cmd.positionId = JsonGetLong(json, "positionId");
   cmd.hasSl      = JsonGetOptionalDouble(json, "sl", cmd.sl);
   cmd.hasTp      = JsonGetOptionalDouble(json, "tp", cmd.tp);
   ProcessCommand(json, cmd);
}

//--- execution.close: all of a position, or — when the message carries a volume — part of it.
void HandleCloseCommand(const string json)
{
   double volume = 0.0;
   bool partial = JsonGetOptionalDouble(json, "volume", volume);
   TradeCommand cmd;
   TradeCommandInit(cmd, partial ? "PARTIAL_CLOSE" : "CLOSE", JsonGetString(json, "id"), JsonGetString(json, "symbol"));
   cmd.positionId = JsonGetLong(json, "positionId");
   cmd.volume     = partial ? volume : 0.0;
   ProcessCommand(json, cmd);
}

//--- execution.cancel: delete a pending order that has not filled.
void HandleCancelCommand(const string json)
{
   TradeCommand cmd;
   TradeCommandInit(cmd, "CANCEL", JsonGetString(json, "id"), JsonGetString(json, "symbol"));
   cmd.orderId = JsonGetLong(json, "orderId");
   ProcessCommand(json, cmd);
}

//+------------------------------------------------------------------+
//| reconcile — EA-06. Resolves every commandId this agent left UNKNOWN  |
//| (written by ExecuteOrder, before the broker call, never rewritten if |
//| the process dies before the broker answers). Runs on the heartbeat  |
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
//    CommandTrace(commandId) — the exact comment ExecuteOrder writes. Deals
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
   string needle = CommandTrace(commandId);

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

//--- 1.12: a LIMIT order of this command that is still resting at the broker — found by the trace its comment carries.
//    A pending order that has not filled is in the terminal's ACTIVE orders, not in the history.
bool SearchActiveOrderForCommand(const string commandId, string &outcome, string &symbol, string &side,
                                  long &brokerOrderId, double &volume, double &price)
{
   string needle = CommandTrace(commandId);
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i); // selects the order by index
      if(ticket == 0)
      {
         continue;
      }
      if((int)OrderGetInteger(ORDER_MAGIC) != InpMagicNumber || OrderGetString(ORDER_COMMENT) != needle)
      {
         continue;
      }
      outcome = "executed";
      symbol = OrderGetString(ORDER_SYMBOL);
      side = TradeOrderTypeIsBuy((ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE)) ? "BUY" : "SELL";
      brokerOrderId = (long)ticket;
      volume = OrderGetDouble(ORDER_VOLUME_CURRENT);
      price = OrderGetDouble(ORDER_PRICE_OPEN);
      return true;
   }
   return false;
}

//--- 1.12: did a MODIFY take effect? Looks at the position NOW: its stop (and target) are the ones the command wanted.
//    The only answer this can give is « yes » — a stop that is not there yet may still be on its way, and the agent never
//    concludes « refused » from an absence.
bool SearchPositionForModify(const CommandRecord &rec, string &outcome, string &symbol, string &side, long &brokerPositionId)
{
   ulong ticket = 0;
   if((rec.sl <= 0 && rec.tp <= 0) || !TradeSelectPosition(rec.brokerPositionId, ticket))
   {
      return false;
   }
   if((int)PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
   {
      return false;
   }
   string positionSymbol = PositionGetString(POSITION_SYMBOL);
   double point = SymbolInfoDouble(positionSymbol, SYMBOL_POINT);
   if(point <= 0)
   {
      return false;
   }
   bool stopThere = rec.sl <= 0 || MathAbs(PositionGetDouble(POSITION_SL) - rec.sl) <= point / 2;
   bool targetThere = rec.tp <= 0 || MathAbs(PositionGetDouble(POSITION_TP) - rec.tp) <= point / 2;
   if(!stopThere || !targetThere)
   {
      return false;
   }
   outcome = "executed";
   symbol = positionSymbol;
   side = ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
   brokerPositionId = rec.brokerPositionId;
   return true;
}

//--- 1.12: did a CLOSE / PARTIAL_CLOSE happen? Scans the ALREADY-SELECTED history for the exit deal that carries this command's
//    trace on this agent's magic number and the position it named.
bool SearchHistoryForClose(const CommandRecord &rec, string &outcome, string &symbol, string &side,
                            long &brokerOrderId, long &brokerPositionId, double &filledVolume, double &averagePrice)
{
   string needle = CommandTrace(rec.commandId);
   int totalDeals = HistoryDealsTotal();
   for(int i = 0; i < totalDeals; i++)
   {
      ulong dealTicket = HistoryDealGetTicket(i);
      if(dealTicket == 0)
      {
         continue;
      }
      if((int)HistoryDealGetInteger(dealTicket, DEAL_MAGIC) != InpMagicNumber || HistoryDealGetString(dealTicket, DEAL_COMMENT) != needle)
      {
         continue;
      }
      ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY && entry != DEAL_ENTRY_INOUT)
      {
         continue; // only a deal that takes volume off a position can be this command's
      }
      if(rec.brokerPositionId > 0 && (long)HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID) != rec.brokerPositionId)
      {
         continue;
      }
      outcome = "executed";
      symbol = HistoryDealGetString(dealTicket, DEAL_SYMBOL);
      // the exit deal goes the other way: a SELL deal closed a BUY position
      side = ((ENUM_DEAL_TYPE)HistoryDealGetInteger(dealTicket, DEAL_TYPE) == DEAL_TYPE_SELL) ? "BUY" : "SELL";
      brokerOrderId = (long)HistoryDealGetInteger(dealTicket, DEAL_ORDER);
      brokerPositionId = (long)HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID);
      filledVolume = HistoryDealGetDouble(dealTicket, DEAL_VOLUME);
      averagePrice = HistoryDealGetDouble(dealTicket, DEAL_PRICE);
      return true;
   }
   return false;
}

//--- 1.12: did a CANCEL happen? The order is no longer active and the ALREADY-SELECTED history says how it ended: cancelled or
//    expired = gone, as the command wanted ("executed"); filled = it filled before the cancel took effect ("rejected" — the
//    one definite negative this agent will state). An order still active, or absent from the history, is not found.
bool SearchHistoryForCancel(const CommandRecord &rec, string &outcome, string &status, string &symbol, string &side)
{
   if(rec.brokerOrderId <= 0 || TradeSelectPendingOrder(rec.brokerOrderId))
   {
      return false; // still resting: the cancel did not (yet) take effect
   }
   int totalOrders = HistoryOrdersTotal();
   for(int i = 0; i < totalOrders; i++)
   {
      ulong ticket = HistoryOrderGetTicket(i);
      if(ticket == 0 || (long)ticket != rec.brokerOrderId)
      {
         continue;
      }
      ENUM_ORDER_STATE state = (ENUM_ORDER_STATE)HistoryOrderGetInteger(ticket, ORDER_STATE);
      symbol = HistoryOrderGetString(ticket, ORDER_SYMBOL);
      side = TradeOrderTypeIsBuy((ENUM_ORDER_TYPE)HistoryOrderGetInteger(ticket, ORDER_TYPE)) ? "BUY" : "SELL";
      if(state == ORDER_STATE_CANCELED || state == ORDER_STATE_EXPIRED)
      {
         outcome = "executed";
         status = "CANCELLED";
         return true;
      }
      if(state == ORDER_STATE_FILLED || state == ORDER_STATE_PARTIAL)
      {
         outcome = "rejected";
         status = "FAILED";
         return true;
      }
      return false;
   }
   return false;
}

//--- One UNKNOWN command: look at the terminal for what it was about. Returns false — « not_found » — when nothing the command
//    would have left is there. NEVER sends anything: this is how a command whose outcome is unknown is resolved without being
//    replayed. `status` is the final status the store will carry.
bool ResolveUnknownCommand(const CommandRecord &rec, string &outcome, string &status, string &symbol, string &side,
                            long &brokerOrderId, long &brokerPositionId, double &filledVolume, double &averagePrice)
{
   outcome = "";
   status = "";
   symbol = rec.symbol;
   side = rec.side;
   brokerOrderId = 0;
   brokerPositionId = 0;
   filledVolume = 0.0;
   averagePrice = 0.0;

   string kind = (rec.kind == "") ? "OPEN" : rec.kind; // a line written before 1.12 was always an order at the market
   if(kind == "OPEN")
   {
      double restingVolume = 0.0;
      double restingPrice = 0.0;
      if(SearchActiveOrderForCommand(rec.commandId, outcome, symbol, side, brokerOrderId, restingVolume, restingPrice))
      {
         status = "SUBMITTED"; // resting: nothing filled, so no volume and no price are reported
         return true;
      }
      if(SearchHistoryForCommand(rec.commandId, outcome, symbol, side, brokerOrderId, brokerPositionId, filledVolume, averagePrice))
      {
         // Reuses the terminal vocabulary of ExecuteOrder (FILLED / FAILED): the reconciled-vs-live distinction lives in
         // execution.reconciled, sent either way, not in this local string. FILLED covers a partial fill too (EA-06 fiche
         // journal) — history does not carry the originally requested volume to tell the two apart.
         status = (outcome == "executed") ? "FILLED" : "FAILED";
         return true;
      }
      return false;
   }
   if(kind == "MODIFY")
   {
      status = "MODIFIED";
      return SearchPositionForModify(rec, outcome, symbol, side, brokerPositionId);
   }
   if(kind == "CLOSE" || kind == "PARTIAL_CLOSE")
   {
      status = "CLOSED";
      return SearchHistoryForClose(rec, outcome, symbol, side, brokerOrderId, brokerPositionId, filledVolume, averagePrice);
   }
   if(kind == "CANCEL")
   {
      brokerOrderId = rec.brokerOrderId;
      return SearchHistoryForCancel(rec, outcome, status, symbol, side);
   }
   return false;
}

void ReconcileUnknownCommands()
{
   CommandRecord unknown[];
   int count = CommandStoreFindUnknown(unknown);
   if(count == 0)
   {
      return;
   }

   datetime from = TimeCurrent() - InpReconciliationLookbackDays * 86400;

   for(int i = 0; i < count; i++)
   {
      string commandId = unknown[i].commandId;
      ReconciliationAttemptsBump(commandId);
      int attempts = ReconciliationAttemptsFor(commandId);

      // The history window is selected again for every command: looking at the terminal for one command must not leave the
      // next one with a history cache that was reloaded for something else.
      if(!HistorySelect(from, TimeCurrent()))
      {
         Print("TradingOsAgent: HistorySelect failed for EA-06 reconciliation window, error ", GetLastError());
         return;
      }

      string outcome, status, symbol, side;
      long brokerOrderId, brokerPositionId;
      double filledVolume, averagePrice;
      bool found = ResolveUnknownCommand(unknown[i], outcome, status, symbol, side, brokerOrderId, brokerPositionId,
                                          filledVolume, averagePrice);

      if(!found)
      {
         // Stays UNKNOWN in the store — retried on the next heartbeat/connect.
         SendReconciled(commandId, "not_found", "", "", 0, 0, 0.0, 0.0, attempts,
                         "not found in the last " + IntegerToString(InpReconciliationLookbackDays) +
                         "d of history (attempt " + IntegerToString(attempts) + ") — will retry");
         continue;
      }

      string detail = "EA-06 reconciliation: " + outcome + " (attempt " + IntegerToString(attempts) + ")";
      CommandRecord resolved;
      CommandRecordInit(resolved, commandId, status, detail, symbol, side, (long)TimeGMT() * 1000);
      resolved.brokerOrderId = brokerOrderId;
      resolved.brokerPositionId = brokerPositionId;
      resolved.filledVolume = filledVolume;
      resolved.averagePrice = averagePrice;
      resolved.kind = unknown[i].kind;
      CommandStoreRecord(resolved);
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
   json += "\"accountId\":\"" + JsonEscape(g_account_id) + "\",";
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
         // I1: the comment is the short trace; the store ties it back.
         knownCommandId = CommandStoreFindByTrace(PositionGetString(POSITION_COMMENT));
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
