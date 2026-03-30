import { useState } from 'react';
import { GridParams, previewGrid, startGrid, getSmartGridParams } from '@/lib/api';
import { Play, Calculator, AlertTriangle, CheckCircle, Brain, RefreshCw, Activity } from 'lucide-react';
import { getPricePrecision } from '@/lib/utils';

interface GridPanelProps {
    symbol: string;
    currentPrice: number;
    onPreview: (lines: number[]) => void;
    onOrders: (orders: any[]) => void;
}

export const GridPanel = ({ symbol, currentPrice, onPreview, onOrders }: GridPanelProps) => {
    const [lowerPrice, setLowerPrice] = useState<string>('');
    const [upperPrice, setUpperPrice] = useState<string>('');
    const [gridCount, setGridCount] = useState<string>('10');
    const [investment, setInvestment] = useState<string>('1000');
    const [status, setStatus] = useState<string>('idle'); // idle, previewing, running
    const [logs, setLogs] = useState<string[]>([]);

    // AI Mode State
    const [isAiMode, setIsAiMode] = useState(false);
    const [aiLoading, setAiLoading] = useState(false);
    const [sentiment, setSentiment] = useState<{ score: number, signal: string } | null>(null);

    const getLower = () => {
        const val = parseFloat(lowerPrice);
        return isNaN(val) ? currentPrice * 0.95 : val;
    };

    const getUpper = () => {
        const val = parseFloat(upperPrice);
        return isNaN(val) ? currentPrice * 1.05 : val;
    };

    const validateInputs = () => {
        const lower = getLower();
        const upper = getUpper();

        if (!lower || !upper) throw new Error("Waiting for price data...");
        if (lower >= upper) throw new Error("Lower price must be less than Upper price.");
        if (!gridCount || parseInt(gridCount) < 2) throw new Error("Grid Count must be at least 2.");
        if (!investment || parseFloat(investment) <= 0) throw new Error("Check Investment amount.");
        return true;
    };

    const fetchSmartParams = async () => {
        setAiLoading(true);
        try {
            const params = await getSmartGridParams(symbol);
            const { precision } = getPricePrecision(currentPrice, symbol);
            setLowerPrice(params.lower_price.toFixed(precision));
            setUpperPrice(params.upper_price.toFixed(precision));
            setGridCount(params.grid_count.toString());
            setSentiment({ score: params.sentiment_score, signal: params.signal });
            setLogs(prev => [`AI: Loaded Smart Params (Sentiment: ${params.sentiment_score.toFixed(2)})`, ...prev]);
        } catch (e: any) {
            setLogs(prev => [`AI Error: ${e.message}`, ...prev]);
        } finally {
            setAiLoading(false);
        }
    };

    const toggleAiMode = () => {
        const newState = !isAiMode;
        setIsAiMode(newState);
        if (newState) {
            fetchSmartParams();
        } else {
            setSentiment(null);
        }
    };

    const handlePreview = async () => {
        try {
            validateInputs();
            const params: GridParams = {
                symbol,
                lower_price: getLower(),
                upper_price: getUpper(),
                grid_count: parseInt(gridCount),
                investment: parseFloat(investment)
            };

            const res = await previewGrid(params);
            onPreview(res.grid_lines);
            setLogs(prev => [`Preview: Generated ${res.grid_lines.length} lines.`, ...prev]);
        } catch (e: any) {
            setLogs(prev => [`Error: ${e.message}`, ...prev]);
        }
    };

    const handleStart = async () => {
        try {
            validateInputs();
            setStatus('running');
            const params: GridParams = {
                symbol,
                lower_price: getLower(),
                upper_price: getUpper(),
                grid_count: parseInt(gridCount),
                investment: parseFloat(investment)
            };

            const res = await startGrid(params);
            setLogs(prev => [`Bot Started (Dry Run). Placed ${res.orders_placed.length} orders.`, ...prev]);
            onOrders(res.orders_placed);
        } catch (e: any) {
            setLogs(prev => [`Error: ${e.message}`, ...prev]);
            setStatus('idle');
        }
    };

    // Calculate Step for display
    const calculatedStep = (() => {
        const lower = getLower();
        const upper = getUpper();
        const count = parseInt(gridCount);
        if (lower && upper && count && count > 0) {
            const { precision } = getPricePrecision(currentPrice, symbol);
            return ((upper - lower) / count).toFixed(precision);
        }
        return '--';
    })();

    return (
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 h-full flex flex-col gap-4 relative overflow-hidden">
            {/* AI Mode Banner */}
            {isAiMode && (
                <div className="absolute top-0 right-0 p-2 opacity-10 pointer-events-none">
                    <Brain className="w-32 h-32 text-emerald-500" />
                </div>
            )}

            <div className="flex justify-between items-center relative z-10">
                <h2 className="text-lg font-bold text-emerald-400 flex items-center gap-2">
                    <Calculator className="w-5 h-5" />
                    Grid Strategy
                </h2>

                <button
                    onClick={toggleAiMode}
                    className={`flex items-center gap-2 px-3 py-1 rounded-full text-xs font-bold transition-all border ${isAiMode
                        ? "bg-purple-900/50 border-purple-500 text-purple-300 shadow-[0_0_15px_rgba(168,85,247,0.3)]"
                        : "bg-zinc-800 border-zinc-700 text-zinc-500 hover:text-zinc-300"
                        }`}
                >
                    <Brain className="w-3 h-3" />
                    AI Smart Mode {isAiMode ? "ON" : "OFF"}
                </button>
            </div>

            {/* Sentiment Badge (Only in AI Mode) */}
            {isAiMode && sentiment && (
                <div className="bg-purple-900/20 border border-purple-800/50 rounded p-2 flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
                    <div className={`w-2 h-2 rounded-full ${Math.abs(sentiment.score) > 2 ? 'bg-red-500 animate-pulse' : 'bg-emerald-500'}`} />
                    <span className="text-xs text-purple-200 font-mono">
                        Sentiment Guard: {Math.abs(sentiment.score) > 2 ? 'ACTIVE (Caution)' : 'Monitoring'}
                    </span>
                    {aiLoading && <RefreshCw className="w-3 h-3 animate-spin text-purple-400 ml-auto" />}
                </div>
            )}

            <div className="grid grid-cols-2 gap-4 relative z-10">
                <div className="flex flex-col gap-1">
                    <label className="text-xs text-zinc-500 flex justify-between">
                        Lower Price
                        {isAiMode && <span className="text-[10px] text-purple-400">Auto-Set</span>}
                    </label>
                    <div className="relative">
                        <input
                            type="number"
                            className={`w-full bg-zinc-950 border rounded p-2 text-sm text-white focus:outline-none transition-colors ${isAiMode ? "border-purple-500/50 focus:border-purple-500" : "border-zinc-700 focus:border-emerald-500"
                                }`}
                            value={lowerPrice}
                            onChange={(e) => setLowerPrice(e.target.value)}
                            placeholder={(currentPrice * 0.95).toFixed(getPricePrecision(currentPrice, symbol).precision)}
                            disabled={isAiMode} // Disable manual input in AI mode
                        />
                    </div>
                </div>
                <div className="flex flex-col gap-1">
                    <label className="text-xs text-zinc-500 flex justify-between">
                        Upper Price
                        {isAiMode && <span className="text-[10px] text-purple-400">Auto-Set</span>}
                    </label>
                    <div className="relative">
                        <input
                            type="number"
                            className={`w-full bg-zinc-950 border rounded p-2 text-sm text-white focus:outline-none transition-colors ${isAiMode ? "border-purple-500/50 focus:border-purple-500" : "border-zinc-700 focus:border-emerald-500"
                                }`}
                            value={upperPrice}
                            onChange={(e) => setUpperPrice(e.target.value)}
                            placeholder={(currentPrice * 1.05).toFixed(getPricePrecision(currentPrice, symbol).precision)}
                            disabled={isAiMode}
                        />
                    </div>
                </div>
            </div>

            {/* Grid Count (Full Width) */}
            <div className="flex flex-col gap-1 relative z-10">
                <label className="text-xs text-zinc-500">Grid Count</label>
                <div className="flex gap-4">
                    <input
                        type="number"
                        className={`flex-1 bg-zinc-950 border rounded p-2 text-sm text-white focus:outline-none transition-colors ${isAiMode ? "border-purple-500/50 focus:border-purple-500" : "border-zinc-700 focus:border-emerald-500"
                            }`}
                        value={gridCount}
                        onChange={(e) => setGridCount(e.target.value)}
                    />
                    <div className="flex items-center px-2 bg-zinc-900/50 rounded border border-zinc-800 min-w-[100px] justify-between">
                        <span className="text-[10px] text-zinc-600 uppercase mr-2">Step</span>
                        <span className="text-emerald-400 text-xs font-mono">{calculatedStep}</span>
                    </div>
                </div>
            </div>

            <div className="flex gap-2 mt-2 relative z-10">
                <button
                    onClick={handlePreview}
                    className="flex-1 bg-zinc-800 hover:bg-zinc-700 text-white rounded py-2 text-sm transition-colors border border-zinc-700"
                >
                    Preview Lines
                </button>
                <button
                    onClick={handleStart}
                    className={`flex-1 text-white rounded py-2 text-sm font-bold shadow-lg flex items-center justify-center gap-2 transition-all ${isAiMode
                        ? "bg-purple-600 hover:bg-purple-700 shadow-purple-900/20"
                        : "bg-emerald-600 hover:bg-emerald-700 shadow-emerald-900/20"
                        }`}
                >
                    <Play className="w-4 h-4" /> {isAiMode ? "Start Smart Grid" : "Start Bot"}
                </button>
            </div>

            {/* Logs Area */}
            <div className="flex-1 bg-black/50 rounded p-2 font-mono text-xs overflow-y-auto border border-zinc-800 min-h-[100px] relative z-10">
                <div className="text-zinc-500 mb-1 border-b border-zinc-800 pb-1 flex items-center gap-2">
                    <Activity className="w-3 h-3 text-yellow-500" />
                    Bot Activity (Dry Run)
                </div>
                {logs.length === 0 && <span className="text-zinc-600 italic">Ready to start...</span>}
                {logs.map((log, i) => (
                    <div key={i} className="mb-1 text-zinc-300 border-l-2 border-zinc-700 pl-2">
                        {log}
                    </div>
                ))}
            </div>
        </div>
    );
};
