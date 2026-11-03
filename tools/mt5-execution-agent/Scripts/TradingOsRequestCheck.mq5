//+------------------------------------------------------------------+
//| TradingOsRequestCheck.mq5 — ADR 0029                              |
//|                                                                   |
//| Builds the broker requests the execution agent WOULD send — with   |
//| the agent's own BuildTradeRequest (Include/TradeRequest.mqh) — and  |
//| asks the server of a DEMO account whether it would take them        |
//| (OrderCheck). It SENDS NOTHING: this file has no call that sends a  |
//| request, and tests/architecture/test_execution_agent.py fails if    |
//| one is ever added. It refuses to run on any account that is not a   |
//| demo.                                                              |
//|                                                                   |
//| What it answers: is the SHAPE of each request right (action, type,  |
//| price, stops, expiration, fill mode, position/order reference) as   |
//| this broker sees it? Not: would the trade be a good one.            |
//|                                                                   |
//| Run it by hand on the demo terminal, read the Experts tab. The      |
//| first four checks need no open position or order. The last three    |
//| (a stop move, a close, a cancel) need the identifier of a position  |
//| and the ticket of a pending order that exist on the terminal — give  |
//| them in the inputs; 0 skips the check.                              |
//+------------------------------------------------------------------+
#property copyright "Trading Operating System — personal use only"
#property version   "1.00"
#property description "ADR 0029 — OrderCheck of the requests the execution agent would send. Sends nothing. Demo accounts only."
#property script_show_inputs

#include "../Include/TradeRequest.mqh"

input string InpSymbol      = "EURUSDm"; // broker-side symbol, visible in Market Watch
input double InpVolume      = 0.01;      // lots used for the checks of new orders
input int    InpStopPoints  = 300;       // stop and target distance from the price, in points (raised to the broker's stops level if lower)
input int    InpMagicNumber = 9765001;   // the magic number the agent would stamp — informational for the check
input long   InpPositionId  = 0;         // POSITION_IDENTIFIER of a position of yours to check a stop move and a close on (0 = skip)
input long   InpOrderId     = 0;         // ticket of a pending order of yours to check a cancel on (0 = skip)
input int    InpPendingMinutes = 60;     // expiration given to the LIMIT check, like InpPendingMaxMinutes of the agent

int g_checked = 0;
int g_accepted = 0;

void CheckRequest(const string label, const TradeCommand &cmd)
{
   MqlTradeRequest request;
   MqlTradeCheckResult check;
   ZeroMemory(check);
   datetime expiration = TimeCurrent() + InpPendingMinutes * 60;
   string unbuildable = BuildTradeRequest(cmd, InpMagicNumber, 10, ORDER_FILLING_IOC, expiration, "TOS check", request);
   if(unbuildable != "")
   {
      PrintFormat("CHECK %-28s NOT BUILT: %s", label, unbuildable);
      return;
   }
   g_checked++;
   if(request.action != TRADE_ACTION_DEAL && request.action != TRADE_ACTION_PENDING)
   {
      // OrderCheck is not asked about stop moves and removals (no margin to check; the agent does not ask either, ADR 0029):
      // the request is built and shown, nothing more.
      int digits = (int)SymbolInfoInteger(request.symbol, SYMBOL_DIGITS);
      PrintFormat("CHECK %-28s BUILT (action %d, no server check for this action): position=%I64u order=%I64u sl=%s tp=%s",
                  label, (int)request.action, request.position, request.order,
                  DoubleToString(request.sl, digits), DoubleToString(request.tp, digits));
      return;
   }
   bool ok = OrderCheck(request, check);
   bool accepted = ok && (check.retcode == 0 || check.retcode == TRADE_RETCODE_DONE);
   if(accepted)
   {
      g_accepted++;
   }
   PrintFormat("CHECK %-28s %s retcode=%u (%s) margin=%.2f free=%.2f",
               label, accepted ? "ACCEPTED" : "REFUSED ", check.retcode, check.comment, check.margin, check.margin_free);
}

void OnStart()
{
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO)
   {
      Print("TradingOsRequestCheck: this account is not a demo — refusing to run. Nothing was checked.");
      return;
   }
   if(!SymbolSelect(InpSymbol, true))
   {
      Print("TradingOsRequestCheck: symbol '", InpSymbol, "' is not available on this terminal.");
      return;
   }
   double point = SymbolInfoDouble(InpSymbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS);
   double bid = SymbolInfoDouble(InpSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(InpSymbol, SYMBOL_ASK);
   if(point <= 0 || bid <= 0 || ask <= 0)
   {
      Print("TradingOsRequestCheck: no quote for '", InpSymbol, "'.");
      return;
   }
   long stopsLevel = SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_STOPS_LEVEL);
   double distance = MathMax((double)InpStopPoints, (double)stopsLevel + 20.0) * point;
   PrintFormat("TradingOsRequestCheck on %s (demo): bid=%s ask=%s stopsLevel=%d points, distance used=%s",
               InpSymbol, DoubleToString(bid, digits), DoubleToString(ask, digits), (int)stopsLevel, DoubleToString(distance, digits));

   TradeCommand cmd;

   // 1. an order at the market, each way
   TradeCommandInit(cmd, "OPEN", "check-market-buy", InpSymbol);
   cmd.side = "BUY"; cmd.orderType = "MARKET"; cmd.volume = InpVolume;
   cmd.sl = bid - distance; cmd.tp = bid + distance;
   CheckRequest("OPEN MARKET BUY", cmd);

   TradeCommandInit(cmd, "OPEN", "check-market-sell", InpSymbol);
   cmd.side = "SELL"; cmd.orderType = "MARKET"; cmd.volume = InpVolume;
   cmd.sl = ask + distance; cmd.tp = ask - distance;
   CheckRequest("OPEN MARKET SELL", cmd);

   // 2. a resting order, each way, well away from the market
   TradeCommandInit(cmd, "OPEN", "check-limit-buy", InpSymbol);
   cmd.side = "BUY"; cmd.orderType = "LIMIT"; cmd.volume = InpVolume;
   cmd.price = ask - 3 * distance; cmd.sl = cmd.price - distance; cmd.tp = cmd.price + 2 * distance;
   CheckRequest("OPEN LIMIT BUY", cmd);

   TradeCommandInit(cmd, "OPEN", "check-limit-sell", InpSymbol);
   cmd.side = "SELL"; cmd.orderType = "LIMIT"; cmd.volume = InpVolume;
   cmd.price = bid + 3 * distance; cmd.sl = cmd.price + distance; cmd.tp = cmd.price - 2 * distance;
   CheckRequest("OPEN LIMIT SELL", cmd);

   // 3. an existing position: a stop move (to the levels it already has — a no-op by design), a close
   ulong ticket = 0;
   if(InpPositionId > 0 && TradeSelectPosition(InpPositionId, ticket))
   {
      TradeCommandInit(cmd, "MODIFY", "check-modify", PositionGetString(POSITION_SYMBOL));
      cmd.positionId = InpPositionId;
      cmd.hasSl = true; cmd.sl = PositionGetDouble(POSITION_SL);
      cmd.hasTp = PositionGetDouble(POSITION_TP) > 0; cmd.tp = PositionGetDouble(POSITION_TP);
      CheckRequest("MODIFY (same levels)", cmd);

      TradeSelectPosition(InpPositionId, ticket);
      TradeCommandInit(cmd, "CLOSE", "check-close", PositionGetString(POSITION_SYMBOL));
      cmd.positionId = InpPositionId;
      CheckRequest("CLOSE", cmd);
   }
   else if(InpPositionId > 0)
   {
      PrintFormat("CHECK MODIFY / CLOSE               SKIPPED: no open position %I64d on this terminal", InpPositionId);
   }

   // 4. an existing pending order: a removal
   if(InpOrderId > 0 && TradeSelectPendingOrder(InpOrderId))
   {
      TradeCommandInit(cmd, "CANCEL", "check-cancel", OrderGetString(ORDER_SYMBOL));
      cmd.orderId = InpOrderId;
      CheckRequest("CANCEL", cmd);
   }
   else if(InpOrderId > 0)
   {
      PrintFormat("CHECK CANCEL                      SKIPPED: no pending order %I64d on this terminal", InpOrderId);
   }

   PrintFormat("TradingOsRequestCheck done: %d request(s) built, %d accepted by the server's check. NO ORDER WAS SENT.",
               g_checked, g_accepted);
}
