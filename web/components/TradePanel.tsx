import { InfoTooltip } from "./InfoTooltip";

export const TradePanel = () => {
    return (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 h-full flex flex-col">
            <h2 className="text-zinc-100 font-semibold mb-6 flex items-center">
                手動下單
                <InfoTooltip text="直接向交易所發送訂單 (策略訊號可覆蓋此操作)" />
            </h2>

            {/* Order Type Tabs */}
            <div className="flex bg-zinc-950 rounded-lg p-1 mb-6">
                <button className="flex-1 py-1 text-sm bg-zinc-800 text-white rounded shadow">限價單 (Limit)</button>
                <button className="flex-1 py-1 text-sm text-zinc-500 hover:text-zinc-300">市價單 (Market)</button>
            </div>

            {/* Inputs */}
            <div className="space-y-4 flex-1">
                <div>
                    <label className="text-xs text-zinc-500 mb-1 block">價格 (USDT)</label>
                    <input type="number" className="w-full bg-zinc-950 border border-zinc-800 text-white p-2 rounded focus:border-emerald-500 outline-none" placeholder="0.00" />
                </div>
                <div>
                    <label className="text-xs text-zinc-500 mb-1 block">數量 (Amount)</label>
                    <input type="number" className="w-full bg-zinc-950 border border-zinc-800 text-white p-2 rounded focus:border-emerald-500 outline-none" placeholder="0.00" />
                </div>

                <div>
                    <label className="text-xs text-zinc-500 mb-1 block flex justify-between">
                        <span>槓桿倍數 (Leverage)</span>
                        <span className="text-zinc-400">10x</span>
                    </label>
                    <input type="range" min="1" max="100" defaultValue="10" className="w-full accent-emerald-500" />
                </div>
            </div>

            {/* Buttons */}
            <div className="grid grid-cols-2 gap-3 mt-6">
                <button className="py-3 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded transiton-colors">
                    買入 / 做多
                </button>
                <button className="py-3 bg-red-600 hover:bg-red-500 text-white font-bold rounded transiton-colors">
                    賣出 / 做空
                </button>
            </div>

            <div className="mt-4 text-center">
                <span className="text-xs text-zinc-600">可用餘額: $1,053.42</span>
            </div>
        </div>
    );
};
