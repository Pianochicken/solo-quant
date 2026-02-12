export interface IndicatorData {
    liquidity_walls: {
        bid_walls: { price: number; volume: number }[];
        ask_walls: { price: number; volume: number }[];
    };
    lsur_z_score: number;
    lsur_history: { time: number; value: number } | null;
    cvd_history: { time: number; value: number }[];
    open_interest: { time: number; value: number }[];
}

export interface MarketData {
    symbol: string;
    data: {
        price: {
            time: number;
            open: number;
            high: number;
            low: number;
            close: number;
            volume: number;
        }[];
        funding: {
            time: number;
            value: number;
        }[];
    };
    indicators: IndicatorData;
}

const API_BASE = 'http://127.0.0.1:8000';

export async function getMarketData(symbol: string, timeframe: string = '1h', limit: number = 100): Promise<MarketData> {
    // Convert slash to dash for URL safety if needed.
    // Our FastAPI backend expects the symbol in the path.
    // We replace slash with dash just to be safe in URL path, but we need to ensure backend handles it.
    // Actually, sending 'BTC/USDT' in path component is tricky. let's encode it or replace.
    // The previous code replaced it with dash.
    const safeSymbol = symbol.replace('/', '-');

    try {
        const res = await fetch(`${API_BASE}/market/${safeSymbol}?timeframe=${timeframe}&limit=${limit}`);
        if (!res.ok) throw new Error('Failed to fetch market data');
        return res.json();
    } catch (error) {
        console.error(error);
        throw error;
    }
}

// --- Quant / Grid API ---

export interface GridParams {
    symbol: string;
    lower_price: number;
    upper_price: number;
    grid_count: number;
    investment: number;
}

export interface GridPreview {
    grid_lines: number[];
    current_price: number;
    simulated_orders: any[];
}

export async function previewGrid(params: GridParams): Promise<GridPreview> {
    const res = await fetch(`${API_BASE}/quant/grid/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
    });
    if (!res.ok) throw new Error('Preview Failed');
    return res.json();
}

export async function startGrid(params: GridParams) {
    const res = await fetch(`${API_BASE}/quant/grid/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
    });
    if (!res.ok) throw new Error('Start Failed');
    return res.json();
}

export interface BacktestParams {
    symbol: string;
    lower_price: number;
    upper_price: number;
    grid_count: number;
    investment: number;
    duration_days: number;
}

export interface BacktestResult {
    metrics: {
        initial_balance: number;
        final_balance: number;
        pnl: number;
        pnl_percent: number;
        total_trades: number;
    };
    equity_curve: { time: number; value: number }[];
    trades: any[];
}

export async function runBacktest(params: BacktestParams): Promise<BacktestResult> {
    const res = await fetch(`${API_BASE}/quant/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
    });
    if (!res.ok) throw new Error('Backtest Failed');
    return res.json();
}
export interface SmartGridParams {
    symbol: string;
    current_price: number;
    lower_price: number;
    upper_price: number;
    grid_count: number;
    sentiment_score: number;
    signal: string;
}

export async function getSmartGridParams(symbol: string): Promise<SmartGridParams> {
    const res = await fetch(`${API_BASE}/quant/smart-params/${symbol.replace('/', '-')}`);
    if (!res.ok) throw new Error('Smart Params Failed');
    return res.json();
}
