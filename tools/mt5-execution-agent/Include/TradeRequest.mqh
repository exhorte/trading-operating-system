//+------------------------------------------------------------------+
//| TradeRequest.mqh — EA-05 (ADR 0029)                               |
//|                                                                   |
//| What the agent is asked to do (TradeCommand) and how that becomes |
//| a broker request (BuildTradeRequest). Nothing in this file sends  |
//| anything: the only OrderSend of the repository is in               |
//| TradingOsAgent.mq5, inside ExecuteOrder, behind its mode barrier.  |
//| The request-check script (Scripts/TradingOsRequestCheck.mq5)       |
//| includes this same file and calls OrderCheck only, so the requests |
//| the agent would send can be validated by the server of a demo      |
//| account without a single order leaving the terminal.               |
//|                                                                   |
//| Positions are looked up by POSITION_IDENTIFIER, never by a ticket   |
//| the core might hold: the two diverge on broker service operations  |
//| (2026-09-05 incident). The ticket is read from the terminal at the  |
//| moment the request is built.                                       |
//+------------------------------------------------------------------+
#ifndef TRADINGOS_TRADE_REQUEST_MQH
#define TRADINGOS_TRADE_REQUEST_MQH

//--- A command as every handler builds it, before it reaches ExecuteOrder.
//    kind: "OPEN" (orderType MARKET | LIMIT) | "MODIFY" | "CLOSE" | "PARTIAL_CLOSE" | "CANCEL".
//    side is the order's own for OPEN; for the others the validation fills it with the side of the target (for the report).
struct TradeCommand
{
   string kind;
   string commandId;
   string symbol;
   string side;
   string orderType;
   double volume;       // OPEN; PARTIAL_CLOSE (lots to close); CLOSE (filled by the validation with the open volume)
   double price;        // LIMIT: the limit price
   double sl;
   double tp;
   bool   hasSl;        // MODIFY: the command names a stop (a null leaves it as it is)
   bool   hasTp;
   long   positionId;   // MODIFY, CLOSE, PARTIAL_CLOSE: POSITION_IDENTIFIER
   long   orderId;      // CANCEL: the pending order's ticket
};

void TradeCommandInit(TradeCommand &cmd, const string kind, const string commandId, const string symbol)
{
   cmd.kind = kind;
   cmd.commandId = commandId;
   cmd.symbol = symbol;
   cmd.side = "";
   cmd.orderType = "";
   cmd.volume = 0.0;
   cmd.price = 0.0;
   cmd.sl = 0.0;
   cmd.tp = 0.0;
   cmd.hasSl = false;
   cmd.hasTp = false;
   cmd.positionId = 0;
   cmd.orderId = 0;
}

bool TradeCommandReducesRiskOnly(const string kind)
{
   return kind == "CLOSE" || kind == "PARTIAL_CLOSE" || kind == "CANCEL";
}

//--- The open position whose POSITION_IDENTIFIER is `identifier`: selected for PositionGet*, its ticket returned.
bool TradeSelectPosition(const long identifier, ulong &ticket)
{
   if(identifier <= 0)
   {
      return false;
   }
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong candidate = PositionGetTicket(i); // selects the position by index
      if(candidate == 0)
      {
         continue;
      }
      if((long)PositionGetInteger(POSITION_IDENTIFIER) == identifier)
      {
         ticket = candidate;
         return true;
      }
   }
   return false;
}

//--- The pending order with this ticket: selected for OrderGet*.
bool TradeSelectPendingOrder(const long ticket)
{
   if(ticket <= 0)
   {
      return false;
   }
   return OrderSelect((ulong)ticket);
}

bool TradeOrderTypeIsPending(const ENUM_ORDER_TYPE type)
{
   return type == ORDER_TYPE_BUY_LIMIT || type == ORDER_TYPE_SELL_LIMIT ||
          type == ORDER_TYPE_BUY_STOP || type == ORDER_TYPE_SELL_STOP ||
          type == ORDER_TYPE_BUY_STOP_LIMIT || type == ORDER_TYPE_SELL_STOP_LIMIT;
}

bool TradeOrderTypeIsBuy(const ENUM_ORDER_TYPE type)
{
   return type == ORDER_TYPE_BUY || type == ORDER_TYPE_BUY_LIMIT ||
          type == ORDER_TYPE_BUY_STOP || type == ORDER_TYPE_BUY_STOP_LIMIT;
}

//--- The broker's minimum distance between the price and a stop or a target, in price units.
double TradeStopsDistance(const string symbol)
{
   return (double)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL) * SymbolInfoDouble(symbol, SYMBOL_POINT);
}

//--- "" when `volume` is a volume the symbol accepts (minimum, maximum, step); else why not.
string TradeVolumeProblem(const string symbol, const double volume)
{
   double minVolume = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxVolume = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(minVolume <= 0 || maxVolume <= 0 || step <= 0)
   {
      return "volume rules of '" + symbol + "' are not available on this terminal";
   }
   if(volume < minVolume - 1e-9 || volume > maxVolume + 1e-9)
   {
      return "volume " + DoubleToString(volume, 2) + " is outside the symbol's [" + DoubleToString(minVolume, 2) +
             ", " + DoubleToString(maxVolume, 2) + "]";
   }
   double steps = (volume - minVolume) / step;
   if(MathAbs(steps - MathRound(steps)) > 1e-6)
   {
      return "volume " + DoubleToString(volume, 2) + " is not a multiple of the symbol's step " + DoubleToString(step, 2);
   }
   return "";
}

//--- Turns a validated command into the one broker request that carries it. Returns "" when the request is built, else the
//    reason it cannot be (a target that is gone, a side that is neither BUY nor SELL). No validation of the trading rules is
//    done here — that is the agent's ValidateTradeCommand, which runs before and again inside ExecuteOrder — and nothing is
//    sent. `pendingExpiration` is a broker (server) time.
string BuildTradeRequest(const TradeCommand &cmd, const int magic, const int deviation,
                         const ENUM_ORDER_TYPE_FILLING marketFilling, const datetime pendingExpiration,
                         const string comment, MqlTradeRequest &request)
{
   ZeroMemory(request);
   request.symbol  = cmd.symbol;
   request.magic   = magic;
   request.comment = comment;
   int digits = (int)SymbolInfoInteger(cmd.symbol, SYMBOL_DIGITS);

   if(cmd.kind == "OPEN")
   {
      bool isBuy = (cmd.side == "BUY");
      if(!isBuy && cmd.side != "SELL")
      {
         return "INVALID_REQUEST: side '" + cmd.side + "' is neither BUY nor SELL";
      }
      request.volume = cmd.volume;
      request.sl     = NormalizeDouble(cmd.sl, digits);
      request.tp     = cmd.tp > 0 ? NormalizeDouble(cmd.tp, digits) : 0.0;
      if(cmd.orderType == "MARKET")
      {
         request.action       = TRADE_ACTION_DEAL;
         request.type         = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
         request.price        = isBuy ? SymbolInfoDouble(cmd.symbol, SYMBOL_ASK) : SymbolInfoDouble(cmd.symbol, SYMBOL_BID);
         request.deviation    = deviation;
         request.type_filling = marketFilling;
         return "";
      }
      if(cmd.orderType == "LIMIT")
      {
         request.action       = TRADE_ACTION_PENDING;
         request.type         = isBuy ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT;
         request.price        = NormalizeDouble(cmd.price, digits);
         request.type_time    = ORDER_TIME_SPECIFIED; // a resting order never lives without an end (ADR 0029)
         request.expiration   = pendingExpiration;
         request.type_filling = ORDER_FILLING_RETURN;
         return "";
      }
      return "ORDER_TYPE_UNSUPPORTED: orderType '" + cmd.orderType + "'";
   }

   if(cmd.kind == "MODIFY" || cmd.kind == "CLOSE" || cmd.kind == "PARTIAL_CLOSE")
   {
      ulong ticket = 0;
      if(!TradeSelectPosition(cmd.positionId, ticket))
      {
         return "POSITION_NOT_FOUND: no open position " + IntegerToString(cmd.positionId) + " on this terminal";
      }
      request.position = ticket;
      if(cmd.kind == "MODIFY")
      {
         // SLTP carries both levels: the one the command does not name keeps the value the position has now.
         request.action = TRADE_ACTION_SLTP;
         request.sl     = cmd.hasSl ? NormalizeDouble(cmd.sl, digits) : PositionGetDouble(POSITION_SL);
         request.tp     = cmd.hasTp ? NormalizeDouble(cmd.tp, digits) : PositionGetDouble(POSITION_TP);
         return "";
      }
      bool wasBuy = ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      request.action       = TRADE_ACTION_DEAL;
      request.type         = wasBuy ? ORDER_TYPE_SELL : ORDER_TYPE_BUY; // the deal that closes goes the other way
      request.price        = wasBuy ? SymbolInfoDouble(cmd.symbol, SYMBOL_BID) : SymbolInfoDouble(cmd.symbol, SYMBOL_ASK);
      request.volume       = (cmd.kind == "CLOSE") ? PositionGetDouble(POSITION_VOLUME) : cmd.volume;
      request.deviation    = deviation;
      request.type_filling = marketFilling;
      return "";
   }

   if(cmd.kind == "CANCEL")
   {
      if(!TradeSelectPendingOrder(cmd.orderId))
      {
         return "ORDER_NOT_FOUND: no pending order " + IntegerToString(cmd.orderId) + " on this terminal";
      }
      request.action = TRADE_ACTION_REMOVE;
      request.order  = (ulong)cmd.orderId;
      return "";
   }

   return "INVALID_REQUEST: unknown command kind '" + cmd.kind + "'";
}

#endif // TRADINGOS_TRADE_REQUEST_MQH
