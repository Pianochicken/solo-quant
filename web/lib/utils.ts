import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs))
}

export function getPricePrecision(price: number, symbol?: string) {
    if (symbol && (symbol.toUpperCase().includes('CC/USDT') || symbol.toUpperCase().includes('CC-USDT'))) {
        return { precision: 5, minMove: 0.00001 };
    }

    const normalizedPrice = Number.isFinite(price) ? Math.abs(price) : 0;
    if (normalizedPrice <= 0) return { precision: 2, minMove: 0.01 };

    if (normalizedPrice < 0.001) return { precision: 7, minMove: 0.0000001 };
    if (normalizedPrice < 0.1) return { precision: 5, minMove: 0.00001 };
    if (normalizedPrice < 1) return { precision: 4, minMove: 0.0001 };
    if (normalizedPrice < 10) return { precision: 3, minMove: 0.001 };
    return { precision: 2, minMove: 0.01 };
}
