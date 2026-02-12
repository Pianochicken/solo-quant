import { TrendingUp, TrendingDown, Activity, Layers } from 'lucide-react';
import { InfoTooltip } from './InfoTooltip';
import { IndicatorData } from '@/lib/api';

interface SentimentPanelProps {
    indicators: IndicatorData | null;
}

export default function SentimentPanel({ indicators }: SentimentPanelProps) {
    if (!indicators) return null;

    const { lsur_z_score, liquidity_walls } = indicators;

    // Z-Score Interpretation
    // > 2: Crowded Long (Bearish Signal) -> Red
    // < -2: Crowded Short (Bullish Signal) -> Green
    // -2 to 2: Neutral -> Gray
    let scoreColor = "text-zinc-400";
    let scoreText = "Neutral";

    if (lsur_z_score > 2) {
        scoreColor = "text-red-400";
        scoreText = "Overcrowded Longs (Bearish)";
    } else if (lsur_z_score < -2) {
        scoreColor = "text-emerald-400";
        scoreText = "Overcrowded Shorts (Bullish)";
    }

    return (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 h-full flex flex-col">
            <h3 className="text-zinc-400 text-xs font-bold uppercase tracking-wider mb-4 flex items-center gap-2">
                <Activity className="w-4 h-4" />
                CoinKarma Sentinel
            </h3>

            <div className="grid grid-cols-2 gap-4 flex-1">
                {/* L/S Z-Score Card */}
                <div className="bg-zinc-950/50 rounded-lg p-3 border border-zinc-800 flex flex-col justify-between">
                    <div>
                        <div className="text-xs text-zinc-500 mb-1 flex items-center">LSUR Z-Score<InfoTooltip text="多空比率 Z 分數：衡量市場多空倉位是否過度擁擠。Z > 2 表示多頭擁擠（看跌），Z < -2 表示空頭擁擠（看漲）" /></div>
                        <div className={`text-2xl font-mono font-bold ${scoreColor}`}>
                            {lsur_z_score.toFixed(2)}
                        </div>
                    </div>
                    <div className={`text-xs mt-2 ${scoreColor} font-medium`}>
                        {scoreText}
                    </div>
                </div>

                {/* Liquidity Walls Summary */}
                <div className="bg-zinc-950/50 rounded-lg p-3 border border-zinc-800 flex flex-col">
                    <div className="text-xs text-zinc-500 mb-2 flex items-center gap-1">
                        <Layers className="w-3 h-3" /> Liquidity Walls<InfoTooltip text="流動性牆：顯示訂單簿中最密集的掛單價位。Resist = 上方賣壓集中區（阻力），Support = 下方買盤集中區（支撐）" />
                    </div>
                    <div className="space-y-1 text-xs font-mono">
                        {/* Show nearest Bid/Ask wall */}
                        <div className="flex justify-between items-center text-red-300">
                            <span>Resist</span>
                            <span>{liquidity_walls?.ask_walls?.[0]?.price.toFixed(0) || '-'}</span>
                        </div>
                        <div className="flex justify-between items-center text-emerald-300">
                            <span>Support</span>
                            <span>{liquidity_walls?.bid_walls?.[0]?.price.toFixed(0) || '-'}</span>
                        </div>
                    </div>
                    <div className="mt-auto text-[10px] text-zinc-600 pt-2">
                        Top 5 levels aggregated
                    </div>
                </div>
            </div>
        </div>
    );
}
