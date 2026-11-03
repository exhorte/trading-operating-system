//+------------------------------------------------------------------+
//| CommandStore.mqh — EA-05                                          |
//|                                                                   |
//| Persists commandId -> last-known result ON DISK, so a repeated     |
//| commandId NEVER re-executes and always returns the same result     |
//| (ADR 0010: "une commande rejouée avec le même commandId retourne   |
//| le résultat précédent ; elle ne produit JAMAIS une seconde         |
//| position"). Survives an EA restart or a terminal restart — an      |
//| in-memory map would not.                                           |
//|                                                                     |
//| Stored under the terminal's sandboxed MQL5\Files\ directory (no    |
//| FILE_COMMON). I1 (2026-09-26): one file per LOGIN and magic number |
//| — the terminal can switch accounts under a running agent, and a    |
//| commandId recorded for one account must never answer for another.  |
//| No file of the older per-magic-only layout existed on this         |
//| terminal when the layout changed: the agent had never received a   |
//| command.                                                            |
//|                                                                     |
//| Format: one line per write, appended, never rewritten in place.    |
//| Since I1 a line carries the whole report, so an outcome can be sent |
//| again after a reconnection (ReplayRecentReports in the agent):      |
//| "<commandId>\t<status>\t<detail>\t<symbol>\t<side>\t<timeMs>\t     |
//|  <orderId>\t<positionId>\t<volume>\t<price>\t<retcode>\t<kind>\t    |
//|  <sl>\t<tp>". The last three (1.12, ADR 0029) say WHAT an UNKNOWN   |
//| line was about — a limit order, a stop move, a close, a cancel — so |
//| that reconciliation can look for the right thing; a line written    |
//| before 1.12 has none of them and reads as an OPEN at the market.    |
//| Lookup scans the whole file and keeps the LAST matching line (last |
//| write wins). A personal trading system issues at most a handful of  |
//| commands a day; a linear scan of a small text file is simple and    |
//| fast enough. This is not a database and must not be asked to be one.|
//+------------------------------------------------------------------+
#ifndef TRADINGOS_COMMAND_STORE_MQH
#define TRADINGOS_COMMAND_STORE_MQH

string g_command_store_file = "";

struct CommandRecord
{
   string commandId;
   string status;
   string detail;
   string symbol;
   string side;
   long   timeMs;
   long   brokerOrderId;
   long   brokerPositionId;
   double filledVolume;
   double averagePrice;
   int    retcode;
   string kind;   // "" (written before 1.12) | OPEN | MODIFY | CLOSE | PARTIAL_CLOSE | CANCEL
   double sl;     // the stop a MODIFY wanted (0 = none named)
   double tp;     // the target a MODIFY wanted (0 = none named)
};

void CommandRecordInit(CommandRecord &rec, const string commandId, const string status, const string detail,
                       const string symbol, const string side, const long timeMs)
{
   rec.commandId = commandId;
   rec.status = status;
   rec.detail = detail;
   rec.symbol = symbol;
   rec.side = side;
   rec.timeMs = timeMs;
   rec.brokerOrderId = 0;
   rec.brokerPositionId = 0;
   rec.filledVolume = 0.0;
   rec.averagePrice = 0.0;
   rec.retcode = 0;
   rec.kind = "";
   rec.sl = 0.0;
   rec.tp = 0.0;
}

void CommandStoreInit(const long login, const int magicNumber)
{
   g_command_store_file = "tradingos_commands_" + IntegerToString(login) + "_" + IntegerToString(magicNumber) + ".log";
}

string CommandStoreSanitize(string value)
{
   StringReplace(value, "\t", " ");
   StringReplace(value, "\r", " ");
   StringReplace(value, "\n", " ");
   return value;
}

//--- One stored line -> record. False for a line too short to mean anything.
bool CommandStoreParseLine(const string line, CommandRecord &rec)
{
   string parts[];
   int n = StringSplit(line, '\t', parts);
   if(n < 2)
   {
      return false;
   }
   CommandRecordInit(rec, parts[0], parts[1], (n >= 3 ? parts[2] : ""), (n >= 4 ? parts[3] : ""),
                     (n >= 5 ? parts[4] : ""), (n >= 6 ? StringToInteger(parts[5]) : 0));
   rec.brokerOrderId = (n >= 7 ? StringToInteger(parts[6]) : 0);
   rec.brokerPositionId = (n >= 8 ? StringToInteger(parts[7]) : 0);
   rec.filledVolume = (n >= 9 ? StringToDouble(parts[8]) : 0.0);
   rec.averagePrice = (n >= 10 ? StringToDouble(parts[9]) : 0.0);
   rec.retcode = (n >= 11 ? (int)StringToInteger(parts[10]) : 0);
   rec.kind = (n >= 12 ? parts[11] : "");
   rec.sl = (n >= 13 ? StringToDouble(parts[12]) : 0.0);
   rec.tp = (n >= 14 ? StringToDouble(parts[13]) : 0.0);
   return true;
}

//--- Returns true and fills rec if commandId has a prior, recorded result.
//    False means this commandId has never been seen on this login.
bool CommandStoreLookup(const string commandId, CommandRecord &rec)
{
   int handle = FileOpen(g_command_store_file, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
   {
      return false; // no store file yet: this commandId has never been recorded
   }

   bool found = false;
   while(!FileIsEnding(handle))
   {
      string line = FileReadString(handle);
      if(StringLen(line) == 0)
      {
         continue;
      }
      CommandRecord candidate;
      if(CommandStoreParseLine(line, candidate) && candidate.commandId == commandId)
      {
         rec = candidate;
         found = true; // keep scanning — the LAST match wins
      }
   }
   FileClose(handle);
   return found;
}

//--- Appends one record. Returns false when it could NOT be persisted —
//    since I1 the caller must act on that: ExecuteOrder refuses to send an
//    order whose UNKNOWN line could not be written, because nothing would
//    then stop a replay of the same commandId from sending a second one.
bool CommandStoreRecord(const CommandRecord &rec)
{
   int handle = FileOpen(g_command_store_file, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
   {
      Print("CommandStoreRecord: FileOpen failed for '", g_command_store_file, "', error ", GetLastError());
      return false;
   }

   if(!FileSeek(handle, 0, SEEK_END))
   {
      Print("CommandStoreRecord: FileSeek failed for '", g_command_store_file, "', error ", GetLastError());
      FileClose(handle);
      return false;
   }
   string line = CommandStoreSanitize(rec.commandId) + "\t" + CommandStoreSanitize(rec.status) + "\t" +
                 CommandStoreSanitize(rec.detail) + "\t" + CommandStoreSanitize(rec.symbol) + "\t" +
                 CommandStoreSanitize(rec.side) + "\t" + IntegerToString(rec.timeMs) + "\t" +
                 IntegerToString(rec.brokerOrderId) + "\t" + IntegerToString(rec.brokerPositionId) + "\t" +
                 DoubleToString(rec.filledVolume, 2) + "\t" + DoubleToString(rec.averagePrice, 8) + "\t" +
                 IntegerToString(rec.retcode) + "\t" + CommandStoreSanitize(rec.kind) + "\t" +
                 DoubleToString(rec.sl, 8) + "\t" + DoubleToString(rec.tp, 8);
   uint written = FileWrite(handle, line);
   FileClose(handle);
   if(written == 0)
   {
      Print("CommandStoreRecord: FileWrite failed for '", g_command_store_file, "', error ", GetLastError());
      return false;
   }
   return true;
}

//--- The last record of every commandId, in first-seen order.
int CommandStoreLatest(CommandRecord &latest[])
{
   ArrayResize(latest, 0);
   int handle = FileOpen(g_command_store_file, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
   {
      return 0; // no store file yet: nothing has ever been recorded
   }

   int count = 0;
   while(!FileIsEnding(handle))
   {
      string line = FileReadString(handle);
      if(StringLen(line) == 0)
      {
         continue;
      }
      CommandRecord rec;
      if(!CommandStoreParseLine(line, rec))
      {
         continue;
      }
      int existing = -1;
      for(int i = 0; i < count; i++)
      {
         if(latest[i].commandId == rec.commandId)
         {
            existing = i;
            break;
         }
      }
      if(existing >= 0)
      {
         latest[existing] = rec; // last write wins
      }
      else
      {
         ArrayResize(latest, count + 1);
         latest[count] = rec;
         count++;
      }
   }
   FileClose(handle);
   return count;
}

//--- EA-06: every command whose most recent recorded status is exactly
//    "UNKNOWN" — last write wins, same rule as CommandStoreLookup. The whole
//    record comes back (1.12): reconciliation needs to know what the line was about.
int CommandStoreFindUnknown(CommandRecord &unknown[])
{
   ArrayResize(unknown, 0);
   CommandRecord latest[];
   int count = CommandStoreLatest(latest);
   int found = 0;
   for(int i = 0; i < count; i++)
   {
      if(latest[i].status == "UNKNOWN")
      {
         ArrayResize(unknown, found + 1);
         unknown[found] = latest[i];
         found++;
      }
   }
   return found;
}

//--- Statuses that end a command's story and are reported to the core:
//    FILLED / PARTIALLY_FILLED (a market order), SUBMITTED (a pending order is
//    resting at the broker), MODIFIED, CLOSED, CANCELLED (1.12), plus the refusals.
bool CommandStoreIsFinalStatus(const string status)
{
   return status == "SIMULATED" || status == "FILLED" || status == "PARTIALLY_FILLED" ||
          status == "SUBMITTED" || status == "MODIFIED" || status == "CLOSED" || status == "CANCELLED" ||
          status == "FAILED" || status == "REJECTED";
}

//--- I1: final outcomes recorded at or after sinceMs — what the agent sends
//    again after a reconnection. The core derives a report's id from its
//    commandId, status and time, so a report it already has is not stored twice.
int CommandStoreRecentFinal(const long sinceMs, CommandRecord &records[])
{
   ArrayResize(records, 0);
   CommandRecord latest[];
   int count = CommandStoreLatest(latest);
   int found = 0;
   for(int i = 0; i < count; i++)
   {
      if(CommandStoreIsFinalStatus(latest[i].status) && latest[i].timeMs >= sinceMs)
      {
         ArrayResize(records, found + 1);
         records[found] = latest[i];
         found++;
      }
   }
   return found;
}

//--- I1: the short trace an order carries in its broker comment. The old
//    "TradingOS <commandId>" ran past the ~31 characters a broker keeps, so
//    reconciliation, which matches on it, could never have found a truncated
//    one. "TOS " + 16 hex characters of SHA-256(commandId) = 20 characters.
string CommandTrace(const string commandId)
{
   uchar data[], key[], hash[];
   int n = StringToCharArray(commandId, data, 0, -1, CP_UTF8);
   if(n > 0 && data[n - 1] == 0)
   {
      ArrayResize(data, n - 1); // count -1 copies the terminating 0: not part of the id
   }
   if(CryptEncode(CRYPT_HASH_SHA256, data, key, hash) < 8)
   {
      return "TOS " + StringSubstr(commandId, 0, 27); // still within 31 characters
   }
   string hex = "";
   for(int i = 0; i < 8; i++)
   {
      hex += StringFormat("%02x", hash[i]);
   }
   return "TOS " + hex;
}

//--- The commandId whose trace is `trace`, or "" — how a position's comment
//    is tied back to its command (ScanOpenPositions).
string CommandStoreFindByTrace(const string trace)
{
   CommandRecord latest[];
   int count = CommandStoreLatest(latest);
   for(int i = 0; i < count; i++)
   {
      if(CommandTrace(latest[i].commandId) == trace)
      {
         return latest[i].commandId;
      }
   }
   return "";
}

#endif // TRADINGOS_COMMAND_STORE_MQH
