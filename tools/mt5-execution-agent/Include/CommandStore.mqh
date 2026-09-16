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
//| FILE_COMMON): each terminal instance is its own environment (ADR    |
//| 0010 isolation — one terminal, one agent instance, one magic        |
//| number per account), so the file naturally never crosses accounts. |
//| The filename is suffixed with the magic number as a second guard   |
//| in case more than one instance ever ran in one terminal.           |
//|                                                                     |
//| Format: one line per write, appended, never rewritten in place —   |
//| "<commandId>\t<status>\t<detail>". Lookup scans the whole file and |
//| keeps the LAST matching line (last write wins). A personal trading |
//| system issues at most a handful of commands a day; a linear scan   |
//| of a small text file is simple and fast enough. This is not a       |
//| database and must not be asked to be one.                          |
//+------------------------------------------------------------------+
#ifndef TRADINGOS_COMMAND_STORE_MQH
#define TRADINGOS_COMMAND_STORE_MQH

string g_command_store_file = "tradingos_commands.log";

void CommandStoreInit(int magicNumber)
{
   g_command_store_file = "tradingos_commands_" + IntegerToString(magicNumber) + ".log";
}

//--- Returns true and fills status/detail if commandId has a prior,
//    recorded result. False means this commandId has never been seen.
bool CommandStoreLookup(const string commandId, string &status, string &detail)
{
   status = "";
   detail = "";

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
      string parts[];
      int n = StringSplit(line, '\t', parts);
      if(n >= 2 && parts[0] == commandId)
      {
         status = parts[1];
         detail = (n >= 3 ? parts[2] : "");
         found = true; // keep scanning — the LAST match wins
      }
   }
   FileClose(handle);
   return found;
}

//--- Appends the result for commandId. Best-effort: if the file cannot be
//    opened, the caller must not assume the record was persisted — this
//    function does not throw, matching the rest of this agent's style of
//    never crashing on an I/O failure.
void CommandStoreRecord(const string commandId, const string status, const string detail)
{
   int handle = FileOpen(g_command_store_file, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
   {
      Print("CommandStoreRecord: FileOpen failed for '", g_command_store_file, "', error ", GetLastError());
      return;
   }

   FileSeek(handle, 0, SEEK_END);
   string safeDetail = detail;
   StringReplace(safeDetail, "\t", " ");
   StringReplace(safeDetail, "\n", " ");
   FileWrite(handle, commandId + "\t" + status + "\t" + safeDetail);
   FileClose(handle);
}

//--- EA-06: returns every commandId whose most recent recorded status is
//    exactly "UNKNOWN" — last write wins, same rule as CommandStoreLookup.
//    Lets reconciliation discover what needs resolving without knowing any
//    commandId in advance. Same linear-scan-of-a-small-file approach as the
//    rest of this store: a personal system leaves at most a handful of
//    UNKNOWN entries ever, not a stream to index.
int CommandStoreFindUnknown(string &commandIds[])
{
   ArrayResize(commandIds, 0);

   int handle = FileOpen(g_command_store_file, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
   {
      return 0; // no store file yet: nothing has ever been recorded
   }

   string ids[];
   string statuses[];
   int count = 0;

   while(!FileIsEnding(handle))
   {
      string line = FileReadString(handle);
      if(StringLen(line) == 0)
      {
         continue;
      }
      string parts[];
      int n = StringSplit(line, '\t', parts);
      if(n < 2)
      {
         continue;
      }

      int existingIndex = -1;
      for(int i = 0; i < count; i++)
      {
         if(ids[i] == parts[0])
         {
            existingIndex = i;
            break;
         }
      }
      if(existingIndex >= 0)
      {
         statuses[existingIndex] = parts[1]; // last write wins
      }
      else
      {
         ArrayResize(ids, count + 1);
         ArrayResize(statuses, count + 1);
         ids[count] = parts[0];
         statuses[count] = parts[1];
         count++;
      }
   }
   FileClose(handle);

   int found = 0;
   for(int i = 0; i < count; i++)
   {
      if(statuses[i] == "UNKNOWN")
      {
         ArrayResize(commandIds, found + 1);
         commandIds[found] = ids[i];
         found++;
      }
   }
   return found;
}

#endif // TRADINGOS_COMMAND_STORE_MQH
