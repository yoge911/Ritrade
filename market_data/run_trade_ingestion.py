import asyncio
import json
import os
from pathlib import Path

from market_data.publishers.redis import RedisMarketDataPublisher
from market_data.sources.binance import BinanceTradeWebSocketSource
from market_data.storage import JsonlTradeArchiveSink

CONFIG_PATH = Path(__file__).resolve().parents[1] / 'tickers_config.json'
ARCHIVE_ROOT = Path(os.environ.get('RITRADE_TRADE_ARCHIVE_DIR', Path(__file__).resolve().parents[1] / 'data' / 'trade_archive'))


def load_tickers() -> list[str]:
    with CONFIG_PATH.open() as config_file:
        return [str(item['ticker']).lower() for item in json.load(config_file)]


async def main() -> None:
    publisher = RedisMarketDataPublisher(
        write_latest_snapshot=True,
        storage_sink=JsonlTradeArchiveSink(ARCHIVE_ROOT),
    )
    tickers = load_tickers()
    tasks = [
        BinanceTradeWebSocketSource(ticker).run(publisher.publish_trade)
        for ticker in tickers
    ]
    print(f'🚀 Starting trade ingestion for {len(tasks)} tickers...')
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
