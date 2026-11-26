export type StrategyMode = 'legacy_v8' | 'macro_cycle';

export interface MacroCycleZonePoint {
    time: number;
    zone: 'neutral' | 'bear_value' | 'regional_value' | 'euphoria_top' | 'bear_regime';
    mayer?: number | null;
    dd_180_pct?: number | null;
    dd_90_pct?: number | null;
}

export interface MacroCycleActivePosition {
    id: string;
    entry_type: string;
    entry_time: number;
    entry_price: number;
    current_price: number;
    pnl_pct: number;
    peak_mfe_pct: number;
    hold_days: number;
    base_stop: number;
    base_stop_disabled: boolean;
    euphoria_armed: boolean;
}

export interface MacroCycleState {
    mode: 'macro_cycle';
    version: string;
    timeframe: string;
    timeframe_warning?: string | null;
    position_state: 'LONG' | 'FLAT';
    stage: string;
    stage_label: string;
    stage_description: string;
    mayer_multiple?: number | null;
    euphoria_mayer_threshold?: number | null;
    dd_180_pct?: number | null;
    dd_180_threshold_pct?: number | null;
    dd_90_pct?: number | null;
    rsi_14?: number | null;
    ema20?: number | null;
    ema50?: number | null;
    ema200?: number | null;
    ema50_rising?: boolean;
    ema200_rising?: boolean;
    left_zones?: {
        bear_value_active: boolean;
        regional_value_active: boolean;
        euphoria_overheated_active: boolean;
        bear_regime_active: boolean;
    };
    active_position?: MacroCycleActivePosition | null;
    derivative_context?: {
        has_deriv: boolean;
        coin_oi_dd_60d?: number | null;
        coin_oi_pct_180d?: number | null;
        fr_7d_mean_pct?: number | null;
        fr_pct_180d?: number | null;
        lsur_z_90d?: number | null;
        washout_60d?: boolean;
        overheated_30d?: boolean;
        summary?: string;
    } | null;
    latest_event?: any;
}

export interface IndicatorData {
    strategy_mode?: StrategyMode;
    lsur_z_score: number;
    lsur_ratio?: number | null;
    lsur_history: { time: number; value: number }[] | null;
    lsur_z_history?: { time: number; value: number; signal?: string | null }[];
    top_ls_ratio?: number | null;
    top_ls_z_score?: number;
    top_ls_history?: { time: number; value: number }[];
    top_ls_z_history?: { time: number; value: number; signal?: string | null }[];
    cvd_history: { time: number; value: number }[];
    open_interest: { time: number; value: number }[];
    oi_percentile: number;
    ema_20?: { time: number; value: number }[];
    ema_fast?: { time: number; value: number }[];
    ema_slow?: { time: number; value: number }[];
    trend_state?: 'uptrend' | 'downtrend' | 'neutral';
    rsi_history?: { time: number; value: number }[];
    composite_score?: number;
    composite_score_history?: { time: number; value: number }[];
    lsur_markers?: {
        time: number;
        position: string;
        color: string;
        shape: string;
        text: string;
        size?: number;
        direction?: string;
        strategy_type?: string;
        archetype?: string;
        cycle_event?: string;
        short_label?: string;
        price?: number | null;
        base_stop?: number | null;
        mayer?: number | null;
        realized_pnl_pct?: number | null;
        peak_mfe_pct?: number | null;
        hold_days?: number | null;
        deriv_context?: any;
    }[];
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
        adx?: number;
        bb_width?: number;
    } | null;
    donchian_channel?: {
        time: number;
        upper: number;
        lower: number;
        middle: number;
    }[];
    macro_cycle_state?: MacroCycleState | null;
    macro_cycle_zones?: MacroCycleZonePoint[];
}

export interface SignalConfig {
    rangingThreshold: number;
    trendingThreshold: number;
    enableProtection: boolean;
    useDynamicProfiles: boolean;
    enableMtfFilter: boolean;  // Layer 3: 4h regime MTF confirmation
    minScore?: number;
    signalTypes?: string;      // e.g. "structure,reversion,breakout"
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

export async function getMarketData(
    symbol: string,
    timeframe: string = '1h',
    limit: number = 100,
    config?: SignalConfig,
    options?: { signal?: AbortSignal; strategyMode?: StrategyMode }
): Promise<MarketData> {
    const safeSymbol = symbol.replace('/', '-');

    try {
        let url = `${API_BASE}/market/${safeSymbol}?timeframe=${timeframe}&limit=${limit}`;
        if (options?.strategyMode) {
            url += `&strategy_mode=${encodeURIComponent(options.strategyMode)}`;
        }
        if (config) {
            url += `&ranging_threshold=${config.rangingThreshold}&trending_threshold=${config.trendingThreshold}&enable_protection=${config.enableProtection}&use_dynamic_profiles=${config.useDynamicProfiles}&enable_mtf_filter=${config.enableMtfFilter ?? false}`;
            if (config.minScore !== undefined) {
                url += `&min_score=${config.minScore}`;
            }
            if (config.signalTypes !== undefined) {
                url += `&signal_types=${encodeURIComponent(config.signalTypes)}`;
            }
        }
        const res = await fetch(url, { signal: options?.signal });
        if (!res.ok) throw new Error('Failed to fetch market data');
        
        const data = await res.json();
        const tzOffsetSec = getTimezoneOffsetSec();
        if (tzOffsetSec !== 0) {
            shiftTimes(data, tzOffsetSec);
        }
        return data;
    } catch (error) {
        if ((error as any)?.name !== 'AbortError') {
            console.error(error);
        }
        throw error;
    }
}

// --- Market Overview & Quadrant Radar API ---

export interface MarketOverviewItem {
    symbol: string;
    symbol_slug: string;
    price: number;
    change_24h_pct: number;
    rsi_4h: number;
    rs_vs_btc: number;
    oi_coin_change_24h_pct: number;
    quadrant: 'strong_add' | 'weak_add' | 'strong_reduce' | 'weak_reduce' | 'neutral';
    regime_4h: 'trending_up' | 'trending_down' | 'ranging';
    latest_signal?: {
        direction: string;
        time: number;
        text: string;
        score: number;
        archetype: string;
        hours_ago: number;
    } | null;
}

export async function getMarketOverview(): Promise<MarketOverviewItem[]> {
    try {
        const res = await fetch(`${API_BASE}/api/market_overview`);
        if (!res.ok) throw new Error('Failed to fetch market overview');
        const data: MarketOverviewItem[] = await res.json();
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
    strategy_mode?: StrategyMode;
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
    enable_partial_tp?: boolean;
    partial_tp_ratio?: number;
    min_score?: number;
    signal_types?: string;
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
    total_funding_pnl?: number;
    avg_mfe_pct?: number;
    avg_mae_pct?: number;
    cagr_pct?: number;
    mar_ratio?: number;
    avg_hold_days?: number;
    time_in_market_pct?: number;
    trades_per_yr?: number;
    buy_and_hold_return_pct?: number;
    buy_and_hold_max_dd_pct?: number;
}

export interface SignalTrade {
    time: number;
    side: string;       // 'open_long' | 'open_short' | 'close_long' | 'close_short'
    price: number;
    amount: number;
    fee: number;
    realized_pnl: number;
    exit_reason: string; // 'tp' | 'sl' | 'trailing' | 'signal_reverse' | 'backtest_end' | ''
    entry_type?: string;
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
    strategy_mode?: StrategyMode;
    metrics: SignalBacktestMetrics;
    equity_curve: { time: number; value: number }[];
    trades: SignalTrade[];
    signals_used: any[];
    positions: SignalPosition[];
    price_data: { time: number; open: number; high: number; low: number; close: number }[];
    macro_cycle_zones?: MacroCycleZonePoint[];
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
    scan_schedule?: string;
    macro_cycle_schedule?: string;
    enable_mtf_filter?: boolean;
    enable_protection?: boolean;
    allow_intraday_prealert?: boolean;
    enable_macro_cycle_alerts?: boolean;
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
