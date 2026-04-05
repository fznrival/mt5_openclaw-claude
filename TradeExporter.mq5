//+------------------------------------------------------------------+
//|  TradeExporter.mq5                                               |
//|  Export closed trades ke CSV untuk dibaca OpenClaw               |
//|  Compatible dengan ICT methodology (Killzone WIB)                |
//+------------------------------------------------------------------+
#property copyright "fznrival"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\DealInfo.mqh>

// === INPUT PARAMETERS ===
input string   CSV_Filename     = "trade_log.csv";   // Nama file output CSV
input bool     ExportOnClose    = true;               // Export saat trade close
input bool     ExportOnStart    = true;               // Export semua history saat EA start
input int      LookbackDays     = 30;                 // Berapa hari history yang diexport

// === GLOBAL VARIABLES ===
CDealInfo      dealInfo;
datetime       lastExportTime   = 0;
string         fullPath;

//+------------------------------------------------------------------+
//| Expert initialization                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   fullPath = CSV_Filename;
   Print("TradeExporter initialized. Output: ", fullPath);
   
   // Export history saat pertama start
   if(ExportOnStart)
   {
      ExportHistoryToCSV();
      Print("Initial export complete.");
   }
   
   // Set timer untuk cek setiap menit
   EventSetTimer(60);
   
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("TradeExporter stopped.");
}

//+------------------------------------------------------------------+
//| Timer - cek dan export setiap 60 detik                           |
//+------------------------------------------------------------------+
void OnTimer()
{
   ExportHistoryToCSV();
}

//+------------------------------------------------------------------+
//| Trade event - trigger saat ada trade baru                        |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& request,
                        const MqlTradeResult& result)
{
   // Hanya proses saat deal selesai (trade close)
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
   {
      if(ExportOnClose)
      {
         Sleep(500); // Tunggu sebentar agar data lengkap
         ExportHistoryToCSV();
      }
   }
}

//+------------------------------------------------------------------+
//| Export semua history ke CSV                                       |
//+------------------------------------------------------------------+
void ExportHistoryToCSV()
{
   datetime fromDate = TimeCurrent() - (datetime)(LookbackDays * 86400);
   datetime toDate   = TimeCurrent();
   
   if(!HistorySelect(fromDate, toDate))
   {
      Print("Failed to select history");
      return;
   }
   
   int totalDeals = HistoryDealsTotal();
   if(totalDeals == 0)
   {
      Print("No deals found in history range.");
      return;
   }
   
   // Buka file untuk write (overwrite setiap kali)
   int fileHandle = FileOpen(fullPath, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fileHandle == INVALID_HANDLE)
   {
      Print("ERROR: Cannot open file ", fullPath, " Error: ", GetLastError());
      return;
   }
   
   // === HEADER CSV ===
   FileWrite(fileHandle,
      "ticket",
      "open_time",
      "close_time",
      "symbol",
      "type",           // BUY / SELL
      "volume",
      "open_price",
      "close_price",
      "sl",
      "tp",
      "profit",
      "commission",
      "swap",
      "net_profit",
      "duration_min",
      "rr_actual",
      "session",        // Asia / London / NewYork
      "comment"
   );
   
   // === DATA ROWS ===
   // Kumpulkan data per position (matching entry & exit)
   for(int i = 0; i < totalDeals; i++)
   {
      ulong dealTicket = HistoryDealGetTicket(i);
      if(dealTicket == 0) continue;
      
      // Hanya ambil deal tipe OUT (trade close)
      ENUM_DEAL_ENTRY dealEntry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
      if(dealEntry != DEAL_ENTRY_OUT) continue;
      
      // Skip deal dengan profit 0 dan tipe balance/credit
      ENUM_DEAL_TYPE dealType = (ENUM_DEAL_TYPE)HistoryDealGetInteger(dealTicket, DEAL_TYPE);
      if(dealType != DEAL_TYPE_BUY && dealType != DEAL_TYPE_SELL) continue;
      
      // Ambil data deal
      datetime closeTime  = (datetime)HistoryDealGetInteger(dealTicket, DEAL_TIME);
      string   symbol     = HistoryDealGetString(dealTicket, DEAL_SYMBOL);
      double   volume     = HistoryDealGetDouble(dealTicket, DEAL_VOLUME);
      double   closePrice = HistoryDealGetDouble(dealTicket, DEAL_PRICE);
      double   profit     = HistoryDealGetDouble(dealTicket, DEAL_PROFIT);
      double   commission = HistoryDealGetDouble(dealTicket, DEAL_COMMISSION);
      double   swap       = HistoryDealGetDouble(dealTicket, DEAL_SWAP);
      double   netProfit  = profit + commission + swap;
      string   comment    = HistoryDealGetString(dealTicket, DEAL_COMMENT);
      ulong    positionId = HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID);
      
      // Cari entry deal yang matching (position ID sama, tipe IN)
      datetime openTime   = closeTime;
      double   openPrice  = closePrice;
      double   sl         = 0;
      double   tp         = 0;
      string   tradeDir   = (dealType == DEAL_TYPE_BUY) ? "SELL" : "BUY"; // OUT deal typenya kebalik
      
      for(int j = 0; j < totalDeals; j++)
      {
         ulong entryTicket = HistoryDealGetTicket(j);
         if(entryTicket == 0) continue;
         
         ulong entryPosId = HistoryDealGetInteger(entryTicket, DEAL_POSITION_ID);
         ENUM_DEAL_ENTRY entryType = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(entryTicket, DEAL_ENTRY);
         
         if(entryPosId == positionId && entryType == DEAL_ENTRY_IN)
         {
            openTime  = (datetime)HistoryDealGetInteger(entryTicket, DEAL_TIME);
            openPrice = HistoryDealGetDouble(entryTicket, DEAL_PRICE);
            ENUM_DEAL_TYPE entryDealType = (ENUM_DEAL_TYPE)HistoryDealGetInteger(entryTicket, DEAL_TYPE);
            tradeDir  = (entryDealType == DEAL_TYPE_BUY) ? "BUY" : "SELL";
            break;
         }
      }
      
      // Hitung durasi dalam menit
      long durationMin = (long)(closeTime - openTime) / 60;
      
      // Hitung RR aktual (sederhana berdasarkan profit vs stop loss estimate)
      double rrActual = 0;
      // RR = profit / (estimasi risk berdasarkan avg loss)
      // Akan dihitung lebih akurat di Python
      
      // Deteksi session berdasarkan waktu close (WIB = UTC+7)
      MqlDateTime closeStruct;
      TimeToStruct(closeTime + 7*3600, closeStruct); // Convert ke WIB
      int hourWIB = closeStruct.hour;
      string session = "Off-Session";
      if(hourWIB >= 3 && hourWIB < 6)   session = "Asia-Killzone";
      else if(hourWIB >= 6 && hourWIB < 9) session = "Asia";
      else if(hourWIB >= 15 && hourWIB < 18) session = "London-Killzone";
      else if(hourWIB >= 18 && hourWIB < 22) session = "London";
      else if(hourWIB >= 20 && hourWIB < 23) session = "NY-Killzone";
      else if(hourWIB >= 23 || hourWIB < 3) session = "NewYork";
      
      // Write row ke CSV
      FileWrite(fileHandle,
         (string)positionId,
         TimeToString(openTime, TIME_DATE|TIME_MINUTES),
         TimeToString(closeTime, TIME_DATE|TIME_MINUTES),
         symbol,
         tradeDir,
         DoubleToString(volume, 2),
         DoubleToString(openPrice, _Digits),
         DoubleToString(closePrice, _Digits),
         DoubleToString(sl, _Digits),
         DoubleToString(tp, _Digits),
         DoubleToString(profit, 2),
         DoubleToString(commission, 2),
         DoubleToString(swap, 2),
         DoubleToString(netProfit, 2),
         (string)durationMin,
         DoubleToString(rrActual, 2),
         session,
         comment
      );
   }
   
   FileClose(fileHandle);
   Print("CSV exported: ", totalDeals, " deals processed -> ", fullPath);
   lastExportTime = TimeCurrent();
}
//+------------------------------------------------------------------+
