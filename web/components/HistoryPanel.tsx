import { useState, useEffect } from 'react';
import { Clock, CheckCircle, XCircle, AlertCircle } from 'lucide-react';

export interface Order {
    id: string;
    symbol: string;
    side: 'buy' | 'sell';
    price: number;
    amount: number;
    status: 'open' | 'filled' | 'canceled' | 'closed'; // 'closed' for dry run
    time: string;
}

interface HistoryPanelProps {
    orders: Order[];
    onCancel?: (orderId: string) => void;
}

export const HistoryPanel = ({ orders = [], onCancel }: HistoryPanelProps) => {
    const [activeTab, setActiveTab] = useState<'orders' | 'history'>('orders');

    return (
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 flex flex-col h-full min-h-[250px]">
            {/* Tabs */}
            <div className="flex gap-6 border-b border-zinc-800 pb-2 mb-4">
                <button
                    onClick={() => setActiveTab('orders')}
                    className={`text-sm font-medium transition-colors ${activeTab === 'orders' ? 'text-emerald-400' : 'text-zinc-500 hover:text-zinc-300'}`}
                >
                    Open Orders ({orders.filter(o => o.status === 'open').length})
                </button>
                <button
                    onClick={() => setActiveTab('history')}
                    className={`text-sm font-medium transition-colors ${activeTab === 'history' ? 'text-emerald-400' : 'text-zinc-500 hover:text-zinc-300'}`}
                >
                    Trade History
                </button>
            </div>

            {/* Content Table */}
            <div className="flex-1 overflow-auto font-mono text-sm">
                <table className="w-full text-left border-collapse">
                    <thead>
                        <tr className="text-zinc-600 border-b border-zinc-800 text-xs uppercase tracking-wider">
                            <th className="py-2">Time</th>
                            <th className="py-2">Symbol</th>
                            <th className="py-2">Side</th>
                            <th className="py-2">Price</th>
                            <th className="py-2">Amount</th>
                            <th className="py-2">Status</th>
                            <th className="py-2 text-right">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {orders.length === 0 && (
                            <tr>
                                <td colSpan={7} className="py-8 text-center text-zinc-600 italic">
                                    No records found.
                                </td>
                            </tr>
                        )}
                        {orders.filter(o => activeTab === 'orders' ? o.status === 'open' : o.status !== 'open').map(order => (
                            <tr key={order.id} className="border-b border-zinc-900/50 hover:bg-zinc-800/20 transition-colors">
                                <td className="py-2 text-zinc-500">{order.time}</td>
                                <td className="py-2 text-white font-bold">{order.symbol}</td>
                                <td className={`py-2 ${order.side === 'buy' ? 'text-emerald-400' : 'text-red-400'}`}>
                                    {order.side.toUpperCase()}
                                </td>
                                <td className="py-2 text-zinc-300">{order.price.toLocaleString()}</td>
                                <td className="py-2 text-zinc-300">{order.amount}</td>
                                <td className="py-2">
                                    <span className={`px-2 py-0.5 rounded text-[10px] uppercase border ${order.status === 'filled' ? 'border-emerald-900 bg-emerald-900/20 text-emerald-500' :
                                        order.status === 'open' ? 'border-yellow-900 bg-yellow-900/20 text-yellow-500' :
                                            'border-zinc-700 bg-zinc-800 text-zinc-500'
                                        }`}>
                                        {order.status}
                                    </span>
                                </td>
                                <td className="py-2 text-right">
                                    {order.status === 'open' && onCancel && (
                                        <button
                                            onClick={() => onCancel(order.id)}
                                            className="text-zinc-500 hover:text-red-400 transition-colors p-1"
                                            title="Cancel Order"
                                        >
                                            <XCircle className="w-4 h-4" />
                                        </button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
