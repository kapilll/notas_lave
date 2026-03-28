"""InstrumentRegistry — centralized symbol mapping + specs.

Symbol mapping lives HERE, not scattered across broker code.
Each instrument knows its exchange symbols, tick sizes, contract specs.
Brokers ask the instrument for their symbol, not the other way around.

Adding a new instrument = adding one entry here.
Adding a new broker = adding its symbol to exchange_symbols dicts.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Instrument:
    symbol: str           # Internal: "BTCUSD"
    name: str             # "Bitcoin / USD"
    contract_size: float  # 1.0 for crypto, 100.0 for gold
    pip_size: float

    # Per-broker symbol mapping
    exchange_symbols: dict[str, str] = field(default_factory=dict)
    # e.g., {"delta": "BTCUSD", "coindcx": "BTCINR", "mt5": "BTCUSD.raw"}

    tick_sizes: dict[str, float] = field(default_factory=dict)

    def exchange_symbol(self, broker: str) -> str:
        sym = self.exchange_symbols.get(broker)
        if not sym:
            raise ValueError(f"{self.symbol} not available on {broker}")
        return sym


# -- Registry --

INSTRUMENTS: dict[str, Instrument] = {
    # === METALS ===
    "XAUUSD": Instrument(
        symbol="XAUUSD", name="Gold Spot",
        contract_size=100.0, pip_size=0.01,
        exchange_symbols={"mt5": "XAUUSD"},
        tick_sizes={"mt5": 0.01},
    ),
    "XAGUSD": Instrument(
        symbol="XAGUSD", name="Silver Spot",
        contract_size=5000.0, pip_size=0.001,
        exchange_symbols={"mt5": "XAGUSD"},
        tick_sizes={"mt5": 0.001},
    ),

    # === MAJOR CRYPTO ===
    "BTCUSD": Instrument(
        symbol="BTCUSD", name="Bitcoin/USD",
        contract_size=1.0, pip_size=0.01,
        exchange_symbols={"delta": "BTCUSD", "coindcx": "BTCINR", "mt5": "BTCUSD"},
        tick_sizes={"delta": 0.10, "coindcx": 1.0},
    ),
    "ETHUSD": Instrument(
        symbol="ETHUSD", name="Ethereum/USD",
        contract_size=1.0, pip_size=0.01,
        exchange_symbols={"delta": "ETHUSD", "coindcx": "ETHINR", "mt5": "ETHUSD"},
        tick_sizes={"delta": 0.01, "coindcx": 0.01},
    ),

    # === LAB INSTRUMENTS ===
    "SOLUSD": Instrument(
        symbol="SOLUSD", name="Solana",
        contract_size=1.0, pip_size=0.01,
        exchange_symbols={"binance": "SOLUSDT", "delta": "SOLUSD"},
        tick_sizes={"binance": 0.01, "delta": 0.01},
    ),
    "XRPUSD": Instrument(
        symbol="XRPUSD", name="XRP",
        contract_size=1.0, pip_size=0.0001,
        exchange_symbols={"binance": "XRPUSDT"},
        tick_sizes={"binance": 0.0001},
    ),
    "BNBUSD": Instrument(
        symbol="BNBUSD", name="BNB",
        contract_size=1.0, pip_size=0.01,
        exchange_symbols={"binance": "BNBUSDT"},
        tick_sizes={"binance": 0.01},
    ),
    "DOGEUSD": Instrument(
        symbol="DOGEUSD", name="Dogecoin",
        contract_size=1.0, pip_size=0.00001,
        exchange_symbols={"binance": "DOGEUSDT"},
        tick_sizes={"binance": 0.00001},
    ),
    "ADAUSD": Instrument(
        symbol="ADAUSD", name="Cardano",
        contract_size=1.0, pip_size=0.0001,
        exchange_symbols={"binance": "ADAUSDT"},
        tick_sizes={"binance": 0.0001},
    ),
    "AVAXUSD": Instrument(
        symbol="AVAXUSD", name="Avalanche",
        contract_size=1.0, pip_size=0.01,
        exchange_symbols={"binance": "AVAXUSDT"},
        tick_sizes={"binance": 0.01},
    ),
    "LINKUSD": Instrument(
        symbol="LINKUSD", name="Chainlink",
        contract_size=1.0, pip_size=0.001,
        exchange_symbols={"binance": "LINKUSDT"},
        tick_sizes={"binance": 0.001},
    ),
    "DOTUSD": Instrument(
        symbol="DOTUSD", name="Polkadot",
        contract_size=1.0, pip_size=0.001,
        exchange_symbols={"binance": "DOTUSDT"},
        tick_sizes={"binance": 0.001},
    ),
    "LTCUSD": Instrument(
        symbol="LTCUSD", name="Litecoin",
        contract_size=1.0, pip_size=0.01,
        exchange_symbols={"binance": "LTCUSDT"},
        tick_sizes={"binance": 0.01},
    ),
    "NEARUSD": Instrument(
        symbol="NEARUSD", name="NEAR Protocol",
        contract_size=1.0, pip_size=0.001,
        exchange_symbols={"binance": "NEARUSDT"},
        tick_sizes={"binance": 0.001},
    ),
    "SUIUSD": Instrument(
        symbol="SUIUSD", name="Sui",
        contract_size=1.0, pip_size=0.0001,
        exchange_symbols={"binance": "SUIUSDT"},
        tick_sizes={"binance": 0.0001},
    ),
    "ARBUSD": Instrument(
        symbol="ARBUSD", name="Arbitrum",
        contract_size=1.0, pip_size=0.0001,
        exchange_symbols={"binance": "ARBUSDT"},
        tick_sizes={"binance": 0.0001},
    ),
    "PEPEUSD": Instrument(
        symbol="PEPEUSD", name="Pepe",
        contract_size=1.0, pip_size=0.00000001,
        exchange_symbols={"binance": "PEPEUSDT"},
        tick_sizes={"binance": 0.00000001},
    ),
    "WIFUSD": Instrument(
        symbol="WIFUSD", name="dogwifhat",
        contract_size=1.0, pip_size=0.0001,
        exchange_symbols={"binance": "WIFUSDT"},
        tick_sizes={"binance": 0.0001},
    ),
    "FTMUSD": Instrument(
        symbol="FTMUSD", name="Fantom",
        contract_size=1.0, pip_size=0.0001,
        exchange_symbols={"binance": "FTMUSDT"},
        tick_sizes={"binance": 0.0001},
    ),
    "ATOMUSD": Instrument(
        symbol="ATOMUSD", name="Cosmos",
        contract_size=1.0, pip_size=0.001,
        exchange_symbols={"binance": "ATOMUSDT"},
        tick_sizes={"binance": 0.001},
    ),
}


def get_instrument(symbol: str) -> Instrument:
    if symbol not in INSTRUMENTS:
        raise KeyError(
            f"Unknown instrument: {symbol}. "
            f"Available: {list(INSTRUMENTS.keys())}"
        )
    return INSTRUMENTS[symbol]
