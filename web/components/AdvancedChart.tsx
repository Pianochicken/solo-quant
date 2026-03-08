
import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, CandlestickSeries, HistogramSeries, LineSeries, Time, CrosshairMode, createSeriesMarkers } from 'lightweight-charts';
import { InfoTooltip } from './InfoTooltip';

interface AdvancedChartProps {
    symbol: string;
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
    } | null;
    gridLines?: number[];
}

export default function AdvancedChart({ symbol, data, indicators, gridLines = [] }: AdvancedChartProps) {
    // Container Refs
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const rsiContainerRef = useRef<HTMLDivElement>(null);
    const cvdContainerRef = useRef<HTMLDivElement>(null);
    const oiContainerRef = useRef<HTMLDivElement>(null);
    const fundingContainerRef = useRef<HTMLDivElement>(null);

    // Chart Instance Refs
    const chartRef = useRef<IChartApi | null>(null);
    const rsiChartRef = useRef<IChartApi | null>(null);
    const cvdChartRef = useRef<IChartApi | null>(null);
    const oiChartRef = useRef<IChartApi | null>(null);
    const fundingChartRef = useRef<IChartApi | null>(null);

    // Series Refs
    const mainSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const cvdSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const oiSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const fundingSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

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

    // Marker Tooltip State
    const [hoveredMarker, setHoveredMarker] = React.useState<{ x: number; y: number; text: string; color: string } | null>(null);

    // 1. INITIALIZATION
    useEffect(() => {
        if (!chartContainerRef.current || !rsiContainerRef.current || !cvdContainerRef.current || !oiContainerRef.current || !fundingContainerRef.current) return;

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
            rightPriceScale: { visible: true, minimumWidth: 80 },
        };

        // --- Main Price Chart ---
        const chart = createChart(chartContainerRef.current, {
            ...commonOptions,
            width: chartContainerRef.current.clientWidth,
            height: 400,
            timeScale: { visible: true, timeVisible: true, secondsVisible: false },
        });
        chartRef.current = chart;
        mainSeriesRef.current = chart.addSeries(CandlestickSeries, {
            upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350',
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
            rightPriceScale: { visible: true, minimumWidth: 80, scaleMargins: { top: 0.05, bottom: 0.05 } },
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
            timeScale: { visible: true, timeVisible: true, secondsVisible: false },
            rightPriceScale: { visible: true, minimumWidth: 80, scaleMargins: { top: 0.1, bottom: 0.1 } },
        });
        fundingChartRef.current = fundingChart;
        fundingSeriesRef.current = fundingChart.addSeries(HistogramSeries, {
            color: '#fbbf24',
            priceFormat: { type: 'custom', formatter: (price: number) => `${price.toFixed(4)}%` },
        });

        // --- Synchronization Loop ---
        const charts = [chart, rsiChart, cvdChart, oiChart, fundingChart];

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

        // Sync Crosshair (Manual propagation)
        // Note: lightweight-charts doesn't natively sync crosshairs perfectly across instances without more complex logic.
        // For now, allow independent crosshair but sync TimeScale is the most important.
        // We will just listen to Main Chart crosshair to update ALL legends.

        chart.subscribeCrosshairMove((param) => {
            // We'll handle data lookup in the Data Effect for simplicity
        });


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

    // 2. DATA UPDATE
    useEffect(() => {
        if (!mainSeriesRef.current || !data) return;

        // Update Price
        mainSeriesRef.current.setData(data.price);

        // Update LSUR Z-Score Markers on Price Chart
        if (indicators?.lsur_markers && indicators.lsur_markers.length > 0) {
            const markers = indicators.lsur_markers
                .map(m => ({
                    time: m.time as Time,
                    position: m.position as 'aboveBar' | 'belowBar',
                    color: m.color,
                    shape: m.shape as 'arrowDown' | 'arrowUp',
                    text: '', // Empty text so it doesn't clutter the chart; we'll show it on hover.
                }))
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

        // Update RSI
        let rsiData: any[] = [];
        if (rsiSeriesRef.current && indicators?.rsi_history) {
            rsiData = indicators.rsi_history.map(item => ({
                time: item.time as Time,
                value: item.value
            }));
            rsiSeriesRef.current.setData(rsiData);
        }

        // Update CVD
        let cvdData: any[] = [];
        if (cvdSeriesRef.current && indicators?.cvd_history) {
            cvdData = indicators.cvd_history.map(item => ({
                time: item.time as Time,
                value: item.value
            }));
            cvdSeriesRef.current.setData(cvdData);
        }

        // Update OI
        let oiData: any[] = [];
        if (oiSeriesRef.current && indicators?.open_interest) {
            oiData = indicators.open_interest.map((item, index, arr) => {
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
            fundingData = data.funding.map((item) => {
                const color = item.value >= 0 ? '#10b981' : '#ef4444';
                return {
                    time: item.time as Time,
                    value: item.value,
                    color: color
                };
            });
            fundingSeriesRef.current.setData(fundingData);
        }

        // SYNC LEGENDS (Listen to Main Chart)
        if (chartRef.current) {
            chartRef.current.subscribeCrosshairMove((param) => {
                // Handle Marker Tooltip (show when hovering over a marker time)
                if (param.time && param.point && indicators?.lsur_markers) {
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
                } else {
                    setHoveredMarker(null);
                }

                if (param.time) {
                    // Find matching points in other datasets
                    const rsiPoint = rsiData.find(p => p.time === param.time);
                    if (rsiPoint) setRsiLegendValue(rsiPoint.value);
                    else setRsiLegendValue(null);

                    const cvdPoint = cvdData.find(p => p.time === param.time);
                    if (cvdPoint) setCvdLegendValue(cvdPoint.value);
                    else setCvdLegendValue(null);

                    const oiPoint = oiData.find(p => p.time === param.time);
                    if (oiPoint) setOiLegendValue(oiPoint.value);
                    else setOiLegendValue(null);

                    const fundingPoint = fundingData.find(p => p.time === param.time);
                    if (fundingPoint) setFundingLegendValue(fundingPoint.value);
                    else setFundingLegendValue(null);

                } else {
                    setRsiLegendValue(null);
                    setCvdLegendValue(null);
                    setOiLegendValue(null);
                    setFundingLegendValue(null);
                }
            });
        }

        // Draw Grid Lines (Only on Price Chart)
        const series = mainSeriesRef.current;
        if (series) {
            gridLinesRef.current.forEach(l => series.removePriceLine(l));
            gridLinesRef.current = [];

            gridLines.forEach((price) => {
                const line = series.createPriceLine({
                    price: price,
                    color: '#eab308',
                    lineWidth: 1,
                    lineStyle: 0,
                    axisLabelVisible: false,
                    title: 'Grid',
                });
                gridLinesRef.current.push(line);
            });
        }

    }, [data, indicators, gridLines]);

    return (
        <div className="w-full flex flex-col gap-1 bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden shadow-lg p-1">
            {/* 1. Main Chart */}
            <div className="relative w-full h-[400px]">
                {/* Marker Hover Tooltip */}
                {hoveredMarker && (
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

            {/* 2. RSI Chart */}
            <div className="relative w-full h-[80px] border-t border-zinc-800">
                <div className="absolute top-1 left-2 z-10 bg-black/50 px-2 py-0.5 rounded text-[10px] text-zinc-400 flex gap-2">
                    <span className="font-bold text-purple-400">RSI (14)</span><InfoTooltip text="相對強弱指數：衡量價格動能的振盪指標。RSI > 70 = 超買（可能回落），RSI < 30 = 超賣（可能反彈）。用於偵測短期價格極端" />
                    <span className="text-zinc-600 text-[9px]">30</span>
                    <span className="text-zinc-600 text-[9px]">70</span>
                    {rsiLegendValue !== null && (
                        <span className={`font-mono ${rsiLegendValue > 70 ? 'text-red-400' : rsiLegendValue < 30 ? 'text-emerald-400' : 'text-zinc-200'}`}>
                            {rsiLegendValue.toFixed(0)}
                        </span>
                    )}
                </div>
                <div ref={rsiContainerRef} className="w-full h-full" />
            </div>

            {/* 3. CVD Chart */}
            <div className="relative w-full h-[100px] border-t border-zinc-800">
                <div className="absolute top-1 left-2 z-10 bg-black/50 px-2 py-0.5 rounded text-[10px] text-zinc-400 flex gap-2">
                    <span className="font-bold text-yellow-500">CVD (Volume Delta)</span><InfoTooltip text="累積成交量差值：追蹤主動買入與賣出的淨差額。上升 = 買方主導，下降 = 賣方主導。反映真實資金流向" />
                    {cvdLegendValue !== null && (
                        <span className="text-zinc-200">{cvdLegendValue.toLocaleString()}</span>
                    )}
                </div>
                <div ref={cvdContainerRef} className="w-full h-full" />
            </div>

            {/* 3. OI Chart */}
            <div className="relative w-full h-[100px] border-t border-zinc-800">
                <div className="absolute top-1 left-2 z-10 bg-black/50 px-2 py-0.5 rounded text-[10px] text-zinc-400 flex gap-2">
                    <span className="font-bold text-blue-400">Open Interest</span><InfoTooltip text="未平倉合約量：市場中所有未結算的合約總值。綠色 = OI 增加（新倉位開設），紅色 = OI 減少（倉位平倉/清算）。注意：OI 本身無法區分多空方向，需搭配 LSUR/CVD 判斷實際偏向" />
                    {oiLegendValue !== null && (
                        <span className="text-zinc-200">{oiLegendValue.toLocaleString()}</span>
                    )}
                </div>
                <div ref={oiContainerRef} className="w-full h-full" />
            </div>

            {/* 4. Funding Chart */}
            <div className="relative w-full h-[100px] border-t border-zinc-800">
                <div className="absolute top-1 left-2 z-10 bg-black/50 px-2 py-0.5 rounded text-[10px] text-zinc-400 flex gap-2">
                    <span className="font-bold text-emerald-400">Funding Rate</span><InfoTooltip text="資金費率：多頭和空頭之間定期支付的費用。正值 = 多頭付費給空頭（看漲情緒高），負值 = 空頭付費給多頭（看跌情緒高）" />
                    {fundingLegendValue !== null && (
                        <span className={`${fundingLegendValue >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {fundingLegendValue.toFixed(4)}%
                        </span>
                    )}
                </div>
                <div ref={fundingContainerRef} className="w-full h-full" />
            </div>
        </div>
    );
}
