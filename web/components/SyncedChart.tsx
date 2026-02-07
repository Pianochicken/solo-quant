"use client"

import { useEffect, useRef } from 'react';
import { createChart, ColorType, IChartApi, CandlestickSeries, HistogramSeries, ISeriesApi } from 'lightweight-charts';

interface SyncedChartProps {
    priceData: {
        time: number;
        open: number;
        high: number;
        low: number;
        close: number;
    }[];
    fundingData: {
        time: number;
        value: number;
    }[];
    colors?: {
        backgroundColor?: string;
        lineColor?: string;
        textColor?: string;
    };
    gridLines?: number[]; // [NEW] List of prices to draw
}

export const SyncedChart = ({ priceData, fundingData, colors, gridLines = [] }: SyncedChartProps) => {
    const mainChartContainerRef = useRef<HTMLDivElement>(null);
    const subChartContainerRef = useRef<HTMLDivElement>(null);

    // Refs to hold chart instances
    const mainChartRef = useRef<IChartApi | null>(null);
    const subChartRef = useRef<IChartApi | null>(null);
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const fundingSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

    // Store price line objects to clear them later
    const activePriceLinesRef = useRef<any[]>([]);

    // Track if we have already fitted content once
    const isFittedRef = useRef(false);

    // 1. Initialize Charts (Run once on mount)
    useEffect(() => {
        if (!mainChartContainerRef.current || !subChartContainerRef.current) return;

        // Prevent double initialization in Strict Mode
        if (mainChartRef.current) return;

        console.log('[SyncedChart] Initializing Charts...');

        // --- Create Main Chart ---
        const mainChart = createChart(mainChartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: 'transparent' },
                textColor: colors?.textColor || '#D9D9D9',
            },
            grid: {
                vertLines: { color: '#2B2B43' },
                horzLines: { color: '#2B2B43' },
            },
            width: mainChartContainerRef.current.clientWidth,
            height: 400,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
            },
        });

        const candleSeries = mainChart.addSeries(CandlestickSeries, {
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderVisible: false,
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
        });

        // --- Create Sub Chart ---
        const subChart = createChart(subChartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: 'transparent' },
                textColor: colors?.textColor || '#D9D9D9',
            },
            grid: {
                vertLines: { color: '#2B2B43' },
                horzLines: { color: '#2B2B43' },
            },
            width: subChartContainerRef.current.clientWidth,
            height: 150,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
            },
        });

        const fundingSeries = subChart.addSeries(HistogramSeries, {
            color: '#26a69a',
            priceFormat: {
                type: 'price',
                precision: 6,
                minMove: 0.000001,
            },
        });

        // --- Synchronization ---
        mainChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
            if (range) subChart.timeScale().setVisibleLogicalRange(range);
        });

        subChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
            if (range) mainChart.timeScale().setVisibleLogicalRange(range);
        });

        // Store refs
        mainChartRef.current = mainChart;
        subChartRef.current = subChart;
        candleSeriesRef.current = candleSeries;
        fundingSeriesRef.current = fundingSeries;

        // Resize Observer
        const handleResize = () => {
            if (mainChartContainerRef.current && mainChartRef.current) {
                mainChartRef.current.applyOptions({ width: mainChartContainerRef.current.clientWidth });
            }
            if (subChartContainerRef.current && subChartRef.current) {
                subChartRef.current.applyOptions({ width: subChartContainerRef.current.clientWidth });
            }
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            mainChart.remove();
            subChart.remove();
            mainChartRef.current = null;
            subChartRef.current = null;
        };
    }, []); // Empty dependency array = run once on mount

    // 2. Update Data (Run whenever data changes)
    useEffect(() => {
        if (!candleSeriesRef.current || !fundingSeriesRef.current) return;
        if (priceData.length === 0) return;

        // Update Candle Data
        candleSeriesRef.current.setData(priceData as any);

        // Update Funding Data
        const coloredFundingData = fundingData.map(d => ({
            time: d.time,
            value: d.value,
            color: d.value > 0.03 ? '#ef4444' : (d.value < 0 ? '#22c55e' : '#3f3f46')
        }));
        fundingSeriesRef.current.setData(coloredFundingData as any);

        // Initial fit content
        if (!isFittedRef.current && mainChartRef.current) {
            mainChartRef.current.timeScale().fitContent();
            isFittedRef.current = true;
        }
    }, [priceData, fundingData]);

    // 3. Update Grid Lines (Run whenever gridLines changes)
    useEffect(() => {
        if (!candleSeriesRef.current) return;

        // Clear existing lines
        activePriceLinesRef.current.forEach(line => {
            candleSeriesRef.current?.removePriceLine(line);
        });
        activePriceLinesRef.current = [];

        // Add new lines
        gridLines.forEach(price => {
            const line = candleSeriesRef.current?.createPriceLine({
                price: price,
                color: '#F0B90B', // Bright Crypto Yellow
                lineWidth: 1, // Thinner for better scaling
                lineStyle: 2, // Dashed
                axisLabelVisible: true,
                title: '',
            });
            if (line) activePriceLinesRef.current.push(line);
        });
    }, [gridLines]);

    return (
        <div className="w-full flex flex-col gap-1 bg-zinc-900/50 border border-zinc-800 rounded-lg p-2">
            <div ref={mainChartContainerRef} className="w-full relative h-[400px]" />
            <div className="px-2 text-xs text-zinc-500 font-semibold flex justify-between">
                <span>Funding Rate (%)</span>
            </div>
            <div ref={subChartContainerRef} className="w-full relative h-[150px]" />
        </div>
    );
};
