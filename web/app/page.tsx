"use client"

import { useState, useEffect, useRef, useMemo } from 'react';
import { getMarketData, getMarketOverview, MarketOverviewItem, SignalConfig } from '@/lib/api';
import AdvancedChart from '@/components/AdvancedChart';
import SentimentPanel from '@/components/SentimentPanel';
import { IndicatorsInfoModal } from '@/components/IndicatorsInfoModal';
import { SignalSettingsModal } from '@/components/SignalSettingsModal';
import { NotificationSettingsModal } from '@/components/NotificationSettingsModal';
import { InfoTooltip } from '@/components/InfoTooltip';
import { RefreshCw, Zap, BarChart3, Clock, AlertTriangle, Info, Settings, Bell, Radio } from 'lucide-react';
import { getPricePrecision } from '@/lib/utils';
import Link from 'next/link';

function formatSignalTime(timeSec: number) {
  const d = new Date(timeSec * 1000);
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  const h = String(d.getUTCHours()).padStart(2, '0');
  const min = String(d.getUTCMinutes()).padStart(2, '0');
  return `${m}/${day} ${h}:${min}`;
}

function getSignalBadge(sig: any) {
  const isBull = sig.direction === 'bullish';
  const text = sig.text || '';
  const isBreakout = sig.strategy_type === 'breakout' || text.includes('BREAKOUT') || text.includes('BREAKDOWN');
  const isStructure = text.includes('CAP') || text.includes('DIV') || text.includes('Structure');

  if (isBreakout) {
    if (isBull) {
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-sky-950/80 border border-sky-500/40 text-sky-400 flex items-center gap-1 shadow-sm shrink-0">
          🚀 BREAKOUT ▲
        </span>
      );
    } else {
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-orange-950/80 border border-orange-500/40 text-orange-400 flex items-center gap-1 shadow-sm shrink-0">
          🚀 BREAKDOWN ▼
        </span>
      );
    }
  }

  if (isStructure) {
    if (isBull) {
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-950/80 border border-cyan-500/40 text-cyan-400 flex items-center gap-1 shadow-sm shrink-0">
          ⚡ STRUCTURE ▲
        </span>
      );
    } else {
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-purple-950/80 border border-purple-500/40 text-purple-400 flex items-center gap-1 shadow-sm shrink-0">
          ⚡ STRUCTURE ▼
        </span>
      );
    }
  }

  if (isBull) {
    return (
      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-950/80 border border-emerald-500/40 text-emerald-400 flex items-center gap-1 shadow-sm shrink-0">
        🟢 BUY ▲
      </span>
    );
  } else {
    return (
      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-red-950/80 border border-red-500/40 text-red-400 flex items-center gap-1 shadow-sm shrink-0">
        🔴 SELL ▼
      </span>
    );
  }
}

const TIMEFRAMES = [
  { label: '15分', value: '15m' },
  { label: '1小時', value: '1h' },
  { label: '4小時', value: '4h' },
  { label: '日線', value: '1d' },
];

export default function Dashboard() {
  const [symbol, setSymbol] = useState('BTC/USDT');
  const [timeframe, setTimeframe] = useState('1h');
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [isClearingCache, setIsClearingCache] = useState(false);
  const [signalPhase, setSignalPhase] = useState<'idle' | 'loading' | 'computing' | 'ready'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Memoized Price Map to resolve trigger prices for markers
  const priceByTime = useMemo(() => {
    const map = new Map<number, number>();
    if (data?.data?.price) {
      for (const p of data.data.price) {
        map.set(p.time, p.close);
      }
    }
    return map;
  }, [data?.data?.price]);

  // Latest 10 signals from lsur_markers (newest first)
  const recentSignals = useMemo(() => {
    const markers = data?.indicators?.lsur_markers || [];
    return [...markers].reverse().slice(0, 10);
  }, [data?.indicators?.lsur_markers]);

  // State for Info Modal
  const [isInfoModalOpen, setIsInfoModalOpen] = useState(false);

  // State for Settings Modal
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [isNotificationSettingsOpen, setIsNotificationSettingsOpen] = useState(false);
  const [signalConfig, setSignalConfig] = useState<SignalConfig>({
    rangingThreshold: 3,
    trendingThreshold: 3,
    enableProtection: true,
    useDynamicProfiles: true,
    enableMtfFilter: true,  // Layer 3: 4h regime MTF confirmation (default on)
    minScore: 0,
    signalTypes: 'structure,reversion,breakout',
  });

  // Five-Coin Macro Overview State
  const [macroOverview, setMacroOverview] = useState<MarketOverviewItem[]>([]);
  const [isOverviewLoading, setIsOverviewLoading] = useState(false);

  // Poll /api/market_overview every 60s
  useEffect(() => {
    let isMounted = true;
    const fetchOverview = async () => {
      try {
        setIsOverviewLoading(true);
        const res = await getMarketOverview();
        if (isMounted && res && res.length > 0) {
          setMacroOverview(res);
        }
      } catch (err) {
        console.error('Failed to load market overview', err);
      } finally {
        if (isMounted) setIsOverviewLoading(false);
      }
    };

    fetchOverview();
    const interval = setInterval(fetchOverview, 60000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Track if this is the initial load for the current timeframe
  const isFirstLoad = useRef(true);

  // Clear old data when timeframe or config changes
  useEffect(() => {
    setData(null);
    setLoading(true);
    setSignalPhase('loading');
    isFirstLoad.current = true;
  }, [symbol, timeframe, signalConfig]);

  // Fetch Data Loop
  useEffect(() => {
    let isMounted = true;

    const fetchData = async () => {
      try {
        setError(null);
        if (!isFirstLoad.current) {
          // Subsequent refreshes: show background updating
          setFetching(true);
        }

        const market = await getMarketData(symbol, timeframe, 1000, signalConfig);
        if (!isMounted) return;

        setData(market);
        setSignalPhase('ready');
        setLastUpdated(new Date());
        isFirstLoad.current = false;
        setLoading(false);
        setFetching(false);
      } catch (e: any) {
        if (!isMounted) return;
        console.error(e);
        setError(e.message || "Failed to fetch data");
        setLoading(false);
        setFetching(false);
        setSignalPhase('idle');
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [symbol, timeframe, signalConfig]);

  const handleClearCache = async () => {
    try {
      setIsClearingCache(true);
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
      await fetch(`${apiUrl}/clear-cache`, { method: 'POST' });
      // Force unmount/remount behavior or just refetch directly
      setData(null);
      setLoading(true);
      isFirstLoad.current = true;
      const res = await getMarketData(symbol, timeframe, 1000, signalConfig);
      setData(res);
      setSignalPhase('ready');
      setLastUpdated(new Date());
    } catch (error) {
      console.error("Failed to clear cache:", error);
    } finally {
      setIsClearingCache(false);
      setLoading(false);
    }
  };

  // Derived State
  const currentPrice = data?.data?.price?.length ? data.data.price[data.data.price.length - 1].close : 0;

  return (
    <main className="min-h-screen bg-black text-zinc-100 p-6 font-sans">
      {/* Header */}
      <div className="flex items-center justify-between mb-8 border-b border-zinc-900 pb-4">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 bg-purple-600 rounded-xl flex items-center justify-center shadow-lg shadow-purple-900/50">
            <Zap className="text-white w-6 h-6 fill-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold bg-gradient-to-r from-purple-400 to-pink-500 bg-clip-text text-transparent">
              SOLO-QUANT
            </h1>
            <div className="text-xs text-zinc-500 font-mono tracking-widest">CRYPTO MACRO & SIGNAL TERMINAL</div>
          </div>
        </div>

        <div className="flex items-center gap-6">
          {/* Timeframe Selector */}
          <div className="flex bg-zinc-900 rounded-lg p-1 border border-zinc-800">
            {TIMEFRAMES.map(tf => (
              <button
                key={tf.value}
                onClick={() => setTimeframe(tf.value)}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors ${timeframe === tf.value ? "bg-purple-900/30 text-purple-400" : "text-zinc-500 hover:text-zinc-300"
                  }`}
              >
                {tf.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            {/* Notification Settings Button */}
            <button
              onClick={() => setIsNotificationSettingsOpen(true)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-blue-400 hover:border-blue-900/50 hover:bg-blue-950/20 transition-all font-medium text-sm"
              title="通知設定"
            >
              <Bell className="w-4 h-4" />
              <span className="hidden sm:inline">通知設定</span>
            </button>

            {/* Settings Button */}
            <button
              onClick={() => setIsSettingsModalOpen(true)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-white hover:bg-zinc-800 transition-all font-medium text-sm"
              title="訊號參數設定"
            >
              <Settings className="w-4 h-4" />
              <span className="hidden sm:inline">訊號設定</span>
            </button>

            {/* Clear Cache Button */}
            <button
              onClick={handleClearCache}
              disabled={isClearingCache}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-white hover:bg-zinc-800 transition-all font-medium text-sm ${isClearingCache ? 'opacity-50 cursor-not-allowed' : ''}`}
              title="清除快取並重新抓取資料"
            >
              <RefreshCw className={`w-4 h-4 ${isClearingCache ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">清除快取</span>
            </button>

            {/* Info Button */}
            <button
              onClick={() => setIsInfoModalOpen(true)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-amber-400 hover:border-amber-900/50 hover:bg-amber-950/20 transition-all font-medium text-sm"
              title="指標說明"
            >
              <Info className="w-4 h-4" />
              指標說明
            </button>

            <Link href="/backtest" className="flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 transition-colors text-sm font-medium text-zinc-400 hover:text-white border border-zinc-800">
              <BarChart3 className="w-4 h-4" />
              Backtester
            </Link>

            <div className="flex items-center">
              <select
                value={symbol}
                onChange={e => setSymbol(e.target.value)}
                className="bg-zinc-900 border border-zinc-800 text-sm font-medium text-white rounded-lg px-3 py-2 outline-none focus:border-zinc-700 transition-colors hover:bg-zinc-800"
              >
                <option value="BTC/USDT">BTC/USDT</option>
                <option value="ETH/USDT">ETH/USDT</option>
                <option value="SOL/USDT">SOL/USDT</option>
                <option value="HYPE/USDT">HYPE/USDT</option>
                <option value="CC/USDT">CC/USDT</option>
              </select>
            </div>

            {lastUpdated && (
              <span className="text-xs text-zinc-600 flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {lastUpdated.toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Multi-Asset Macro & Quadrant Strip */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-purple-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-purple-500"></span>
            </span>
            <span className="text-xs font-bold text-zinc-300 uppercase tracking-wider flex items-center gap-1.5">
              五幣種宏觀強弱與四象限雷達列 (Macro & Quadrant Strip)
              <InfoTooltip
                width={320}
                text={"【五幣種宏觀強弱與四象限雷達列】\n即時跨幣種橫向對比 BTC、ETH、SOL、HYPE、CC 五大資產之相對動能與合約籌碼：\n• 相對 BTC 強弱 (RS)：該幣 4h RSI 減去 BTC 4h RSI，>0 代表強勢領漲/抗跌，<0 代表走勢弱於大盤。\n• 24h 幣本位持倉變化率 (OI)：以幣為單位衡量持倉增減，排除幣價漲跌造成的被動虛增，洞察主力真實多空加減倉。\n• 籌碼四象限定位：精準分類為強勢加倉、弱勢加倉、強勢減倉、弱勢減倉與中性盤整。\n• 4H 宏觀環境 & 最新訊號：提示大級別趨勢與最近進場時機。\n點擊任一幣種卡片即可立即切換主圖分析標的。"}
              />
            </span>
          </div>
          <span className="text-[11px] font-mono text-zinc-500">
            {isOverviewLoading ? '更新戰情數據中...' : '每 60 秒自動刷新'}
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          {(macroOverview.length > 0 ? macroOverview : [
            { symbol: 'BTC/USDT', symbol_slug: 'BTC-USDT', price: 0, change_24h_pct: 0, rsi_4h: 50, rs_vs_btc: 0, oi_coin_change_24h_pct: 0, quadrant: 'neutral' as const, regime_4h: 'ranging' as const },
            { symbol: 'ETH/USDT', symbol_slug: 'ETH-USDT', price: 0, change_24h_pct: 0, rsi_4h: 50, rs_vs_btc: 0, oi_coin_change_24h_pct: 0, quadrant: 'neutral' as const, regime_4h: 'ranging' as const },
            { symbol: 'SOL/USDT', symbol_slug: 'SOL-USDT', price: 0, change_24h_pct: 0, rsi_4h: 50, rs_vs_btc: 0, oi_coin_change_24h_pct: 0, quadrant: 'neutral' as const, regime_4h: 'ranging' as const },
            { symbol: 'HYPE/USDT', symbol_slug: 'HYPE-USDT', price: 0, change_24h_pct: 0, rsi_4h: 50, rs_vs_btc: 0, oi_coin_change_24h_pct: 0, quadrant: 'neutral' as const, regime_4h: 'ranging' as const },
            { symbol: 'CC/USDT', symbol_slug: 'CC-USDT', price: 0, change_24h_pct: 0, rsi_4h: 50, rs_vs_btc: 0, oi_coin_change_24h_pct: 0, quadrant: 'neutral' as const, regime_4h: 'ranging' as const },
          ]).map((item) => {
            const isSelected = symbol === item.symbol;
            const precision = getPricePrecision(item.price || 0, item.symbol).precision;

            let quadBadge = <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-zinc-800 text-zinc-400 border border-zinc-700">⚪ 中性盤整</span>;
            let quadExplanation = "【⚪ 中性盤整 (Neutral)】\n• 判定條件：24h 幣本位 OI 變化在 ±3% 內\n• 籌碼意義：合約資金無明顯單邊流向，處於橫盤蓄勢狀態。";
            if (item.quadrant === 'strong_add') {
              quadBadge = <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-950/80 text-emerald-400 border border-emerald-500/40">🔥 強勢加倉</span>;
              quadExplanation = "【🔥 強勢加倉 (Strong Add)】\n• 判定條件：RS > 0 且 24h 幣本位 OI > +3%\n• 籌碼意義：該幣動能強於 BTC，且主力資金積極真金白銀增開合約追多，為最強主升浪標的。";
            } else if (item.quadrant === 'weak_add') {
              quadBadge = <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-950/80 text-amber-400 border border-amber-500/40">🩸 弱勢加倉</span>;
              quadExplanation = "【🩸 弱勢加倉 (Weak Add)】\n• 判定條件：RS < 0 且 24h 幣本位 OI > +3%\n• 籌碼意義：走勢弱於 BTC 但持倉逆勢激增，多為左側摸底或主力誘多出貨，需高度警惕假反彈。";
            } else if (item.quadrant === 'strong_reduce') {
              quadBadge = <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-purple-950/80 text-purple-400 border border-purple-500/40">⚡ 強勢減倉</span>;
              quadExplanation = "【⚡ 強勢減倉 (Strong Reduce)】\n• 判定條件：RS > 0 且 24h 幣本位 OI < -3%\n• 籌碼意義：價格雖走強但合約持續減倉，主力獲利結算或多頭動能空轉，追高風險升高。";
            } else if (item.quadrant === 'weak_reduce') {
              quadBadge = <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-blue-950/80 text-blue-400 border border-blue-500/40">🧊 弱勢減倉</span>;
              quadExplanation = "【🧊 弱勢減倉 (Weak Reduce)】\n• 判定條件：RS < 0 且 24h 幣本位 OI < -3%\n• 籌碼意義：動能弱於 BTC 且合約平倉撤退，為典型空頭去槓桿或止損踩踏。";
            }

            return (
              <button
                key={item.symbol}
                onClick={() => setSymbol(item.symbol)}
                className={`p-3 rounded-xl border text-left transition-all flex flex-col gap-2 relative overflow-hidden group ${
                  isSelected
                    ? 'bg-purple-950/30 border-purple-500 shadow-lg shadow-purple-900/30 ring-1 ring-purple-500'
                    : 'bg-zinc-900/70 border-zinc-800 hover:border-zinc-700 hover:bg-zinc-850'
                }`}
              >
                {/* Line 1: Symbol + Price + 24h Change % */}
                <div className="flex items-center justify-between w-full">
                  <span className="font-bold text-xs tracking-wider text-zinc-200 group-hover:text-purple-300 transition-colors font-mono">
                    {item.symbol}
                  </span>
                  <div className="text-right">
                    <div className="font-mono text-xs font-bold text-zinc-100">
                      {item.price > 0 ? item.price.toFixed(precision) : '—'}
                    </div>
                    <div className="flex items-center justify-end gap-0.5">
                      <span className={`font-mono text-[10px] font-medium ${
                        item.change_24h_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                      }`}>
                        {item.change_24h_pct >= 0 ? `+${item.change_24h_pct.toFixed(2)}%` : `${item.change_24h_pct.toFixed(2)}%`}
                      </span>
                      <InfoTooltip
                        text="【24h 價格漲跌幅】\n以 4H 週期 6 根 K 線前（24 小時前）收盤價作為基準計算之價格變動百分比。"
                        width={220}
                        className="ml-0.5"
                        iconClassName="h-2.5 w-2.5 text-zinc-600 hover:text-zinc-300"
                      />
                    </div>
                  </div>
                </div>

                {/* Line 2: Quadrant Badge + RS vs BTC + 24h Coin OI % */}
                <div className="flex items-center justify-between gap-1 w-full pt-1 border-t border-zinc-800/60">
                  <div className="flex items-center">
                    {quadBadge}
                    <InfoTooltip
                      text={quadExplanation}
                      width={260}
                      className="ml-0.5"
                      iconClassName="h-3 w-3 text-zinc-600 hover:text-amber-400"
                    />
                  </div>
                  <div className="text-[10px] font-mono text-zinc-400 flex items-center gap-1">
                    <span className={item.rs_vs_btc > 0 ? 'text-emerald-400' : (item.rs_vs_btc < 0 ? 'text-rose-400' : 'text-zinc-400')}>
                      RS {item.rs_vs_btc > 0 ? `+${item.rs_vs_btc}` : item.rs_vs_btc}
                    </span>
                    <InfoTooltip
                      text={"【相對強弱差值 (RS vs BTC)】\n公式：該幣 4H RSI(14) - BTC 4H RSI(14)\n• > 0 (綠字)：動能強於比特幣（強勢標的）\n• < 0 (紅字)：動能弱於比特幣（弱勢標的）\n• BTC 自身基準固定為 0.0"}
                      width={250}
                      className="ml-0"
                      iconClassName="h-2.5 w-2.5 text-zinc-600 hover:text-emerald-400"
                    />
                    <span className="text-zinc-600 mx-0.5">|</span>
                    <span className={item.oi_coin_change_24h_pct > 0 ? 'text-emerald-400' : (item.oi_coin_change_24h_pct < 0 ? 'text-rose-400' : 'text-zinc-400')}>
                      OI {item.oi_coin_change_24h_pct > 0 ? `+${item.oi_coin_change_24h_pct.toFixed(1)}%` : `${item.oi_coin_change_24h_pct.toFixed(1)}%`}
                    </span>
                    <InfoTooltip
                      text={"【24h 幣本位持倉變化率】\n公式：(USD OI / 價格) 24h 增減 %\n排除幣價單邊漲跌造成的合約總額被動膨脹/縮水，精準反映市場真實合約張數的主力加減倉。"}
                      width={260}
                      className="ml-0"
                      iconClassName="h-2.5 w-2.5 text-zinc-600 hover:text-blue-400"
                    />
                  </div>
                </div>

                {/* Line 3: 4H Regime + Latest Signal */}
                <div className="flex items-center justify-between text-[10px] font-mono text-zinc-400 pt-1 border-t border-zinc-800/40 w-full">
                  <div className="flex items-center">
                    <span className={`px-1 rounded text-[9px] font-bold ${
                      item.regime_4h === 'trending_up'
                        ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-500/30'
                        : item.regime_4h === 'trending_down'
                        ? 'bg-rose-950/60 text-rose-400 border border-rose-500/30'
                        : 'bg-zinc-800/80 text-zinc-400 border border-zinc-700/50'
                    }`}>
                      {item.regime_4h === 'trending_up' ? '4H ↗ 趨勢多' : (item.regime_4h === 'trending_down' ? '4H ↘ 趨勢空' : '4H ⇄ 盤整')}
                    </span>
                    <InfoTooltip
                      text={"【4H 宏觀環境】\n• ↗ 趨勢多：4H 大週期處於強多頭，1H 逆向空單受 MTF 防護抑制\n• ↘ 趨勢空：4H 大週期處於強空頭，1H 逆向多單受 MTF 防護抑制\n• ⇄ 盤整：大週期處於區間震盪"}
                      width={250}
                      className="ml-0.5"
                      iconClassName="h-2.5 w-2.5 text-zinc-600 hover:text-zinc-300"
                    />
                  </div>

                  <div className="flex items-center justify-end truncate max-w-[125px]">
                    <span className="truncate text-zinc-400" title={item.latest_signal?.text || '無觸發訊號'}>
                      {item.latest_signal ? (
                        <span className={item.latest_signal.direction === 'bullish' ? 'text-emerald-400' : 'text-rose-400'}>
                          {item.latest_signal.direction === 'bullish' ? '↑' : '↓'} {item.latest_signal.archetype} ({item.latest_signal.hours_ago}h)
                        </span>
                      ) : (
                        '—'
                      )}
                    </span>
                    <InfoTooltip
                      text={"【最新策略訊號】\n最近一次在 1h 或 4h 週期觸發之複合訊號：\n• ↑ 多頭 / ↓ 空頭\n• Archetype 類型：\n  - Breakout (突破🚀)\n  - Structure (結構🔄)\n  - Reversion (反轉🧲)\n• (xx.x h)：距今小時數，數值越小代表越即時，避免延遲追價。"}
                      width={260}
                      className="ml-0.5"
                      iconClassName="h-2.5 w-2.5 text-zinc-600 hover:text-purple-400"
                    />
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex flex-col gap-6 flex-1 min-h-0">
        {loading || !data ? (
          <div className="flex-1 flex flex-col items-center justify-center min-h-[580px] bg-zinc-950/60 border border-zinc-900 rounded-2xl p-12 relative overflow-hidden shadow-2xl">
            {/* Ambient background glows */}
            <div className="absolute w-[450px] h-[450px] bg-purple-600/10 rounded-full blur-3xl pointer-events-none -top-24 -left-24 animate-pulse" />
            <div className="absolute w-[450px] h-[450px] bg-blue-600/10 rounded-full blur-3xl pointer-events-none -bottom-24 -right-24 animate-pulse" />

            <div className="relative flex flex-col items-center z-10 max-w-md text-center">
              {/* Terminal radar / spinner */}
              <div className="relative flex items-center justify-center mb-6">
                <span className="absolute w-16 h-16 rounded-full border border-purple-500/30 animate-ping"></span>
                <div className="w-14 h-14 rounded-full border-2 border-purple-500/20 border-t-purple-400 animate-spin"></div>
                <Zap className="absolute w-6 h-6 text-purple-400 fill-purple-400/20" />
              </div>

              <div className="text-zinc-100 font-bold text-lg mb-2 tracking-wide">
                載入市場數據與指標分析中...
              </div>
              <p className="text-zinc-500 text-xs font-mono leading-relaxed mb-5">
                同步多交易所訂單流 (CVD)、大戶持倉比 (LSUR)、資金費率與多週期共振結構
              </p>

              <div className="flex items-center gap-2 bg-zinc-900/80 border border-zinc-800/80 px-4 py-1.5 rounded-full text-xs font-mono">
                <span className="text-purple-400 font-bold">{symbol}</span>
                <span className="text-zinc-600">•</span>
                <span className="text-zinc-300 font-semibold">{timeframe}</span>
                <span className="text-zinc-600">•</span>
                <span className="text-emerald-400 flex items-center gap-1.5">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                  即時運算中
                </span>
              </div>
            </div>
          </div>
        ) : error ? (
          <div className="flex-1 flex flex-col items-center justify-center min-h-[580px] bg-zinc-950/60 border border-zinc-900 rounded-2xl p-12 text-center">
            <AlertTriangle className="w-12 h-12 mb-3 text-red-400 animate-bounce" />
            <div className="text-lg font-bold text-zinc-100 mb-1">連線錯誤</div>
            <div className="text-xs font-mono text-zinc-500 mb-6 max-w-md">{error}</div>
            <button
              onClick={() => {
                setData(null);
                setLoading(true);
              }}
              className="px-4 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-sm font-medium text-white transition-colors flex items-center gap-2 shadow-lg"
            >
              <RefreshCw className="w-4 h-4" />
              重新載入
            </button>
          </div>
        ) : (
          /* Top Section: Chart & Analysis (Flex-1 to fill space) */
          <div className="grid grid-cols-12 gap-6 flex-1 min-h-[500px]">
            {/* Left Column: Main Chart (Price) */}
            <div className="col-span-12 lg:col-span-8 flex flex-col h-full bg-zinc-950/50 rounded-2xl border border-zinc-900 p-1 relative overflow-hidden">
              {/* Signal Status Badge */}
              {(() => {
                const markers = data?.indicators?.lsur_markers;
                const signalCount = markers?.length ?? 0;
                const bullCount = markers?.filter((m: any) => m.direction === 'bullish').length ?? 0;
                const bearCount = markers?.filter((m: any) => m.direction === 'bearish').length ?? 0;

                if (fetching) {
                  return (
                    <div className="absolute top-3 right-3 z-40 flex items-center gap-2 bg-zinc-900/90 backdrop-blur-sm border border-zinc-700 rounded-lg px-3 py-1.5 text-xs">
                      <RefreshCw className="w-3 h-3 text-amber-400 animate-spin" />
                      <span className="text-zinc-400">更新訊號中...</span>
                    </div>
                  );
                }

                if (signalCount > 0) {
                  return (
                    <div className="absolute top-3 right-3 z-40 flex items-center gap-2 bg-zinc-900/80 backdrop-blur-sm border border-zinc-800 rounded-lg px-3 py-1.5 text-xs">
                      <Zap className="w-3 h-3 text-amber-400" />
                      <span className="text-zinc-300">{signalCount} 個訊號</span>
                      <span className="text-zinc-600">|</span>
                      <span className="text-emerald-400">{bullCount}↑</span>
                      <span className="text-red-400">{bearCount}↓</span>
                    </div>
                  );
                }

                return null;
              })()}

              {/* ADVANCED CHART (Price + Embedded OI) */}
              <AdvancedChart
                symbol={symbol}
                timeframe={timeframe}
                data={data?.data || null}
                indicators={data?.indicators || null}
                gridLines={[]}
              />
            </div>

            {/* Right Column: Analysis & Recent Signals */}
            <div className="col-span-12 lg:col-span-4 flex flex-col gap-4 h-full overflow-y-auto pr-2 custom-scrollbar">
              {/* 1. Sentinel (Sentiment) */}
              <SentimentPanel 
                indicators={data?.indicators || null} 
                timeframe={timeframe} 
                enableProtection={signalConfig.enableProtection}
              />

              {/* 2. Recent Signals Radar */}
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col gap-3">
                <div className="flex items-center justify-between border-b border-zinc-800/80 pb-3">
                  <div className="flex items-center gap-2">
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-purple-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-purple-500"></span>
                    </span>
                    <h3 className="text-zinc-200 text-xs font-bold uppercase tracking-wider flex items-center gap-1.5">
                      <Radio className="w-3.5 h-3.5 text-purple-400" />
                      Recent Signals (近期觸發訊號)
                    </h3>
                  </div>
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-zinc-800/80 text-zinc-400 border border-zinc-700/50">
                    總計 {data?.indicators?.lsur_markers?.length ?? 0} 筆
                  </span>
                </div>

                {recentSignals.length === 0 ? (
                  <div className="text-center py-8 text-zinc-600 text-xs font-mono">
                    目前無觸發之買賣訊號
                  </div>
                ) : (
                  <div className="flex flex-col gap-2 max-h-[480px] overflow-y-auto pr-1 custom-scrollbar">
                    {recentSignals.map((sig: any, idx: number) => {
                      const closePrice = priceByTime.get(sig.time);
                      const pricePrecision = getPricePrecision(closePrice || 0, symbol).precision;

                      return (
                        <div
                          key={`${sig.time}-${idx}`}
                          className="p-2.5 rounded-lg bg-zinc-950/60 border border-zinc-800/70 hover:border-zinc-700 transition-colors flex flex-col gap-1.5"
                        >
                          <div className="flex items-center justify-between text-xs">
                            <div className="flex items-center gap-2">
                              {getSignalBadge(sig)}
                              <span className="font-mono text-zinc-400 text-[11px]">
                                {formatSignalTime(sig.time)}
                              </span>
                            </div>
                            <div className="font-mono font-bold text-zinc-200">
                              {closePrice ? closePrice.toFixed(pricePrecision) : '—'}
                            </div>
                          </div>
                          <div
                            className="text-[11px] font-mono text-zinc-400 truncate bg-zinc-900/70 px-2 py-1 rounded border border-zinc-800/50 hover:text-zinc-200 transition-colors"
                            title={sig.text}
                          >
                            {sig.text}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Indicators Information Modal */}
      <IndicatorsInfoModal
        isOpen={isInfoModalOpen}
        onClose={() => setIsInfoModalOpen(false)}
      />

      {/* Signal Settings Modal */}
      <SignalSettingsModal
        isOpen={isSettingsModalOpen}
        onClose={() => setIsSettingsModalOpen(false)}
        currentConfig={signalConfig}
        onSave={setSignalConfig}
      />

      {/* Notification Settings Modal */}
      <NotificationSettingsModal 
        isOpen={isNotificationSettingsOpen}
        onClose={() => setIsNotificationSettingsOpen(false)}
      />
    </main>
  );
}
