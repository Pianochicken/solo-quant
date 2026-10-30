#!/usr/bin/env python3
"""
Solo-Quant Slice Packager for Deep AI Agent Review.
Generates 3 topic-based review slices in both Repomix XML and Markdown formats:
- slice_a_quant (Quant Engine & Pipeline)
- slice_b_backend (Backend Architecture & Concurrency)
- slice_c_frontend (Frontend Terminal & State)
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SLICES = {
    "slice_a_quant": {
        "title": "切片 A：量化核心與數據管線包 (Quant Engine & Pipeline)",
        "focus": [
            "時間序列零未來函數 (Zero Look-Ahead Bias)",
            "雙交易所流動性對齊 (Binance & OKX OI/Taker volume scaling & boundary alignment)",
            "狀態機記憶體生命週期 (Position Lifecycle, Ratchet Trailing Stop Floor)",
            "多層共振動態門檻演算法 (Reversion, Breakout, Capitulation, Divergence, MTF, BTC Macro)",
            "資料庫寫入防死鎖與排序機制 (PostgreSQL Deterministic Primary Key Upsert)"
        ],
        "files": [
            "api/core/indicators.py",
            "api/core/fetcher.py",
            "api/core/signal_scanner.py",
            "api/quant/signal_strategy.py",
            "api/quant/signal_backtester.py",
            "api/quant/position.py",
            "api/db/database.py",
            "api/db/crud.py",
            "api/db/models.py",
        ]
    },
    "slice_b_backend": {
        "title": "切片 B：後端架構與系統排程包 (Backend Architecture & Concurrency)",
        "focus": [
            "FastAPI 線程池 (ThreadPoolExecutor) 與非同步協程衝突防護",
            "背景定時預熱 (APScheduler Pre-warmer) 與記憶體快取競態條件 (Race Conditions)",
            "資料庫連線池耗盡防護 (SQLAlchemy QueuePool 50 connections & pool_recycle)",
            "Telegram 推播佇列、錯誤降級機制與時區動態轉換 (NEXT_PUBLIC_TIMEZONE_OFFSET)",
            "Docker 服務編排、容器環境變數與資源對齊"
        ],
        "files": [
            "api/main.py",
            "api/core/notifier.py",
            "api/core/utils/chart.py",
            "api/Dockerfile",
            "web/Dockerfile",
            "docker-compose.yml",
        ]
    },
    "slice_c_frontend": {
        "title": "切片 C：前端狀態同步與圖表渲染包 (Frontend Terminal & State)",
        "focus": [
            "Next.js 7 層圖表 (Lightweight Charts Canvas) 記憶體釋放與響應式重繪",
            "十字線跨圖表高頻訂閱防抖 (Crosshair Sync) 與指標連動效能",
            "五幣種宏觀強弱與四象限雷達列狀態同步 (點擊切換、60s 自動輪詢、防冒泡)",
            "前端資料契約 (API Contracts) 與 TypeScript 型別定義對齊",
            "回測頁面 (Backtester) 時間框架、適應性期間與實證最佳化風控參數連動"
        ],
        "files": [
            "web/app/page.tsx",
            "web/app/backtest/page.tsx",
            "web/components/AdvancedChart.tsx",
            "web/components/SentimentPanel.tsx",
            "web/components/InfoTooltip.tsx",
            "web/components/SignalSettingsModal.tsx",
            "web/lib/api.ts",
        ]
    }
}

def export_slice_xml(slice_id: str, slice_info: dict, out_path: Path):
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(f'<repomix_bundle title="{slice_info["title"]}">\n')
        f.write('  <review_focus>\n')
        for focus in slice_info["focus"]:
            f.write(f'    <point>{focus}</point>\n')
        f.write('  </review_focus>\n')
        f.write('  <files>\n')
        for rel_file in slice_info["files"]:
            file_path = ROOT / rel_file
            if not file_path.exists():
                print(f"⚠️ Warning: {rel_file} does not exist.")
                continue
            content = file_path.read_text(encoding='utf-8', errors='replace')
            f.write(f'    <file path="{rel_file}">\n')
            f.write('<![CDATA[\n')
            f.write(content)
            if not content.endswith('\n'):
                f.write('\n')
            f.write(']]>\n')
            f.write('    </file>\n')
        f.write('  </files>\n')
        f.write('</repomix_bundle>\n')
    print(f"✅ Generated XML: {out_path.name} ({out_path.stat().st_size / 1024:.1f} KB)")

def export_slice_markdown(slice_id: str, slice_info: dict, out_path: Path):
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"# {slice_info['title']}\n\n")
        f.write("## 🎯 審核核心重點 (Review Focus)\n")
        for i, focus in enumerate(slice_info["focus"], 1):
            f.write(f"{i}. **{focus}**\n")
        f.write("\n## 📁 包含檔案清單\n")
        for rel_file in slice_info["files"]:
            f.write(f"- `{rel_file}`\n")
        f.write("\n---\n\n")
        f.write("## 📄 原始碼檔案內容\n\n")
        for rel_file in slice_info["files"]:
            file_path = ROOT / rel_file
            if not file_path.exists():
                continue
            ext = file_path.suffix.lstrip('.')
            lang = 'python' if ext == 'py' else ('typescript' if ext in ('ts', 'tsx') else ('yaml' if ext in ('yml', 'yaml') else ext))
            if file_path.name == 'Dockerfile':
                lang = 'dockerfile'
            f.write(f"### File: `{rel_file}`\n\n")
            f.write(f"```{lang}\n")
            f.write(file_path.read_text(encoding='utf-8', errors='replace'))
            if not f.tell() or True:
                f.write("\n")
            f.write("```\n\n")
    print(f"✅ Generated Markdown: {out_path.name} ({out_path.stat().st_size / 1024:.1f} KB)")

if __name__ == '__main__':
    print("🚀 Packaging 3 Review Slices for Solo-Quant...")
    for s_id, s_info in SLICES.items():
        xml_out = ROOT / f"{s_id}.xml"
        md_out = ROOT / f"{s_id}.md"
        export_slice_xml(s_id, s_info, xml_out)
        export_slice_markdown(s_id, s_info, md_out)
    print("\n🎉 All slices generated successfully in project root!")
