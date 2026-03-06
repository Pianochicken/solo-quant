"use client"

import { useState, useEffect, useRef } from 'react';
import { getMarketData } from '@/lib/api';
import AdvancedChart from '@/components/AdvancedChart';
import { GridPanel } from '@/components/GridPanel';
import SentimentPanel from '@/components/SentimentPanel';
import { HistoryPanel, Order } from '@/components/HistoryPanel';
import { RefreshCw, Zap, BarChart3, Clock, AlertTriangle } from 'lucide-react';
import Link from 'next/link';

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
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // State for Grid & Orders
  const [gridLines, setGridLines] = useState<number[]>([]);
  const [historyOrders, setHistoryOrders] = useState<Order[]>([]);

  // Frontend Cache to eliminate loading spinners on timeframe switch
  const dataCache = useRef<Record<string, any>>({});

  // Fetch Data Loop
  useEffect(() => {
    let isMounted = true;
    const cacheKey = `${symbol}_${timeframe}`;

    // 1. Instant UI update if we have cached data for this timeframe
    if (dataCache.current[cacheKey]) {
      setData(dataCache.current[cacheKey]);
      setLoading(false);
    } else {
      setLoading(true);
    }

    const fetchData = async () => {
      try {
        setError(null);
        // Pass timeframe to API
        const market = await getMarketData(symbol, timeframe, 1000);

        if (!isMounted) return; // Prevent race conditions if user clicked rapidly

        // Safely update cache and state quietly in background
        dataCache.current[cacheKey] = market;
        setData(market);
        setLastUpdated(new Date());
        setLoading(false);
      } catch (e: any) {
        if (!isMounted) return;
        console.error(e);
        setError(e.message || "Failed to fetch data");
        setLoading(false);
      }
    };

    fetchData(); // Initial
    const interval = setInterval(fetchData, 15000); // Poll every 15s to avoid rate limits
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [symbol, timeframe]);

  // Derived State
  const currentPrice = data?.data?.price?.length ? data.data.price[data.data.price.length - 1].close : 0;

  // Simulated Matching Engine (Simple)
  useEffect(() => {
    if (historyOrders.length === 0 || !currentPrice) return;
    let hasUpdates = false;
    const updatedOrders = historyOrders.map(order => {
      if (order.status !== 'open') return order;
      // Check fills
      const isBuyFill = order.side === 'buy' && currentPrice <= order.price;
      const isSellFill = order.side === 'sell' && currentPrice >= order.price;
      if (isBuyFill || isSellFill) {
        hasUpdates = true;
        return { ...order, status: 'filled', time: new Date().toLocaleTimeString() };
      }
      return order;
    });
    if (hasUpdates) setHistoryOrders(updatedOrders as Order[]);
  }, [currentPrice, historyOrders]);

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
            <div className="text-xs text-zinc-500 font-mono tracking-widest">AI GRID TRADING SYSTEM</div>
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

          <Link href="/backtest" className="flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 transition-colors text-sm font-medium text-zinc-400 hover:text-white border border-zinc-800">
            <BarChart3 className="w-4 h-4" />
            Backtester
          </Link>

          <div className="flex items-center gap-2 bg-zinc-900 rounded-lg p-1 border border-zinc-800">
            {['BTC/USDT', 'ETH/USDT', 'SOL/USDT'].map(s => (
              <button
                key={s}
                onClick={() => { setSymbol(s); }}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all ${symbol === s
                  ? 'bg-zinc-800 text-white shadow-sm'
                  : 'text-zinc-500 hover:text-zinc-300'
                  }`}
              >
                {s.split('/')[0]}
              </button>
            ))}
          </div>

          {lastUpdated && (
            <span className="text-xs text-zinc-600 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-6 flex-1 min-h-0">
        {/* Top Section: Chart & Analysis (Flex-1 to fill space) */}
        <div className="grid grid-cols-12 gap-6 flex-1 min-h-[500px]">
          {/* Left Column: Main Chart (Price) */}
          <div className="col-span-12 lg:col-span-8 flex flex-col h-full bg-zinc-950/50 rounded-2xl border border-zinc-900 p-1 relative overflow-hidden">
            {loading && (
              <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm rounded-2xl">
                <RefreshCw className="w-8 h-8 text-purple-500 animate-spin" />
              </div>
            )}
            {error && (
              <div className="absolute inset-0 z-50 flex flex-col items-center justify-center text-red-400">
                <AlertTriangle className="w-10 h-10 mb-2" />
                <div>Connection Error: {error}</div>
              </div>
            )}

            {/* ADVANCED CHART (Price + Embedded OI) */}
            <AdvancedChart
              symbol={symbol}
              data={data?.data || null}
              indicators={data?.indicators || null}
              gridLines={gridLines}
            />
          </div>

          {/* Right Column: Analysis & Grid Controls */}
          <div className="col-span-12 lg:col-span-4 flex flex-col gap-4 h-full overflow-y-auto pr-2 custom-scrollbar">
            {/* 1. Sentinel (Sentiment) */}
            <SentimentPanel indicators={data?.indicators || null} />

            {/* 2. Grid Strategy Controls */}
            <GridPanel
              symbol={symbol}
              currentPrice={currentPrice}
              onPreview={(lines) => setGridLines(lines)}
              onOrders={(newOrders) => {
                const formatted = newOrders.map((o: any) => ({
                  id: o.id || Math.random().toString(),
                  symbol: o.symbol,
                  side: o.side,
                  price: o.price,
                  amount: o.amount,
                  status: o.status === 'closed' ? 'filled' : o.status,
                  time: new Date().toLocaleTimeString()
                }));
                setHistoryOrders(prev => [...formatted, ...prev]);
                setGridLines(formatted.map((o: any) => o.price));
              }}
            />
          </div>
        </div>

        {/* Bottom Section: History / Orders (Fixed Height) */}
        <div className="h-[300px] flex-none">
          <HistoryPanel
            orders={historyOrders}
            onCancel={(id) => setHistoryOrders(prev => prev.map(o => o.id === id ? { ...o, status: 'canceled' } : o))}
          />
        </div>
      </div>
    </main>
  );
}
