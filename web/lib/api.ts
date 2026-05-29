export interface IndicatorData {
    lsur_z_score: number;
    lsur_history: { time: number; value: number } | null;
    cvd_history: { time: number; value: number }[];
    open_interest: { time: number; value: number }[];
    oi_percentile: number;
    ema_fast?: { time: number; value: number }[];
    ema_slow?: { time: number; value: number }[];
    trend_state?: 'uptrend' | 'downtrend' | 'neutral';
    rsi_history?: { time: number; value: number }[];
    composite_score?: number;
    composite_score_history?: { time: number; value: number }[];
    market_regime?: any;
    market_regime_history?: any;
    exchange_breakdown?: {
        binance: number;
        okx: number;
        total: number;
    };
    mtf_4h_regime?: {
        regime: string;
        direction: string;
        adx: number;
    } | null;
}

export interface SignalConfig {
    rangingThreshold: number;
    trendingThreshold: number;
    enableProtection: boolean;
    useDynamicProfiles: boolean;
    enableMtfFilter: boolean;  // Layer 3: 4h regime MTF confirmation
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

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

export function getTimezoneOffsetSec(): number {
    const envOffset = process.env.NEXT_PUBLIC_TIMEZONE_OFFSET;
    if (envOffset !== undefined && envOffset !== '') {
        return parseFloat(envOffset) * 3600;
    }
    // Default to browser's local timezone if not explicitly set at build time
    return new Date().getTimezoneOffset() * -60;
}

export function shiftTimes(obj: any, offsetSec: number) {
    if (!obj || typeof obj !== 'object') return;
    if (Array.isArray(obj)) {
        for (let i = 0; i < obj.length; i++) {
            shiftTimes(obj[i], offsetSec);
        }
    } else {
        if ('time' in obj && typeof obj.time === 'number') {
            obj.time += offsetSec;
        }
        for (const key in obj) {
            if (Object.prototype.hasOwnProperty.call(obj, key)) {
                shiftTimes(obj[key], offsetSec);
            }
        }
    }
}

export async function getMarketData(symbol: string, timeframe: string = '1h', limit: number = 100, config?: SignalConfig): Promise<MarketData> {
    const safeSymbol = symbol.replace('/', '-');

    try {
        let url = `${API_BASE}/market/${safeSymbol}?timeframe=${timeframe}&limit=${limit}`;
        if (config) {
            url += `&ranging_threshold=${config.rangingThreshold}&trending_threshold=${config.trendingThreshold}&enable_protection=${config.enableProtection}&use_dynamic_profiles=${config.useDynamicProfiles}&enable_mtf_filter=${config.enableMtfFilter ?? false}`;
        }
        const res = await fetch(url);
        if (!res.ok) throw new Error('Failed to fetch market data');
        
        const data = await res.json();
        const tzOffsetSec = getTimezoneOffsetSec();
        if (tzOffsetSec !== 0) {
            shiftTimes(data, tzOffsetSec);
        }
        return data;
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
    fee_rate?: number;
    is_ai_mode?: boolean;
    ranging_threshold?: number;
    trending_threshold?: number;
    enable_protection?: boolean;
    use_dynamic_profiles?: boolean;
}

export interface BacktestResult {
    metrics: {
        initial_balance: number;
        final_balance: number;
        pnl: number;
        pnl_percent: number;
        total_trades: number;
        total_fees_paid: number;
    };
    ai_metrics?: {
        protected_buys: number;
        protected_sells: number;
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

export async function getSmartGridParams(symbol: string, durationDays: number = 0): Promise<SmartGridParams> {
    const query = durationDays > 0 ? `?duration_days=${durationDays}` : '';
    const res = await fetch(`${API_BASE}/quant/smart-params/${symbol.replace('/', '-')}${query}`);
    if (!res.ok) throw new Error('Smart Params Failed');
    return res.json();
}

// --- Signal-Driven Strategy API (v2) ---

export interface SignalBacktestParams {
    symbol: string;
    investment: number;
    duration_days: number;
    timeframe: string;
    risk_per_trade_pct: number;
    take_profit_pct: number;
    stop_loss_pct: number;
    trailing_stop_pct: number;
    trailing_activation_pct: number;
    max_positions: number;
    fee_rate: number;
    allow_short: boolean;
    reverse_on_signal: boolean;
    ranging_threshold: number;
    trending_threshold: number;
    enable_protection: boolean;
    use_dynamic_profiles: boolean;
    enable_mtf_filter: boolean;  // Layer 3: 4h regime MTF confirmation
}

export interface SignalBacktestMetrics {
    initial_balance: number;
    final_balance: number;
    pnl: number;
    pnl_percent: number;
    total_trades: number;
    win_rate: number;
    winning_trades: number;
    losing_trades: number;
    avg_win_pct: number;
    avg_loss_pct: number;
    profit_factor: number;
    max_drawdown_pct: number;
    sharpe_ratio: number;
    total_fees_paid: number;
}

export interface SignalTrade {
    time: number;
    side: string;       // 'open_long' | 'open_short' | 'close_long' | 'close_short'
    price: number;
    amount: number;
    fee: number;
    realized_pnl: number;
    exit_reason: string; // 'tp' | 'sl' | 'trailing' | 'signal_reverse' | 'backtest_end' | ''
    position_id: string;
    equity: number;
}

export interface SignalPosition {
    id: string;
    side: string;
    entry_price: number;
    entry_time: number;
    size: number;
    cost: number;
    take_profit: number;
    stop_loss: number;
    trailing_active: boolean;
    trailing_stop_price: number;
    exit_price: number;
    exit_time: number;
    exit_reason: string;
    realized_pnl: number;
    fees_paid: number;
    is_closed: boolean;
}

export interface SignalBacktestResult {
    metrics: SignalBacktestMetrics;
    equity_curve: { time: number; value: number }[];
    trades: SignalTrade[];
    signals_used: any[];
    positions: SignalPosition[];
    price_data: { time: number; open: number; high: number; low: number; close: number }[];
}

export async function runSignalBacktest(params: SignalBacktestParams): Promise<SignalBacktestResult> {
    const res = await fetch(`${API_BASE}/quant/signal-backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
    });
    if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Signal Backtest Failed: ${detail}`);
    }
    
    const data = await res.json();
    const tzOffsetSec = getTimezoneOffsetSec();
    if (tzOffsetSec !== 0) {
        shiftTimes(data, tzOffsetSec);
    }
    return data;
}

// --- Notification Config API ---

export interface NotificationConfig {
    enabled: boolean;
    monitored_symbols: string[];
}

export async function getNotificationConfig(): Promise<NotificationConfig> {
    const res = await fetch(`${API_BASE}/notifications/config`);
    if (!res.ok) throw new Error('Failed to fetch notification config');
    return res.json();
}

export async function updateNotificationConfig(config: NotificationConfig): Promise<NotificationConfig> {
    const res = await fetch(`${API_BASE}/notifications/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    });
    if (!res.ok) throw new Error('Failed to update notification config');
    return res.json();
}

export async function sendTestNotification(): Promise<void> {
    const res = await fetch(`${API_BASE}/notifications/test`, {
        method: 'POST'
    });
    if (!res.ok) throw new Error('Failed to send test notification');
}
