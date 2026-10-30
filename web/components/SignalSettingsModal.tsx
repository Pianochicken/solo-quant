import { useState, useEffect } from 'react';
import { X, Settings2 } from 'lucide-react';
import { SignalConfig } from '@/lib/api';

interface SignalSettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
    currentConfig: SignalConfig;
    onSave: (config: SignalConfig) => void;
}

export function SignalSettingsModal({ isOpen, onClose, currentConfig, onSave }: SignalSettingsModalProps) {
    const [config, setConfig] = useState<SignalConfig>(currentConfig);

    useEffect(() => {
        if (isOpen) {
            setConfig(currentConfig);
        }
    }, [isOpen, currentConfig]);

    if (!isOpen) return null;

    const handleSave = () => {
        onSave(config);
        onClose();
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl w-full max-w-md shadow-2xl flex flex-col">
                <div className="px-6 py-4 border-b border-zinc-800 flex items-center justify-between bg-zinc-900/90 rounded-t-2xl">
                    <div className="flex items-center gap-3">
                        <Settings2 className="w-5 h-5 text-purple-400" />
                        <h2 className="text-lg font-bold text-zinc-100">Trade Signal Settings</h2>
                    </div>
                    <button onClick={onClose} className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors">
                        <X className="w-5 h-5" />
                    </button>
                </div>
                
                <div className="p-6 space-y-6">
                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-2">Ranging Regime Threshold 震盪行情門檻</label>
                        <div className="flex items-center gap-4">
                            <input 
                                type="range" min="1" max="10" 
                                value={config.rangingThreshold} 
                                onChange={(e) => setConfig({...config, rangingThreshold: parseInt(e.target.value)})}
                                className="w-full accent-purple-500" 
                            />
                            <span className="text-xl font-mono text-amber-400 font-bold w-8 text-right">{config.rangingThreshold}/10</span>
                        </div>
                        <p className="text-xs text-zinc-500 mt-1">震盪行情觸發訊號的最低指標數量。</p>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-2">Trending Regime Threshold 趨勢行情門檻</label>
                        <div className="flex items-center gap-4">
                            <input 
                                type="range" min="1" max="10" 
                                value={config.trendingThreshold} 
                                onChange={(e) => setConfig({...config, trendingThreshold: parseInt(e.target.value)})}
                                className="w-full accent-emerald-500" 
                            />
                            <span className="text-xl font-mono text-emerald-400 font-bold w-8 text-right">{config.trendingThreshold}/10</span>
                        </div>
                        <p className="text-xs text-zinc-500 mt-1">趨勢行情觸發訊號的最低指標數量。</p>
                    </div>

                    <div className="pt-2 border-t border-zinc-800">
                        <label className="flex items-center gap-3 cursor-pointer">
                            <input 
                                type="checkbox" 
                                checked={config.enableProtection}
                                onChange={(e) => setConfig({...config, enableProtection: e.target.checked})}
                                className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-purple-500 focus:ring-purple-500 focus:ring-offset-zinc-900"
                            />
                            <div>
                                <span className="block text-sm font-medium text-zinc-300">Enable Directional Protection 勿空/勿多保護</span>
                                <span className="block text-xs text-zinc-500">上漲趨勢阻擋看跌訊號，下跌趨勢阻擋看漲訊號。</span>
                            </div>
                        </label>
                    </div>

                    <div className="pt-4 border-t border-zinc-800">
                        <label className="flex gap-3 cursor-pointer items-start">
                            <div className="mt-1">
                                <input 
                                    type="checkbox" 
                                    checked={config.useDynamicProfiles}
                                    onChange={(e) => setConfig({...config, useDynamicProfiles: e.target.checked})}
                                    className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-purple-500 focus:ring-purple-500 focus:ring-offset-zinc-900"
                                />
                            </div>
                            <div>
                                <span className="block text-sm font-medium text-zinc-300">Enable Dynamic Asset Profiles 動態幣種指標參數</span>
                                <span className="block text-xs text-zinc-500 mt-1 leading-relaxed">
                                    開啟後，AI 會自動根據當前選擇幣種（如 BTC, SOL, HYPE...）的特性與波幅來動態放寬或收緊 RSI、資金費率等觸發門檻，顯著降低高波動山寨幣的假訊號。
                                </span>
                            </div>
                        </label>
                    </div>

                    <div className="pt-4 border-t border-zinc-800">
                        <label className="flex gap-3 cursor-pointer items-start">
                            <div className="mt-1">
                                <input 
                                    type="checkbox" 
                                    checked={config.enableMtfFilter ?? false}
                                    onChange={(e) => setConfig({...config, enableMtfFilter: e.target.checked})}
                                    className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-indigo-500 focus:ring-indigo-500 focus:ring-offset-zinc-900"
                                />
                            </div>
                            <div>
                                <div className="flex items-center gap-2">
                                    <span className="block text-sm font-medium text-zinc-300">Enable MTF Confirmation 多時間框架共振</span>
                                    <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-indigo-900/50 text-indigo-300 border border-indigo-800/50">Layer 3</span>
                                </div>
                                <span className="block text-xs text-zinc-500 mt-1 leading-relaxed">
                                    開啟後，1h 回歸信號僅在 4h 趨勢方向一致或中性時發出。若 4h 為強力下跌趨勢，買入信號將被過濾；反之亦然。有效降低逆勢假訊號（僅限 1h/15m 時間框架）。
                                </span>
                            </div>
                        </label>
                    </div>

                    {/* Minimum Confluence Score Selector */}
                    <div className="pt-4 border-t border-zinc-800">
                        <label className="block text-sm font-medium text-zinc-300 mb-1">
                            Min Confluence Score 最低共振分數門檻
                        </label>
                        <select
                            value={config.minScore ?? 0}
                            onChange={(e) => setConfig({ ...config, minScore: parseFloat(e.target.value) })}
                            className="w-full bg-zinc-950 border border-zinc-700 rounded-lg p-2 text-sm text-zinc-200 outline-none focus:border-purple-500 transition-colors font-mono"
                        >
                            <option value="0">Default (依週期預設門檻)</option>
                            <option value="3.5">3.5 分以上</option>
                            <option value="4.0">4.0 分以上 (嚴格共振)</option>
                            <option value="4.5">4.5 分以上 (極高確定性)</option>
                            <option value="5.0">5.0 分以上 (頂級拐點)</option>
                        </select>
                        <p className="text-xs text-zinc-500 mt-1">
                            過濾低於指定綜合分數的訊號，僅在圖表上保留高確定性之共振或突破點。
                        </p>
                    </div>

                    {/* Signal Archetype Checkboxes */}
                    <div className="pt-4 border-t border-zinc-800 space-y-2">
                        <label className="block text-sm font-medium text-zinc-300">
                            Signal Archetypes 允許顯示之訊號類型
                        </label>
                        {(() => {
                            const raw = (config.signalTypes ?? 'structure,reversion,breakout').toLowerCase();
                            const types = raw.split(',').map(s => s.trim());
                            const toggleType = (t: string) => {
                                const exists = types.includes(t);
                                const next = exists ? types.filter(x => x !== t) : [...types, t];
                                setConfig({ ...config, signalTypes: next.join(',') });
                            };

                            return (
                                <div className="space-y-2 pt-1">
                                    <label className="flex items-center gap-3 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={types.includes('structure')}
                                            onChange={() => toggleType('structure')}
                                            className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-purple-600 focus:ring-purple-500"
                                        />
                                        <div>
                                            <span className="text-xs font-medium text-zinc-300">⚡ 結構拐點 (Structure: CAP / DIV)</span>
                                            <span className="block text-[11px] text-zinc-500">爆倉拋售底 (Capitulation) 與 CVD 背離點 (Divergence)。</span>
                                        </div>
                                    </label>

                                    <label className="flex items-center gap-3 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={types.includes('reversion')}
                                            onChange={() => toggleType('reversion')}
                                            className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-purple-600 focus:ring-purple-500"
                                        />
                                        <div>
                                            <span className="text-xs font-medium text-zinc-300">🔁 均線回踩與回歸 (Reversion / Pullback)</span>
                                            <span className="block text-[11px] text-zinc-500">EMA50 乖離拉回、震盪超買超賣與多指標共振。</span>
                                        </div>
                                    </label>

                                    <label className="flex items-center gap-3 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={types.includes('breakout')}
                                            onChange={() => toggleType('breakout')}
                                            className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-purple-600 focus:ring-purple-500"
                                        />
                                        <div>
                                            <span className="text-xs font-medium text-zinc-300">🚀 順勢突破 (Breakout / Breakdown)</span>
                                            <span className="block text-[11px] text-zinc-500">唐奇安通道突破、MACD 動能放大與突破趨勢單。</span>
                                        </div>
                                    </label>
                                </div>
                            );
                        })()}
                    </div>
                </div>

                <div className="p-4 border-t border-zinc-800 flex justify-end gap-3 rounded-b-2xl bg-zinc-950/50">
                    <button 
                        onClick={onClose}
                        className="px-4 py-2 text-sm font-medium text-zinc-300 bg-zinc-800 hover:bg-zinc-700 rounded-lg transition-colors"
                    >
                        Cancel
                    </button>
                    <button 
                        onClick={handleSave}
                        className="px-4 py-2 text-sm font-medium text-white bg-purple-600 hover:bg-purple-500 rounded-lg transition-colors shadow-lg shadow-purple-900/20"
                    >
                        Apply & Reload 確定
                    </button>
                </div>
            </div>
        </div>
    );
}
