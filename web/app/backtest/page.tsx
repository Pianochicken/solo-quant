"use client"

import { useState, useEffect, useRef } from 'react';
import { SignalBacktestParams, SignalBacktestResult, runSignalBacktest } from '@/lib/api';
import { ArrowLeft, Play, Calculator, Activity, TrendingUp, TrendingDown, DollarSign, Target, Shield, Crosshair, BarChart3, Percent, ArrowDownUp, Zap } from 'lucide-react';
import { createChart, ColorType, AreaSeries, CandlestickSeries, createSeriesMarkers } from 'lightweight-charts';
import { InfoTooltip } from '@/components/InfoTooltip';
import Link from 'next/link';
import { getPricePrecision } from '@/lib/utils';

// Empirical optimal risk profiles by symbol and timeframe (derived from historical MFE/MAE distributions)
const OPTIMAL_RISK_PROFILES: Record<string, Record<string, { stop_loss_pct: number; take_profit_pct: number; trailing_activation_pct: number; trailing_stop_pct: number }>> = {
    BTC: {
        '1h': { stop_loss_pct: 1.4, take_profit_pct: 1.5, trailing_activation_pct: 0.65, trailing_stop_pct: 0.30 },
        '4h': { stop_loss_pct: 2.2, take_profit_pct: 2.8, trailing_activation_pct: 1.20, trailing_stop_pct: 0.50 },
        '1d': { stop_loss_pct: 5.0, take_profit_pct: 6.5, trailing_activation_pct: 2.80, trailing_stop_pct: 1.10 },
    },
    ETH: {
        '1h': { stop_loss_pct: 1.8, take_profit_pct: 2.1, trailing_activation_pct: 0.90, trailing_stop_pct: 0.40 },
        '4h': { stop_loss_pct: 2.8, take_profit_pct: 3.8, trailing_activation_pct: 1.60, trailing_stop_pct: 0.70 },
        '1d': { stop_loss_pct: 7.5, take_profit_pct: 10.5, trailing_activation_pct: 4.20, trailing_stop_pct: 1.60 },
    },
    SOL: {
        '1h': { stop_loss_pct: 2.0, take_profit_pct: 2.6, trailing_activation_pct: 1.00, trailing_stop_pct: 0.45 },
        '4h': { stop_loss_pct: 3.5, take_profit_pct: 3.6, trailing_activation_pct: 1.60, trailing_stop_pct: 0.70 },
        '1d': { stop_loss_pct: 9.0, take_profit_pct: 12.0, trailing_activation_pct: 5.00, trailing_stop_pct: 2.00 },
    },
    CC: {
        '1h': { stop_loss_pct: 3.0, take_profit_pct: 3.0, trailing_activation_pct: 1.30, trailing_stop_pct: 0.55 },
        '4h': { stop_loss_pct: 6.0, take_profit_pct: 6.8, trailing_activation_pct: 3.00, trailing_stop_pct: 1.20 },
        '1d': { stop_loss_pct: 9.5, take_profit_pct: 11.5, trailing_activation_pct: 5.00, trailing_stop_pct: 2.00 },
    },
    HYPE: {
        '1h': { stop_loss_pct: 2.8, take_profit_pct: 2.6, trailing_activation_pct: 1.10, trailing_stop_pct: 0.50 },
        '4h': { stop_loss_pct: 4.2, take_profit_pct: 3.2, trailing_activation_pct: 1.60, trailing_stop_pct: 0.70 },
        '1d': { stop_loss_pct: 10.0, take_profit_pct: 13.0, trailing_activation_pct: 5.50, trailing_stop_pct: 2.20 },
    },
};

const DURATION_OPTIONS: Record<string, { value: string; label: string }[]> = {
    '1h': [
        { value: '30', label: 'Last 30 Days' },
        { value: '60', label: 'Last 60 Days' },
        { value: '90', label: 'Last 90 Days' },
        { value: '180', label: 'Last 180 Days' },
    ],
    '4h': [
        { value: '60', label: 'Last 60 Days' },
        { value: '90', label: 'Last 90 Days' },
        { value: '180', label: 'Last 180 Days' },
        { value: '365', label: 'Last 365 Days' },
    ],
    '1d': [
        { value: '180', label: 'Last 180 Days' },
        { value: '365', label: 'Last 365 Days' },
        { value: '730', label: 'Last 730 Days' },
    ],
};

export default function BacktestPage() {
    // Basic Simulation Parameters
    const [symbol, setSymbol] = useState('BTC/USDT');
    const [timeframe, setTimeframe] = useState<'1h' | '4h' | '1d'>('1h');
    const [duration, setDuration] = useState('30');
    const [feeRate, setFeeRate] = useState('0.05');
    const [investment, setInvestment] = useState('10000');

    // Risk & Position Parameters (Default to BTC 1h Optimal Profile)
    const [riskPerTrade, setRiskPerTrade] = useState('2.0');
    const [takeProfit, setTakeProfit] = useState('1.5');
    const [stopLoss, setStopLoss] = useState('1.4');
    const [trailingStop, setTrailingStop] = useState('0.30');
    const [trailingActivation, setTrailingActivation] = useState('0.65');
    const [maxPositions, setMaxPositions] = useState('1');
    const [allowShort, setAllowShort] = useState(true);
    const [reverseOnSignal, setReverseOnSignal] = useState(true);

    // Advanced Strategy Toggles
    const [useDynamicProfiles, setUseDynamicProfiles] = useState(true);
    const [enableProtection, setEnableProtection] = useState(true);
    const [enableMtfFilter, setEnableMtfFilter] = useState(true);
    const [autoRiskProfile, setAutoRiskProfile] = useState(true);

    const [loading, setLoading] = useState(false);
    const [signalResult, setSignalResult] = useState<SignalBacktestResult | null>(null);

    const equityCurve = signalResult?.equity_curve ?? [];
    const trades = signalResult?.trades ?? [];

    const chartContainerRef = useRef<HTMLDivElement>(null);
    const priceChartRef = useRef<HTMLDivElement>(null);

    // Helper: current optimal profile base
    const coinKey = symbol.split('/')[0];
    const currentBase = OPTIMAL_RISK_PROFILES[coinKey]?.[timeframe] || OPTIMAL_RISK_PROFILES['BTC']['1h'];

    // Auto-adapt risk parameters when Symbol or Timeframe changes if autoRiskProfile is active
    useEffect(() => {
        if (!autoRiskProfile) return;
        const base = OPTIMAL_RISK_PROFILES[coinKey]?.[timeframe] || OPTIMAL_RISK_PROFILES['BTC']['1h'];
        setStopLoss(base.stop_loss_pct.toString());
        setTakeProfit(base.take_profit_pct.toString());
        setTrailingActivation(base.trailing_activation_pct.toString());
        setTrailingStop(base.trailing_stop_pct.toString());
    }, [symbol, timeframe, autoRiskProfile, coinKey]);

    // Handle timeframe change with auto duration linking
    const handleTimeframeChange = (newTf: '1h' | '4h' | '1d') => {
        setTimeframe(newTf);
        if (newTf === '1h') setDuration('30');
        else if (newTf === '4h') setDuration('90');
        else if (newTf === '1d') setDuration('365');
    };

    // Equity Chart Effect
    useEffect(() => {
        if (!equityCurve.length || !chartContainerRef.current) return;

        const chart = createChart(chartContainerRef.current, {
            layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#d1d5db', attributionLogo: false },
            grid: { vertLines: { color: '#27272a' }, horzLines: { color: '#27272a' } },
            width: chartContainerRef.current.clientWidth,
            height: 380,
            timeScale: { timeVisible: true, secondsVisible: false },
        });

        const pnl = signalResult?.metrics?.pnl ?? 0;
        const lineColor = pnl >= 0 ? '#10b981' : '#ef4444';

        const areaSeries = chart.addSeries(AreaSeries, {
            lineColor,
            topColor: `${lineColor}33`,
            bottomColor: `${lineColor}05`,
            lineWidth: 2,
        });

        const sortedEquity = [...equityCurve]
            .sort((a, b) => a.time - b.time)
            .map(item => ({ ...item, time: item.time as any }));
        areaSeries.setData(sortedEquity);
        chart.timeScale().fitContent();

        const handleResize = () => chart.applyOptions({ width: chartContainerRef.current?.clientWidth || 0 });
        window.addEventListener('resize', handleResize);
        return () => { window.removeEventListener('resize', handleResize); chart.remove(); };
    }, [equityCurve, signalResult]);

    // Price Chart + Trade Markers Effect
    useEffect(() => {
        if (!signalResult?.price_data?.length || !priceChartRef.current) return;

        const chart = createChart(priceChartRef.current, {
            layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#d1d5db', attributionLogo: false },
            grid: { vertLines: { color: '#222' }, horzLines: { color: '#222' } },
            width: priceChartRef.current.clientWidth,
            height: 380,
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
            .map(c => ({ ...c, time: c.time as any }));
        candleSeries.setData(sorted);

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
                    time: t.time as any,
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
    }, [signalResult]);

    const handleRun = async () => {
        setLoading(true);
        try {
            const params: SignalBacktestParams = {
                symbol,
                investment: parseFloat(investment),
                duration_days: parseInt(duration),
                timeframe,
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
                enable_mtf_filter: enableMtfFilter,
            };
            const res = await runSignalBacktest(params);
            setSignalResult(res);
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
                    <div>
                        <h1 className="text-2xl font-bold bg-gradient-to-r from-purple-400 via-pink-500 to-indigo-400 bg-clip-text text-transparent">
                            Signal Strategy Backtester
                        </h1>
                        <p className="text-xs text-zinc-500 mt-0.5">
                            Confluence Signals · Dynamic MFE/MAE Calibration · Multi-Timeframe Execution
                        </p>
                    </div>
                </div>
                <div className="text-xs text-zinc-500 font-mono flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                    SOLO-QUANT :: SIMULATION-ENV
                </div>
            </div>

            <div className="grid grid-cols-12 gap-8">
                {/* Configuration Panel */}
                <div className="col-span-12 lg:col-span-4 bg-zinc-900/50 p-6 rounded-xl border border-zinc-800 flex flex-col justify-between">
                    <div>
                        <div className="flex justify-between items-center mb-5 pb-3 border-b border-zinc-800/80">
                            <h2 className="text-base font-bold text-white flex items-center gap-2">
                                <Calculator className="w-4 h-4 text-purple-400" />
                                Strategy Configuration
                            </h2>
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-purple-900/30 text-purple-300 border border-purple-800/50">
                                {symbol} · {timeframe.toUpperCase()}
                            </span>
                        </div>

                        <div className="space-y-4">
                            {/* Strategy Toggles */}
                            <div className="bg-zinc-950/60 p-3 rounded-lg border border-zinc-800/60 space-y-2.5">
                                {/* 1. Dynamic Profiles toggle */}
                                <label className="flex items-start gap-2 cursor-pointer group">
                                    <div className="relative flex items-center pt-0.5">
                                        <input type="checkbox" checked={useDynamicProfiles} onChange={(e) => setUseDynamicProfiles(e.target.checked)} className="peer sr-only" />
                                        <div className="w-7 h-3.5 bg-zinc-800 rounded-full peer peer-checked:bg-purple-600 transition-colors"></div>
                                        <div className="absolute left-0.5 top-1 w-2.5 h-2.5 bg-zinc-400 rounded-full transition-all peer-checked:translate-x-3.5 peer-checked:bg-white"></div>
                                    </div>
                                    <div className="text-xs text-zinc-300 font-medium flex items-center">
                                        動態幣種參數 (Dynamic Profiles)
                                        <InfoTooltip text={!useDynamicProfiles ? "【固定標準參數】\nRSI: 25~75\nFunding: -0.4% ~ +1.0%\nEMA偏離: 標準閾值" : symbol.includes('SOL') || symbol.includes('ETH') ? "【Midcap 擴寬參數】\nRSI: 20~80\nFunding: -0.6% ~ +1.5%\nEMA偏離: 加寬 50%" : symbol.includes('HYPE') || symbol.includes('CC') ? "【Alt 極端參數】\nRSI: 15~85\nFunding: -1.0% ~ +2.5%\nEMA偏離: 加倍 100%" : "【Major 標準參數】\nRSI: 25~75\nFunding: -0.4% ~ +1.0%\nEMA偏離: 標準閾值"} />
                                    </div>
                                </label>

                                {/* 2. Regime Filter toggle */}
                                <label className="flex items-start gap-2 cursor-pointer group">
                                    <div className="relative flex items-center pt-0.5">
                                        <input type="checkbox" checked={enableProtection} onChange={(e) => setEnableProtection(e.target.checked)} className="peer sr-only" />
                                        <div className="w-7 h-3.5 bg-zinc-800 rounded-full peer peer-checked:bg-purple-600 transition-colors"></div>
                                        <div className="absolute left-0.5 top-1 w-2.5 h-2.5 bg-zinc-400 rounded-full transition-all peer-checked:translate-x-3.5 peer-checked:bg-white"></div>
                                    </div>
                                    <div className="text-xs text-zinc-300 font-medium flex items-center">
                                        開啟趨勢過濾 (Regime Filter)
                                        <InfoTooltip text="關閉可測試全部逆勢信號。開啟則會依據大趨勢防護（如 EMA 順勢防護與唐奇安突破首根確認）過濾逆勢交易。" />
                                    </div>
                                </label>

                                {/* 3. MTF Filter toggle */}
                                <label className="flex items-start gap-2 cursor-pointer group">
                                    <div className="relative flex items-center pt-0.5">
                                        <input type="checkbox" checked={enableMtfFilter} onChange={(e) => setEnableMtfFilter(e.target.checked)} className="peer sr-only" />
                                        <div className="w-7 h-3.5 bg-zinc-800 rounded-full peer peer-checked:bg-indigo-600 transition-colors"></div>
                                        <div className="absolute left-0.5 top-1 w-2.5 h-2.5 bg-zinc-400 rounded-full transition-all peer-checked:translate-x-3.5 peer-checked:bg-white"></div>
                                    </div>
                                    <div className="text-xs text-zinc-300 font-medium flex items-center gap-1">
                                        MTF 多時間框架確認
                                        <span className="px-1 py-0.2 text-[9px] font-bold rounded bg-indigo-900/50 text-indigo-300 border border-indigo-800/50">4H</span>
                                        <InfoTooltip text="開啟後，當 4h 大週期處於強烈單邊趨勢時，禁止在 1h 開立逆向回歸單，避免逆大勢接刀。" />
                                    </div>
                                </label>

                                {/* 4. Auto Risk Profile toggle */}
                                <label className="flex items-start gap-2 cursor-pointer group">
                                    <div className="relative flex items-center pt-0.5">
                                        <input type="checkbox" checked={autoRiskProfile} onChange={(e) => setAutoRiskProfile(e.target.checked)} className="peer sr-only" />
                                        <div className="w-7 h-3.5 bg-zinc-800 rounded-full peer peer-checked:bg-emerald-600 transition-colors"></div>
                                        <div className="absolute left-0.5 top-1 w-2.5 h-2.5 bg-zinc-400 rounded-full transition-all peer-checked:translate-x-3.5 peer-checked:bg-white"></div>
                                    </div>
                                    <div className="text-xs text-zinc-300 font-medium flex items-center gap-1">
                                        自動最佳化風控 (Auto Risk Profile)
                                        <span className="px-1 py-0.2 text-[9px] font-bold rounded bg-emerald-900/50 text-emerald-300 border border-emerald-800/50">MFE/MAE</span>
                                        <InfoTooltip text="切換幣種或時間框架時，自動代入實證 MFE/MAE 最佳化止損 (SL)、止盈 (TP) 與追蹤保本 (Trail) 參數。" />
                                    </div>
                                </label>
                            </div>

                            {/* Symbol & Timeframe */}
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <label className="block text-xs text-zinc-500 mb-1">Symbol</label>
                                    <select value={symbol} onChange={e => setSymbol(e.target.value)} className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 transition-colors outline-none font-mono">
                                        <option value="BTC/USDT">BTC/USDT</option>
                                        <option value="ETH/USDT">ETH/USDT</option>
                                        <option value="SOL/USDT">SOL/USDT</option>
                                        <option value="HYPE/USDT">HYPE/USDT</option>
                                        <option value="CC/USDT">CC/USDT</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-xs text-zinc-500 mb-1">Timeframe</label>
                                    <select value={timeframe} onChange={e => handleTimeframeChange(e.target.value as any)} className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 transition-colors outline-none font-mono">
                                        <option value="1h">1h (Hourly)</option>
                                        <option value="4h">4h (Swing)</option>
                                        <option value="1d">1d (Daily)</option>
                                    </select>
                                </div>
                            </div>

                            {/* Investment & Duration */}
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <label className="block text-xs text-zinc-500 mb-1">Investment (USDT)</label>
                                    <input value={investment} onChange={e => setInvestment(e.target.value)} type="number" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none font-mono" />
                                </div>
                                <div>
                                    <label className="block text-xs text-zinc-500 mb-1">Duration</label>
                                    <select value={duration} onChange={e => setDuration(e.target.value)} className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 transition-colors outline-none font-mono">
                                        {DURATION_OPTIONS[timeframe]?.map(opt => (
                                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                                        ))}
                                    </select>
                                </div>
                            </div>

                            {/* Trading Fee */}
                            <div>
                                <label className="block text-xs text-zinc-500 mb-1 flex items-center justify-between">
                                    <span>Trading Fee (%)</span>
                                    <span className="text-[10px] text-zinc-500 font-mono">Perps 0.05%</span>
                                </label>
                                <input type="number" step="0.01" value={feeRate} onChange={e => setFeeRate(e.target.value)} className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none font-mono" />
                            </div>

                            {/* === Risk & Position Management === */}
                            <div className="border-t border-zinc-800/80 pt-3">
                                <div className="flex justify-between items-center mb-3">
                                    <p className="text-[10px] uppercase tracking-wider text-purple-400 font-bold flex items-center gap-1">
                                        <Target className="w-3 h-3" /> Risk & Position
                                    </p>
                                    <div className="flex gap-1.5">
                                        <button 
                                            onClick={() => {
                                                setStopLoss(currentBase.stop_loss_pct.toString());
                                                setTakeProfit(currentBase.take_profit_pct.toString());
                                                setTrailingActivation(currentBase.trailing_activation_pct.toString());
                                                setTrailingStop(currentBase.trailing_stop_pct.toString());
                                            }}
                                            className="px-2 py-1 text-[10px] font-bold rounded transition border bg-zinc-800 text-zinc-300 border-zinc-700 hover:text-white hover:bg-zinc-700 hover:border-purple-500 flex items-center gap-1"
                                            title="填入當前幣種與週期之實證最佳參數"
                                        >
                                            <Target className="w-2.5 h-2.5 text-purple-400" /> 🎯 實證最佳基準
                                        </button>
                                        <button 
                                            onClick={() => {
                                                setStopLoss(currentBase.stop_loss_pct.toString());
                                                setTakeProfit((currentBase.take_profit_pct * 1.4).toFixed(2));
                                                setTrailingActivation((currentBase.trailing_activation_pct * 1.3).toFixed(2));
                                                setTrailingStop((currentBase.trailing_stop_pct * 1.25).toFixed(2));
                                            }}
                                            className="px-2 py-1 text-[10px] font-bold rounded transition border bg-zinc-800 text-zinc-300 border-zinc-700 hover:text-white hover:bg-zinc-700 hover:border-indigo-500 flex items-center gap-1"
                                            title="放大止盈與追蹤距離至 1.4 倍以捕捉延伸波段"
                                        >
                                            <Zap className="w-2.5 h-2.5 text-indigo-400" /> 🚀 波段放大 (1.4x)
                                        </button>
                                    </div>
                                </div>

                                <div className="grid grid-cols-2 gap-3 mb-3">
                                    <div>
                                        <label className="block text-xs text-zinc-500 mb-1 flex items-center gap-1">
                                            Risk / Trade % 
                                            <InfoTooltip text={"每筆交易最多虧損總資金的百分比。\n\n例：資金 $10,000，Risk = 2%\n→ 單筆最大虧損限制為 $200\n→ 系統依止損距離自動換算合約開倉張數，確保虧損絕不穿透風控限制。"} />
                                        </label>
                                        <input value={riskPerTrade} onChange={e => setRiskPerTrade(e.target.value)} type="number" step="0.5" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none font-mono" />
                                    </div>
                                    <div>
                                        <label className="block text-xs text-zinc-500 mb-1 flex items-center gap-1">
                                            Max Positions
                                            <InfoTooltip text="同時間允許持有的最大併行倉位數。建議設為 1，避免在波段末端重複疊倉產生高額手續費與過度暴露。" />
                                        </label>
                                        <input value={maxPositions} onChange={e => setMaxPositions(e.target.value)} type="number" min="1" max="10" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none font-mono" />
                                    </div>
                                </div>

                                <div className="grid grid-cols-3 gap-2.5 mb-3">
                                    <div>
                                        <label className="block text-xs text-zinc-500 mb-1 flex items-center gap-1">
                                            <Shield className="w-3 h-3 text-red-400" /> SL %
                                        </label>
                                        <input value={stopLoss} onChange={e => setStopLoss(e.target.value)} type="number" step="0.1" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none font-mono" />
                                    </div>
                                    <div>
                                        <label className="block text-xs text-zinc-500 mb-1 flex items-center gap-1">
                                            <Target className="w-3 h-3 text-emerald-400" /> TP %
                                        </label>
                                        <input value={takeProfit} onChange={e => setTakeProfit(e.target.value)} type="number" step="0.1" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none font-mono" />
                                    </div>
                                    <div>
                                        <label className="block text-xs text-zinc-500 mb-1 flex items-center gap-1">
                                            <ArrowDownUp className="w-3 h-3 text-amber-400" /> Trail %
                                        </label>
                                        <input value={trailingStop} onChange={e => setTrailingStop(e.target.value)} type="number" step="0.05" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none font-mono" />
                                    </div>
                                </div>

                                <div className="mb-3">
                                    <label className="block text-xs text-zinc-500 mb-1 flex items-center gap-1">
                                        Trail Activation % 
                                        <InfoTooltip text="浮盈達此百分比後，追蹤止損機制才會正式啟動。啟動後止損線將自動移至保本價，並隨著獲利延伸持續向上跟隨。" />
                                    </label>
                                    <input value={trailingActivation} onChange={e => setTrailingActivation(e.target.value)} type="number" step="0.05" className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:border-purple-500 outline-none font-mono" />
                                </div>

                                <div className="flex gap-4 pt-1">
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input type="checkbox" checked={allowShort} onChange={e => setAllowShort(e.target.checked)} className="accent-purple-500 w-3.5 h-3.5" />
                                        <span className="text-xs text-zinc-300">Allow Short</span>
                                    </label>
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input type="checkbox" checked={reverseOnSignal} onChange={e => setReverseOnSignal(e.target.checked)} className="accent-purple-500 w-3.5 h-3.5" />
                                        <span className="text-xs text-zinc-300 flex items-center gap-1">
                                            Reverse on Signal 
                                            <InfoTooltip text="持有多單時若出現反向空頭信號 → 自動平多並反向開空（反之亦然）。" />
                                        </span>
                                    </label>
                                </div>
                            </div>
                        </div>
                    </div>

                    <button
                        onClick={handleRun}
                        disabled={loading}
                        className="w-full mt-6 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold py-3 rounded-lg shadow-lg flex items-center justify-center gap-2 transition-all"
                    >
                        {loading ? <Activity className="animate-spin w-5 h-5" /> : <Play className="w-5 h-5 fill-white" />}
                        {loading ? "Simulating Market Execution..." : "Run Signal Simulation"}
                    </button>
                </div>

                {/* Results Panel */}
                <div className="col-span-12 lg:col-span-8 flex flex-col gap-6">
                    {/* Metrics Cards */}
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                        {[
                            {
                                label: 'PnL (Net)',
                                icon: <DollarSign className="w-3 h-3" />,
                                value: signalResult ? `$${signalResult.metrics.pnl.toFixed(2)}` : '--',
                                color: signalResult && signalResult.metrics.pnl >= 0 ? 'text-emerald-400' : 'text-red-400',
                                size: 'text-xl',
                                tooltip: '回測期間扣除雙邊手續費後的總淨盈虧金額'
                            },
                            {
                                label: 'Return %',
                                icon: <TrendingUp className="w-3 h-3" />,
                                value: signalResult ? `${signalResult.metrics.pnl_percent.toFixed(2)}%` : '--',
                                color: signalResult && signalResult.metrics.pnl_percent >= 0 ? 'text-emerald-400' : 'text-red-400',
                                size: 'text-xl',
                                tooltip: '相對於初始本金的累計淨投資報酬率'
                            },
                            {
                                label: 'Win Rate',
                                icon: <Target className="w-3 h-3" />,
                                value: signalResult ? `${signalResult.metrics.win_rate.toFixed(1)}%` : '--',
                                color: signalResult && signalResult.metrics.win_rate >= 50 ? 'text-emerald-400' : 'text-amber-400',
                                size: 'text-xl',
                                tooltip: '獲利平倉交易筆數佔總平倉交易筆數的百分比'
                            },
                            {
                                label: 'Max Drawdown',
                                icon: <Shield className="w-3 h-3" />,
                                value: signalResult ? `${signalResult.metrics.max_drawdown_pct.toFixed(2)}%` : '--',
                                color: 'text-red-400',
                                size: 'text-xl',
                                tooltip: '淨值曲線由歷史最高峰回落至最低谷的最大累積跌幅 (MDD)'
                            },
                            {
                                label: 'Profit Factor',
                                icon: <BarChart3 className="w-3 h-3" />,
                                value: signalResult ? signalResult.metrics.profit_factor.toFixed(2) : '--',
                                color: signalResult && signalResult.metrics.profit_factor >= 1.5 ? 'text-emerald-400' : 'text-zinc-100',
                                size: 'text-xl',
                                tooltip: '毛獲利總額除以毛虧損總額之比值，數值大於 1.5 代表具備穩健優勢'
                            },
                            {
                                label: 'Sharpe Ratio',
                                icon: <Percent className="w-3 h-3" />,
                                value: signalResult ? signalResult.metrics.sharpe_ratio.toFixed(2) : '--',
                                color: signalResult && signalResult.metrics.sharpe_ratio >= 1 ? 'text-emerald-400' : 'text-zinc-100',
                                size: 'text-xl',
                                tooltip: '年化夏普比率，衡量策略每承受一單位波動風險所能換取的超額報酬'
                            },
                            {
                                label: 'Total Trades',
                                icon: <Activity className="w-3 h-3" />,
                                value: signalResult ? `${signalResult.metrics.winning_trades}W / ${signalResult.metrics.losing_trades}L` : '--',
                                color: 'text-zinc-100',
                                size: 'text-lg',
                                tooltip: '回測期間累積完成的平倉交易總數（勝場數 W / 敗場數 L）'
                            },
                            {
                                label: 'Total Fees',
                                icon: <Calculator className="w-3 h-3" />,
                                value: signalResult ? `$${signalResult.metrics.total_fees_paid.toFixed(2)}` : '--',
                                color: 'text-zinc-400',
                                size: 'text-lg',
                                tooltip: '回測期間進出場累積扣除的交易所交易手續費總額'
                            },
                            {
                                label: 'Avg MFE (最高波段)',
                                icon: <TrendingUp className="w-3 h-3" />,
                                value: signalResult?.metrics?.avg_mfe_pct != null ? `+${signalResult.metrics.avg_mfe_pct.toFixed(2)}%` : '--',
                                color: 'text-emerald-400',
                                size: 'text-xl',
                                tooltip: '進場後在持倉期間平均最高達到的浮盈幅度，代表訊號的獲利天花板'
                            },
                            {
                                label: 'Avg MAE (平均浮虧)',
                                icon: <TrendingDown className="w-3 h-3" />,
                                value: signalResult?.metrics?.avg_mae_pct != null ? `-${Math.abs(signalResult.metrics.avg_mae_pct).toFixed(2)}%` : '--',
                                color: 'text-red-400',
                                size: 'text-xl',
                                tooltip: '進場後在持倉期間平均承受的最大逆向浮虧，可用來設定合理的止損底線'
                            },
                        ].map((card, i) => (
                            <div key={i} className="bg-zinc-900 border border-zinc-800 p-3 rounded-xl min-h-[90px] flex flex-col justify-between">
                                <span className="text-zinc-500 text-[10px] uppercase flex items-center gap-1">
                                    {card.icon} {card.label}
                                    {card.tooltip && <InfoTooltip text={card.tooltip} />}
                                </span>
                                <div className={`${card.size} font-mono font-bold mt-1 ${card.color}`}>{card.value}</div>
                            </div>
                        ))}
                    </div>

                    {/* Equity Curve Chart */}
                    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col relative">
                        <div className="flex justify-between items-center mb-3">
                            <h3 className="text-zinc-400 text-sm font-medium flex items-center gap-2">
                                <TrendingUp className="w-4 h-4 text-emerald-400" /> Equity Curve (淨值成長曲線)
                            </h3>
                            {signalResult && (
                                <span className="text-[10px] font-mono text-zinc-500">
                                    Initial: ${signalResult.metrics.initial_balance.toLocaleString()} → Final: ${signalResult.metrics.final_balance.toLocaleString()}
                                </span>
                            )}
                        </div>
                        <div ref={chartContainerRef} className="w-full min-h-[380px] relative" />
                        {!signalResult && !loading && (
                            <div className="absolute inset-0 flex items-center justify-center text-zinc-600 italic pointer-events-none">
                                請在左側點選「Run Signal Simulation」執行策略回測
                            </div>
                        )}
                    </div>

                    {/* Price Chart with Trade Markers */}
                    {signalResult?.price_data && (
                        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col">
                            <h3 className="text-zinc-400 text-sm font-medium mb-2 flex items-center justify-between">
                                <span className="flex items-center gap-2">
                                    <Crosshair className="w-4 h-4 text-purple-400" /> Price Chart & Execution Markers (K 線進出場標註)
                                </span>
                                <div className="flex gap-3 text-[10px] font-mono">
                                    <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-emerald-500 rounded-full"></span> BUY/Long</span>
                                    <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-red-500 rounded-full"></span> SHORT</span>
                                    <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-amber-500 rounded-full"></span> Close (TP/SL/Trail)</span>
                                    <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-purple-400 rounded-full"></span> Reverse</span>
                                </div>
                            </h3>
                            <div ref={priceChartRef} className="w-full min-h-[380px]" />
                        </div>
                    )}
                </div>
            </div>

            {/* Trade History */}
            {trades.length > 0 && (
                <div className="mt-8 bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col">
                    <h3 className="text-zinc-400 text-sm font-medium flex justify-between items-center mb-4">
                        <span>Trade History ({trades.length} Trades)</span>
                        <span className="text-[11px] font-mono text-zinc-500">Execution Log</span>
                    </h3>
                    <div className="overflow-auto max-h-[400px]">
                        <table className="w-full text-left border-collapse text-sm text-zinc-300 font-mono">
                            <thead>
                                <tr className="text-zinc-500 border-b border-zinc-800 text-xs uppercase tracking-wider sticky top-0 bg-zinc-900 z-10">
                                    <th className="py-2.5">Time</th>
                                    <th className="py-2.5">Side</th>
                                    <th className="py-2.5 text-right">Price</th>
                                    <th className="py-2.5 text-right">Amount</th>
                                    <th className="py-2.5 text-right">Fee</th>
                                    <th className="py-2.5 text-right">Realized PnL</th>
                                    <th className="py-2.5 text-center">Exit Reason</th>
                                    <th className="py-2.5 text-right">Equity Balance</th>
                                </tr>
                            </thead>
                            <tbody>
                                {trades.map((trade: any, i: number) => {
                                    const pricePrecision = getPricePrecision(trade.price, symbol).precision;
                                    const pnlValue = trade.realized_pnl || 0;
                                    const amtDisplay = trade.amount < 0.0001 ? Number(trade.amount).toFixed(8) : Number(trade.amount).toFixed(4);

                                    const sideStr = trade.side || '';
                                    const isOpen = sideStr.startsWith('open');
                                    const isLong = sideStr.includes('long');
                                    const badgeColor = isOpen
                                        ? (isLong ? 'border-emerald-900 bg-emerald-900/20 text-emerald-400' : 'border-red-900 bg-red-900/20 text-red-400')
                                        : (isLong ? 'border-emerald-900 bg-emerald-900/20 text-emerald-300' : 'border-red-900 bg-red-900/20 text-red-300');
                                    const sideLabel = sideStr.replace('_', ' ').toUpperCase();

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
                                                {new Date(trade.time * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' })}
                                            </td>
                                            <td className="py-2">
                                                <span className={`px-1.5 py-0.5 rounded text-[10px] text-center inline-block uppercase border ${badgeColor}`}>
                                                    {sideLabel}
                                                </span>
                                            </td>
                                            <td className="py-2 text-right text-zinc-100">${Number(trade.price).toFixed(pricePrecision)}</td>
                                            <td className="py-2 text-right text-zinc-400">{amtDisplay}</td>
                                            <td className="py-2 text-right text-zinc-500">${(trade.fee || 0).toFixed(4)}</td>
                                            <td className={`py-2 text-right font-medium ${!isOpen && pnlValue > 0 ? 'text-emerald-400' : !isOpen && pnlValue < 0 ? 'text-red-400' : 'text-zinc-600'}`}>
                                                {!isOpen ? (pnlValue > 0 ? '+' : '') + pnlValue.toFixed(2) : '-'}
                                            </td>
                                            <td className="py-2 text-center">
                                                {reason && <span className={`text-[9px] px-1.5 py-0.5 rounded border ${reasonColors[reason] || 'bg-zinc-800 text-zinc-400 border-zinc-700'}`}>{reason.toUpperCase()}</span>}
                                            </td>
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
    );
}
