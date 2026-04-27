"use client"

import { useState, useEffect, useRef } from 'react';
import { BacktestParams, runBacktest, BacktestResult, getSmartGridParams, SignalBacktestParams, SignalBacktestResult, runSignalBacktest } from '@/lib/api';
import { ArrowLeft, Play, Calculator, Activity, TrendingUp, DollarSign, Brain, RefreshCw, Target, Shield, Crosshair, BarChart3, Percent, ArrowDownUp } from 'lucide-react';
import { createChart, ColorType, AreaSeries, CandlestickSeries, createSeriesMarkers } from 'lightweight-charts';
import { InfoTooltip } from '@/components/InfoTooltip';
import Link from 'next/link';
import { getPricePrecision } from '@/lib/utils';

type StrategyMode = 'grid' | 'signal';

export default function BacktestPage() {
    // Strategy Mode
    const [strategyMode, setStrategyMode] = useState<StrategyMode>('signal');

    const [symbol, setSymbol] = useState('BTC/USDT');
    const [duration, setDuration] = useState('30');
    const [feeRate, setFeeRate] = useState('0.08');
    const [investment, setInvestment] = useState('10000');

    // Grid params
    const [lowerPrice, setLowerPrice] = useState('60000');
    const [upperPrice, setUpperPrice] = useState('70000');
    const [gridCount, setGridCount] = useState('20');

    // Signal params
    const [riskPerTrade, setRiskPerTrade] = useState('2.0');
    const [takeProfit, setTakeProfit] = useState('4.0');
    const [stopLoss, setStopLoss] = useState('2.0');
    const [trailingStop, setTrailingStop] = useState('1.5');
    const [trailingActivation, setTrailingActivation] = useState('1.0');
    const [maxPositions, setMaxPositions] = useState('3');
    const [allowShort, setAllowShort] = useState(true);
    const [reverseOnSignal, setReverseOnSignal] = useState(true);

    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState<BacktestResult | null>(null);
    const [signalResult, setSignalResult] = useState<SignalBacktestResult | null>(null);

    // AI Mode (grid only)
    const [isAiMode, setIsAiMode] = useState(true);
    const [useDynamicProfiles, setUseDynamicProfiles] = useState(true);
    const [enableProtection, setEnableProtection] = useState(false); // Default to false to match main page
    const [aiLoading, setAiLoading] = useState(false);

    // Unified result accessors
    const activeResult = strategyMode === 'signal' ? signalResult : result;
    const equityCurve = activeResult?.equity_curve ?? [];
    const trades = activeResult?.trades ?? [];

    const chartContainerRef = useRef<HTMLDivElement>(null);

    // Timezone offset (seconds) so charts display local time instead of UTC
    const tzOffsetSec = new Date().getTimezoneOffset() * -60;

    // Chart Effect
    useEffect(() => {
        if (!equityCurve.length || !chartContainerRef.current) return;

        const chart = createChart(chartContainerRef.current, {
            layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#d1d5db' },
            grid: { vertLines: { color: '#333' }, horzLines: { color: '#333' } },
            width: chartContainerRef.current.clientWidth,
            height: 400,
            timeScale: { timeVisible: true, secondsVisible: false },
        });

        const pnl = strategyMode === 'signal'
            ? (signalResult?.metrics?.pnl ?? 0)
            : (result?.metrics?.pnl ?? 0);
        const lineColor = pnl >= 0 ? '#10b981' : '#ef4444';

        const areaSeries = chart.addSeries(AreaSeries, {
            lineColor, topColor: lineColor, bottomColor: `${lineColor}1a`,
        });

        const sortedEquity = [...equityCurve]
            .sort((a, b) => a.time - b.time)
            .map(item => ({ ...item, time: (item.time + tzOffsetSec) as any }));
        areaSeries.setData(sortedEquity);
        chart.timeScale().fitContent();

        const handleResize = () => chart.applyOptions({ width: chartContainerRef.current?.clientWidth || 0 });
        window.addEventListener('resize', handleResize);
        return () => { window.removeEventListener('resize', handleResize); chart.remove(); };
    }, [equityCurve, result, signalResult, strategyMode]);

    // Price chart ref
    const priceChartRef = useRef<HTMLDivElement>(null);

    // Price Chart + Trade Markers Effect (Signal mode only)
    useEffect(() => {
        if (strategyMode !== 'signal' || !signalResult?.price_data?.length || !priceChartRef.current) return;

        const chart = createChart(priceChartRef.current, {
            layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#d1d5db' },
            grid: { vertLines: { color: '#222' }, horzLines: { color: '#222' } },
            width: priceChartRef.current.clientWidth,
            height: 400,
            timeScale: { timeVisible: true, secondsVisible: false },
            crosshair: { mode: 0 },
        });

        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#10b981', downColor: '#ef4444',
            borderUpColor: '#10b981', borderDownColor: '#ef4444',
            wickUpColor: '#10b981', wickDownColor: '#ef4444',
        });

        const sorted = [...signalResult.price_data]
            .sort((a, b) => a.time - b.time)
            .map(c => ({ time: (c.time + tzOffsetSec) as any, open: c.open, high: c.high, low: c.low, close: c.close }));
        candleSeries.setData(sorted);

        // Build markers from trades
        const markerColors: Record<string, string> = {
            open_long: '#10b981', open_short: '#ef4444',
            close_long: '#f59e0b', close_short: '#f59e0b',
        };
        const reasonEmoji: Record<string, string> = {
            tp: 'TP ✓', sl: 'SL ✗', trailing: 'TRAIL', signal_reverse: 'REV', backtest_end: 'END',
        };

        const markers = signalResult.trades
            .map(t => {
                const isOpen = t.side.startsWith('open');
                const isLong = t.side.includes('long');
                const label = isOpen
                    ? (isLong ? 'BUY' : 'SHORT')
                    : (reasonEmoji[t.exit_reason] || 'CLOSE');
                return {
                    time: (t.time + tzOffsetSec) as any,
                    position: (isOpen ? (isLong ? 'belowBar' : 'aboveBar') : (isLong ? 'aboveBar' : 'belowBar')) as any,
                    color: markerColors[t.side] || '#a78bfa',
                    shape: (isOpen ? 'arrowUp' : 'arrowDown') as any,
                    text: label,
                };
            })
            .sort((a: any, b: any) => a.time - b.time);

        createSeriesMarkers(candleSeries, markers);
        chart.timeScale().fitContent();

        const handleResize = () => chart.applyOptions({ width: priceChartRef.current?.clientWidth || 0 });
        window.addEventListener('resize', handleResize);
        return () => { window.removeEventListener('resize', handleResize); chart.remove(); };
    }, [signalResult, strategyMode]);

    const fetchSmartParams = async () => {
        setAiLoading(true);
        try {
            const params = await getSmartGridParams(symbol, parseInt(duration));
            const precision = getPricePrecision(params.current_price, symbol).precision;
            setLowerPrice(params.lower_price.toFixed(precision));
            setUpperPrice(params.upper_price.toFixed(precision));
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

    // Auto-update AI params if duration changes while AI mode is active
    useEffect(() => {
        if (isAiMode) {
            fetchSmartParams();
        }
    }, [duration, symbol]);

    const handleRun = async () => {
        setLoading(true);
        try {
            if (strategyMode === 'signal') {
                const params: SignalBacktestParams = {
                    symbol,
                    investment: parseFloat(investment),
                    duration_days: parseInt(duration),
                    timeframe: '1h',
                    risk_per_trade_pct: parseFloat(riskPerTrade),
                    take_profit_pct: parseFloat(takeProfit),
                    stop_loss_pct: parseFloat(stopLoss),
                    trailing_stop_pct: parseFloat(trailingStop),
                    trailing_activation_pct: parseFloat(trailingActivation),
                    max_positions: parseInt(maxPositions),
                    fee_rate: parseFloat(feeRate) / 100,
                    allow_short: allowShort,
                    reverse_on_signal: reverseOnSignal,
                    ranging_threshold: 3,
                    trending_threshold: 3,
                    enable_protection: enableProtection,
                    use_dynamic_profiles: useDynamicProfiles,
                };
                const res = await runSignalBacktest(params);
                setSignalResult(res);
                setResult(null);
            } else {
                const params: BacktestParams = {
                    symbol,
                    lower_price: parseFloat(lowerPrice),
                    upper_price: parseFloat(upperPrice),
                    grid_count: parseInt(gridCount),
                    investment: parseFloat(investment),
                    duration_days: parseInt(duration),
                    fee_rate: parseFloat(feeRate) / 100,
                    is_ai_mode: isAiMode,
                    ranging_threshold: 3,
                    trending_threshold: 3,
                    enable_protection: isAiMode,
                    use_dynamic_profiles: useDynamicProfiles,
                };
                const res = await runBacktest(params);
                setResult(res);
                setSignalResult(null);
            }
        } catch (e: any) {
            console.error(e);
            alert(`Backtest Failed: ${e.message}`);
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
                <div className="col-span-12 lg:col-span-4 bg-zinc-900/50 p-6 rounded-xl border border-zinc-800">
                    <div className="flex justify-between items-center mb-6">
                        <h2 className="text-lg font-bold text-white flex items-center gap-2">
                            <Calculator className="w-5 h-5 text-purple-400" />
                            Parameters
                        </h2>
                    </div>

                    {/* Strategy Mode Toggle */}
                    <div className="flex gap-2 mb-5">
                        <button onClick={() => setStrategyMode('signal')} className={`flex-1 py-2 px-3 rounded-lg text-xs font-bold transition-all border flex items-center justify-center gap-1.5 ${strategyMode === 'signal' ? 'bg-purple-900/50 border-purple-500 text-purple-300 shadow-[0_0_15px_rgba(168,85,247,0.2)]' : 'bg-zinc-800/50 border-zinc-700 text-zinc-500 hover:text-zinc-300'}`}>
                            <Crosshair className="w-3.5 h-3.5" /> Signal Strategy
                        </button>
                        <button onClick={() => setStrategyMode('grid')} className={`flex-1 py-2 px-3 rounded-lg text-xs font-bold transition-all border flex items-center justify-center gap-1.5 ${strategyMode === 'grid' ? 'bg-emerald-900/50 border-emerald-500 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.2)]' : 'bg-zinc-800/50 border-zinc-700 text-zinc-500 hover:text-zinc-300'}`}>
                            <BarChart3 className="w-3.5 h-3.5" /> Grid Strategy
                        </button>
                    </div>

                    <div className="space-y-4">
                        {/* Dynamic Profiles toggle */}
                        <label className="flex items-start gap-2 cursor-pointer group mb-2">
                            <div className="relative flex items-center pt-1">
                                <input type="checkbox" checked={useDynamicProfiles} onChange={(e) => setUseDynamicProfiles(e.target.checked)} className="peer sr-only" />
                                <div className="w-8 h-4 bg-zinc-800 rounded-full peer peer-checked:bg-purple-600 transition-colors"></div>
                                <div className="absolute left-1 top-1.5 w-2 h-2 bg-zinc-400 rounded-full transition-all peer-checked:translate-x-4 peer-checked:bg-white"></div>
                            </div>
                            <div className="text-xs text-zinc-300 font-medium flex items-center">
                                動態幣種參數 (Dynamic Profiles)
                                <InfoTooltip text={!useDynamicProfiles ? "【固定標準參數】\nRSI: 25~75\nFunding: -0.4% ~ +1.0%\nEMA偏離: 標準閾值" : symbol.includes('SOL') || symbol.includes('ETH') ? "【Midcap 擴寬參數】\nRSI: 20~80\nFunding: -0.6% ~ +1.5%\nEMA偏離: 加寬 50%" : symbol.includes('HYPE') || symbol.includes('CC') ? "【Alt 極端參數】\nRSI: 15~85\nFunding: -1.0% ~ +2.5%\nEMA偏離: 加倍 100%" : "【Major 標準參數】\nRSI: 25~75\nFunding: -0.4% ~ +1.0%\nEMA偏離: 標準閾值"} />
                            </div>
                        </label>
                        
                        {strategyMode === 'signal' && (
                            <label className="flex items-start gap-2 cursor-pointer group mb-2">
                                <div className="relative flex items-center pt-1">
                                    <input type="checkbox" checked={enableProtection} onChange={(e) => setEnableProtection(e.target.checked)} className="peer sr-only" />
                                    <div className="w-8 h-4 bg-zinc-800 rounded-full peer peer-checked:bg-purple-600 transition-colors"></div>
                                    <div className="absolute left-1 top-1.5 w-2 h-2 bg-zinc-400 rounded-full transition-all peer-checked:translate-x-4 peer-checked:bg-white"></div>
                                </div>
                                <div className="text-xs text-zinc-300 font-medium flex items-center">
                                    開啟趨勢過濾 (Regime Filter)
                                    <InfoTooltip text="關閉可測試全部訊號（符合主頁預設值）。開啟則會過濾掉逆勢操作。" />
                                </div>
                            </label>
                        )}

                        {/* Common: Symbol */}
                        <div>
                            <label className="block text-xs text-zinc-500 mb-1">Symbol</label>
                            <select value={symbol} onChange={e => setSymbol(e.target.value)} className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 transition-colors outline-none">
                                <option value="BTC/USDT">BTC/USDT</option>
                                <option value="ETH/USDT">ETH/USDT</option>
                                <option value="SOL/USDT">SOL/USDT</option>
                                <option value="HYPE/USDT">HYPE/USDT</option>
                                <option value="CC/USDT">CC/USDT</option>
                            </select>
                        </div>

                        {/* Common: Investment + Duration + Fee */}
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-xs text-zinc-500 mb-1">Investment (USDT)</label>
                                <input value={investment} onChange={e => setInvestment(e.target.value)} type="number" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none" />
                            </div>
                            <div>
                                <label className="block text-xs text-zinc-500 mb-1">Duration</label>
                                <select value={duration} onChange={e => setDuration(e.target.value)} className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 transition-colors outline-none">
                                    <option value="3">Last 3 Days</option>
                                    <option value="7">Last 7 Days</option>
                                    <option value="14">Last 14 Days</option>
                                    <option value="30">Last 30 Days</option>
                                    <option value="90">Last 90 Days</option>
                                </select>
                            </div>
                        </div>
                        <div>
                            <label className="block text-xs text-zinc-500 mb-1">Trading Fee (%)</label>
                            <input type="number" step="0.01" value={feeRate} onChange={e => setFeeRate(e.target.value)} className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none" />
                        </div>

                        {/* === Signal Strategy Params === */}
                        {strategyMode === 'signal' && (
                            <>
                                <div className="border-t border-zinc-800 pt-4 mt-2">
                                    <p className="text-[10px] uppercase tracking-wider text-purple-400 font-bold mb-3 flex items-center gap-1"><Target className="w-3 h-3" /> Risk & Position</p>
                                </div>
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-xs text-zinc-500 mb-1 flex items-center gap-1">Risk / Trade % <InfoTooltip text={"每筆交易最多虧掉總資金的幾%。\n\n例：資金 $10,000，Risk = 2%\n→ 每筆最多虧 $200\n→ SL = 2% 時，倉位 = $200 / $2,000 = 0.1 BTC\n\nSL 越大 → 倉位自動縮小，確保虧損始終不超過 2%"} /></label>
                                        <input value={riskPerTrade} onChange={e => setRiskPerTrade(e.target.value)} type="number" step="0.5" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none" />
                                    </div>
                                    <div>
                                        <label className="block text-xs text-zinc-500 mb-1">Max Positions</label>
                                        <input value={maxPositions} onChange={e => setMaxPositions(e.target.value)} type="number" min="1" max="10" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none" />
                                    </div>
                                </div>
                                <div className="grid grid-cols-3 gap-3">
                                    <div>
                                        <label className="block text-xs text-zinc-500 mb-1 flex items-center gap-1"><Shield className="w-3 h-3 text-red-400" /> SL %</label>
                                        <input value={stopLoss} onChange={e => setStopLoss(e.target.value)} type="number" step="0.5" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none" />
                                    </div>
                                    <div>
                                        <label className="block text-xs text-zinc-500 mb-1 flex items-center gap-1"><Target className="w-3 h-3 text-emerald-400" /> TP %</label>
                                        <input value={takeProfit} onChange={e => setTakeProfit(e.target.value)} type="number" step="0.5" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none" />
                                    </div>
                                    <div>
                                        <label className="block text-xs text-zinc-500 mb-1 flex items-center gap-1"><ArrowDownUp className="w-3 h-3 text-amber-400" /> Trail %</label>
                                        <input value={trailingStop} onChange={e => setTrailingStop(e.target.value)} type="number" step="0.5" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none" />
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-xs text-zinc-500 mb-1 flex items-center gap-1">Trail Activation % <InfoTooltip text="浮盈達此百分比後，追蹤止損才會啟動。避免在波動中過早觸發。" /></label>
                                    <input value={trailingActivation} onChange={e => setTrailingActivation(e.target.value)} type="number" step="0.5" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none" />
                                </div>
                                <div className="flex gap-4">
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input type="checkbox" checked={allowShort} onChange={e => setAllowShort(e.target.checked)} className="accent-purple-500 w-3.5 h-3.5" />
                                        <span className="text-xs text-zinc-300">Allow Short</span>
                                    </label>
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input type="checkbox" checked={reverseOnSignal} onChange={e => setReverseOnSignal(e.target.checked)} className="accent-purple-500 w-3.5 h-3.5" />
                                        <span className="text-xs text-zinc-300 flex items-center gap-1">Reverse on Signal <InfoTooltip text="持有 Long 時出現 Bearish 信號 → 自動平 Long 並開 Short（反之亦然）" /></span>
                                    </label>
                                </div>
                            </>
                        )}

                        {/* === Grid Strategy Params === */}
                        {strategyMode === 'grid' && (
                            <>
                                <div className="border-t border-zinc-800 pt-4 mt-2">
                                    <p className="text-[10px] uppercase tracking-wider text-emerald-400 font-bold mb-3 flex items-center gap-1"><BarChart3 className="w-3 h-3" /> Grid Config</p>
                                    <div className="flex items-center gap-2 mb-3">
                                        <button onClick={toggleAiMode} className={`flex items-center gap-2 px-3 py-1 rounded-full text-xs font-bold transition-all border ${isAiMode ? "bg-purple-900/50 border-purple-500 text-purple-300" : "bg-zinc-800 border-zinc-700 text-zinc-500 hover:text-zinc-300"}`}>
                                            {aiLoading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Brain className="w-3 h-3" />}
                                            AI {isAiMode ? "ON" : "OFF"}
                                        </button>
                                    </div>
                                </div>
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="flex justify-between text-xs text-zinc-500 mb-1">Lower Price {isAiMode && <span className="text-purple-400">Auto</span>}</label>
                                        <input disabled={isAiMode || aiLoading} value={lowerPrice} onChange={e => setLowerPrice(e.target.value)} type="number" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none disabled:opacity-50" />
                                    </div>
                                    <div>
                                        <label className="flex justify-between text-xs text-zinc-500 mb-1">Upper Price {isAiMode && <span className="text-purple-400">Auto</span>}</label>
                                        <input disabled={isAiMode || aiLoading} value={upperPrice} onChange={e => setUpperPrice(e.target.value)} type="number" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none disabled:opacity-50" />
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-xs text-zinc-500 mb-1">Grid Count</label>
                                    <input value={gridCount} onChange={e => setGridCount(e.target.value)} type="number" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none" />
                                </div>
                            </>
                        )}

                        <button
                            onClick={handleRun}
                            disabled={loading || aiLoading}
                            className="w-full mt-4 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold py-3 rounded-lg shadow-lg flex items-center justify-center gap-2 transition-all"
                        >
                            {loading ? <Activity className="animate-spin w-5 h-5" /> : aiLoading ? <RefreshCw className="animate-spin w-5 h-5" /> : <Play className="w-5 h-5" />}
                            {loading ? "Running Simulation..." : aiLoading ? "Fetching AI Parameters..." : "Run Backtest"}
                        </button>
                    </div>
                </div>

                {/* Results Panel */}
                <div className="col-span-12 lg:col-span-8 flex flex-col gap-6">
                    {/* Metrics Cards */}
                    {strategyMode === 'signal' ? (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            {[
                                { label: 'PnL (Net)', icon: <DollarSign className="w-3 h-3" />, value: signalResult ? `$${signalResult.metrics.pnl.toFixed(2)}` : '--', color: signalResult && signalResult.metrics.pnl >= 0 ? 'text-emerald-400' : 'text-red-400', size: 'text-xl' },
                                { label: 'Return %', icon: <TrendingUp className="w-3 h-3" />, value: signalResult ? `${signalResult.metrics.pnl_percent.toFixed(2)}%` : '--', color: signalResult && signalResult.metrics.pnl_percent >= 0 ? 'text-emerald-400' : 'text-red-400', size: 'text-xl' },
                                { label: 'Win Rate', icon: <Target className="w-3 h-3" />, value: signalResult ? `${signalResult.metrics.win_rate.toFixed(1)}%` : '--', color: signalResult && signalResult.metrics.win_rate >= 50 ? 'text-emerald-400' : 'text-amber-400', size: 'text-xl' },
                                { label: 'Max Drawdown', icon: <Shield className="w-3 h-3" />, value: signalResult ? `${signalResult.metrics.max_drawdown_pct.toFixed(2)}%` : '--', color: 'text-red-400', size: 'text-xl' },
                                { label: 'Profit Factor', icon: <BarChart3 className="w-3 h-3" />, value: signalResult ? signalResult.metrics.profit_factor.toFixed(2) : '--', color: signalResult && signalResult.metrics.profit_factor >= 1.5 ? 'text-emerald-400' : 'text-zinc-100', size: 'text-xl' },
                                { label: 'Sharpe Ratio', icon: <Percent className="w-3 h-3" />, value: signalResult ? signalResult.metrics.sharpe_ratio.toFixed(2) : '--', color: signalResult && signalResult.metrics.sharpe_ratio >= 1 ? 'text-emerald-400' : 'text-zinc-100', size: 'text-xl' },
                                { label: 'Total Trades', icon: <Activity className="w-3 h-3" />, value: signalResult ? `${signalResult.metrics.winning_trades}W / ${signalResult.metrics.losing_trades}L` : '--', color: 'text-zinc-100', size: 'text-lg' },
                                { label: 'Total Fees', icon: <Calculator className="w-3 h-3" />, value: signalResult ? `$${signalResult.metrics.total_fees_paid.toFixed(2)}` : '--', color: 'text-zinc-400', size: 'text-lg' },
                            ].map((card, i) => (
                                <div key={i} className="bg-zinc-900 border border-zinc-800 p-3 rounded-xl min-h-[90px] flex flex-col justify-between">
                                    <span className="text-zinc-500 text-[10px] uppercase flex items-center gap-1">{card.icon} {card.label}</span>
                                    <div className={`${card.size} font-mono font-bold mt-1 ${card.color}`}>{card.value}</div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="grid grid-cols-4 gap-4">
                            <div className="bg-zinc-900 border border-zinc-800 p-4 rounded-xl min-h-[120px] flex flex-col justify-between">
                                <div>
                                    <span className="text-zinc-500 text-xs uppercase flex items-center gap-1"><DollarSign className="w-3 h-3" /> PnL (Net)</span>
                                    <div className={`text-2xl font-mono font-bold mt-2 ${result && result.metrics.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{result ? `$${result.metrics.pnl.toFixed(2)}` : '--'}</div>
                                </div>
                            </div>
                            <div className="bg-zinc-900 border border-zinc-800 p-4 rounded-xl min-h-[120px] flex flex-col justify-between">
                                <div>
                                    <span className="text-zinc-500 text-xs uppercase flex items-center gap-1"><Calculator className="w-3 h-3" /> Total Fees</span>
                                    <div className="text-xl font-mono font-bold mt-2 text-zinc-100">{result ? `$${result.metrics.total_fees_paid?.toFixed(4) || '0.0000'}` : '--'}</div>
                                </div>
                            </div>
                            <div className="bg-zinc-900 border border-zinc-800 p-4 rounded-xl min-h-[120px] flex flex-col justify-between">
                                <div>
                                    <span className="text-zinc-500 text-xs uppercase flex items-center gap-1"><TrendingUp className="w-3 h-3" /> Return %</span>
                                    <div className={`text-2xl font-mono font-bold mt-2 ${result && result.metrics.pnl_percent >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{result ? `${result.metrics.pnl_percent.toFixed(2)}%` : '--'}</div>
                                </div>
                            </div>
                            <div className="bg-zinc-900 border border-zinc-800 p-4 rounded-xl min-h-[120px] flex flex-col justify-between">
                                <div>
                                    <span className="text-zinc-500 text-xs uppercase flex items-center gap-1"><Activity className="w-3 h-3" /> Total Trades</span>
                                    <div className="text-2xl font-mono font-bold mt-2 text-zinc-100">{result ? result.metrics.total_trades : '--'}</div>
                                </div>
                                <div className="mt-2 flex gap-1 flex-wrap min-h-[22px]">
                                    {(result?.ai_metrics?.protected_buys ?? 0) > 0 && (<span className="text-[10px] bg-blue-900/30 text-blue-400 px-2 py-0.5 rounded border border-blue-800">PAUSED {result!.ai_metrics!.protected_buys}</span>)}
                                    {(result?.ai_metrics?.protected_sells ?? 0) > 0 && (<span className="text-[10px] bg-amber-900/30 text-amber-400 px-2 py-0.5 rounded border border-amber-800">PAUSED {result!.ai_metrics!.protected_sells}</span>)}
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Chart */}
                    <div className="flex-1 bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col relative">
                        <h3 className="text-zinc-400 text-sm font-medium mb-4">Equity Curve</h3>
                        <div ref={chartContainerRef} className="flex-1 w-full min-h-[400px] relative" />
                        {!activeResult && !loading && (
                            <div className="absolute inset-0 flex items-center justify-center text-zinc-600 italic pointer-events-none">
                                Run a simulation to view results.
                            </div>
                        )}
                    </div>

                    {/* Price Chart with Trade Markers (Signal mode only) */}
                    {strategyMode === 'signal' && signalResult?.price_data && (
                        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col">
                            <h3 className="text-zinc-400 text-sm font-medium mb-1 flex items-center justify-between">
                                <span>Price Chart & Trade Markers</span>
                                <div className="flex gap-3 text-[10px] font-mono">
                                    <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-emerald-500 rounded-full"></span> BUY/Long</span>
                                    <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-red-500 rounded-full"></span> SHORT</span>
                                    <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-amber-500 rounded-full"></span> Close (TP/SL/Trail)</span>
                                    <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-purple-400 rounded-full"></span> Reverse</span>
                                </div>
                            </h3>
                            <div ref={priceChartRef} className="w-full min-h-[400px]" />
                        </div>
                    )}
                </div>
            </div>

            {/* Trade History */}
            {trades.length > 0 && (
                <div className="mt-8 bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col">
                            <h3 className="text-zinc-400 text-sm font-medium flex justify-between items-center mb-4">
                                <span>Trade History ({trades.length})</span>
                            </h3>
                            <div className="overflow-auto max-h-[400px]">
                                <table className="w-full text-left border-collapse text-sm text-zinc-300 font-mono">
                                    <thead>
                                        <tr className="text-zinc-500 border-b border-zinc-800 text-xs uppercase tracking-wider sticky top-0 bg-zinc-900 z-10">
                                            <th className="py-2">Time</th>
                                            <th className="py-2">Side</th>
                                            <th className="py-2 text-right">Price</th>
                                            <th className="py-2 text-right">Amount</th>
                                            <th className="py-2 text-right">Fee</th>
                                            <th className="py-2 text-right">PnL</th>
                                            {strategyMode === 'signal' && <th className="py-2 text-center">Reason</th>}
                                            <th className="py-2 text-right">Equity</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {trades.map((trade: any, i: number) => {
                                            const pricePrecision = getPricePrecision(trade.price, symbol).precision;
                                            const pnlValue = trade.realized_pnl || 0;
                                            const amtDisplay = trade.amount < 0.0001 ? Number(trade.amount).toFixed(8) : Number(trade.amount).toFixed(4);

                                            // Side badge styling
                                            const sideStr = trade.side || '';
                                            const isOpen = sideStr.startsWith('open');
                                            const isLong = sideStr.includes('long') || sideStr === 'buy';
                                            const isClose = sideStr.startsWith('close') || sideStr === 'sell';
                                            const badgeColor = isOpen
                                                ? (isLong ? 'border-emerald-900 bg-emerald-900/20 text-emerald-500' : 'border-red-900 bg-red-900/20 text-red-500')
                                                : (isLong ? 'border-emerald-900 bg-emerald-900/20 text-emerald-400' : 'border-red-900 bg-red-900/20 text-red-400');
                                            const sideLabel = strategyMode === 'signal'
                                                ? sideStr.replace('_', ' ').toUpperCase()
                                                : sideStr.toUpperCase();

                                            // Exit reason badge
                                            const reason = trade.exit_reason || '';
                                            const reasonColors: Record<string, string> = {
                                                tp: 'bg-emerald-900/30 text-emerald-400 border-emerald-800',
                                                sl: 'bg-red-900/30 text-red-400 border-red-800',
                                                trailing: 'bg-amber-900/30 text-amber-400 border-amber-800',
                                                signal_reverse: 'bg-purple-900/30 text-purple-400 border-purple-800',
                                                backtest_end: 'bg-zinc-800 text-zinc-400 border-zinc-700',
                                            };

                                            return (
                                                <tr key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors">
                                                    <td className="py-2 text-zinc-400 whitespace-nowrap">
                                                        {new Date(trade.time * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })}
                                                    </td>
                                                    <td className="py-2">
                                                        <span className={`px-1.5 py-0.5 rounded text-[10px] text-center inline-block uppercase border ${badgeColor}`}>
                                                            {sideLabel}
                                                        </span>
                                                    </td>
                                                    <td className="py-2 text-right text-zinc-100">${Number(trade.price).toFixed(pricePrecision)}</td>
                                                    <td className="py-2 text-right text-zinc-400">{amtDisplay}</td>
                                                    <td className="py-2 text-right text-zinc-500">${(trade.fee || 0).toFixed(4)}</td>
                                                    <td className={`py-2 text-right ${isClose && pnlValue > 0 ? 'text-emerald-400' : isClose && pnlValue < 0 ? 'text-red-400' : 'text-zinc-600'}`}>
                                                        {isClose ? (pnlValue > 0 ? '+' : '') + pnlValue.toFixed(2) : '-'}
                                                    </td>
                                                    {strategyMode === 'signal' && (
                                                        <td className="py-2 text-center">
                                                            {reason && <span className={`text-[9px] px-1.5 py-0.5 rounded border ${reasonColors[reason] || 'bg-zinc-800 text-zinc-400 border-zinc-700'}`}>{reason.toUpperCase()}</span>}
                                                        </td>
                                                    )}
                                                    <td className="py-2 text-right text-zinc-100 font-bold">${Number(trade.equity).toFixed(2)}</td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}
        </main>
    )
}
