"""
Entry point for the Notas Lave trading engine.

Run with: python run.py
Or with: uvicorn src.api.server:app --reload --port 8000
"""

import uvicorn
from src.config import config

if __name__ == "__main__":
    print("Starting Notas Lave Trading Engine...")
    print(f"  Instruments: {config.instruments}")
    print(f"  Entry TFs:   {config.entry_timeframes}")
    print(f"  Context TFs: {config.context_timeframes}")
    print(f"  API:         http://{config.api_host}:{config.api_port}")
    print(f"  Dashboard:   http://localhost:3000")
    print()

    uvicorn.run(
        "src.api.server:app",
        host=config.api_host,
        port=config.api_port,
        reload=True,
    )
