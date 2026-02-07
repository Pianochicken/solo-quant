import { Info } from 'lucide-react';
import { useState } from 'react';

export const InfoTooltip = ({ text }: { text: string }) => {
    const [visible, setVisible] = useState(false);

    return (
        <div className="relative inline-flex items-center ml-2"
            onMouseEnter={() => setVisible(true)}
            onMouseLeave={() => setVisible(false)}>
            <Info className="h-4 w-4 text-zinc-500 hover:text-emerald-500 cursor-help" />
            {visible && (
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-48 p-2 bg-zinc-800 border border-zinc-700 rounded text-xs text-zinc-200 shadow-xl z-50">
                    {text}
                    {/* Tiny triangle */}
                    <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-zinc-800"></div>
                </div>
            )}
        </div>
    );
};
