"use client"

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Cell } from 'recharts';

interface FundingProps {
    data: {
        time: number;
        value: number;
    }[];
}

export const FundingChart = ({ data }: FundingProps) => {

    // Format time for tooltip
    const formattedData = data.map(d => ({
        ...d,
        date: new Date(d.time * 1000).toLocaleDateString() + ' ' + new Date(d.time * 1000).getHours() + ':00'
    }));

    return (
        <div className="w-full h-[250px] border border-zinc-800 rounded-lg bg-zinc-900/50 p-4 mt-4">
            <h3 className="text-sm font-semibold text-zinc-400 mb-2">Funding Rate Heatmap</h3>
            <ResponsiveContainer width="100%" height="100%">
                <BarChart data={formattedData}>
                    <XAxis
                        dataKey="date"
                        hide
                    />
                    <YAxis
                        hide
                        domain={['auto', 'auto']}
                    />
                    <Tooltip
                        contentStyle={{ backgroundColor: '#18181b', borderColor: '#27272a' }}
                        itemStyle={{ color: '#e4e4e7' }}
                    />
                    <ReferenceLine y={0.01} stroke="#52525b" strokeDasharray="3 3" />
                    <Bar dataKey="value">
                        {formattedData.map((entry, index) => (
                            <Cell
                                key={`cell-${index}`}
                                fill={entry.value > 0.01 ? '#ef4444' : (entry.value < 0 ? '#22c55e' : '#3f3f46')}
                            />
                        ))}
                    </Bar>
                </BarChart>
            </ResponsiveContainer>
        </div>
    );
};
