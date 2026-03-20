"""
Instrument specifications — pip values, lot sizes, spread, and contract details.

This is Fix #2 from the critical fixes plan. Every instrument has different
characteristics that affect position sizing, P&L calculation, and risk.

SPOT vs FUTURES:
- FundingPips trades SPOT (CFD) instruments, not futures
- XAUUSD = spot gold (no expiry, trades 24/5)
- GC=F = gold FUTURES (COMEX, has expiry, different price)
- We must use spot data, not futures

PIP VALUE:
- A "pip" is the smallest standard price movement
- Gold: 1 pip = $0.01, but a $1 move on 1 lot (100 oz) = $100
- Forex: 1 pip = 0.0001 for most pairs
- Getting this wrong means risking 10x or 100x what you intended
"""

from dataclasses import dataclass


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
    margin_pct: float         # Margin requirement (not used in paper trading but good to know)
    sessions: str             # When this instrument trades (for kill zone awareness)

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

    def calculate_position_size(
        self,
        entry: float,
        stop_loss: float,
        account_balance: float,
        risk_pct: float = 0.01,
    ) -> float:
        """
        Calculate position size based on risk percentage.

        Formula:
        1. How much money can we risk? → account_balance * risk_pct
        2. How much do we lose per lot if SL is hit? → price_diff * contract_size
        3. How many lots? → risk_amount / loss_per_lot

        Example (Gold, $100K account, 1% risk, $10 SL):
        - Risk amount = $100,000 * 0.01 = $1,000
        - Loss per lot = $10 * 100 oz = $1,000
        - Position size = $1,000 / $1,000 = 1.0 lot
        """
        risk_amount = account_balance * risk_pct
        price_risk = abs(entry - stop_loss)

        if price_risk <= 0:
            return 0.0

        loss_per_lot = price_risk * self.contract_size
        lots = risk_amount / loss_per_lot

        # Round to lot step
        lots = round(lots / self.lot_step) * self.lot_step
        # Clamp to min/max
        lots = max(self.min_lot, min(lots, self.max_lot))

        return round(lots, 4)

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
    "XAUUSD": InstrumentSpec(
        symbol="XAUUSD",
        name="Gold Spot",
        pip_size=0.01,
        contract_size=100,          # 100 troy ounces per lot
        pip_value_per_lot=1.0,      # $1 per pip (0.01) per lot
        min_lot=0.01,
        max_lot=50.0,
        lot_step=0.01,
        spread_typical=0.30,        # ~30 cents typical on FundingPips
        margin_pct=0.01,            # 1% margin (100:1 leverage)
        sessions="24/5 (closed Sat-Sun)",
    ),
    "XAGUSD": InstrumentSpec(
        symbol="XAGUSD",
        name="Silver Spot",
        pip_size=0.001,
        contract_size=5000,         # 5000 troy ounces per lot
        pip_value_per_lot=5.0,      # $5 per pip (0.001) per lot
        min_lot=0.01,
        max_lot=50.0,
        lot_step=0.01,
        spread_typical=0.03,        # ~3 cents typical
        margin_pct=0.01,
        sessions="24/5 (closed Sat-Sun)",
    ),
    "BTCUSD": InstrumentSpec(
        symbol="BTCUSD",
        name="Bitcoin",
        pip_size=0.01,
        contract_size=1,            # 1 BTC per lot
        pip_value_per_lot=0.01,     # $0.01 per pip per lot
        min_lot=0.01,
        max_lot=10.0,
        lot_step=0.01,
        spread_typical=15.0,        # ~$15 typical spread
        margin_pct=0.005,           # 0.5% margin (200:1)
        sessions="24/7",
    ),
    "ETHUSD": InstrumentSpec(
        symbol="ETHUSD",
        name="Ethereum",
        pip_size=0.01,
        contract_size=1,            # 1 ETH per lot
        pip_value_per_lot=0.01,
        min_lot=0.1,
        max_lot=100.0,
        lot_step=0.1,
        spread_typical=1.50,        # ~$1.50 typical
        margin_pct=0.005,
        sessions="24/7",
    ),
}


def get_instrument(symbol: str) -> InstrumentSpec:
    """Get instrument specification. Raises KeyError if not found."""
    if symbol not in INSTRUMENTS:
        raise KeyError(f"Unknown instrument: {symbol}. Available: {list(INSTRUMENTS.keys())}")
    return INSTRUMENTS[symbol]
