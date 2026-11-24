import { TrendingUp, TrendingDown, Activity, Layers, Shield } from 'lucide-react';
import { InfoTooltip } from './InfoTooltip';
import { IndicatorData } from '@/lib/api';
import { getThresholds } from '@/lib/thresholds';

interface SentimentPanelProps {
    indicators: IndicatorData | null;
    timeframe?: string;
    enableProtection?: boolean;
}

export default function SentimentPanel({ indicators, timeframe = '1h', enableProtection = false }: SentimentPanelProps) {
    if (!indicators) return null;

    const { lsur_z_score } = indicators;
    const T = getThresholds(timeframe);

    // Helper: convert L/S ratio to Long percentage (0-100)
    const toLongPct = (ratio: number) => (ratio / (1 + ratio)) * 100;

    // Retail Global Account Ratio (fallback to latest lsur_history item if needed)
    const latestLsHist = indicators.lsur_history?.length
        ? indicators.lsur_history[indicators.lsur_history.length - 1]?.value
        : null;
    const retailRatio =
        typeof indicators.lsur_ratio === 'number' && indicators.lsur_ratio > 0
            ? indicators.lsur_ratio
            : typeof latestLsHist === 'number' && latestLsHist > 0
                ? latestLsHist
                : null;
    const retailLongPct = retailRatio !== null ? toLongPct(retailRatio) : null;

    // Top 20% Trader Position Ratio (Binance Whale OI Bias)
    const whaleRatio =
        typeof indicators.top_ls_ratio === 'number' && indicators.top_ls_ratio > 0
            ? indicators.top_ls_ratio
            : null;
    const whaleZ = typeof indicators.top_ls_z_score === 'number' ? indicators.top_ls_z_score : null;
    const whaleLongPct = whaleRatio !== null ? toLongPct(whaleRatio) : null;

    let whaleColor = 'text-zinc-400';
    let whaleText = '多空均衡';
    if (whaleRatio !== null) {
        if (whaleRatio >= 1.15) {
            whaleColor = 'text-sky-400';
            whaleText = '大戶偏多';
        } else if (whaleRatio <= 0.85) {
            whaleColor = 'text-rose-400';
            whaleText = '大戶偏空';
        }
    }

    // Z-Score Interpretation (using timeframe-adaptive thresholds)
    let scoreColor = "text-zinc-400";
    let scoreText = "中性常態";

    if (lsur_z_score > T.z_bear) {
        scoreColor = "text-red-400";
        scoreText = "相對偏多擁擠 (反向看跌)";
    } else if (lsur_z_score < T.z_bull) {
        scoreColor = "text-emerald-400";
        scoreText = "相對偏空擁擠 (反向看漲)";
    }

    // Smart Money Divergence (Whale Position Long% vs Retail Account Long%)
    const divergenceDiff =
        whaleLongPct !== null && retailLongPct !== null ? whaleLongPct - retailLongPct : null;

    // Context-aware Z-score window label, dynamic badge styling, and live verdict for tooltips
    const tfWindowMap: Record<string, string> = {
        '15m': '近 90 根 15m ≈ 22.5 小時',
        '1h': '近 90 小時 ≈ 3.75 天',
        '4h': '近 90 根 4h = 15 天',
        '1d': '近 90 日（初期依累積約 30 天）',
    };
    const windowLabel = tfWindowMap[timeframe] || '近 90 期';

    let whaleZBadgeClass = 'text-zinc-400 bg-zinc-900 border-zinc-800';
    if (whaleZ !== null) {
        if (whaleZ <= -2.0) whaleZBadgeClass = 'text-rose-300 bg-rose-950/50 border-rose-500/40';
        else if (whaleZ <= -1.0) whaleZBadgeClass = 'text-amber-300 bg-amber-950/40 border-amber-500/40';
        else if (whaleZ >= 2.0) whaleZBadgeClass = 'text-emerald-300 bg-emerald-950/50 border-emerald-500/40';
        else if (whaleZ >= 1.0) whaleZBadgeClass = 'text-sky-300 bg-sky-950/40 border-sky-500/40';
    }

    let whaleLiveSummary = '尚無足夠大戶持倉資料可進行當下解讀。';
    if (whaleRatio !== null && whaleZ !== null && whaleLongPct !== null) {
        const invPhrase = whaleRatio >= 1.15 ? '大戶底倉偏多' : (whaleRatio <= 0.85 ? '大戶底倉偏空' : '大戶底倉均衡');
        let zPhrase = '且位於近期正常波動區間內';
        if (whaleZ <= -2.0) zPhrase = '且遠低於近期常態（極端減多／加空警戒）';
        else if (whaleZ <= -1.0) zPhrase = '但明顯低於近期均值，顯示大戶正在獲利減多或加空避險';
        else if (whaleZ >= 2.0) zPhrase = '且遠高於近期常態（極端積極加多）';
        else if (whaleZ >= 1.0) zPhrase = '且明顯高於近期均值，顯示大戶近期積極加倉做多';
        whaleLiveSummary = `💡 目前解讀（比值 ${whaleRatio.toFixed(2)}｜多 ${whaleLongPct.toFixed(1)}%｜Z ${whaleZ >= 0 ? '+' : ''}${whaleZ.toFixed(2)}）：\n${invPhrase}，${zPhrase}。`;
    }

    let retailZBadgeClass = 'text-zinc-400 bg-zinc-900 border-zinc-800';
    if (lsur_z_score > T.z_bear) {
        retailZBadgeClass = 'text-red-300 bg-red-950/50 border-red-500/40';
    } else if (lsur_z_score < T.z_bull) {
        retailZBadgeClass = 'text-emerald-300 bg-emerald-950/50 border-emerald-500/40';
    }

    let retailLiveSummary = '尚無足夠散戶多空比資料可進行當下解讀。';
    if (retailRatio !== null && retailLongPct !== null) {
        let retailVerdict = '散戶多空情緒位於近期正常波動區間，尚未觸發極端反向擠壓訊號。';
        if (lsur_z_score < T.z_bull) {
            retailVerdict = '散戶多頭佔比雖仍可能 > 50%，但已顯著低於近 90 期散戶常態偏多基準，籌碼洗盤偏乾淨，已觸發反向看漲情緒加分。';
        } else if (lsur_z_score > T.z_bear) {
            retailVerdict = '散戶做多情緒顯著高於近 90 期均值，多頭過於擁擠，已觸發反向看跌警訊（防向下洗盤）。';
        }
        retailLiveSummary = `💡 目前解讀（比值 ${retailRatio.toFixed(2)}｜多 ${retailLongPct.toFixed(1)}%｜Z ${lsur_z_score >= 0 ? '+' : ''}${lsur_z_score.toFixed(2)}）：\n${retailVerdict}`;
    }

    // EMA Trend
    const trendState = indicators.trend_state || 'neutral';
    let trendColor = 'text-zinc-400';
    let trendLabel = 'Neutral';
    let TrendIcon = Activity;
    if (trendState === 'uptrend') {
        trendColor = 'text-emerald-400';
        trendLabel = 'Uptrend';
        TrendIcon = TrendingUp;
    } else if (trendState === 'downtrend') {
        trendColor = 'text-red-400';
        trendLabel = 'Downtrend';
        TrendIcon = TrendingDown;
    }

    // Market Regime
    const regime = (indicators as any).market_regime || { regime: 'ranging', direction: 'neutral', adx: 0, no_short: false, no_long: false };
    let regimeColor = 'text-amber-400';
    let regimeLabel = '🔄 Ranging';
    let regimeBgClass = 'border-amber-900/30';

    if (regime.regime === 'trending') {
        if (regime.direction === 'up') {
            regimeColor = 'text-emerald-400';
            regimeLabel = '📈 Trending ↑';
            regimeBgClass = 'border-emerald-900/30';
        } else {
            regimeColor = 'text-red-400';
            regimeLabel = '📉 Trending ↓';
            regimeBgClass = 'border-red-900/30';
        }
    }

    return (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 h-full flex flex-col">
            <h3 className="text-zinc-400 text-xs font-bold uppercase tracking-wider mb-4 flex items-center gap-2">
                <Activity className="w-4 h-4" />
                Sentiment Sentinel
            </h3>

            <div className="grid grid-cols-2 gap-4 flex-1">
                {/* Market Regime Card — NEW: spans full width */}
                <div className={`bg-zinc-950/50 rounded-lg p-3 border ${regimeBgClass} flex flex-col col-span-2`}>
                    <div className="flex items-center justify-between">
                        <div>
                            <div className="text-xs text-zinc-500 mb-1 flex items-center">Market Regime<InfoTooltip text="行情體制判斷：使用 ADX、布林帶寬度、CVD 斜率三因子投票決定目前是「震盪行情」還是「趨勢行情」。匯合門檻與保護機制會根據您的「訊號設定」自動切換。" /></div>
                            <div className={`text-xl font-mono font-bold ${regimeColor}`}>
                                {regimeLabel}
                            </div>
                        </div>
                        {indicators.mtf_4h_regime && (
                            <div className="flex flex-col items-end">
                                <span className="text-[10px] text-zinc-500 font-mono mb-1">MTF (4H)</span>
                                {(() => {
                                    const mtf = indicators.mtf_4h_regime;
                                    if (mtf.regime === 'trending') {
                                        if (mtf.direction === 'up') {
                                            return (
                                                <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-emerald-950/70 border border-emerald-500/40 text-emerald-400 flex items-center gap-1 shadow-sm">
                                                    4H: Trending ↑
                                                </span>
                                            );
                                        } else {
                                            return (
                                                <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-red-950/70 border border-red-500/40 text-red-400 flex items-center gap-1 shadow-sm">
                                                    4H: Trending ↓
                                                </span>
                                            );
                                        }
                                    } else {
                                        return (
                                            <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-amber-950/70 border border-amber-500/40 text-amber-400 flex items-center gap-1 shadow-sm">
                                                4H: Ranging
                                            </span>
                                        );
                                    }
                                })()}
                            </div>
                        )}
                    </div>

                    <div className="grid grid-cols-3 gap-2 mt-3 pt-3 border-t border-zinc-800/50">
                        <div className="text-center group relative">
                            <div className="text-[10px] text-zinc-600 mb-1 flex justify-center items-center">
                                ADX
                                <InfoTooltip text="Average Directional Index (平均趨向指數)。衡量趨勢的「強度」而非方向。數值大於 25 代表市場具有強烈的單邊趨勢動能；小於 25 則為盤整。" />
                            </div>
                            <div className={`text-sm font-mono font-bold ${regime.adx > 25 ? 'text-purple-400' : 'text-zinc-500'}`}>
                                {regime.adx?.toFixed(1) || '—'}
                            </div>
                        </div>
                        
                        <div className="text-center group relative">
                            <div className="text-[10px] text-zinc-600 mb-1 flex justify-center items-center">
                                BB Width
                                <InfoTooltip text="Bollinger Bands Width (布林帶寬度擴張率)。計算當前布林帶寬度是否大於過去 20 根 K 線平均寬度的 1.5 倍。用來捕捉波動率從收斂轉為爆發的起漲點。" />
                            </div>
                            <div className={`text-sm font-mono font-bold ${regime.bb_width_ratio > 1.5 ? 'text-purple-400' : 'text-zinc-500'}`}>
                                {regime.bb_width_ratio?.toFixed(2) || '—'}x
                            </div>
                        </div>

                        <div className="text-center group relative">
                            <div className="text-[10px] text-zinc-600 mb-1 flex justify-center items-center">
                                CVD 斜率
                                <InfoTooltip text="Cumulative Volume Delta (累積成交量差) 的坡度連續性。計算「過去 10 根 K 線」內，主力資金是否持續同向淨流入/淨流出。一致性大於 70% 視為強烈趨勢資金。" />
                            </div>
                            <div className={`text-sm font-mono font-bold ${regime.cvd_consistency >= 0.7 ? 'text-purple-400' : 'text-zinc-500'}`}>
                                {regime.cvd_consistency !== undefined ? `${(regime.cvd_consistency * 100).toFixed(0)}%` : '—'}
                            </div>
                        </div>
                    </div>

                    {enableProtection && (regime.no_short || regime.no_long) && (
                        <div className="mt-2 flex gap-2">
                            {regime.no_short && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-950/50 border border-emerald-800/30 text-emerald-400 text-[10px] font-medium">
                                    <Shield className="w-3 h-3" /> 勿空保護
                                </span>
                            )}
                            {regime.no_long && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-red-950/50 border border-red-800/30 text-red-400 text-[10px] font-medium">
                                    <Shield className="w-3 h-3" /> 勿多保護
                                </span>
                            )}
                        </div>
                    )}
                </div>

                {/* Market Pulse Card — NEW */}
                {(() => {
                    let pulseValue: number | null = null;
                    if (typeof (indicators as any).composite_score === 'number') {
                        pulseValue = (indicators as any).composite_score;
                    }
                    let pColor = 'text-zinc-400';
                    let pBg = 'border-zinc-800';
                    let pText = 'Neutral';
                    if (pulseValue !== null) {
                        if (pulseValue <= 20) { pColor = 'text-emerald-400'; pBg = 'border-emerald-900/30'; pText = 'Extreme Bullish (Oversold)'; }
                        else if (pulseValue < 40) { pColor = 'text-emerald-300'; pText = 'Bullish'; }
                        else if (pulseValue > 80) { pColor = 'text-red-400'; pBg = 'border-red-900/30'; pText = 'Extreme Bearish (Overbought)'; }
                        else if (pulseValue > 60) { pColor = 'text-red-300'; pText = 'Bearish'; }
                    }

                    return (
                        <div className={`bg-zinc-950/50 rounded-lg p-3 border ${pBg} flex flex-col col-span-2`}>
                            <div className="flex items-center justify-between">
                                <div>
                                    <div className="text-xs text-zinc-500 mb-1 flex items-center">Market Pulse<InfoTooltip text="綜合情緒指數 (0-100)：加權合併了核心指標的狀態。分數越低代表群眾過度看跌(超賣)，是買入良機；分數越高代表群眾過度看漲(超買)，是危險信號。" /></div>
                                    <div className={`text-xl font-mono font-bold ${pColor}`}>
                                        {pulseValue !== null ? pulseValue.toFixed(1) : '—'}
                                    </div>
                                </div>
                                <div className="text-right flex flex-col justify-end">
                                    <div className={`text-xs font-medium ${pColor}`}>
                                        {pText}
                                    </div>
                                </div>
                            </div>

                            {/* Simple Progress Bar */}
                            {pulseValue !== null && (
                                <div className="relative w-full mt-3">
                                    <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden flex">
                                        <div className="h-full bg-emerald-500" style={{ width: '20%' }}></div>
                                        <div className="h-full bg-zinc-600" style={{ width: '60%' }}></div>
                                        <div className="h-full bg-red-500" style={{ width: '20%' }}></div>
                                    </div>
                                    {/* Indicator Pip */}
                                    <div className="absolute top-1/2 -translate-y-1/2 h-3 w-1 bg-white rounded-sm shadow-sm" style={{ left: `calc(${Math.min(Math.max(pulseValue, 0), 100)}% - 2px)` }}></div>
                                </div>
                            )}
                        </div>
                    );
                })()}

                {/* Long / Short Positioning Card: Top Traders vs Retail Accounts */}
                <div className="bg-zinc-950/50 rounded-lg p-3 border border-zinc-800 flex flex-col gap-3 col-span-2">
                    <div className="text-[11px] font-bold uppercase tracking-wider text-zinc-400 flex items-center justify-between">
                        <span className="flex items-center">
                            多空籌碼對比 Positioning
                            <InfoTooltip text="拆解未平倉量 (OI) 背後的多空資金偏向：上方為「前 20% 頂級大戶持倉量比 (真金白銀順向參考)」，下方為「全市場帳戶數多空比與 Z 分數 (散戶擁擠度反向指標)」。" />
                        </span>
                    </div>

                    {/* Section 1: Binance Top 20% Trader Position Ratio */}
                    <div className="space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-xs text-sky-400 font-medium flex items-center shrink-0">
                                🐋 大戶持倉多空比
                                <InfoTooltip
                                    width={330}
                                    text={"【🐋 大戶持倉多空比（絕對底倉）】\n• 資料來源：Binance 官方合約統計 API（topLongShortPositionRatio），由交易所內部篩選「保證金餘額前 20%」頂級交易員，依實際多空總倉位規模加權（總多倉 ÷ 總空倉），非算人頭。\n• 比值解讀：> 1.0 代表大戶多倉大於空倉（例：1.66 ≈ 多 62.4% / 空 37.6%）。\n• 注意：主流幣長期具結構性偏多基準（常見 1.5～2.3），務必搭配右側 Z 分數觀察邊際增減。"}
                                />
                            </span>
                            <div className="flex items-center gap-1.5 font-mono shrink-0">
                                <span className={`text-base font-bold ${whaleColor}`}>
                                    {whaleRatio !== null ? whaleRatio.toFixed(2) : '—'}
                                </span>
                                {whaleZ !== null && whaleRatio !== null && (
                                    <span className="inline-flex items-center">
                                        <span className={`text-[10px] px-1.5 py-0.5 rounded border ${whaleZBadgeClass}`}>
                                            Z {whaleZ >= 0 ? '+' : ''}{whaleZ.toFixed(2)}
                                        </span>
                                        <InfoTooltip
                                            width={340}
                                            className="ml-0.5"
                                            iconClassName="h-3 w-3 text-zinc-500 hover:text-sky-400 cursor-help transition-colors"
                                            text={`【大戶持倉 Z 分數（相對常態變化）】\n公式：(當前比值 − 近 90 期均值) ÷ 標準差（${windowLabel}）\n• -1.0 < Z < +1.0：正常波動區間\n• Z ≤ -1.0：顯著低於均值（大戶減多／加空降溫）\n• Z ≥ +1.0：顯著高於均值（大戶積極加多）\n• |Z| ≥ 2.0：極端籌碼偏移（波段轉折前夕）\n\n${whaleLiveSummary}`}
                                        />
                                    </span>
                                )}
                                <span className={`text-[11px] font-sans font-medium ${whaleColor}`}>
                                    {whaleText}
                                </span>
                            </div>
                        </div>

                        {whaleLongPct !== null && (
                            <div className="space-y-1">
                                <div className="flex justify-between text-[10px] font-mono">
                                    <span className="text-emerald-400">多 {whaleLongPct.toFixed(1)}%</span>
                                    <span className="text-rose-400">空 {(100 - whaleLongPct).toFixed(1)}%</span>
                                </div>
                                <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden flex" aria-hidden="true">
                                    <div className="h-full bg-emerald-500 transition-all duration-300" style={{ width: `${whaleLongPct}%` }}></div>
                                    <div className="h-full bg-rose-500 transition-all duration-300" style={{ width: `${100 - whaleLongPct}%` }}></div>
                                </div>
                            </div>
                        )}
                    </div>

                    <div className="border-t border-zinc-800/60" />

                    {/* Section 2: Global Account LSUR & Z-Score */}
                    <div className="space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-xs text-fuchsia-400 font-medium flex items-center shrink-0">
                                👥 散戶帳戶多空比 (LSUR)
                                <InfoTooltip
                                    width={320}
                                    text={`【👥 散戶帳戶多空比 (LSUR)】\n• 資料來源：Binance ＋ OKX 全市場帳戶數多空比（1 人 1 票，反映散戶擁擠度，屬反向情緒指標）。\n• 90 期滾動 Z 分數（門檻隨週期調整）：\n  - Z > ${T.z_bear}：散戶多頭過度擁擠（偏空警訊／防向下洗盤）\n  - Z < ${T.z_bull}：散戶空頭過度擁擠（偏多訊號／易生軋空）\n• 搭配上方「大戶持倉比」可辨識大戶與散戶的籌碼方向背離。`}
                                />
                            </span>
                            <div className="flex items-center gap-1.5 font-mono shrink-0">
                                <span className="text-sm font-bold text-zinc-200">
                                    {retailRatio !== null ? retailRatio.toFixed(2) : '—'}
                                </span>
                                <span className="inline-flex items-center">
                                    <span className={`text-xs font-bold px-1.5 py-0.5 rounded border ${retailZBadgeClass}`}>
                                        Z {lsur_z_score >= 0 ? '+' : ''}{lsur_z_score.toFixed(2)}
                                    </span>
                                    <InfoTooltip
                                        width={340}
                                        className="ml-0.5"
                                        iconClassName="h-3 w-3 text-zinc-500 hover:text-fuchsia-400 cursor-help transition-colors"
                                        text={`【散戶 LSUR 90 期 Z 分數（反向情緒指標）】\n公式：(當前比值 − 近 90 期均值) ÷ 標準差（${windowLabel}）\n• 方向與大戶相反：散戶天然偏愛做多（常態 65%～75%），即使多 > 50%，只要比平常明顯減少（Z 偏負），仍屬相對偏空／洗盤充分。\n• 當前 ${timeframe} 門檻：Z ≤ ${T.z_bull} 觸發反向看漲（易軋空）；Z ≥ ${T.z_bear} 觸發反向看跌（易洗盤）。\n• 訊號權重：直接參與主圖買賣箭頭評分（第 1 號指標，趨勢中具鈍化過濾）及 Market Pulse（15%）。\n\n${retailLiveSummary}`}
                                    />
                                </span>
                            </div>
                        </div>

                        {retailLongPct !== null && (
                            <div className="space-y-1">
                                <div className="flex justify-between text-[10px] font-mono">
                                    <span className="text-emerald-400">多 {retailLongPct.toFixed(1)}%</span>
                                    <span className={`${scoreColor} font-sans text-[10px] font-medium`}>{scoreText}</span>
                                    <span className="text-rose-400">空 {(100 - retailLongPct).toFixed(1)}%</span>
                                </div>
                                <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden flex" aria-hidden="true">
                                    <div className="h-full bg-emerald-500/80 transition-all duration-300" style={{ width: `${retailLongPct}%` }}></div>
                                    <div className="h-full bg-rose-500/80 transition-all duration-300" style={{ width: `${100 - retailLongPct}%` }}></div>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Section 3: Smart Money Divergence Footer */}
                    {divergenceDiff !== null && (() => {
                        const divTooltipText = "【聰明錢分歧判定（大戶 vs 散戶）】\n公式：大戶多倉佔比 % − 散戶多頭帳戶佔比 %\n• ≥ +5%（🐋 聰明錢偏多分歧）：大戶做多比例明顯高於散戶，常見於主力吸籌或逼空前夕。\n• ≤ -5%（⚠️ 散戶偏多分歧）：散戶過度樂觀抄底、大戶相對保守或加空，須提防洗盤派發。\n• -5% ～ +5%（⚖️ 結構同步）：兩者方向一致，留意 OI 與資金費率是否過熱。";
                        if (divergenceDiff >= 5) {
                            return (
                                <div className="pt-1">
                                    <div className="px-2.5 py-1.5 rounded-md bg-emerald-950/40 border border-emerald-500/30 text-emerald-300 text-[11px] font-medium flex items-center justify-between gap-2">
                                        <span>🐋 聰明錢偏多分歧（大戶多倉佔比高出散戶 +{divergenceDiff.toFixed(1)}%）</span>
                                        <InfoTooltip width={320} className="ml-0 shrink-0" iconClassName="h-3.5 w-3.5 text-emerald-400/70 hover:text-emerald-200 cursor-help transition-colors" text={divTooltipText} />
                                    </div>
                                </div>
                            );
                        }
                        if (divergenceDiff <= -5) {
                            return (
                                <div className="pt-1">
                                    <div className="px-2.5 py-1.5 rounded-md bg-red-950/40 border border-red-500/30 text-red-300 text-[11px] font-medium flex items-center justify-between gap-2">
                                        <span>⚠️ 散戶偏多分歧（大戶多倉佔比低於散戶 {divergenceDiff.toFixed(1)}%）</span>
                                        <InfoTooltip width={320} className="ml-0 shrink-0" iconClassName="h-3.5 w-3.5 text-red-400/70 hover:text-red-200 cursor-help transition-colors" text={divTooltipText} />
                                    </div>
                                </div>
                            );
                        }
                        return (
                            <div className="pt-1">
                                <div className="px-2.5 py-1.5 rounded-md bg-zinc-900/80 border border-zinc-800 text-zinc-400 text-[11px] font-medium flex items-center justify-between gap-2">
                                    <span>⚖️ 大戶與散戶多空結構同步（差距 {divergenceDiff >= 0 ? '+' : ''}{divergenceDiff.toFixed(1)}%）</span>
                                    <InfoTooltip width={320} className="ml-0 shrink-0" iconClassName="h-3.5 w-3.5 text-zinc-500 hover:text-zinc-300 cursor-help transition-colors" text={divTooltipText} />
                                </div>
                            </div>
                        );
                    })()}
                </div>

                {/* EMA Trend Card */}
                <div className="bg-zinc-950/50 rounded-lg p-3 border border-zinc-800 flex flex-col justify-between">
                    <div>
                        <div className="text-xs text-zinc-500 mb-1 flex items-center">EMA Trend<InfoTooltip text={`EMA 趨勢過濾器：使用 EMA50 和 EMA200 判斷趨勢方向。當前週期的 EMA 乖離率門檻為 ±${T.ema_pct}%，偏離過大時會觸發訊號`} /></div>
                        <div className={`text-xl font-mono font-bold ${trendColor} flex items-center gap-1.5`}>
                            <TrendIcon className="w-5 h-5 shrink-0" />
                            <span>{trendLabel}</span>
                        </div>
                    </div>
                    <div className="text-[10px] text-zinc-600 mt-2">
                        EMA50 / EMA200 Filter
                    </div>
                </div>

                {/* RSI Card */}
                <div className="bg-zinc-950/50 rounded-lg p-3 border border-zinc-800 flex flex-col justify-between">
                    <div>
                        <div className="text-xs text-zinc-500 mb-1 flex items-center">RSI (14)<InfoTooltip text={`相對強弱指數：衡量價格動能的振盪指標。RSI > ${T.rsi_bear} = 超買（可能回落），RSI < ${T.rsi_bull} = 超賣（可能反彈）。門檻會隨週期動態調整`} /></div>
                        {(() => {
                            const rsiValue = indicators.rsi_history?.[indicators.rsi_history.length - 1]?.value;
                            const rsiColor = rsiValue != null ? (rsiValue > T.rsi_bear ? 'text-red-400' : rsiValue < T.rsi_bull ? 'text-emerald-400' : 'text-zinc-400') : 'text-zinc-600';
                            const rsiStatus = rsiValue != null ? (rsiValue > T.rsi_bear ? 'Overbought' : rsiValue < T.rsi_bull ? 'Oversold' : 'Neutral') : '—';
                            return (
                                <>
                                    <div className={`text-2xl font-mono font-bold ${rsiColor}`}>
                                        {rsiValue != null ? rsiValue.toFixed(1) : '—'}
                                    </div>
                                    <div className={`text-xs mt-2 ${rsiColor} font-medium`}>
                                        {rsiStatus}
                                    </div>
                                </>
                            );
                        })()}
                    </div>
                </div>

                {/* OI Percentile Card */}
                <div className="bg-zinc-950/50 rounded-lg p-3 border border-zinc-800 flex flex-col col-span-2">
                    <div className="text-xs text-zinc-500 mb-2 flex items-center gap-1">
                        <Layers className="w-3 h-3" /> OI Percentile<InfoTooltip text="未平倉量百分位：當前 OI 在過去 90 天中的排名。> 70% 表示槓桿處於高位，市場波動加劇。< 30% 表示槓桿偏低，波動可能較小" />
                    </div>
                    {(() => {
                        const oiPct = indicators.oi_percentile;
                        const oiColor = oiPct != null ? (oiPct >= 70 ? 'text-orange-400' : oiPct <= 30 ? 'text-blue-400' : 'text-zinc-400') : 'text-zinc-600';
                        const oiStatus = oiPct != null ? (oiPct >= 70 ? 'High Leverage' : oiPct <= 30 ? 'Low Leverage' : 'Normal') : '—';
                        return (
                            <>
                                <div className={`text-2xl font-mono font-bold ${oiColor}`}>
                                    {oiPct != null ? `${oiPct.toFixed(0)}%` : '—'}
                                </div>
                                <div className={`text-xs mt-1 ${oiColor} font-medium`}>
                                    {oiStatus}
                                </div>
                            </>
                        );
                    })()}
                </div>

                {/* Global Liquidity Data Flow Card */}
                {indicators.exchange_breakdown && (() => {
                    const { binance = 0, okx = 0, total } = indicators.exchange_breakdown;
                    const safeTotal = total || (binance + okx) || 0;
                    const binancePct = safeTotal > 0 ? (binance / safeTotal) * 100 : 0;
                    const okxPct = safeTotal > 0 ? (okx / safeTotal) * 100 : 0;

                    return (
                        <div className="bg-zinc-950/50 rounded-lg p-3 border border-zinc-800 flex flex-col col-span-2 mt-2">
                            <div className="flex justify-between items-center mb-2">
                                <div className="text-xs text-zinc-500 flex items-center gap-1">
                                    <Layers className="w-3 h-3" /> Liquidity Sources<InfoTooltip text="全球流動性比例：顯示當前指標的數據來源組成。Binance 與 OKX 的數據皆「僅」來自其各自的「USDT 本位永續合約 (USDT-Margined Perpetuals)」，不包含 USDC 或幣本位。這代表最核心的零售與機構投機資金流向。" />
                                </div>
                                <div className="text-xs font-mono font-medium text-zinc-400">
                                    Total: ${(safeTotal / 1e9).toFixed(2)}B
                                </div>
                            </div>
                            
                            <div className="space-y-2">
                                <div className="flex justify-between text-[10px] uppercase font-bold tracking-wider mb-1">
                                    <span className="text-yellow-500">
                                        Binance {binance === 0 ? '—' : `${binancePct.toFixed(1)}%`}
                                    </span>
                                    <span className="text-blue-500">
                                        OKX {okx === 0 ? '—' : `${okxPct.toFixed(1)}%`}
                                    </span>
                                </div>
                                <div className="relative w-full h-2 bg-zinc-800 rounded-full overflow-hidden flex">
                                    {binancePct > 0 && (
                                        <div className="h-full bg-yellow-500 transition-all duration-300" style={{ width: `${binancePct}%` }}></div>
                                    )}
                                    {okxPct > 0 && (
                                        <div className="h-full bg-blue-500 transition-all duration-300" style={{ width: `${okxPct}%` }}></div>
                                    )}
                                </div>
                            </div>
                        </div>
                    );
                })()}
            </div>
        </div>
    );
}
