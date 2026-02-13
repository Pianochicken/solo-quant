import { Info } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';

export const InfoTooltip = ({ text }: { text: string }) => {
    const [visible, setVisible] = useState(false);
    const [position, setPosition] = useState({ top: 0, left: 0 });
    const iconRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (visible && iconRef.current) {
            const rect = iconRef.current.getBoundingClientRect();
            const tooltipWidth = 200; // 估計 tooltip 寬度
            const tooltipHeight = 80; // 估計 tooltip 高度

            // 預設在 icon 上方置中
            let top = rect.top - tooltipHeight - 8;
            let left = rect.left + rect.width / 2 - tooltipWidth / 2;

            // 如果超出右側邊界，向左對齊
            if (left + tooltipWidth > window.innerWidth - 10) {
                left = window.innerWidth - tooltipWidth - 10;
            }

            // 如果超出左側邊界，向右對齊
            if (left < 10) {
                left = 10;
            }

            // 如果超出上方邊界，顯示在下方
            if (top < 10) {
                top = rect.bottom + 8;
            }

            setPosition({ top, left });
        }
    }, [visible]);

    return (
        <>
            <div
                ref={iconRef}
                className="relative inline-flex items-center ml-2"
                onMouseEnter={() => setVisible(true)}
                onMouseLeave={() => setVisible(false)}
            >
                <Info className="h-4 w-4 text-zinc-500 hover:text-emerald-500 cursor-help" />
            </div>
            {visible && createPortal(
                <div
                    className="fixed w-[200px] p-2 bg-zinc-800 border border-zinc-700 rounded text-xs text-zinc-200 shadow-xl z-[9999] pointer-events-none"
                    style={{
                        top: `${position.top}px`,
                        left: `${position.left}px`,
                    }}
                >
                    {text}
                </div>,
                document.body
            )}
        </>
    );
};
