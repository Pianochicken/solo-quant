import { useEffect, useRef } from 'react';
import { createChart, ColorType, IChartApi, CandlestickSeries } from 'lightweight-charts';

interface ChartProps {
    data: {
        time: number;
        open: number;
        high: number;
        low: number;
        close: number;
    }[];
}

export const CandleChart = ({ data }: ChartProps) => {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);

    useEffect(() => {
        if (!chartContainerRef.current) return;

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: 'transparent' },
                textColor: '#D9D9D9',
            },
            grid: {
                vertLines: { color: '#2B2B43' },
                horzLines: { color: '#2B2B43' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 400,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
            },
        });

        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderVisible: false,
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
        });

        // Cast data to any to bypass strict 'Time' type checking for simple unix timestamps
        // lightweight-charts v5 accepts seconds (UTCTimestamp) which is number, but TS needs assertion
        candleSeries.setData(data as any);

        // Fit content
        chart.timeScale().fitContent();

        chartRef.current = chart;

        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [data]);

    return (
        <div className="w-full h-[400px] border border-zinc-800 rounded-lg bg-zinc-900/50 p-4 relative">
            <div ref={chartContainerRef} className="absolute inset-0 top-4 left-2 right-2 bottom-2" />
        </div>
    );
};
