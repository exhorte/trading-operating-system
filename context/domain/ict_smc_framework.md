# ICT/SMC Framework

## Purpose

The ICT/SMC framework is an analysis engine. It does not execute trades by itself.

It transforms market data into structured features and context.

## Target Engines

Price Engine:

- OHLC
- tick data
- ATR
- spread
- tick size
- symbol metadata

Swing Engine:

- swing highs
- swing lows
- fractal points
- internal/external swings

Market Structure Engine:

- BOS
- CHOCH
- MSS
- trend
- range
- transition

Liquidity Engine:

- buy-side liquidity
- sell-side liquidity
- equal highs/lows
- previous day high/low
- internal/external liquidity
- swept liquidity

PD Array Engine:

- fair value gaps
- inverse FVG
- order blocks
- breaker blocks
- mitigation blocks
- balanced price ranges
- rejection blocks
- volume imbalances

Premium Discount Engine:

- 50%
- premium
- discount
- OTE
- consequent encroachment

SMT Engine:

- divergence between correlated assets such as Gold/Silver, Gold/DXY, EURUSD/DXY, indices, BTC.

Session Engine:

- Sydney
- Tokyo
- London
- New York
- Silver Bullet windows
- lunch
- London close
- power hour

News And Macro Engine:

- NFP
- CPI
- FOMC
- PPI
- PCE
- PMI
- high-impact USD events

Bias Engine:

- merges structure, liquidity, SMT, macro, sessions, and PD arrays.

Scoring Engine:

- converts qualitative concepts into weighted, testable features.

Entry Engine:

- models sequences such as sweep -> displacement -> FVG/OB -> retracement -> execution candidate.

Trade Management Engine:

- SL
- TP
- break-even
- trailing
- partial close
- scale-out

Analytics Engine:

- stores why a trade was considered or executed.

## Required Output Shape

The framework should eventually return a `MarketContext` object, not dozens of unrelated booleans.

