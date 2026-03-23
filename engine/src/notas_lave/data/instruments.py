"""
Instrument specifications — pip values, lot sizes, spread, and contract details.

This is Fix #2 from the critical fixes plan. Every instrument has different
characteristics that affect position sizing, P&L calculation, and risk.

SPOT vs FUTURES:
- FundingPips trades SPOT (CFD) instruments, not futures
- XAUUSD = spot gold (no expiry, trades 24/5)
- GC=F = gold FUTURES (COMEX, has expiry, different price)
- We must use spot data, not futures

COINDCX INSTRUMENTS:
- BTCUSDT / ETHUSDT = crypto perpetual futures on CoinDCX
- Traded in USDT (≈ USD), margins can be in INR
- CoinDCX fees: 0.02% maker, 0.04% taker (futures)
- Leverage up to 15x on crypto futures

PIP VALUE:
- A "pip" is the smallest standard price movement
- Gold: 1 pip = $0.01, but a $1 move on 1 lot (100 oz) = $100
- Forex: 1 pip = 0.0001 for most pairs
- Crypto: 1 pip = $0.01 for BTC (we use USDT pricing)
- Getting this wrong means risking 10x or 100x what you intended

LEVERAGE POSITION SIZING:
With leverage, position size is limited by TWO constraints:
1. Risk budget: How much can you lose on this trade? (same as without leverage)
2. Margin requirement: Does notional_value / leverage fit in your available balance?
The position size is the MINIMUM of these two constraints.
"""

from dataclasses import dataclass


# MM-02: Session-based spread multipliers per instrument.
# Spreads widen during low-liquidity sessions and narrow during active ones.
SPREAD_MULTIPLIERS: dict[str, dict[str, float]] = {
    "XAUUSD": {
        "asian": 2.5,      # 0-7 UTC: low liquidity for metals
        "london": 0.8,     # 8-11 UTC: London open, good liquidity
        "overlap": 0.6,    # 12-16 UTC: London+NY overlap, tightest spreads
        "newyork": 1.0,    # 17-21 UTC: NY session
        "late": 1.5,       # 22-23 UTC: low liquidity
    },
    "XAGUSD": {
        "asian": 2.5,
        "london": 0.8,
        "overlap": 0.6,
        "newyork": 1.0,
        "late": 1.5,
    },
    "BTCUSD": {
        "active": 0.7,     # High volume hours
        "quiet": 1.5,      # Low volume hours
        "weekend": 2.0,    # Saturday/Sunday: wider spreads
    },
    "ETHUSD": {
        "active": 0.7,
        "quiet": 1.5,
        "weekend": 2.0,
    },
    "BTCUSDT": {
        "active": 0.7,
        "quiet": 1.5,
        "weekend": 2.0,
    },
    "ETHUSDT": {
        "active": 0.7,
        "quiet": 1.5,
        "weekend": 2.0,
    },
    # MM-A03 FIX: Default multipliers for all other crypto instruments.
    # Without these, lab instruments use constant spread_typical at all hours.
    "_crypto_default": {
        "active": 0.7,
        "quiet": 1.5,
        "weekend": 2.0,
    },
}


def _get_metals_session(hour_utc: int) -> str:
    """Determine metals trading session from UTC hour."""
    if 0 <= hour_utc <= 7:
        return "asian"
    elif 8 <= hour_utc <= 11:
        return "london"
    elif 12 <= hour_utc <= 16:
        return "overlap"
    elif 17 <= hour_utc <= 21:
        return "newyork"
    else:
        return "late"


def _get_crypto_session(hour_utc: int, day_of_week: int) -> str:
    """
    Determine crypto session. day_of_week: 0=Monday, 6=Sunday.
    Active hours: 12-21 UTC (US/Europe overlap). Weekend = Sat/Sun.
    """
    if day_of_week >= 5:  # Saturday=5, Sunday=6
        return "weekend"
    elif 12 <= hour_utc <= 21:
        return "active"
    else:
        return "quiet"


@dataclass(frozen=True)
class InstrumentSpec:
    """Specification for a tradeable instrument."""
    symbol: str
    name: str
    pip_size: float           # Minimum price increment that matters
    contract_size: float      # Units per 1.0 lot
    pip_value_per_lot: float  # Dollar value of 1 pip move on 1 standard lot
    min_lot: float            # Minimum position size
    max_lot: float            # Maximum position size
    lot_step: float           # Lot size increment
    spread_typical: float     # Typical spread in price units (not pips)
    margin_pct: float         # Margin requirement (1/leverage)
    sessions: str             # When this instrument trades
    # CoinDCX-specific
    maker_fee_pct: float = 0.0     # Maker fee as decimal (0.0002 = 0.02%)
    taker_fee_pct: float = 0.0     # Taker fee as decimal
    max_leverage: float = 1.0      # Maximum allowed leverage
    currency: str = "USD"          # Quote currency (USD or USDT)
    min_notional: float = 0.0      # Minimum order value in quote currency (exchange requirement)
    # MM-01: Per-instrument slippage in ticks (1 tick = pip_size)
    # Slippage makes SL fills WORSE and TP fills slightly worse, modeling
    # real-world order book gaps during fast moves.
    slippage_ticks: int = 0        # Default 0; overridden per instrument below

    def get_spread(self, hour_utc: int | None = None, day_of_week: int | None = None) -> float:
        """
        MM-02: Get session-adjusted spread.

        If hour_utc is None, returns spread_typical (backward compatible).
        Otherwise applies session multiplier based on time of day.

        Args:
            hour_utc: Hour in UTC (0-23). None = use static spread.
            day_of_week: 0=Monday, 6=Sunday. Used for crypto weekend detection.
        """
        if hour_utc is None:
            return self.spread_typical

        multipliers = SPREAD_MULTIPLIERS.get(self.symbol)
        # MM-A03: Fall back to crypto default if no instrument-specific multipliers
        if not multipliers:
            multipliers = SPREAD_MULTIPLIERS.get("_crypto_default")
        if not multipliers:
            return self.spread_typical

        # Determine session
        metals = {"XAUUSD", "XAGUSD"}
        if self.symbol in metals:
            session = _get_metals_session(hour_utc)
        else:
            session = _get_crypto_session(hour_utc, day_of_week if day_of_week is not None else 0)

        mult = multipliers.get(session, 1.0)
        return self.spread_typical * mult

    def pips_to_price(self, pips: float) -> float:
        """Convert pip count to price movement."""
        return pips * self.pip_size

    def price_to_pips(self, price_diff: float) -> float:
        """Convert price movement to pip count."""
        return price_diff / self.pip_size if self.pip_size > 0 else 0

    def calculate_pnl(self, entry: float, exit: float, lots: float, direction: str) -> float:
        """
        Calculate P&L for a closed trade.

        For Gold: 1 lot = 100 oz. A $1 move = $100 per lot.
        For BTC:  1 lot = 1 BTC. A $1 move = $1 per lot.
        """
        if direction == "LONG":
            price_diff = exit - entry
        else:
            price_diff = entry - exit

        return price_diff * self.contract_size * lots

    def calculate_trading_fee(self, entry: float, lots: float, is_maker: bool = False) -> float:
        """
        Calculate trading fee for an order.

        CoinDCX charges maker/taker fees on the notional value.
        FundingPips/MT5 fees are baked into the spread, so this returns 0.
        """
        fee_pct = self.maker_fee_pct if is_maker else self.taker_fee_pct
        notional = entry * self.contract_size * lots
        return notional * fee_pct

    def calculate_position_size(
        self,
        entry: float,
        stop_loss: float,
        account_balance: float,
        risk_pct: float = 0.01,
        leverage: float = 1.0,
    ) -> float:
        """
        Calculate position size with leverage support.

        TWO constraints checked:
        1. Risk budget: How many lots so that if SL is hit, we lose risk_pct of balance
        2. Margin requirement: Does notional / leverage fit in available balance

        The position size is the MINIMUM of these two.

        Example (BTC, 1000 INR ≈ $12 balance, 2% risk, 15x leverage, $300 SL):
        - Risk amount = $12 * 0.02 = $0.24
        - Loss per lot = $300 * 1 = $300
        - Lots from risk = $0.24 / $300 = 0.0008 BTC
        - Notional = 0.0008 * $85,000 = $68
        - Margin needed = $68 / 15 = $4.53 → fits in $12 balance ✓
        """
        risk_amount = account_balance * risk_pct
        price_risk = abs(entry - stop_loss)

        if price_risk <= 0 or entry <= 0:
            return 0.0

        # Constraint 1: Risk budget
        loss_per_lot = price_risk * self.contract_size
        lots_from_risk = risk_amount / loss_per_lot

        # Constraint 2: Margin requirement (only matters with leverage)
        effective_leverage = min(leverage, self.max_leverage)
        if effective_leverage > 1:
            notional_per_lot = entry * self.contract_size
            margin_per_lot = notional_per_lot / effective_leverage
            lots_from_margin = account_balance / margin_per_lot if margin_per_lot > 0 else lots_from_risk
            # Use 80% of max margin to leave buffer for fees + price movement
            lots_from_margin *= 0.80
        else:
            lots_from_margin = lots_from_risk  # No leverage constraint

        # Take the smaller of the two constraints
        lots = min(lots_from_risk, lots_from_margin)

        # Round to lot step
        lots = round(lots / self.lot_step) * self.lot_step
        # Clamp to min/max
        lots = max(self.min_lot, min(lots, self.max_lot))

        # P0 FIX (QR-07): If clamping to min_lot pushed actual risk above
        # the risk budget, reject the trade entirely. Without this, a $100
        # account risking 0.3% on Gold with a $5 SL would get clamped from
        # 0.0006 lots to 0.01 lots — turning 0.3% risk into 5% risk.
        actual_risk = lots * price_risk * self.contract_size
        if actual_risk > risk_amount * 1.01:  # 1% tolerance for floating-point rounding
            return 0.0

        # P1 FIX (AT-14): Check minimum notional value requirement.
        # Exchanges like CoinDCX reject orders below a minimum order value.
        # If the computed position doesn't meet the minimum, reject it rather
        # than letting it fail at the exchange.
        if self.min_notional > 0:
            notional_value = lots * entry * self.contract_size
            if notional_value < self.min_notional:
                return 0.0

        return round(lots, 6)

    def calculate_liquidation_price(
        self, entry: float, lots: float, balance: float,
        leverage: float, direction: str,
    ) -> float:
        """
        Calculate approximate liquidation price.

        You get liquidated when unrealized loss exceeds your margin.
        Margin = notional / leverage. When loss = margin, you're liquidated.

        This is critical for leveraged trading — if your SL is beyond the
        liquidation price, you'll get liquidated before your SL triggers.
        """
        notional = entry * self.contract_size * lots
        margin = notional / leverage if leverage > 0 else balance

        # Use actual margin or balance, whichever is smaller
        available_margin = min(margin, balance)
        loss_per_unit = available_margin / (self.contract_size * lots) if lots > 0 else 0

        if direction == "LONG":
            return entry - loss_per_unit
        else:
            return entry + loss_per_unit

    def apply_spread(self, price: float, direction: str) -> float:
        """
        Apply spread to get realistic fill price.

        LONG (buy): you pay the ASK = price + half spread (worse for you)
        SHORT (sell): you get the BID = price - half spread (worse for you)
        """
        half_spread = self.spread_typical / 2
        if direction == "LONG":
            return price + half_spread
        else:
            return price - half_spread

    def breakeven_price(self, entry: float, direction: str) -> float:
        """
        True breakeven accounting for spread.
        Moving SL to entry_price is NOT breakeven — you'd lose the spread.
        True breakeven = entry + spread for longs, entry - spread for shorts.
        """
        if direction == "LONG":
            return entry + self.spread_typical
        else:
            return entry - self.spread_typical


# ---- Instrument Registry ----

INSTRUMENTS: dict[str, InstrumentSpec] = {
    # === PROP FIRM INSTRUMENTS (FundingPips / MT5) ===
    "XAUUSD": InstrumentSpec(
        symbol="XAUUSD",
        name="Gold Spot",
        pip_size=0.01,
        contract_size=100,          # 100 troy ounces per lot
        pip_value_per_lot=1.0,
        min_lot=0.01,
        max_lot=50.0,
        lot_step=0.01,
        spread_typical=0.30,        # ~30 cents typical on FundingPips
        margin_pct=0.01,            # 1% margin (100:1 leverage)
        sessions="24/5 (closed Sat-Sun)",
        slippage_ticks=3,           # MM-01: Gold — 3 ticks slippage
    ),
    "XAGUSD": InstrumentSpec(
        symbol="XAGUSD",
        name="Silver Spot",
        pip_size=0.001,
        contract_size=5000,
        pip_value_per_lot=5.0,
        min_lot=0.01,
        max_lot=50.0,
        lot_step=0.01,
        spread_typical=0.03,
        margin_pct=0.01,
        sessions="24/5 (closed Sat-Sun)",
        slippage_ticks=2,           # MM-01: Silver — 2 ticks slippage
    ),
    "BTCUSD": InstrumentSpec(
        symbol="BTCUSD",
        name="Bitcoin",
        pip_size=0.01,
        contract_size=1,            # 1 BTC per lot
        pip_value_per_lot=0.01,
        min_lot=0.01,
        max_lot=10.0,
        lot_step=0.01,
        spread_typical=15.0,        # ~$15 typical spread
        margin_pct=0.005,           # 0.5% margin (200:1)
        sessions="24/7",
        slippage_ticks=5,           # MM-01: BTC — 5 ticks slippage
    ),
    "ETHUSD": InstrumentSpec(
        symbol="ETHUSD",
        name="Ethereum",
        pip_size=0.01,
        contract_size=1,
        pip_value_per_lot=0.01,
        min_lot=0.1,
        max_lot=100.0,
        lot_step=0.1,
        spread_typical=1.50,
        margin_pct=0.005,
        sessions="24/7",
        slippage_ticks=2,           # MM-01: ETH — 2 ticks slippage
    ),

    # === PERSONAL INSTRUMENTS (CoinDCX Futures) ===
    "BTCUSDT": InstrumentSpec(
        symbol="BTCUSDT",
        name="Bitcoin Perpetual (CoinDCX)",
        pip_size=0.01,
        contract_size=1,            # 1 BTC per contract
        pip_value_per_lot=0.01,
        min_lot=0.0001,             # CoinDCX allows tiny positions
        max_lot=5.0,
        lot_step=0.0001,
        spread_typical=5.0,         # ~$5 spread on CoinDCX futures
        margin_pct=0.0667,          # 1/15 = 6.67% (15x leverage)
        sessions="24/7",
        maker_fee_pct=0.0002,       # 0.02% maker
        taker_fee_pct=0.0004,       # 0.04% taker
        max_leverage=15.0,
        currency="USDT",
        min_notional=5.0,           # CoinDCX minimum order value in USDT
        slippage_ticks=5,           # MM-01: BTCUSDT — 5 ticks slippage
    ),
    "ETHUSDT": InstrumentSpec(
        symbol="ETHUSDT",
        name="Ethereum Perpetual (CoinDCX)",
        pip_size=0.01,
        contract_size=1,            # 1 ETH per contract
        pip_value_per_lot=0.01,
        min_lot=0.001,
        max_lot=50.0,
        lot_step=0.001,
        spread_typical=1.00,        # ~$1 spread on CoinDCX
        margin_pct=0.0667,
        sessions="24/7",
        maker_fee_pct=0.0002,
        taker_fee_pct=0.0004,
        max_leverage=15.0,
        currency="USDT",
        min_notional=5.0,           # CoinDCX minimum order value in USDT
        slippage_ticks=2,           # MM-01: ETHUSDT — 2 ticks slippage
    ),
    # === LAB INSTRUMENTS (more crypto for learning) ===
    "SOLUSD": InstrumentSpec(
        symbol="SOLUSD", name="Solana",
        pip_size=0.01, contract_size=1, pip_value_per_lot=0.01,
        min_lot=0.1, max_lot=500.0, lot_step=0.1,
        spread_typical=0.10, margin_pct=0.01,
        sessions="24/7", slippage_ticks=2,
    ),
    "XRPUSD": InstrumentSpec(
        symbol="XRPUSD", name="XRP",
        pip_size=0.0001, contract_size=1, pip_value_per_lot=0.0001,
        min_lot=10.0, max_lot=50000.0, lot_step=1.0,
        spread_typical=0.002, margin_pct=0.01,
        sessions="24/7", slippage_ticks=3,
    ),
    "BNBUSD": InstrumentSpec(
        symbol="BNBUSD", name="BNB",
        pip_size=0.01, contract_size=1, pip_value_per_lot=0.01,
        min_lot=0.01, max_lot=100.0, lot_step=0.01,
        spread_typical=0.20, margin_pct=0.01,
        sessions="24/7", slippage_ticks=2,
    ),
    "DOGEUSD": InstrumentSpec(
        symbol="DOGEUSD", name="Dogecoin",
        pip_size=0.00001, contract_size=1, pip_value_per_lot=0.00001,
        min_lot=100.0, max_lot=500000.0, lot_step=1.0,
        spread_typical=0.0005, margin_pct=0.01,
        sessions="24/7", slippage_ticks=5,
    ),
    "ADAUSD": InstrumentSpec(
        symbol="ADAUSD", name="Cardano",
        pip_size=0.0001, contract_size=1, pip_value_per_lot=0.0001,
        min_lot=10.0, max_lot=100000.0, lot_step=1.0,
        spread_typical=0.002, margin_pct=0.01,
        sessions="24/7", slippage_ticks=3,
    ),
    "AVAXUSD": InstrumentSpec(
        symbol="AVAXUSD", name="Avalanche",
        pip_size=0.01, contract_size=1, pip_value_per_lot=0.01,
        min_lot=0.1, max_lot=1000.0, lot_step=0.1,
        spread_typical=0.08, margin_pct=0.01,
        sessions="24/7", slippage_ticks=2,
    ),
    "LINKUSD": InstrumentSpec(
        symbol="LINKUSD", name="Chainlink",
        pip_size=0.001, contract_size=1, pip_value_per_lot=0.001,
        min_lot=1.0, max_lot=10000.0, lot_step=0.1,
        spread_typical=0.02, margin_pct=0.01,
        sessions="24/7", slippage_ticks=2,
    ),
    "DOTUSD": InstrumentSpec(
        symbol="DOTUSD", name="Polkadot",
        pip_size=0.001, contract_size=1, pip_value_per_lot=0.001,
        min_lot=1.0, max_lot=10000.0, lot_step=0.1,
        spread_typical=0.01, margin_pct=0.01,
        sessions="24/7", slippage_ticks=2,
    ),
    "LTCUSD": InstrumentSpec(
        symbol="LTCUSD", name="Litecoin",
        pip_size=0.01, contract_size=1, pip_value_per_lot=0.01,
        min_lot=0.1, max_lot=1000.0, lot_step=0.1,
        spread_typical=0.05, margin_pct=0.01,
        sessions="24/7", slippage_ticks=2,
    ),
    "NEARUSD": InstrumentSpec(
        symbol="NEARUSD", name="NEAR Protocol",
        pip_size=0.001, contract_size=1, pip_value_per_lot=0.001,
        min_lot=1.0, max_lot=10000.0, lot_step=0.1,
        spread_typical=0.01, margin_pct=0.01,
        sessions="24/7", slippage_ticks=3,
    ),
    "SUIUSD": InstrumentSpec(
        symbol="SUIUSD", name="Sui",
        pip_size=0.0001, contract_size=1, pip_value_per_lot=0.0001,
        min_lot=1.0, max_lot=50000.0, lot_step=1.0,
        spread_typical=0.005, margin_pct=0.01,
        sessions="24/7", slippage_ticks=3,
    ),
    "ARBUSD": InstrumentSpec(
        symbol="ARBUSD", name="Arbitrum",
        pip_size=0.0001, contract_size=1, pip_value_per_lot=0.0001,
        min_lot=1.0, max_lot=50000.0, lot_step=1.0,
        spread_typical=0.002, margin_pct=0.01,
        sessions="24/7", slippage_ticks=3,
    ),
    "PEPEUSD": InstrumentSpec(
        symbol="PEPEUSD", name="Pepe",
        pip_size=0.00000001, contract_size=1, pip_value_per_lot=0.00000001,
        min_lot=100000.0, max_lot=100000000.0, lot_step=100.0,
        spread_typical=0.0000001, margin_pct=0.01,
        sessions="24/7", slippage_ticks=8,
    ),
    "WIFUSD": InstrumentSpec(
        symbol="WIFUSD", name="dogwifhat",
        pip_size=0.0001, contract_size=1, pip_value_per_lot=0.0001,
        min_lot=1.0, max_lot=100000.0, lot_step=1.0,
        spread_typical=0.003, margin_pct=0.01,
        sessions="24/7", slippage_ticks=5,
    ),
    "FTMUSD": InstrumentSpec(
        symbol="FTMUSD", name="Fantom",
        pip_size=0.0001, contract_size=1, pip_value_per_lot=0.0001,
        min_lot=1.0, max_lot=50000.0, lot_step=1.0,
        spread_typical=0.002, margin_pct=0.01,
        sessions="24/7", slippage_ticks=3,
    ),
    "ATOMUSD": InstrumentSpec(
        symbol="ATOMUSD", name="Cosmos",
        pip_size=0.001, contract_size=1, pip_value_per_lot=0.001,
        min_lot=0.1, max_lot=5000.0, lot_step=0.1,
        spread_typical=0.02, margin_pct=0.01,
        sessions="24/7", slippage_ticks=2,
    ),
}


def get_instrument(symbol: str) -> InstrumentSpec:
    """Get instrument specification. Raises KeyError if not found."""
    if symbol not in INSTRUMENTS:
        raise KeyError(f"Unknown instrument: {symbol}. Available: {list(INSTRUMENTS.keys())}")
    return INSTRUMENTS[symbol]


def get_personal_instruments() -> list[InstrumentSpec]:
    """Get CoinDCX instruments for personal trading mode."""
    return [spec for spec in INSTRUMENTS.values() if spec.max_leverage > 1]


def get_prop_instruments() -> list[InstrumentSpec]:
    """Get FundingPips instruments for prop firm mode."""
    return [spec for spec in INSTRUMENTS.values() if spec.max_leverage <= 1]
