import { useState } from 'react';
import { GridParams, previewGrid, startGrid } from '@/lib/api';
import { Play, Calculator, AlertTriangle, CheckCircle } from 'lucide-react';

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
            return ((upper - lower) / count).toFixed(2);
        }
        return '--';
    })();

    return (
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 h-full flex flex-col gap-4">
            <h2 className="text-lg font-bold text-emerald-400 flex items-center gap-2">
                <Calculator className="w-5 h-5" />
                Grid Strategy
            </h2>

            <div className="grid grid-cols-2 gap-4">
                <div className="flex flex-col gap-1">
                    <label className="text-xs text-zinc-500">Lower Price</label>
                    <div className="relative">
                        <input
                            type="number"
                            className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:outline-none focus:border-emerald-500 transition-colors"
                            value={lowerPrice}
                            onChange={(e) => setLowerPrice(e.target.value)}
                            placeholder={(currentPrice * 0.95).toFixed(1)}
                        />
                    </div>
                </div>
                <div className="flex flex-col gap-1">
                    <label className="text-xs text-zinc-500">Upper Price</label>
                    <div className="relative">
                        <input
                            type="number"
                            className="w-full bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:outline-none focus:border-emerald-500 transition-colors"
                            value={upperPrice}
                            onChange={(e) => setUpperPrice(e.target.value)}
                            placeholder={(currentPrice * 1.05).toFixed(1)}
                        />
                    </div>
                </div>
            </div>

            {/* Grid Count (Full Width) */}
            <div className="flex flex-col gap-1">
                <label className="text-xs text-zinc-500">Grid Count</label>
                <div className="flex gap-4">
                    <input
                        type="number"
                        className="flex-1 bg-zinc-950 border border-zinc-700 rounded p-2 text-sm text-white focus:outline-none focus:border-emerald-500 transition-colors"
                        value={gridCount}
                        onChange={(e) => setGridCount(e.target.value)}
                    />
                    <div className="flex items-center px-2 bg-zinc-900/50 rounded border border-zinc-800 min-w-[100px] justify-between">
                        <span className="text-[10px] text-zinc-600 uppercase mr-2">Step</span>
                        <span className="text-emerald-400 text-xs font-mono">{calculatedStep}</span>
                    </div>
                </div>
            </div>

            <div className="flex gap-2 mt-2">
                <button
                    onClick={handlePreview}
                    className="flex-1 bg-zinc-800 hover:bg-zinc-700 text-white rounded py-2 text-sm transition-colors border border-zinc-700"
                >
                    Preview Lines
                </button>
                <button
                    onClick={handleStart}
                    className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded py-2 text-sm font-bold shadow-lg shadow-emerald-900/20 flex items-center justify-center gap-2"
                >
                    <Play className="w-4 h-4" /> Start Bot
                </button>
            </div>

            {/* Logs Area */}
            <div className="flex-1 bg-black/50 rounded p-2 font-mono text-xs overflow-y-auto border border-zinc-800 min-h-[100px]">
                <div className="text-zinc-500 mb-1 border-b border-zinc-800 pb-1 flex items-center gap-2">
                    <AlertTriangle className="w-3 h-3 text-yellow-500" />
                    System Logs (Dry Run)
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
