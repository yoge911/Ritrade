import asyncio
import json
from pathlib import Path

from market_data.publishers.redis import RedisMarketDataPublisher
from market_data.sources.binance import BinanceTradeWebSocketSource

CONFIG_PATH = Path(__file__).resolve().parents[1] / 'tickers_config.json'


def load_tickers() -> list[str]:
    with CONFIG_PATH.open() as config_file:
        return [str(item['ticker']).lower() for item in json.load(config_file)]


async def main() -> None:
    publisher = RedisMarketDataPublisher()
    tickers = load_tickers()
    tasks = [
        BinanceTradeWebSocketSource(ticker).run(publisher.publish_trade)
        for ticker in tickers
    ]
    print(f'🚀 Starting trade ingestion for {len(tasks)} tickers...')
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
