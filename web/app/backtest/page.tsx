"use client"

import { useState, useEffect, useRef } from 'react';
import { BacktestParams, runBacktest, BacktestResult, getSmartGridParams } from '@/lib/api';
import { ArrowLeft, Play, Calculator, Activity, TrendingUp, DollarSign, Brain, RefreshCw } from 'lucide-react';
import { createChart, ColorType, AreaSeries } from 'lightweight-charts';
import Link from 'next/link';

export default function BacktestPage() {
    const [symbol, setSymbol] = useState('BTC/USDT');
    const [duration, setDuration] = useState('7');
    const [lowerPrice, setLowerPrice] = useState('60000');
    const [upperPrice, setUpperPrice] = useState('70000');
    const [gridCount, setGridCount] = useState('20');
    const [investment, setInvestment] = useState('1000');

    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState<BacktestResult | null>(null);

    // AI Mode
    const [isAiMode, setIsAiMode] = useState(false);
    const [aiLoading, setAiLoading] = useState(false);

    const chartContainerRef = useRef<HTMLDivElement>(null);

    // Chart Effect
    useEffect(() => {
        if (!result || !chartContainerRef.current) return;

        const chart = createChart(chartContainerRef.current, {
            layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#d1d5db' },
            grid: { vertLines: { color: '#333' }, horzLines: { color: '#333' } },
            width: chartContainerRef.current.clientWidth,
            height: 400,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
            }
        });

        const areaSeries = chart.addSeries(AreaSeries, {
            lineColor: '#10b981', topColor: '#10b981', bottomColor: 'rgba(16, 185, 129, 0.1)',
        });

        // Ensure data is sorted by time
        const sortedEquity = [...result.equity_curve].sort((a, b) => a.time - b.time);
        areaSeries.setData(sortedEquity);
        chart.timeScale().fitContent();

        const handleResize = () => chart.applyOptions({ width: chartContainerRef.current?.clientWidth || 0 });
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [result]);

    const fetchSmartParams = async () => {
        setAiLoading(true);
        try {
            const params = await getSmartGridParams(symbol);
            setLowerPrice(params.lower_price.toFixed(1));
            setUpperPrice(params.upper_price.toFixed(1));
            setGridCount(params.grid_count.toString());
        } catch (e: any) {
            console.error(e);
            alert("AI Params Failed: " + e.message);
        } finally {
            setAiLoading(false);
        }
    };

    const toggleAiMode = () => {
        const newState = !isAiMode;
        setIsAiMode(newState);
        if (newState) {
            fetchSmartParams();
        }
    };

    const handleRun = async () => {
        setLoading(true);
        try {
            const params: BacktestParams = {
                symbol,
                lower_price: parseFloat(lowerPrice),
                upper_price: parseFloat(upperPrice),
                grid_count: parseInt(gridCount),
                investment: parseFloat(investment),
                duration_days: parseInt(duration)
            };
            const res = await runBacktest(params);
            setResult(res);
        } catch (e) {
            console.error(e);
            alert("Backtest Failed. Check console.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <main className="min-h-screen bg-black text-zinc-100 p-6 font-sans">
            {/* Header */}
            <div className="flex items-center justify-between mb-8 border-b border-zinc-900 pb-4">
                <div className="flex items-center gap-4">
                    <Link href="/" className="p-2 hover:bg-zinc-900 rounded-full transition-colors text-zinc-400 hover:text-white">
                        <ArrowLeft className="w-5 h-5" />
                    </Link>
                    <h1 className="text-2xl font-bold bg-gradient-to-r from-purple-400 to-pink-500 bg-clip-text text-transparent">
                        Strategy Backtester
                    </h1>
                </div>
                <div className="text-xs text-zinc-500 font-mono">
                    SOLO-QUANT :: SIMULATION-ENV
                </div>
            </div>

            <div className="grid grid-cols-12 gap-8">
                {/* Configuration Panel */}
                <div className="col-span-12 lg:col-span-4 bg-zinc-900/50 p-6 rounded-xl border border-zinc-800 h-fit">
                    <div className="flex justify-between items-center mb-6">
                        <h2 className="text-lg font-bold text-white flex items-center gap-2">
                            <Calculator className="w-5 h-5 text-purple-400" />
                            Parameters
                        </h2>

                        <button
                            onClick={toggleAiMode}
                            className={`flex items-center gap-2 px-3 py-1 rounded-full text-xs font-bold transition-all border ${isAiMode
                                ? "bg-purple-900/50 border-purple-500 text-purple-300 shadow-[0_0_15px_rgba(168,85,247,0.3)]"
                                : "bg-zinc-800 border-zinc-700 text-zinc-500 hover:text-zinc-300"
                                }`}
                        >
                            {aiLoading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Brain className="w-3 h-3" />}
                            AI {isAiMode ? "ON" : "OFF"}
                        </button>
                    </div>

                    <div className="space-y-4">
                        <div>
                            <label className="block text-xs text-zinc-500 mb-1">Symbol</label>
                            <select
                                value={symbol}
                                onChange={e => setSymbol(e.target.value)}
                                className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 transition-colors outline-none"
                            >
                                <option value="BTC/USDT">BTC/USDT</option>
                                <option value="ETH/USDT">ETH/USDT</option>
                                <option value="SOL/USDT">SOL/USDT</option>
                            </select>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="flex justify-between text-xs text-zinc-500 mb-1">
                                    Lower Price
                                    {isAiMode && <span className="text-purple-400">Auto</span>}
                                </label>
                                <input disabled={isAiMode} value={lowerPrice} onChange={e => setLowerPrice(e.target.value)} type="number" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none disabled:opacity-50" />
                            </div>
                            <div>
                                <label className="flex justify-between text-xs text-zinc-500 mb-1">
                                    Upper Price
                                    {isAiMode && <span className="text-purple-400">Auto</span>}
                                </label>
                                <input disabled={isAiMode} value={upperPrice} onChange={e => setUpperPrice(e.target.value)} type="number" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none disabled:opacity-50" />
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-xs text-zinc-500 mb-1">Grid Count</label>
                                <input value={gridCount} onChange={e => setGridCount(e.target.value)} type="number" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none" />
                            </div>
                            <div>
                                <label className="block text-xs text-zinc-500 mb-1">Investment</label>
                                <input value={investment} onChange={e => setInvestment(e.target.value)} type="number" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none" />
                            </div>
                        </div>

                        <div>
                            <label className="block text-xs text-zinc-500 mb-1">Duration (Days)</label>
                            <select
                                value={duration}
                                onChange={e => setDuration(e.target.value)}
                                className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 transition-colors outline-none"
                            >
                                <option value="3">Last 3 Days</option>
                                <option value="7">Last 7 Days</option>
                                <option value="30">Last 30 Days</option>
                            </select>
                        </div>

                        <button
                            onClick={handleRun}
                            disabled={loading}
                            className="w-full mt-4 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white font-bold py-3 rounded-lg shadow-lg flex items-center justify-center gap-2 transition-all"
                        >
                            {loading ? <Activity className="animate-spin w-5 h-5" /> : <Play className="w-5 h-5" />}
                            {loading ? "Running Simulation..." : "Run Backtest"}
                        </button>
                    </div>
                </div>

                {/* Results Panel */}
                <div className="col-span-12 lg:col-span-8 flex flex-col gap-6">
                    {/* Metrics Cards */}
                    <div className="grid grid-cols-3 gap-4">
                        <div className="bg-zinc-900 border border-zinc-800 p-4 rounded-xl">
                            <span className="text-zinc-500 text-xs uppercase flex items-center gap-1"><DollarSign className="w-3 h-3" /> PnL (Net)</span>
                            <div className={`text-2xl font-mono font-bold mt-2 ${result && result.metrics.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                {result ? `$${result.metrics.pnl.toFixed(2)}` : '--'}
                            </div>
                        </div>
                        <div className="bg-zinc-900 border border-zinc-800 p-4 rounded-xl">
                            <span className="text-zinc-500 text-xs uppercase flex items-center gap-1"><TrendingUp className="w-3 h-3" /> Return %</span>
                            <div className={`text-2xl font-mono font-bold mt-2 ${result && result.metrics.pnl_percent >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                {result ? `${result.metrics.pnl_percent.toFixed(2)}%` : '--'}
                            </div>
                        </div>
                        <div className="bg-zinc-900 border border-zinc-800 p-4 rounded-xl">
                            <span className="text-zinc-500 text-xs uppercase flex items-center gap-1"><Activity className="w-3 h-3" /> Total Trades</span>
                            <div className="text-2xl font-mono font-bold mt-2 text-zinc-100">
                                {result ? result.metrics.total_trades : '--'}
                            </div>
                        </div>
                    </div>

                    {/* Chart */}
                    <div className="flex-1 bg-zinc-900 border border-zinc-800 rounded-xl p-4 min-h-[400px] flex flex-col">
                        <h3 className="text-zinc-400 text-sm font-medium mb-4">Equity Curve</h3>
                        <div ref={chartContainerRef} className="flex-1 w-full" />
                        {!result && !loading && (
                            <div className="flex h-full items-center justify-center text-zinc-600 italic">
                                Run a simulation to view results.
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </main>
    )
}
