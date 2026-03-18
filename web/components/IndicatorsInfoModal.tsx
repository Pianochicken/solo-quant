import { X, Zap } from 'lucide-react';

interface IndicatorsInfoModalProps {
    isOpen: boolean;
    onClose: () => void;
}

export function IndicatorsInfoModal({ isOpen, onClose }: IndicatorsInfoModalProps) {
    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl w-full max-w-4xl max-h-[85vh] overflow-y-auto shadow-2xl custom-scrollbar flex flex-col">
                {/* Header */}
                <div className="sticky top-0 z-10 bg-zinc-900/90 backdrop-blur-md border-b border-zinc-800 px-6 py-4 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <Zap className="w-5 h-5 text-amber-400" />
                        <h2 className="text-lg font-bold text-zinc-100">Multi-Indicator Confluence Signal (v5)</h2>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                {/* Content */}
                <div className="p-6 space-y-6">
                    <div className="space-y-3">
                        <p className="text-sm text-zinc-400 leading-relaxed">
                            此系統升級為「兩階段狀態機（State Machine）」獵殺流動性邏輯。為了解決「共線性誤判」（避免只因為價格急跌就累積滿分），目前的指標被歸類為「價格(Price)」、「情緒(Sentiment)」與「動能(Momentum)」三個維度。
                        </p>
                        <div className="bg-amber-500/10 border border-amber-500/20 p-3 rounded-lg text-sm text-amber-200 leading-relaxed">
                            <span className="font-bold flex items-center gap-2 mb-1"><Zap className="w-4 h-4" /> 觸發條件升級：Setup $\rightarrow$ Trigger</span>
                            要觸發 ⚡ 訊號不再要求所有條件在「同一時間點」發生，而是模擬真人交易員的觀察過程：<br/>
                            1. <strong>醞釀期 (Setup)：</strong> 當「情緒」或「動能」維度出現極端分數時，系統進入「備戰狀態」並開始 3 根 K 線的倒數。<br/>
                            2. <strong>觸發期 (Trigger)：</strong> 在倒數期間內，如果「價格」維度出現反應（如：插針收回、RSI超賣轉折），使得<strong>總分與維度數量（須 $\ge 2$ 個維度）達標</strong>，才會正式開火亮出 ⚡ 訊號。
                        </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

                        {/* 1. LSUR Z-Score */}
                        <div className="bg-zinc-950/50 border border-zinc-800 rounded-lg p-4 flex flex-col h-full relative">
                            <div className="flex items-center gap-2 mb-2">
                                <span className="absolute top-4 right-4 text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">Sentiment</span>
                                <span className="flex items-center justify-center w-6 h-6 rounded bg-purple-500/20 text-purple-400 text-xs font-bold shrink-0">1</span>
                                <h3 className="font-semibold text-zinc-200">LSUR Z-Score (多空比 Z 分數)</h3>
                            </div>
                            <p className="text-xs text-zinc-400 mb-3 flex-grow">衡量散戶多空部位的極端程度（情緒反指標）。Z 值越高代表散戶越看多，越容易引發向下洗盤。</p>
                            <div className="overflow-x-auto rounded border border-zinc-800">
                                <table className="w-full text-[10px] text-left">
                                    <thead className="bg-zinc-800/50 text-zinc-400 uppercase">
                                        <tr><th className="px-2 py-1">週期</th><th className="px-2 py-1 text-emerald-400">看漲門檻 (過度做空)</th><th className="px-2 py-1 text-red-400">看跌門檻 (過度做多)</th></tr>
                                    </thead>
                                    <tbody className="divide-y divide-zinc-800/50 text-zinc-300">
                                        <tr><td className="px-2 py-1">15m</td><td className="px-2 py-1">Z ≤ -1.5</td><td className="px-2 py-1">Z ≥ 1.5</td></tr>
                                        <tr><td className="px-2 py-1">1h</td><td className="px-2 py-1">Z ≤ -1.2</td><td className="px-2 py-1">Z ≥ 1.2</td></tr>
                                        <tr><td className="px-2 py-1">4h</td><td className="px-2 py-1">Z ≤ -1.0</td><td className="px-2 py-1">Z ≥ 1.0</td></tr>
                                        <tr><td className="px-2 py-1">1d</td><td className="px-2 py-1">Z ≤ -0.8</td><td className="px-2 py-1">Z ≥ 0.8</td></tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        {/* 2. OI × Price */}
                        <div className="bg-zinc-950/50 border border-zinc-800 rounded-lg p-4 flex flex-col h-full relative">
                            <div className="flex items-center gap-2 mb-2">
                                <span className="absolute top-4 right-4 text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">Momentum</span>
                                <span className="flex items-center justify-center w-6 h-6 rounded bg-blue-500/20 text-blue-400 text-xs font-bold shrink-0">2</span>
                                <h3 className="font-semibold text-zinc-200">OI × Price (未平倉量與價格背離)</h3>
                            </div>
                            <p className="text-xs text-zinc-400 mb-3 flex-grow">結合槓桿燃料(OI)與價格走勢，判斷真假突破與見底訊號。</p>
                            <div className="overflow-x-auto rounded border border-zinc-800 mb-3">
                                <table className="w-full text-[10px] text-left">
                                    <thead className="bg-zinc-800/50 text-zinc-400 uppercase">
                                        <tr><th className="px-2 py-1">週期</th><th className="px-2 py-1">價格變動門檻</th><th className="px-2 py-1">對比範圍</th></tr>
                                    </thead>
                                    <tbody className="divide-y divide-zinc-800/50 text-zinc-300">
                                        <tr><td className="px-2 py-1">15m</td><td className="px-2 py-1">±0.3%</td><td className="px-2 py-1">近 1 小時 (4根)</td></tr>
                                        <tr><td className="px-2 py-1">1h</td><td className="px-2 py-1">±0.5%</td><td className="px-2 py-1">近 3 小時 (3根)</td></tr>
                                        <tr><td className="px-2 py-1">4h</td><td className="px-2 py-1">±1.0%</td><td className="px-2 py-1">近 12 小時 (3根)</td></tr>
                                        <tr><td className="px-2 py-1">1d</td><td className="px-2 py-1">±1.5%</td><td className="px-2 py-1">近 3 天 (3根)</td></tr>
                                    </tbody>
                                </table>
                            </div>
                            <div className="space-y-1 text-[11px] mt-auto">
                                <div className="text-emerald-400"><span className="font-bold">激進看漲：</span> 價格↑ 且 OI↑ (增量做多) 或是 價格↓ 且 OI大降 5% (爆倉見底)</div>
                                <div className="text-red-400"><span className="font-bold">激進看跌：</span> 價格↓ 且 OI↑ (增量做空) 或是 價格↑ 且 OI大降 5% (軋空到頂)</div>
                            </div>
                        </div>

                        {/* 3. Funding Rate */}
                        <div className="bg-zinc-950/50 border border-zinc-800 rounded-lg p-4 flex flex-col h-full relative">
                            <div className="flex items-center gap-2 mb-2">
                                <span className="absolute top-4 right-4 text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">Sentiment</span>
                                <span className="flex items-center justify-center w-6 h-6 rounded bg-emerald-500/20 text-emerald-400 text-xs font-bold shrink-0">3</span>
                                <h3 className="font-semibold text-zinc-200">OI-Weighted Funding Rate (資金費率)</h3>
                            </div>
                            <p className="text-xs text-zinc-400 mb-3 flex-grow">永續合約多空雙方支付的利息。當費率極端時，代表該方向擁擠。v5 系統加入 OI 變化：若費率極端且 OI 持續增加，視為高危險訊號（加滿分）；若 OI 開始下降（代表平倉），則危險訊號減半。</p>
                            <div className="overflow-x-auto rounded border border-zinc-800">
                                <table className="w-full text-[10px] text-left">
                                    <thead className="bg-zinc-800/50 text-zinc-400 uppercase">
                                        <tr><th className="px-2 py-1">週期</th><th className="px-2 py-1 text-emerald-400">看漲門檻 (過度看空)</th><th className="px-2 py-1 text-red-400">看跌門檻 (過度看多)</th></tr>
                                    </thead>
                                    <tbody className="divide-y divide-zinc-800/50 text-zinc-300">
                                        <tr><td className="px-2 py-1">15m</td><td className="px-2 py-1">FR &lt; -0.005%</td><td className="px-2 py-1">FR &gt; 0.010%</td></tr>
                                        <tr><td className="px-2 py-1">1h</td><td className="px-2 py-1">FR &lt; -0.003%</td><td className="px-2 py-1">FR &gt; 0.008%</td></tr>
                                        <tr><td className="px-2 py-1">4h</td><td className="px-2 py-1">FR &lt; -0.002%</td><td className="px-2 py-1">FR &gt; 0.006%</td></tr>
                                        <tr><td className="px-2 py-1">1d</td><td className="px-2 py-1">FR &lt; -0.001%</td><td className="px-2 py-1">FR &gt; 0.005%</td></tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        {/* 4. RSI */}
                        <div className="bg-zinc-950/50 border border-zinc-800 rounded-lg p-4 flex flex-col h-full relative">
                            <div className="flex items-center gap-2 mb-2">
                                <span className="absolute top-4 right-4 text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">Price</span>
                                <span className="flex items-center justify-center w-6 h-6 rounded bg-indigo-500/20 text-indigo-400 text-xs font-bold shrink-0">4</span>
                                <h3 className="font-semibold text-zinc-200">RSI (相對強弱指數)</h3>
                            </div>
                            <p className="text-xs text-zinc-400 mb-3 flex-grow">衡量價格動能的經典振盪指標。越長的週期，RSI 到達極端的難度越高，因此門檻隨之放寬。</p>
                            <div className="overflow-x-auto rounded border border-zinc-800">
                                <table className="w-full text-[10px] text-left">
                                    <thead className="bg-zinc-800/50 text-zinc-400 uppercase">
                                        <tr><th className="px-2 py-1">週期</th><th className="px-2 py-1 text-emerald-400">看漲門檻 (超賣區)</th><th className="px-2 py-1 text-red-400">看跌門檻 (超買區)</th></tr>
                                    </thead>
                                    <tbody className="divide-y divide-zinc-800/50 text-zinc-300">
                                        <tr><td className="px-2 py-1">15m</td><td className="px-2 py-1">RSI &lt; 25</td><td className="px-2 py-1">RSI &gt; 75</td></tr>
                                        <tr><td className="px-2 py-1">1h</td><td className="px-2 py-1">RSI &lt; 30</td><td className="px-2 py-1">RSI &gt; 70</td></tr>
                                        <tr><td className="px-2 py-1">4h</td><td className="px-2 py-1">RSI &lt; 35</td><td className="px-2 py-1">RSI &gt; 65</td></tr>
                                        <tr><td className="px-2 py-1">1d</td><td className="px-2 py-1">RSI &lt; 40</td><td className="px-2 py-1">RSI &gt; 60</td></tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        {/* 5. EMA Zone */}
                        <div className="bg-zinc-950/50 border border-zinc-800 rounded-lg p-4 flex flex-col h-full relative">
                            <div className="flex items-center gap-2 mb-2">
                                <span className="absolute top-4 right-4 text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">Price</span>
                                <span className="flex items-center justify-center w-6 h-6 rounded bg-orange-500/20 text-orange-400 text-xs font-bold shrink-0">5</span>
                                <h3 className="font-semibold text-zinc-200">EMA Zone (均線乖離率)</h3>
                            </div>
                            <p className="text-xs text-zinc-400 mb-3 flex-grow">價格距離 EMA 50 (指數移動平均線) 的偏離程度。物極必反，偏離過大會回歸均值。</p>
                            <div className="overflow-x-auto rounded border border-zinc-800">
                                <table className="w-full text-[10px] text-left">
                                    <thead className="bg-zinc-800/50 text-zinc-400 uppercase">
                                        <tr><th className="px-2 py-1">週期</th><th className="px-2 py-1 text-emerald-400">看漲 (向下重度崩跌)</th><th className="px-2 py-1 text-red-400">看跌 (向上過度拉升)</th></tr>
                                    </thead>
                                    <tbody className="divide-y divide-zinc-800/50 text-zinc-300">
                                        <tr><td className="px-2 py-1">15m</td><td className="px-2 py-1">偏離 &lt; -0.5%</td><td className="px-2 py-1">偏離 &gt; 0.5%</td></tr>
                                        <tr><td className="px-2 py-1">1h</td><td className="px-2 py-1">偏離 &lt; -1.0%</td><td className="px-2 py-1">偏離 &gt; 1.0%</td></tr>
                                        <tr><td className="px-2 py-1">4h</td><td className="px-2 py-1">偏離 &lt; -2.0%</td><td className="px-2 py-1">偏離 &gt; 2.0%</td></tr>
                                        <tr><td className="px-2 py-1">1d</td><td className="px-2 py-1">偏離 &lt; -3.0%</td><td className="px-2 py-1">偏離 &gt; 3.0%</td></tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        {/* 6. Bollinger %B */}
                        <div className="bg-zinc-950/50 border border-zinc-800 rounded-lg p-4 flex flex-col h-full relative">
                            <div className="flex items-center gap-2 mb-2">
                                <span className="absolute top-4 right-4 text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">Price</span>
                                <span className="flex items-center justify-center w-6 h-6 rounded bg-pink-500/20 text-pink-400 text-xs font-bold shrink-0">6</span>
                                <h3 className="font-semibold text-zinc-200">Bollinger %B (布林通道振幅)</h3>
                            </div>
                            <p className="text-xs text-zinc-400 mb-3 flex-grow">衡量價格相對於布林通道上下軌的位置。%B &gt; 1 代表突破上軌，%B &lt; 0 代表跌破下軌。</p>
                            <div className="overflow-x-auto rounded border border-zinc-800">
                                <table className="w-full text-[10px] text-left">
                                    <thead className="bg-zinc-800/50 text-zinc-400 uppercase">
                                        <tr><th className="px-2 py-1">週期</th><th className="px-2 py-1 text-emerald-400">看漲門檻 (跌破下軌)</th><th className="px-2 py-1 text-red-400">看跌門檻 (突破上軌)</th></tr>
                                    </thead>
                                    <tbody className="divide-y divide-zinc-800/50 text-zinc-300">
                                        <tr><td className="px-2 py-1">15m</td><td className="px-2 py-1">%B ≤ 0.10</td><td className="px-2 py-1">%B ≥ 0.90</td></tr>
                                        <tr><td className="px-2 py-1">1h</td><td className="px-2 py-1">%B ≤ 0.08</td><td className="px-2 py-1">%B ≥ 0.92</td></tr>
                                        <tr><td className="px-2 py-1">4h / 1d</td><td className="px-2 py-1">%B ≤ 0.05</td><td className="px-2 py-1">%B ≥ 0.95</td></tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        {/* 7. CVD */}
                        <div className="bg-zinc-950/50 border border-zinc-800 rounded-lg p-4 flex flex-col h-full md:col-span-2 relative">
                            <div className="flex items-center gap-2 mb-2">
                                <span className="absolute top-4 right-4 text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">Momentum</span>
                                <span className="flex items-center justify-center w-6 h-6 rounded bg-yellow-500/20 text-yellow-500 text-xs font-bold shrink-0">7</span>
                                <h3 className="font-semibold text-zinc-200">CVD (累積成交量差值)</h3>
                            </div>
                            <p className="text-xs text-zinc-400 mb-2">追蹤主動買入（Taker Buy）與主動賣出（Taker Sell）的淨差額，反映真實資金流向。此訊號沒有固定門檻，而是動態計算當前 K 棒的 CVD 減去過去 N 根 K 棒的 CVD，若為正則加 1 分(看漲)，若為負則加 1 分(看跌)。(N = 3 根)</p>
                        </div>

                        {/* 8. Market Regime Detection */}
                        <div className="bg-zinc-950/50 border border-emerald-900/40 rounded-lg p-4 flex flex-col h-full md:col-span-2">
                            <div className="flex items-center gap-2 mb-2">
                                <span className="flex items-center justify-center w-6 h-6 rounded bg-emerald-500/20 text-emerald-400 text-xs font-bold shrink-0">8</span>
                                <h3 className="font-semibold text-emerald-400">Market Regime (行情體制判斷)</h3>
                            </div>
                            <p className="text-xs text-zinc-400 mb-2">使用三個大數據因子投票，動態判斷目前的市場狀態並調整訊號過濾機制：</p>
                            <ul className="text-xs text-zinc-400 space-y-1 ml-4 list-disc mb-3">
                                <li><strong className="text-zinc-200">ADX 動向指數：</strong>ADX &gt; 25 代表趨勢形成。</li>
                                <li><strong className="text-zinc-200">布林帶寬度擴張：</strong>寬度大於過去均值 1.5 倍代表波動放大。</li>
                                <li><strong className="text-zinc-200">CVD 斜率方向：</strong>CVD 近期走勢 70% 的時間朝向同一方向。</li>
                            </ul>
                            <div className="bg-zinc-900/50 p-2 rounded text-[11px] text-zinc-300">
                                <span className="text-emerald-400 font-bold">機制：</span>若 3 者中有 2 者成立，判定為「趨勢行情」，會自動套用您設定的趨勢門檻；您也可以隨時調整是否啟用逆勢保護（勿空/勿多）。
                            </div>
                        </div>

                    </div>

                    <div className="bg-zinc-950/50 border border-zinc-800 rounded-lg p-4 flex flex-col h-full md:col-span-2 relative">
                        <div className="flex items-center gap-2 mb-2">
                            <span className="flex items-center justify-center w-6 h-6 rounded bg-zinc-500/20 text-zinc-400 text-xs font-bold shrink-0">9</span>
                            <h3 className="font-semibold text-zinc-200">Market Pulse (綜合情緒指數)</h3>
                        </div>
                        <p className="text-xs text-zinc-400 mb-2">將上述 7 種核心指標的狀態，加權計算為 0 ~ 100 的綜合指數。這不是買賣觸發訊號，而是用來直觀感受市場整體的溫度：</p>

                        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 mb-3 mt-1 text-[11px]">
                            <div className="bg-zinc-900/50 p-2 rounded border border-zinc-800"><span className="text-zinc-500">LSUR 多空比:</span> <strong className="text-zinc-200">15%</strong></div>
                            <div className="bg-zinc-900/50 p-2 rounded border border-zinc-800"><span className="text-zinc-500">CVD 資金動能:</span> <strong className="text-zinc-200">20%</strong></div>
                            <div className="bg-zinc-900/50 p-2 rounded border border-zinc-800"><span className="text-zinc-500">RSI 相對強弱:</span> <strong className="text-zinc-200">10%</strong></div>
                            <div className="bg-zinc-900/50 p-2 rounded border border-zinc-800"><span className="text-zinc-500">OI 加權資金費率:</span> <strong className="text-zinc-200">15%</strong></div>
                            <div className="bg-zinc-900/50 p-2 rounded border border-zinc-800"><span className="text-zinc-500">EMA 乖離率:</span> <strong className="text-zinc-200">15%</strong></div>
                            <div className="bg-zinc-900/50 p-2 rounded border border-zinc-800"><span className="text-zinc-500">布林帶 %B:</span> <strong className="text-zinc-200">10%</strong></div>
                            <div className="bg-zinc-900/50 p-2 rounded border border-zinc-800"><span className="text-zinc-500">OI 籌碼背離:</span> <strong className="text-zinc-200">15%</strong></div>
                        </div>

                        <ul className="text-xs text-zinc-400 space-y-1 ml-4 list-disc">
                            <li><strong className="text-emerald-400">0 - 20 (極度看漲)：</strong>市場極度超賣、空頭擁擠、極度負值，隨時可能發生強勁的反彈。</li>
                            <li><strong className="text-zinc-400">40 - 60 (中性)：</strong>市場情緒穩定，多空力量均衡。</li>
                            <li><strong className="text-red-400">80 - 100 (極度看跌)：</strong>市場極度超買、多頭擁擠、極度正值，隨時可能發生崩跌。</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    );
}
