import { Info } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';

interface InfoTooltipProps {
    text: string;
    className?: string;
    iconClassName?: string;
    width?: number;
}

export const InfoTooltip = ({ text, className, iconClassName, width = 240 }: InfoTooltipProps) => {
    const [visible, setVisible] = useState(false);
    const [position, setPosition] = useState({ top: 0, left: 0 });
    const iconRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (visible && iconRef.current) {
            const rect = iconRef.current.getBoundingClientRect();
            const tooltipWidth = width;
            const tooltipHeight = 90; // 預估高度

            // 預設在 icon 上方置中
            let top = rect.top - tooltipHeight - 8;
            let left = rect.left + rect.width / 2 - tooltipWidth / 2;

            // 如果超出右側邊界，向左對齊
            if (left + tooltipWidth > window.innerWidth - 12) {
                left = window.innerWidth - tooltipWidth - 12;
            }

            // 如果超出左側邊界，向右對齊
            if (left < 12) {
                left = 12;
            }

            // 如果超出上方邊界，顯示在下方
            if (top < 12) {
                top = rect.bottom + 8;
            }

            setPosition({ top, left });
        }
    }, [visible, width]);

    return (
        <>
            <div
                ref={iconRef}
                className={`relative inline-flex items-center ${className ?? 'ml-1.5'}`}
                onMouseEnter={() => setVisible(true)}
                onMouseLeave={() => setVisible(false)}
                onClick={(e) => {
                    e.stopPropagation();
                    e.preventDefault();
                }}
                onMouseDown={(e) => {
                    e.stopPropagation();
                }}
            >
                <Info className={iconClassName ?? "h-3.5 w-3.5 text-zinc-500 hover:text-purple-400 cursor-help transition-colors"} />
            </div>
            {visible && typeof document !== 'undefined' && createPortal(
                <div
                    className="fixed p-2.5 bg-zinc-900/95 border border-zinc-700/80 rounded-lg text-xs leading-relaxed text-zinc-200 shadow-2xl z-[9999] pointer-events-none whitespace-pre-wrap font-sans backdrop-blur-md"
                    style={{
                        top: `${position.top}px`,
                        left: `${position.left}px`,
                        width: `${width}px`,
                    }}
                >
                    {text}
                </div>,
                document.body
            )}
        </>
    );
};
