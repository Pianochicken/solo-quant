"use client"

import { useEffect, useState } from 'react';
import { getMarketData, MarketData } from '@/lib/api';
import { SyncedChart } from '@/components/SyncedChart';
import { TradePanel } from '@/components/TradePanel';
import { GridPanel } from '@/components/GridPanel';
import { HistoryPanel, Order } from '@/components/HistoryPanel';
import { InfoTooltip } from '@/components/InfoTooltip';
import { Activity, ArrowUpRight, Signal, Clock, Calculator } from 'lucide-react';
import Link from 'next/link';
import { cn } from '@/lib/utils';

const SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'];
const TIMEFRAMES = [
  { label: '1分', value: '1m' },
  { label: '15分', value: '15m' },
  { label: '1小時', value: '1h' },
  { label: '4小時', value: '4h' },
  { label: '日線', value: '1d' },
  { label: '週線', value: '1w' },
];

export default function Home() {
  const [data, setData] = useState<MarketData | null>(null);
  const [loading, setLoading] = useState(true);
  const [symbol, setSymbol] = useState('BTC/USDT');
  const [timeframe, setTimeframe] = useState('1h');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [gridLines, setGridLines] = useState<number[]>([]);
  const [historyOrders, setHistoryOrders] = useState<Order[]>([]); // [NEW] Order History State

  // Clear grid lines when symbol changes
  useEffect(() => {
    setGridLines([]);
  }, [symbol]);

  async function fetchData() {
    try {
      const res = await getMarketData(symbol, timeframe, 1000); // Fetch 1000 candles for better scrolling
      setData(res);
      setLastUpdated(new Date());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  // Initial Load & Symbol/Timeframe Change
  useEffect(() => {
    setLoading(true);
    fetchData();
  }, [symbol, timeframe]);

  // Auto-Refresh (Real-time update) - Every 5 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      fetchData(); // Silent update (no loading spinner)
    }, 5000);
    return () => clearInterval(interval);
  }, [symbol, timeframe]);

  // Derived State (Safe Access)
  const currentPrice = data?.data?.price?.length ? data.data.price[data.data.price.length - 1].close : 0;
  const currentFunding = data?.data?.funding?.length ? data.data.funding[data.data.funding.length - 1].value : 0;

  // [NEW] Simulated Matching Engine for Dry Run
  useEffect(() => {
    if (historyOrders.length === 0 || !currentPrice) return;

    let hasUpdates = false;
    const updatedOrders = historyOrders.map(order => {
      // Only check open orders
      if (order.status !== 'open') return order;

      // Check for fill
      const isBuyFill = order.side === 'buy' && currentPrice <= order.price;
      const isSellFill = order.side === 'sell' && currentPrice >= order.price;

      if (isBuyFill || isSellFill) {
        hasUpdates = true;
        return { ...order, status: 'filled', time: new Date().toLocaleTimeString() };
      }
      return order;
    });

    if (hasUpdates) {
      setHistoryOrders(updatedOrders as Order[]);
    }
  }, [currentPrice, historyOrders]);

  // Signal Logic
  let signalText = "中性 (Neutral)";
  let signalColor = "text-zinc-400";
  if (currentFunding > 0.03) {
    signalText = "賣出 (過熱)";
    signalColor = "text-red-500";
  } else if (currentFunding < -0.01) {
    signalText = "買入 (軋空)";
    signalColor = "text-emerald-500";
  }

  // Loading Skeleton
  if (!data && loading) return (
    <div className="min-h-screen bg-black text-white flex items-center justify-center">
      <div className="animate-pulse flex flex-col items-center">
        <Activity className="h-10 w-10 text-emerald-500 mb-4" />
        <p className="text-zinc-500">正在初始化 {symbol}...</p>
      </div>
    </div>
  );

  if (!data) return <div className="min-h-screen bg-black text-white p-8">無法載入數據，請確認後端伺服器是否運行。</div>;



  return (
    <main className="min-h-screen bg-black text-zinc-100 p-6 font-sans flex flex-col relative">
      {/* Loading Overlay for Switching */}
      {loading && (
        <div className="absolute inset-0 z-50 bg-black/60 backdrop-blur-[2px] flex items-center justify-center transition-opacity duration-300">
          <div className="flex flex-col items-center p-6 bg-zinc-900 border border-zinc-800 rounded-2xl shadow-2xl skew-x-[-2deg]">
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 bg-emerald-500 rounded-full animate-bounce" style={{ animationDelay: '0s' }} />
              <div className="w-3 h-3 bg-cyan-500 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }} />
              <div className="w-3 h-3 bg-indigo-500 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
            </div>
            <span className="mt-4 text-xs font-mono text-zinc-400 tracking-widest">SWITCHING :: {symbol}</span>
          </div>
        </div>
      )}

      {/* --- Top Bar: Header & Controls --- */}
      <header className="flex justify-between items-center mb-6 pb-4 border-b border-zinc-900">
        <div className="flex items-center gap-6">
          <h1 className="text-xl font-bold bg-gradient-to-r from-emerald-400 to-cyan-500 bg-clip-text text-transparent mr-4">
            SoloQuant
          </h1>

          {/* Symbol Selector */}
          <div className="flex bg-zinc-900 rounded-lg p-1 border border-zinc-800">
            {SYMBOLS.map(sym => (
              <button
                key={sym}
                onClick={() => setSymbol(sym)}
                className={cn(
                  "px-3 py-1 text-sm font-medium rounded transition-colors",
                  symbol === sym ? "bg-zinc-800 text-white shadow" : "text-zinc-500 hover:text-zinc-300"
                )}
              >
                {sym.split('/')[0]}
              </button>
            ))}
          </div>

          {/* Timeframe Selector */}
          <div className="flex bg-zinc-900 rounded-lg p-1 border border-zinc-800">
            {TIMEFRAMES.map(tf => (
              <button
                key={tf.value}
                onClick={() => setTimeframe(tf.value)}
                className={cn(
                  "px-3 py-1 text-xs font-medium rounded transition-colors",
                  timeframe === tf.value ? "bg-emerald-900/30 text-emerald-400" : "text-zinc-500 hover:text-zinc-300"
                )}
              >
                {tf.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-4">
          {lastUpdated && (
            <span className="text-xs text-zinc-600 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              最後更新: {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <div className="flex items-center gap-3">
            <Link href="/backtest" className="px-3 py-1 bg-purple-900/30 border border-purple-800 rounded text-xs text-purple-400 hover:bg-purple-900/50 transition-colors flex items-center gap-2">
              <Calculator className="w-3 h-3" />
              Backtest
            </Link>
            <div className="px-3 py-1 bg-zinc-900 rounded border border-zinc-800 text-xs text-zinc-400 flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              已連線 (Connected)
            </div>
          </div>
        </div>
      </header>

      {/* --- Main Content Area --- */}
      <div className="flex flex-col gap-6 flex-1">

        {/* Top Section: Charts & Operations */}
        <div className="grid grid-cols-12 gap-6 min-h-[500px]">

          {/* Left Column: Charts & Metrics (Width: 9) */}
          <div className="col-span-12 lg:col-span-9 flex flex-col gap-6">
            {/* Metrics Row */}
            <div className="grid grid-cols-3 gap-4">
              <div className="p-4 bg-zinc-900/30 border border-zinc-800 rounded-xl flex justify-between items-start">
                <div>
                  <span className="text-zinc-500 text-xs uppercase tracking-wider flex items-center">
                    當前價格 (Price)
                    <InfoTooltip text="Spot Spot Spot." />
                  </span>
                  <div className="text-2xl font-mono font-medium mt-1">${currentPrice.toLocaleString()}</div>
                </div>
                <ArrowUpRight className="h-4 w-4 text-emerald-500" />
              </div>

              <div className="p-4 bg-zinc-900/30 border border-zinc-800 rounded-xl flex justify-between items-start">
                <div>
                  <span className="text-zinc-500 text-xs uppercase tracking-wider flex items-center">
                    資金費率 (Funding Rate)
                    <InfoTooltip text="Perp Funding Rate." />
                  </span>
                  <div className={`text-2xl font-mono font-medium mt-1 ${currentFunding > 0.01 ? 'text-red-400' : 'text-emerald-400'}`}>
                    {currentFunding.toFixed(4)}%
                  </div>
                </div>
                <Activity className="h-4 w-4 text-zinc-600" />
              </div>

              <div className="p-4 bg-zinc-900/30 border border-zinc-800 rounded-xl flex justify-between items-start">
                <div>
                  <span className="text-zinc-500 text-xs uppercase tracking-wider flex items-center">
                    策略訊號 (Signal)
                    <InfoTooltip text="System Signal." />
                  </span>
                  <div className={`text-xl font-bold mt-1 flex items-center gap-2 ${signalColor}`}>
                    {signalText}
                  </div>
                </div>
                <Signal className="h-4 w-4 text-zinc-600" />
              </div>
            </div>

            {/* Main Charts */}
            <div className="flex-1 min-h-[400px]">
              <SyncedChart
                priceData={data.data.price}
                fundingData={data.data.funding}
                gridLines={historyOrders.filter(o => o.status === 'open').length > 0
                  ? historyOrders.filter(o => o.status === 'open').map(o => o.price)
                  : gridLines}
              />
            </div>
          </div>

          {/* Right Column: Grid Panel (Width: 3) */}
          <div className="col-span-12 lg:col-span-3 flex flex-col gap-4">
            <GridPanel
              symbol={symbol}
              currentPrice={currentPrice}
              onPreview={(lines) => setGridLines(lines)}
              onOrders={(newOrders) => {
                // Format new orders from backend to UI structure
                const formatted = newOrders.map((o: any) => ({
                  id: o.id || Math.random().toString(),
                  symbol: o.symbol,
                  side: o.side,
                  price: o.price,
                  amount: o.amount,
                  status: o.status === 'closed' ? 'filled' : o.status, // Dry run 'closed' -> 'filled' visually
                  time: new Date().toLocaleTimeString()
                }));
                setHistoryOrders(prev => [...formatted, ...prev]);
              }}
            />
          </div>
        </div>

        {/* Bottom Section: History & Logs */}
        <div className="w-full">
          <HistoryPanel
            orders={historyOrders}
            onCancel={(id) => {
              setHistoryOrders(prev => prev.map(o => o.id === id ? { ...o, status: 'canceled' } : o));
            }}
          />
        </div>

      </div>
    </main>
  );
}
