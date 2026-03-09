/**
 * Timeframe-adaptive threshold profiles for the Confluence Signal System v4.
 * These values mirror the PROFILES dict in api/core/indicators.py.
 * Both the chart tooltips and the sentiment panel use these to display
 * context-accurate descriptions.
 */

export interface ThresholdProfile {
    rsi_bull: number;
    rsi_bear: number;
    ema_pct: number;
    fr_bull: number;
    fr_bear: number;
    bb_bull: number;
    bb_bear: number;
    z_bull: number;
    z_bear: number;
}

export const THRESHOLD_PROFILES: Record<string, ThresholdProfile> = {
    '15m': {
        rsi_bull: 25, rsi_bear: 75,
        ema_pct: 0.5,
        fr_bull: -0.005, fr_bear: 0.01,
        bb_bull: 0.10, bb_bear: 0.90,
        z_bull: -1.5, z_bear: 1.5,
    },
    '1h': {
        rsi_bull: 30, rsi_bear: 70,
        ema_pct: 1.0,
        fr_bull: -0.003, fr_bear: 0.008,
        bb_bull: 0.08, bb_bear: 0.92,
        z_bull: -1.2, z_bear: 1.2,
    },
    '4h': {
        rsi_bull: 35, rsi_bear: 65,
        ema_pct: 2.0,
        fr_bull: -0.002, fr_bear: 0.006,
        bb_bull: 0.05, bb_bear: 0.95,
        z_bull: -1.0, z_bear: 1.0,
    },
    '1d': {
        rsi_bull: 40, rsi_bear: 60,
        ema_pct: 3.0,
        fr_bull: -0.001, fr_bear: 0.005,
        bb_bull: 0.05, bb_bear: 0.95,
        z_bull: -0.8, z_bear: 0.8,
    },
};

export function getThresholds(timeframe: string): ThresholdProfile {
    return THRESHOLD_PROFILES[timeframe] || THRESHOLD_PROFILES['1h'];
}
