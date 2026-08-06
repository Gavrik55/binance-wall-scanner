//------------------------------------------------------------------------------
//
// Tiger DOM Logger for comparing Tiger.com order book data with Binance Wall Scanner.
// Put this file into: C:\Users\<USER>\Documents\TigerTrade\Indicators
//
//------------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Runtime.Serialization;
using System.Text;
using TigerTrade.Chart.Base;
using TigerTrade.Chart.Indicators.Common;
using TigerTrade.Chart.Indicators.Enums;
using TigerTrade.Dx;

namespace TigerTrade.Chart.Indicators.Custom
{
    [DataContract(Name = "TigerDomLoggerIndicator", Namespace = "http://schemas.datacontract.org/2004/07/TigerTrade.Chart.Indicators.Custom")]
    [Indicator("X_TigerDomLogger", "*Tiger DOM Logger", true, Type = typeof(TigerDomLoggerIndicator))]
    internal sealed class TigerDomLoggerIndicator : IndicatorBase
    {
        private const string Header =
            "source,row_type,local_time,ts_epoch_ms,symbol,side,price_ticks,price,raw_size,raw_size_quote,display_size,best_bid,best_ask,spread,dist_abs,dist_pct,is_best";

        private bool _enabled;

        [DataMember(Name = "Enabled")]
        [Category("Logger"), DisplayName("Enabled"), DefaultValue(false)]
        public bool Enabled
        {
            get { return _enabled; }
            set
            {
                if (value == _enabled)
                {
                    return;
                }

                _enabled = value;
                OnPropertyChanged();
            }
        }

        private int _intervalMs;

        [DataMember(Name = "IntervalMs")]
        [Category("Logger"), DisplayName("Interval, ms"), DefaultValue(250)]
        public int IntervalMs
        {
            get { return _intervalMs; }
            set
            {
                value = Math.Max(50, Math.Min(5000, value));

                if (value == _intervalMs)
                {
                    return;
                }

                _intervalMs = value;
                OnPropertyChanged();
            }
        }

        private int _maxLevelsPerSide;

        [DataMember(Name = "MaxLevelsPerSide")]
        [Category("Logger"), DisplayName("Max levels per side"), DefaultValue(50)]
        public int MaxLevelsPerSide
        {
            get { return _maxLevelsPerSide; }
            set
            {
                value = Math.Max(1, Math.Min(500, value));

                if (value == _maxLevelsPerSide)
                {
                    return;
                }

                _maxLevelsPerSide = value;
                OnPropertyChanged();
            }
        }

        private decimal _minRawSize;

        [DataMember(Name = "MinRawSize")]
        [Category("Logger"), DisplayName("Min raw size"), DefaultValue(typeof(decimal), "0")]
        public decimal MinRawSize
        {
            get { return _minRawSize; }
            set
            {
                value = Math.Max(0m, value);

                if (value == _minRawSize)
                {
                    return;
                }

                _minRawSize = value;
                OnPropertyChanged();
            }
        }

        private bool _onlyChangedRows;

        [DataMember(Name = "OnlyChangedRows")]
        [Category("Logger"), DisplayName("Only changed rows"), DefaultValue(false)]
        public bool OnlyChangedRows
        {
            get { return _onlyChangedRows; }
            set
            {
                if (value == _onlyChangedRows)
                {
                    return;
                }

                _onlyChangedRows = value;
                _lastRows.Clear();
                OnPropertyChanged();
            }
        }

        private string _outputFolder;

        [DataMember(Name = "OutputFolder")]
        [Category("Logger"), DisplayName("Output folder")]
        public string OutputFolder
        {
            get
            {
                return string.IsNullOrWhiteSpace(_outputFolder) ? DefaultOutputFolder() : _outputFolder;
            }
            set
            {
                value = string.IsNullOrWhiteSpace(value) ? DefaultOutputFolder() : value.Trim();

                if (value == _outputFolder)
                {
                    return;
                }

                _outputFolder = value;
                _currentPath = null;
                OnPropertyChanged();
            }
        }

        private int _roundValues;

        [DataMember(Name = "RoundValues")]
        [Category("Logger"), DisplayName("Display size decimals"), DefaultValue(8)]
        public int RoundValues
        {
            get { return _roundValues; }
            set
            {
                value = Math.Max(-4, Math.Min(8, value));

                if (value == _roundValues)
                {
                    return;
                }

                _roundValues = value;
                OnPropertyChanged();
            }
        }

        [Browsable(false)]
        public override bool ShowIndicatorValues
        {
            get { return false; }
        }

        [Browsable(false)]
        public override bool ShowIndicatorLabels
        {
            get { return false; }
        }

        [Browsable(false)]
        public override IndicatorCalculation Calculation
        {
            get { return IndicatorCalculation.OnEachTick; }
        }

        private DateTime _lastWriteUtc = DateTime.MinValue;
        private string _currentPath;
        private string _currentSymbol;
        private readonly HashSet<string> _lastRows = new HashSet<string>();

        public TigerDomLoggerIndicator()
        {
            ShowIndicatorTitle = true;
            Enabled = false;
            IntervalMs = 250;
            MaxLevelsPerSide = 50;
            MinRawSize = 0m;
            OnlyChangedRows = false;
            OutputFolder = DefaultOutputFolder();
            RoundValues = 8;
        }

        protected override void Execute()
        {
        }

        public override void Render(DxVisualQueue visual)
        {
            TryWriteSnapshot();
        }

        private void TryWriteSnapshot()
        {
            if (!Enabled)
            {
                return;
            }

            var nowUtc = DateTime.UtcNow;
            if ((nowUtc - _lastWriteUtc).TotalMilliseconds < IntervalMs)
            {
                return;
            }

            _lastWriteUtc = nowUtc;

            try
            {
                var dp = DataProvider;
                var symbol = dp.Symbol;
                var md = dp.GetRawMarketDepth();
                var step = dp.Step;

                if (md == null || md.BidQuotes == null || md.AskQuotes == null ||
                    md.BidQuotes.Count == 0 || md.AskQuotes.Count == 0 ||
                    md.MaxBidPrice <= 0 || md.MinAskPrice <= 0)
                {
                    return;
                }

                var symbolName = SafeCsv(symbol.ToString());
                EnsureFile(symbolName);

                var bestBid = md.MaxBidPrice * step;
                var bestAsk = md.MinAskPrice * step;
                var spread = bestAsk - bestBid;
                var tsMs = new DateTimeOffset(nowUtc).ToUnixTimeMilliseconds();
                var localTime = DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss.fff", CultureInfo.InvariantCulture);

                var rows = new StringBuilder();
                var snapshotRows = new HashSet<string>();

                AppendSide(rows, localTime, tsMs, symbolName, "ASK", md.MinAskPrice, md.MaxAskPrice,
                    md.AskQuotes, step, bestBid, bestAsk, spread, false, snapshotRows);

                AppendSide(rows, localTime, tsMs, symbolName, "BID", md.MaxBidPrice, md.MinBidPrice,
                    md.BidQuotes, step, bestBid, bestAsk, spread, true, snapshotRows);

                if (rows.Length > 0)
                {
                    File.AppendAllText(_currentPath, rows.ToString(), Encoding.UTF8);
                }

                if (OnlyChangedRows)
                {
                    _lastRows.Clear();

                    foreach (var row in snapshotRows)
                    {
                        _lastRows.Add(row);
                    }
                }
            }
            catch
            {
                // Tiger runs indicators on the terminal side. Logging errors must not break trading UI.
            }
        }

        private void AppendSide(
            StringBuilder rows,
            string localTime,
            long tsMs,
            string symbolName,
            string side,
            long startPriceTicks,
            long endPriceTicks,
            IReadOnlyDictionary<long, ValueTuple<long, long>> quotes,
            double step,
            double bestBid,
            double bestAsk,
            double spread,
            bool descending,
            HashSet<string> snapshotRows)
        {
            var written = 0;
            var scanned = 0;
            var priceTicks = startPriceTicks;

            while (written < MaxLevelsPerSide && scanned < 20000)
            {
                scanned++;

                if (descending && priceTicks < endPriceTicks)
                {
                    break;
                }

                if (!descending && priceTicks > endPriceTicks)
                {
                    break;
                }

                if (quotes.ContainsKey(priceTicks))
                {
                    var quote = quotes[priceTicks];
                    var rawSize = quote.Item1;
                    var rawSizeQuote = quote.Item2;

                    if (rawSize >= MinRawSize)
                    {
                        var price = priceTicks * step;
                        var distAbs = side == "BID" ? bestBid - price : price - bestAsk;
                        var distPctBase = side == "BID" ? bestBid : bestAsk;
                        var distPct = distPctBase > 0 ? distAbs / distPctBase * 100.0 : 0.0;
                        var isBest = priceTicks == startPriceTicks;
                        var displaySize = DataProvider.Symbol.FormatRawSize(rawSize, RoundValues, false);

                        var rowKey = side + "|" + priceTicks + "|" + rawSize;
                        snapshotRows.Add(rowKey);

                        if (!OnlyChangedRows || !_lastRows.Contains(rowKey))
                        {
                            rows.Append("tiger,DOM,");
                            rows.Append(Escape(localTime)).Append(",");
                            rows.Append(tsMs.ToString(CultureInfo.InvariantCulture)).Append(",");
                            rows.Append(Escape(symbolName)).Append(",");
                            rows.Append(side).Append(",");
                            rows.Append(priceTicks.ToString(CultureInfo.InvariantCulture)).Append(",");
                            rows.Append(price.ToString("0.############", CultureInfo.InvariantCulture)).Append(",");
                            rows.Append(rawSize.ToString(CultureInfo.InvariantCulture)).Append(",");
                            rows.Append(rawSizeQuote.ToString(CultureInfo.InvariantCulture)).Append(",");
                            rows.Append(Escape(displaySize)).Append(",");
                            rows.Append(bestBid.ToString("0.############", CultureInfo.InvariantCulture)).Append(",");
                            rows.Append(bestAsk.ToString("0.############", CultureInfo.InvariantCulture)).Append(",");
                            rows.Append(spread.ToString("0.############", CultureInfo.InvariantCulture)).Append(",");
                            rows.Append(distAbs.ToString("0.############", CultureInfo.InvariantCulture)).Append(",");
                            rows.Append(distPct.ToString("0.############", CultureInfo.InvariantCulture)).Append(",");
                            rows.Append(isBest ? "1" : "0");
                            rows.AppendLine();
                        }

                        written++;
                    }
                }

                priceTicks += descending ? -1 : 1;
            }
        }

        private void EnsureFile(string symbolName)
        {
            var folder = OutputFolder;
            Directory.CreateDirectory(folder);

            if (_currentPath != null && _currentSymbol == symbolName)
            {
                return;
            }

            _currentSymbol = symbolName;
            _lastRows.Clear();

            var safeSymbol = SafeFileName(symbolName);
            var stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture);
            _currentPath = Path.Combine(folder, "tiger_dom_" + safeSymbol + "_" + stamp + ".csv");

            File.WriteAllText(_currentPath, Header + Environment.NewLine, Encoding.UTF8);
        }

        private static string DefaultOutputFolder()
        {
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                "TigerTrade",
                "DomLogs");
        }

        private static string SafeFileName(string value)
        {
            var safe = new StringBuilder();
            var invalid = Path.GetInvalidFileNameChars();

            foreach (var ch in value)
            {
                safe.Append(Array.IndexOf(invalid, ch) >= 0 ? '_' : ch);
            }

            return safe.Length == 0 ? "symbol" : safe.ToString();
        }

        private static string SafeCsv(string value)
        {
            return string.IsNullOrWhiteSpace(value) ? "" : value.Trim();
        }

        private static string Escape(string value)
        {
            value = value ?? "";

            if (value.IndexOfAny(new[] { ',', '"', '\r', '\n' }) < 0)
            {
                return value;
            }

            return "\"" + value.Replace("\"", "\"\"") + "\"";
        }
    }
}
