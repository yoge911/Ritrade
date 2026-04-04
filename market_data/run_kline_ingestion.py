import asyncio
import json
from pathlib import Path

from market_data.publishers.redis import RedisMarketDataPublisher
from market_data.sources.binance import BinanceKlineWebSocketSource

CONFIG_PATH = Path(__file__).resolve().parents[1] / 'tickers_config.json'
DEFAULT_INTERVAL = '1m'


def load_tickers() -> list[str]:
    with CONFIG_PATH.open() as config_file:
        return [str(item['ticker']).lower() for item in json.load(config_file)]


async def main() -> None:
    publisher = RedisMarketDataPublisher()
    tickers = load_tickers()
    tasks = [
        BinanceKlineWebSocketSource(ticker, DEFAULT_INTERVAL).run(publisher.publish_kline)
        for ticker in tickers
    ]
    print(f'🚀 Starting kline ingestion for {len(tasks)} tickers at {DEFAULT_INTERVAL}...')
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
