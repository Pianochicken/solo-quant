
import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, CandlestickSeries, HistogramSeries, LineSeries, Time, CrosshairMode, createSeriesMarkers } from 'lightweight-charts';
import { InfoTooltip } from './InfoTooltip';
import { getThresholds } from '@/lib/thresholds';
import { getPricePrecision } from '@/lib/utils';

interface AdvancedChartProps {
    symbol: string;
    timeframe?: string;
    data: {
        price: any[];
        funding: any[];
    } | null;
    indicators: {
        lsur_z_score: number;
        lsur_history: any[];
        lsur_z_history?: { time: number; value: number }[];
        lsur_markers?: { time: number; position: string; color: string; shape: string; text: string }[];
        cvd_history: { time: number; value: number }[];
        open_interest: { time: number; value: number }[];
        ema_fast?: { time: number; value: number }[];
        ema_slow?: { time: number; value: number }[];
        trend_state?: 'uptrend' | 'downtrend' | 'neutral';
        rsi_history?: { time: number; value: number }[];
        composite_score?: { time: number; value: number }[];
        funding_history?: { time: number; value: number }[];
        market_regime_history?: { time: number; regime: string; direction: string }[];
    } | null;
    gridLines?: number[];
}

export default function AdvancedChart({ symbol, timeframe = '1h', data, indicators, gridLines = [] }: AdvancedChartProps) {
    const T = getThresholds(timeframe);
    // Container Refs
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const rsiContainerRef = useRef<HTMLDivElement>(null);
    const cvdContainerRef = useRef<HTMLDivElement>(null);
    const oiContainerRef = useRef<HTMLDivElement>(null);
    const fundingContainerRef = useRef<HTMLDivElement>(null);
    const pulseContainerRef = useRef<HTMLDivElement>(null);
    const regimeContainerRef = useRef<HTMLDivElement>(null);

    // Chart Instance Refs
    const chartRef = useRef<IChartApi | null>(null);
    const rsiChartRef = useRef<IChartApi | null>(null);
    const cvdChartRef = useRef<IChartApi | null>(null);
    const oiChartRef = useRef<IChartApi | null>(null);
    const fundingChartRef = useRef<IChartApi | null>(null);
    const pulseChartRef = useRef<IChartApi | null>(null);
    const regimeChartRef = useRef<IChartApi | null>(null);

    // Series Refs
    const mainSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const cvdSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const oiSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const fundingSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const pulseSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const regimeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

    // Overlay Refs
    const gridLinesRef = useRef<any[]>([]);
    const markersPluginRef = useRef<any>(null);
    const emaFastSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const emaSlowSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

    // Legend State
    const [rsiLegendValue, setRsiLegendValue] = React.useState<number | null>(null);
    const [cvdLegendValue, setCvdLegendValue] = React.useState<number | null>(null);
    const [oiLegendValue, setOiLegendValue] = React.useState<number | null>(null);
    const [fundingLegendValue, setFundingLegendValue] = React.useState<number | null>(null);
    const [pulseLegendValue, setPulseLegendValue] = React.useState<number | null>(null);
    const [regimeLegendValue, setRegimeLegendValue] = React.useState<{regime: string, direction: string} | null>(null);

    // Marker Tooltip State
    const [hoveredMarker, setHoveredMarker] = React.useState<{ x: number; y: number; text: string; color: string } | null>(null);

    // 1. INITIALIZATION
    useEffect(() => {
        if (!chartContainerRef.current || !rsiContainerRef.current || !cvdContainerRef.current || !oiContainerRef.current || !fundingContainerRef.current || !pulseContainerRef.current || !regimeContainerRef.current) return;

        // Utility: Abbreviate large numbers
        const abbreviateNumber = (value: number): string => {
            const abs = Math.abs(value);
            if (abs >= 1e9) return (value / 1e9).toFixed(2) + 'B';
            if (abs >= 1e6) return (value / 1e6).toFixed(2) + 'M';
            if (abs >= 1e3) return (value / 1e3).toFixed(1) + 'K';
            return value.toFixed(2);
        };

        const commonOptions = {
            layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#d1d5db' },
            grid: { vertLines: { color: '#27272a' }, horzLines: { color: '#27272a' } },
            timeScale: { visible: false, timeVisible: true, secondsVisible: false },
            crosshair: { mode: CrosshairMode.Normal },
            rightPriceScale: { visible: true, minimumWidth: 120 },
        };

        // --- Main Price Chart ---
        const chart = createChart(chartContainerRef.current, {
            ...commonOptions,
            width: chartContainerRef.current.clientWidth,
            height: 400,
            timeScale: { visible: true, timeVisible: true, secondsVisible: false },
        });
        chartRef.current = chart;

        const priceData = data?.price || [];
        const currentPrice = priceData.length ? priceData[priceData.length - 1].close : 0;
        const { precision, minMove } = getPricePrecision(currentPrice, symbol);
        
        mainSeriesRef.current = chart.addSeries(CandlestickSeries, {
            upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350',
            priceFormat: { type: 'price', precision, minMove },
        });

        // EMA Lines on Price Chart
        emaFastSeriesRef.current = chart.addSeries(LineSeries, {
            color: '#f97316',  // Orange for EMA50
            lineWidth: 1,
            crosshairMarkerVisible: false,
            priceLineVisible: false,
            lastValueVisible: false,
        });
        emaSlowSeriesRef.current = chart.addSeries(LineSeries, {
            color: '#a855f7',  // Purple for EMA200
            lineWidth: 1,
            crosshairMarkerVisible: false,
            priceLineVisible: false,
            lastValueVisible: false,
        });

        // --- RSI Chart (Line, 0-100) ---
        const rsiChart = createChart(rsiContainerRef.current, {
            ...commonOptions,
            width: rsiContainerRef.current.clientWidth,
            height: 80,
            rightPriceScale: { visible: true, minimumWidth: 120, scaleMargins: { top: 0.05, bottom: 0.05 } },
        });
        rsiChartRef.current = rsiChart;
        rsiSeriesRef.current = rsiChart.addSeries(LineSeries, {
            color: '#a78bfa',  // Purple
            lineWidth: 2,
            priceFormat: { type: 'custom', formatter: (price: number) => price.toFixed(0) },
        });

        // --- CVD Chart (Line) ---
        const cvdChart = createChart(cvdContainerRef.current, {
            ...commonOptions,
            width: cvdContainerRef.current.clientWidth,
            height: 100,
            localization: {
                priceFormatter: abbreviateNumber,
            },
        });
        cvdChartRef.current = cvdChart;
        cvdSeriesRef.current = cvdChart.addSeries(LineSeries, {
            color: '#eab308', // Yellow
            lineWidth: 2,
            priceFormat: { type: 'custom', formatter: abbreviateNumber },
        });

        // --- OI Chart (Histogram) ---
        const oiChart = createChart(oiContainerRef.current, {
            ...commonOptions,
            width: oiContainerRef.current.clientWidth,
            height: 100,
        });
        oiChartRef.current = oiChart;
        oiSeriesRef.current = oiChart.addSeries(HistogramSeries, {
            color: '#2962ff',
            priceFormat: { type: 'volume' },
        });

        // --- Funding Rate Chart (Histogram) ---
        const fundingChart = createChart(fundingContainerRef.current, {
            ...commonOptions,
            width: fundingContainerRef.current.clientWidth,
            height: 100,
            timeScale: { visible: false, timeVisible: true, secondsVisible: false },
            rightPriceScale: { visible: true, minimumWidth: 120, scaleMargins: { top: 0.1, bottom: 0.1 } },
        });
        fundingChartRef.current = fundingChart;
        fundingSeriesRef.current = fundingChart.addSeries(HistogramSeries, {
            color: '#fbbf24',
            priceFormat: { type: 'custom', formatter: (price: number) => `${price.toFixed(4)}%` },
        });

        // --- Market Pulse Chart (Line) ---
        const pulseChart = createChart(pulseContainerRef.current, {
            ...commonOptions,
            width: pulseContainerRef.current.clientWidth,
            height: 100,
            timeScale: { visible: false, timeVisible: true, secondsVisible: false },
            rightPriceScale: { visible: true, minimumWidth: 120, scaleMargins: { top: 0.1, bottom: 0.1 } },
        });
        pulseChartRef.current = pulseChart;
        pulseSeriesRef.current = pulseChart.addSeries(LineSeries, {
            color: '#a8a29e', // base gray
            lineWidth: 2,
            priceFormat: { type: 'custom', formatter: (price: number) => price.toFixed(1) },
        });

        // Add 20 and 80 grid lines for Pulse
        pulseSeriesRef.current.createPriceLine({ price: 80, color: '#ef4444', lineWidth: 1, lineStyle: 2, axisLabelVisible: false });
        pulseSeriesRef.current.createPriceLine({ price: 20, color: '#10b981', lineWidth: 1, lineStyle: 2, axisLabelVisible: false });

        // --- Regime Chart (Histogram) ---
        const regimeChart = createChart(regimeContainerRef.current, {
            ...commonOptions,
            width: regimeContainerRef.current.clientWidth,
            height: 60,
            timeScale: { visible: true, timeVisible: true, secondsVisible: false }, // Bottom-most chart shows time
            rightPriceScale: { visible: true, minimumWidth: 120, scaleMargins: { top: 0.1, bottom: 0.1 } },
        });
        regimeChartRef.current = regimeChart;
        regimeSeriesRef.current = regimeChart.addSeries(HistogramSeries, {
            color: '#52525b',
            priceFormat: { type: 'custom', formatter: () => '' }, // Hide price axis numbers for this boolean chart
            priceScaleId: '', // Prevents price scale from displaying values
        });
        
        // Hide right price scale since it's just a constant height
        regimeChart.priceScale('').applyOptions({
            visible: false,
        });

        // --- Synchronization Loop ---
        const charts = [chart, rsiChart, cvdChart, oiChart, fundingChart, pulseChart, regimeChart];

        // Sync TimeScales
        charts.forEach((c1, i) => {
            const timeScale = c1.timeScale();
            timeScale.subscribeVisibleLogicalRangeChange((range) => {
                if (range) {
                    charts.forEach((c2, j) => {
                        if (i !== j) c2.timeScale().setVisibleLogicalRange(range);
                    });
                }
            });
        });

        // Sync Crosshair (Manual propagation) handled in the Data effect to access data points
        // We will just expose the charts to a higher scope or rely on useEffect dependencies.


        // Resize Handler
        const handleResize = () => {
            const w = chartContainerRef.current?.clientWidth || 0;
            if (w > 0) {
                charts.forEach(c => {
                    c.applyOptions({ width: w });
                    c.timeScale().fitContent();
                });
            }
        };

        window.addEventListener('resize', handleResize);

        // Initial fit
        setTimeout(() => {
            charts.forEach(c => c.timeScale().fitContent());
        }, 100);

        return () => {
            window.removeEventListener('resize', handleResize);
            charts.forEach(c => c.remove());
        };
    }, []);

    useEffect(() => {
        if (!mainSeriesRef.current) return;

        const priceData = data?.price || [];
        const currentPrice = priceData.length ? priceData[priceData.length - 1].close : 0;
        const { precision, minMove } = getPricePrecision(currentPrice, symbol);

        mainSeriesRef.current.applyOptions({
            priceFormat: { type: 'price', precision, minMove },
        });
    }, [symbol, data?.price]);

    // 2. DATA UPDATE
    useEffect(() => {
        if (!mainSeriesRef.current || !data) return;

        // Update Price
        mainSeriesRef.current.setData(data.price);

        // Update LSUR Z-Score Markers on Price Chart
        if (indicators?.lsur_markers && indicators.lsur_markers.length > 0) {
            const markers = indicators.lsur_markers
                .filter(m => m.time && m.position && m.color && (m.shape === 'arrowUp' || m.shape === 'arrowDown'))
                .map(m => {
                    const markerData: any = {
                        time: m.time as Time,
                        position: m.position as 'aboveBar' | 'belowBar',
                        color: m.color,
                        shape: m.shape as 'arrowDown' | 'arrowUp',
                        size: 1, // explicit size
                    };
                    return markerData;
                })
                .sort((a, b) => (a.time as number) - (b.time as number));

            // v5 API: createSeriesMarkers returns a plugin with setMarkers()
            if (markersPluginRef.current) {
                markersPluginRef.current.setMarkers(markers);
            } else {
                markersPluginRef.current = createSeriesMarkers(mainSeriesRef.current, markers);
            }
        } else if (markersPluginRef.current) {
            markersPluginRef.current.setMarkers([]);
        }

        // Update EMA Lines
        if (emaFastSeriesRef.current && indicators?.ema_fast) {
            emaFastSeriesRef.current.setData(
                indicators.ema_fast.map(item => ({ time: item.time as Time, value: item.value }))
            );
        }
        if (emaSlowSeriesRef.current && indicators?.ema_slow) {
            emaSlowSeriesRef.current.setData(
                indicators.ema_slow.map(item => ({ time: item.time as Time, value: item.value }))
            );
        }

        // Helper to perfectly align indicator timelines with the main price chart
        // by filling missing records with whitespace data { time: t }
        const priceTimes = data.price.map(p => p.time as Time);
        const alignData = (rawArray: any[], mapFn: (item: any, i: number, arr: any[]) => any) => {
            if (!Array.isArray(rawArray) || rawArray.length === 0) return [];
            const mapped = rawArray.map(mapFn);
            const dataMap = new Map();
            mapped.forEach(item => dataMap.set(item.time, item));
            return priceTimes.map(t => {
                if (dataMap.has(t)) return dataMap.get(t);
                return { time: t }; // whitespace
            });
        };

        // Update RSI
        let rsiData: any[] = [];
        if (rsiSeriesRef.current && indicators?.rsi_history) {
            rsiData = alignData(indicators.rsi_history, item => ({
                time: item.time as Time,
                value: item.value
            }));
            rsiSeriesRef.current.setData(rsiData);
        }

        // Update CVD
        let cvdData: any[] = [];
        if (cvdSeriesRef.current && indicators?.cvd_history) {
            cvdData = alignData(indicators.cvd_history, item => ({
                time: item.time as Time,
                value: item.value
            }));
            cvdSeriesRef.current.setData(cvdData);
        }

        // Update OI
        let oiData: any[] = [];
        if (oiSeriesRef.current && indicators?.open_interest) {
            oiData = alignData(indicators.open_interest, (item, index, arr) => {
                const prev = arr[index - 1]?.value || item.value;
                const color = item.value >= prev ? 'rgba(38, 166, 154, 0.6)' : 'rgba(239, 83, 80, 0.6)';
                return {
                    time: item.time as Time,
                    value: item.value,
                    color: color
                };
            });
            oiSeriesRef.current.setData(oiData);
        }

        // Update Funding
        let fundingData: any[] = [];
        if (fundingSeriesRef.current && data.funding) {
            fundingData = data.funding.map(item => {
                const color = item.value >= 0 ? '#10b981' : '#ef4444';
                return {
                    time: item.time as Time,
                    value: item.value,
                    color: color
                };
            });
            fundingSeriesRef.current.setData(fundingData);
        }

        // Update Market Pulse
        let pulseData: any[] = [];
        if (pulseSeriesRef.current && (indicators as any)?.composite_score_history) {
            pulseData = alignData((indicators as any).composite_score_history, item => {
                let color = '#a8a29e'; // Gray neutral
                if (item.value >= 80) color = '#ef4444'; // Red extreme bearish
                else if (item.value <= 20) color = '#10b981'; // Green extreme bullish
                return {
                    time: item.time as Time,
                    value: item.value,
                    color: color
                };
            });
            pulseSeriesRef.current.setData(pulseData);
        }

        // Update Regime Chart
        let regimeData: any[] = [];
        if (regimeSeriesRef.current && indicators?.market_regime_history) {
            regimeData = alignData(indicators.market_regime_history, item => {
                let color = '#f59e0b'; // Amber (Ranging)
                
                if (item.regime === 'trending') {
                    if (item.direction === 'up') {
                        color = '#10b981'; // Green
                    } else if (item.direction === 'down') {
                        color = '#ef4444'; // Red
                    }
                }
                
                return {
                    time: item.time as Time,
                    value: 1, // Constant height for all bars
                    color: color,
                    // Store original data for the legend
                    regime: item.regime,
                    direction: item.direction
                };
            });
            regimeSeriesRef.current.setData(regimeData);
        }

        // SYNC LEGENDS AND CROSSHAIR Bidirectionally
        const chartsArray = [
            { api: chartRef.current, series: mainSeriesRef.current, data: data.price },
            { api: rsiChartRef.current, series: rsiSeriesRef.current, data: rsiData },
            { api: cvdChartRef.current, series: cvdSeriesRef.current, data: cvdData },
            { api: oiChartRef.current, series: oiSeriesRef.current, data: oiData },
            { api: fundingChartRef.current, series: fundingSeriesRef.current, data: fundingData },
            { api: pulseChartRef.current, series: pulseSeriesRef.current, data: pulseData },
            { api: regimeChartRef.current, series: regimeSeriesRef.current, data: regimeData }
        ];

        const syncCrosshairHandler = (sourceChartApi: IChartApi, param: any) => {
            // Handle Marker Tooltip (show when hovering over a marker time)
            if (param.time && param.point && indicators?.lsur_markers && sourceChartApi === chartRef.current) {
                const marker = indicators.lsur_markers.find(m => m.time === param.time);
                if (marker && marker.text) {
                    setHoveredMarker({
                        x: param.point.x,
                        y: param.point.y,
                        text: marker.text,
                        color: marker.color
                    });
                } else {
                    setHoveredMarker(null);
                }
            } else if (!param.time) {
                setHoveredMarker(null);
            }

            if (!param.time) {
                // Clear crosshairs and legends
                chartsArray.forEach(c => {
                    if (c.api && c.api !== sourceChartApi) {
                        c.api.clearCrosshairPosition();
                    }
                });
                setRsiLegendValue(null);
                setCvdLegendValue(null);
                setOiLegendValue(null);
                setFundingLegendValue(null);
                setPulseLegendValue(null);
                setRegimeLegendValue(null);
                return;
            }

            // Sync other charts and legends
            chartsArray.forEach(c => {
                if (!c.api || !c.series) return;

                const pointData = c.data.find((p: any) => p.time === param.time);

                // Update Legend state based on chart type
                if (c.api === rsiChartRef.current) setRsiLegendValue(pointData ? pointData.value : null);
                if (c.api === cvdChartRef.current) setCvdLegendValue(pointData ? pointData.value : null);
                if (c.api === oiChartRef.current) setOiLegendValue(pointData ? pointData.value : null);
                if (c.api === fundingChartRef.current) setFundingLegendValue(pointData ? pointData.value : null);
                if (c.api === pulseChartRef.current) setPulseLegendValue(pointData ? pointData.value : null);
                if (c.api === regimeChartRef.current) setRegimeLegendValue(pointData ? { regime: pointData.regime, direction: pointData.direction } : null);

                // Sync Crosshair Line
                if (c.api !== sourceChartApi) {
                    if (pointData) {
                        // For Candlestick (price) determine value from close
                        let crosshairValue = pointData.value;
                        if (crosshairValue === undefined && pointData.close !== undefined) {
                            crosshairValue = pointData.close;
                        }
                        if (crosshairValue !== undefined && !isNaN(crosshairValue)) {
                            c.api.setCrosshairPosition(crosshairValue, param.time, c.series as any);
                        }
                    }
                }
            });
        };

        // Attach to all
        const unsubscribeHandlers: (() => void)[] = [];
        chartsArray.forEach(c => {
            if (c.api) {
                const handler = (param: any) => syncCrosshairHandler(c.api!, param);
                c.api.subscribeCrosshairMove(handler);
                unsubscribeHandlers.push(() => {
                    // Type safely check before unsubscribing
                    if (c.api) c.api.unsubscribeCrosshairMove(handler);
                });
            }
        });

        // Draw Grid Lines (Only on Price Chart)
        const series = mainSeriesRef.current;
        if (series) {
            gridLinesRef.current.forEach(l => series.removePriceLine(l));
            gridLinesRef.current = [];

            gridLines.filter(p => !isNaN(p) && p > 0).forEach((price) => {
                const line = series.createPriceLine({
                    price: price,
                    color: '#eab308',
                    lineWidth: 1,
                    lineStyle: 3,
                    axisLabelVisible: false
                });
                gridLinesRef.current.push(line);
            });
        }

        // Cleanup event listeners
        return () => {
            unsubscribeHandlers.forEach(unsub => unsub());
        };

    }, [data, indicators, gridLines]);

    return (
        <div className="w-full flex flex-col gap-1 bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden shadow-lg p-1">
            {/* 1. Main Chart */}
            <div
                className="relative w-full h-[400px]"
                onMouseLeave={() => setHoveredMarker(null)}
            >
                {/* Marker Hover Tooltip */}
                {hoveredMarker && hoveredMarker.text && (
                    <div
                        className="absolute z-50 px-2 py-1 bg-zinc-800/90 backdrop-blur-sm border border-zinc-700 rounded text-xs pointer-events-none whitespace-nowrap shadow-xl font-mono"
                        style={{
                            left: hoveredMarker.x + 10,
                            top: Math.max(10, hoveredMarker.y - 30),
                            color: hoveredMarker.color
                        }}
                    >
                        {hoveredMarker.text}
                    </div>
                )}

                <div className="absolute top-2 left-2 z-10 bg-black/50 px-2 py-1 rounded text-xs text-zinc-400 flex items-center gap-3">
                    <span className="flex items-center">Price<InfoTooltip text="K線圖：顯示價格走勢。綠色為上漲，紅色為下跌。箭頭標記為多指標匯合信號。橙色線 = EMA50，紫色線 = EMA200" /></span>
                    <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-orange-500 inline-block"></span><span className="text-[10px]">EMA50</span></span>
                    <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-purple-500 inline-block"></span><span className="text-[10px]">EMA200</span></span>
                </div>
                <div ref={chartContainerRef} className="w-full h-full" />
                <div className="absolute top-2 right-2 z-10 flex gap-2">
                    <div className="bg-black/50 px-2 py-1 rounded text-xs text-zinc-500">
                        {symbol}
                    </div>
                </div>
            </div>

            {/* 2. Market Pulse Chart */}
            <div className="relative w-full h-[100px] border-t border-zinc-800">
                <div className="absolute top-1 left-2 z-10 bg-black/50 px-2 py-0.5 rounded text-[10px] text-zinc-400 flex gap-2">
                    <span className="font-bold text-zinc-300">Market Pulse</span><InfoTooltip text="綜合情緒指數 (0-100)：匯總所有 7 種指標的得分。越接近 100 代表市場越看跌（做空擁擠／超買），越接近 0 代表市場越看漲（做多擁擠／超賣）。" />
                    {typeof pulseLegendValue === 'number' && (
                        <span className={`font-mono font-bold ${pulseLegendValue >= 80 ? 'text-red-400' : pulseLegendValue <= 20 ? 'text-emerald-400' : 'text-zinc-400'}`}>
                            {pulseLegendValue.toFixed(1)}
                        </span>
                    )}
                </div>
                <div ref={pulseContainerRef} className="w-full h-full" />
            </div>

            {/* 3. RSI Chart */}
            <div className="relative w-full h-[80px] border-t border-zinc-800">
                <div className="absolute top-1 left-2 z-10 bg-black/50 px-2 py-0.5 rounded text-[10px] text-zinc-400 flex gap-2">
                    <span className="font-bold text-purple-400">RSI (14)</span><InfoTooltip text={`相對強弱指數：衡量價格動能的振盪指標。RSI > ${T.rsi_bear} = 超買（可能回落），RSI < ${T.rsi_bull} = 超賣（可能反彈）。門檻會隨週期動態調整`} />
                    <span className="text-zinc-600 text-[9px]">{T.rsi_bull}</span>
                    <span className="text-zinc-600 text-[9px]">{T.rsi_bear}</span>
                    {typeof rsiLegendValue === 'number' && (
                        <span className={`font-mono ${rsiLegendValue > T.rsi_bear ? 'text-red-400' : rsiLegendValue < T.rsi_bull ? 'text-emerald-400' : 'text-zinc-200'}`}>
                            {rsiLegendValue.toFixed(0)}
                        </span>
                    )}
                </div>
                <div ref={rsiContainerRef} className="w-full h-full" />
            </div>

            {/* 4. CVD Chart */}
            <div className="relative w-full h-[100px] border-t border-zinc-800">
                <div className="absolute top-1 left-2 z-10 bg-black/50 px-2 py-0.5 rounded text-[10px] text-zinc-400 flex gap-2">
                    <span className="font-bold text-yellow-500">CVD (Volume Delta)</span><InfoTooltip text="累積成交量差值：追蹤主動買入與賣出的淨差額。上升 = 買方主導，下降 = 賣方主導。反映真實資金流向" />
                    {typeof cvdLegendValue === 'number' && (
                        <span className="text-zinc-200">{cvdLegendValue.toLocaleString()}</span>
                    )}
                </div>
                <div ref={cvdContainerRef} className="w-full h-full" />
            </div>

            {/* 5. OI Chart */}
            <div className="relative w-full h-[100px] border-t border-zinc-800">
                <div className="absolute top-1 left-2 z-10 bg-black/50 px-2 py-0.5 rounded text-[10px] text-zinc-400 flex gap-2">
                    <span className="font-bold text-blue-400">Open Interest</span><InfoTooltip text="未平倉合約量：市場中所有未結算的合約總值。綠色 = OI 增加（新倉位開設），紅色 = OI 減少（倉位平倉/清算）。注意：OI 本身無法區分多空方向，需搭配 LSUR/CVD 判斷實際偏向" />
                    {typeof oiLegendValue === 'number' && (
                        <span className="text-zinc-200">{oiLegendValue.toLocaleString()}</span>
                    )}
                </div>
                <div ref={oiContainerRef} className="w-full h-full" />
            </div>

            {/* 6. Funding Chart */}
            <div className="relative w-full h-[100px] border-t border-zinc-800">
                <div className="absolute top-1 left-2 z-10 bg-black/50 px-2 py-0.5 rounded text-[10px] text-zinc-400 flex gap-2">
                    <span className="font-bold text-emerald-400">Funding Rate</span><InfoTooltip text={`資金費率：多空之間定期支付的費用。FR > ${T.fr_bear}% = 多頭過多（看跌），FR < ${T.fr_bull}% = 空頭過多（看漲）。門檻會隨週期動態調整`} />
                    {typeof fundingLegendValue === 'number' && (
                        <span className={`${fundingLegendValue >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {fundingLegendValue.toFixed(4)}%
                        </span>
                    )}
                </div>
                <div ref={fundingContainerRef} className="w-full h-full" />
            </div>

            {/* 7. Regime Chart */}
            <div className="relative w-full h-[60px] border-t border-zinc-800">
                <div className="absolute top-1 left-2 z-10 bg-black/50 px-2 py-0.5 rounded text-[10px] text-zinc-400 flex gap-2">
                    <span className="font-bold text-zinc-300">Market Regime</span><InfoTooltip text="市場趨勢狀態：+1 為強勢多頭 (Uptrend)，-1 為強勢空頭 (Downtrend)，0 為盤整 (Ranging)。趨勢確認時，系統會自動放寬同方向的進場條件。" />
                    {regimeLegendValue && (
                        <span className={`font-bold ${regimeLegendValue.regime === 'trending' ? (regimeLegendValue.direction === 'up' ? 'text-emerald-400' : 'text-red-400') : 'text-zinc-400'}`}>
                            {regimeLegendValue.regime === 'trending' ? (regimeLegendValue.direction === 'up' ? 'Uptrend' : 'Downtrend') : 'Ranging'}
                        </span>
                    )}
                </div>
                <div ref={regimeContainerRef} className="w-full h-full" />
            </div>
        </div>
    );
}
