# SUT ATR Headliner 2026 — analysis and Pine v6 port

## What the two files are

- `.cs` file: only NinjaTrader's auto-generated wrapper code (the indicator cache
  factory methods). No calculation logic. The real logic lived in the compiled DLL.
- `.dll`: a protected NinjaTrader 8 vendor export. It bundles the entire standard
  NinjaTrader indicator library plus the custom `SUTATR2026` class. The custom
  class override bodies (`OnStateChange`, `OnBarUpdate`, `OnRender`, `DrawLabel`)
  were stripped to empty `ret` stubs on export, so the exact render math is not in
  the binary.

## What was recovered from surviving metadata (exact)

Class: `NinjaTrader.NinjaScript.Indicators.StartupTrading.SUTATR2026`
DisplayName: `SUT_ATR`

Internal fields:
- `R_ATR_S` (double) — the ATR value
- `PrTk` (double) — tick size
- `textBrush`, `bgBrush`, `labelFormat`, `cachedRT` — SharpDX render resources for
  drawing a text label on the chart (a "headliner")

Inputs, group `ATR Parameters`:

| Name | Type | Range | Order | Description |
|------|------|-------|-------|-------------|
| Number of Bars | int | 1 to 2147483647 | 0 | ATR Number of bars used for the ATR |
| Factor | double | 0.1 to max | 1 | ATR Multiplier |
| Plot Bars | bool | — | 2 | ATR |

Default values were set inside the stripped `OnStateChange`, so they are not
recoverable. The port uses `NumberOfBars = 14` (NinjaTrader ATR default) and
`Factor = 1.0`.

## Behavior (inferred, since render logic was stripped)

- Compute ATR over `NumberOfBars` bars. NinjaTrader ATR uses Wilder smoothing,
  which matches Pine `ta.atr` (RMA based), so the values align.
- `proj = ATR * Factor`.
- Draw a large text "headliner" label on the chart showing the ATR value (in price
  and in ticks) and the `ATR * Factor` projection.
- `Plot Bars` colors bars whose true range exceeds `proj`, flagging volatility.

## Port

`SUT_ATR_Headliner_2026.pine` — Pine Script v6. Input names, ranges, and grouping
match the recovered metadata. Lines are tagged EXACT vs INFERRED in the header so
you can confirm the display choices against your original chart.

## Limits

The bar-coloring rule and the exact label format are reconstructed, not read from
the binary. If your original colored bars on a different condition or showed a
different label, tell me the on-chart behavior and I will match it.
