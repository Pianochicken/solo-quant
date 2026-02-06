---
name: Quantitative Trading Development
description: Best practices and guidelines for building robust quantitative trading systems, specifically Grid Trading and Automations.
---

# Quantitative Trading Development Skill

This skill outlines the professional approach to building a Quantitative Trading Platform like "SoloQuant".

## 1. System Architecture: The "Loop"
A robust quant system consists of three distinct layers. Do not mix them.

1.  **Data Layer (The Source)**
    *   **Responsibility**: Fetching raw data (Price, Orderbook, Account Balance).
    *   **Rule**: Normalize all data into a standard format (e.g., Pandas DataFrame or strict Pydantic models). Never pass raw API responses to strategies.
    *   **Key Tech**: `ccxt`, `pandas`.

2.  **Strategy Layer (The Brain)**
    *   **Responsibility**: Pure logic. Inputs -> Decision.
    *   **Rule**: **Stateless** (ideally). Given `MarketData` and `CurrentPositions`, it should output `TargetPositions` or `Signals`.
    *   **Grid Logic**:
        *   Calculate Grid Levels (Geometric vs Arithmetic).
        *   Identify necessary orders (Buy Low, Sell High).
        *   Output: "Place Buy Limit @ 60000, Place Sell Limit @ 61000".

3.  **Execution Layer (The Hands)**
    *   **Responsibility**: interacting with the Exchange.
    *   **Rule**: **Idempotency**. If I tell you to "Place Buy @ 60000" twice, you should check if it exists first.
    *   **Safety**: Rate limiting, signature handling, double-checking leverage settings.

## 2. Grid Trading Specifics
Grid trading requires precise state management.

### Data Structures
Use a structured object for the Grid:
```python
class GridBot:
    upper_price: float
    lower_price: float
    grid_count: int
    active_orders: List[Order] # Track what is live
```

### The Workflow
1.  **Cancel All**: On startup (or reset), cancel open orders to ensure a clean slate.
2.  **Plan**: Calculate where lines *should* be.
3.  **Diff**: Compare "Should be" with "Actual Open Orders".
4.  **Execute**: Place missing orders.

## 3. Backtesting (Verification)
Before running live, a strategy must be backtested.

*   **Vectorized Backtesting (Fast)**: Use Pandas to calculate PnL over the entire history array at once. Good for initial validation.
*   **Event-Driven Backtesting (Accurate)**: Simulate the loop (see Section 1) candle-by-candle. Good for Grid Trading to test "fill" probabilities.

## 4. Safety First Rules
*   **Dry Run Mode**: Always implement a flag `dry_run=True` where orders are printed, not sent.
*   **Stop Loss**: Hard-coded emergency close if price deviates X% from grid.
*   **Exception Handling**: Network errors happen. The bot must retry, not crash.

## 5. User Interface (Frontend)
Quant UIs differ from regular trading UIs.
*   **Visualization**: Show the **Grid Lines** explicitly on the chart.
*   **Performance**: Show Realized PnL (from grid arbs) vs Unrealized PnL (holding value).
*   **Control**: "Start", "Stop", "Panic Close" buttons are essential.
