//+------------------------------------------------------------------+
//| JsonLite.mqh — EA-05                                              |
//|                                                                   |
//| MQL5 has no built-in JSON library. Every message this agent reads |
//| or writes (lib/contracts/mt5-wire.ts, context/execution/protocol.md) |
//| is a FLAT object — no nested objects or arrays in any field this   |
//| agent parses or emits. This file is a purpose-built flat-object    |
//| scanner, not a general JSON parser: it must not be reused for a    |
//| nested payload without being rewritten first.                     |
//+------------------------------------------------------------------+
#ifndef TRADINGOS_JSON_LITE_MQH
#define TRADINGOS_JSON_LITE_MQH

bool JsonIsWhitespace(ushort c)
{
   return c == ' ' || c == '\t' || c == '\n' || c == '\r';
}

//--- Escapes a string for embedding as a JSON string value.
string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\n", "\\n");
   StringReplace(value, "\r", "\\r");
   StringReplace(value, "\t", "\\t");
   return value;
}

//--- Finds the raw value text for a top-level key in a flat JSON object.
//    Strings are unescaped and unquoted; numbers/bools are returned
//    verbatim as text; isNull is set for a JSON null. Returns false if the
//    key is absent or the object is malformed at that point.
bool JsonFindRaw(const string json, const string key, string &rawValue, bool &isNull)
{
   rawValue = "";
   isNull = false;
   int len = StringLen(json);
   string needle = "\"" + key + "\"";
   int pos = StringFind(json, needle);
   if(pos < 0)
   {
      return false;
   }

   int cursor = pos + StringLen(needle);
   while(cursor < len && JsonIsWhitespace(StringGetCharacter(json, cursor)))
   {
      cursor++;
   }
   if(cursor >= len || StringGetCharacter(json, cursor) != ':')
   {
      return false;
   }
   cursor++;
   while(cursor < len && JsonIsWhitespace(StringGetCharacter(json, cursor)))
   {
      cursor++;
   }
   if(cursor >= len)
   {
      return false;
   }

   ushort c = StringGetCharacter(json, cursor);
   if(c == '"')
   {
      string outStr = "";
      int i = cursor + 1;
      while(i < len)
      {
         ushort ch = StringGetCharacter(json, i);
         if(ch == '\\' && i + 1 < len)
         {
            ushort next = StringGetCharacter(json, i + 1);
            if(next == 'n')      outStr += "\n";
            else if(next == 'r') outStr += "\r";
            else if(next == 't') outStr += "\t";
            else if(next == '"') outStr += "\"";
            else if(next == '\\') outStr += "\\";
            else outStr += StringSubstr(json, i + 1, 1);
            i += 2;
            continue;
         }
         if(ch == '"')
         {
            break;
         }
         outStr += StringSubstr(json, i, 1);
         i++;
      }
      rawValue = outStr;
      return true;
   }

   if(c == 'n' && StringSubstr(json, cursor, 4) == "null")
   {
      isNull = true;
      return true;
   }

   int i = cursor;
   while(i < len)
   {
      ushort ch = StringGetCharacter(json, i);
      if(ch == ',' || ch == '}' || ch == ']' || JsonIsWhitespace(ch))
      {
         break;
      }
      i++;
   }
   rawValue = StringSubstr(json, cursor, i - cursor);
   return true;
}

bool JsonHasKey(const string json, const string key)
{
   string raw;
   bool isNull;
   return JsonFindRaw(json, key, raw, isNull);
}

string JsonGetString(const string json, const string key, const string defaultValue = "")
{
   string raw;
   bool isNull;
   if(!JsonFindRaw(json, key, raw, isNull) || isNull)
   {
      return defaultValue;
   }
   return raw;
}

double JsonGetDouble(const string json, const string key, const double defaultValue = 0.0)
{
   string raw;
   bool isNull;
   if(!JsonFindRaw(json, key, raw, isNull) || isNull)
   {
      return defaultValue;
   }
   return StringToDouble(raw);
}

long JsonGetLong(const string json, const string key, const long defaultValue = 0)
{
   string raw;
   bool isNull;
   if(!JsonFindRaw(json, key, raw, isNull) || isNull)
   {
      return defaultValue;
   }
   return StringToInteger(raw);
}

#endif // TRADINGOS_JSON_LITE_MQH
