import { useState, useEffect } from 'react';
import { X, Bell, BellRing, Send, Loader2 } from 'lucide-react';
import { NotificationConfig, getNotificationConfig, updateNotificationConfig, sendTestNotification } from '@/lib/api';

interface NotificationSettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
}

const AVAILABLE_SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'HYPE/USDT', 'CC/USDT'];

export function NotificationSettingsModal({ isOpen, onClose }: NotificationSettingsModalProps) {
    const [config, setConfig] = useState<NotificationConfig | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [isTesting, setIsTesting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (isOpen) {
            fetchConfig();
        }
    }, [isOpen]);

    const fetchConfig = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const data = await getNotificationConfig();
            setConfig(data);
        } catch (err: any) {
            setError(err.message || 'Failed to load config');
        } finally {
            setIsLoading(false);
        }
    };

    const handleSave = async () => {
        if (!config) return;
        setIsSaving(true);
        setError(null);
        try {
            await updateNotificationConfig(config);
            onClose();
        } catch (err: any) {
            setError(err.message || 'Failed to save config');
        } finally {
            setIsSaving(false);
        }
    };

    const handleTestNotification = async () => {
        setIsTesting(true);
        setError(null);
        try {
            await sendTestNotification();
            alert('Test notification sent successfully!');
        } catch (err: any) {
            setError(err.message || 'Failed to send test notification');
        } finally {
            setIsTesting(false);
        }
    };

    const toggleSymbol = (symbol: string) => {
        if (!config) return;
        const newSymbols = config.monitored_symbols.includes(symbol)
            ? config.monitored_symbols.filter(s => s !== symbol)
            : [...config.monitored_symbols, symbol];
        setConfig({ ...config, monitored_symbols: newSymbols });
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl w-full max-w-md shadow-2xl flex flex-col">
                <div className="px-6 py-4 border-b border-zinc-800 flex items-center justify-between bg-zinc-900/90 rounded-t-2xl">
                    <div className="flex items-center gap-3">
                        <BellRing className="w-5 h-5 text-blue-400" />
                        <h2 className="text-lg font-bold text-zinc-100">Notification Settings</h2>
                    </div>
                    <button onClick={onClose} className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors">
                        <X className="w-5 h-5" />
                    </button>
                </div>
                
                <div className="p-6 space-y-6">
                    {error && (
                        <div className="p-3 rounded-lg bg-red-900/30 border border-red-900/50 text-red-400 text-sm">
                            {error}
                        </div>
                    )}

                    {isLoading || !config ? (
                        <div className="flex justify-center py-8">
                            <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
                        </div>
                    ) : (
                        <>
                            <div className="flex items-center justify-between">
                                <div>
                                    <h3 className="text-sm font-medium text-zinc-200">Enable Telegram Alerts</h3>
                                    <p className="text-xs text-zinc-500 mt-1">Receive signals directly via Telegram.</p>
                                </div>
                                <label className="relative inline-flex items-center cursor-pointer">
                                    <input 
                                        type="checkbox" 
                                        className="sr-only peer"
                                        checked={config.enabled}
                                        onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
                                    />
                                    <div className="w-11 h-6 bg-zinc-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                                </label>
                            </div>

                            <div className="pt-4 border-t border-zinc-800">
                                <h3 className="text-sm font-medium text-zinc-200 mb-3">Monitored Symbols</h3>
                                <div className="grid grid-cols-2 gap-3">
                                    {AVAILABLE_SYMBOLS.map(sym => (
                                        <label key={sym} className="flex items-center gap-3 cursor-pointer p-2 rounded-lg hover:bg-zinc-800/50 transition-colors">
                                            <input 
                                                type="checkbox" 
                                                checked={config.monitored_symbols.includes(sym)}
                                                onChange={() => toggleSymbol(sym)}
                                                className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-900"
                                            />
                                            <span className="text-sm font-medium text-zinc-300">{sym}</span>
                                        </label>
                                    ))}
                                </div>
                                <p className="text-xs text-zinc-500 mt-3">
                                    The signal scanner runs every 15 minutes (:00, :15, :30, :45) for selected symbols.
                                </p>
                            </div>

                            <div className="pt-4 border-t border-zinc-800">
                                <button
                                    onClick={handleTestNotification}
                                    disabled={isTesting}
                                    className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors text-sm font-medium disabled:opacity-50"
                                >
                                    {isTesting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                                    Send Test Notification
                                </button>
                            </div>
                        </>
                    )}
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
                        disabled={isSaving || isLoading || !config}
                        className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors shadow-lg shadow-blue-900/20 disabled:opacity-50"
                    >
                        {isSaving && <Loader2 className="w-4 h-4 animate-spin" />}
                        Save Settings
                    </button>
                </div>
            </div>
        </div>
    );
}
