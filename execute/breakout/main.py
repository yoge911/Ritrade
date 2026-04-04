import asyncio
import json
import os
import redis
from execute.services.execution import ExecutionService
from execute.services.kline import Kline
from execute.services.trade import Trade
from execute.strategy.fixed_stop import FixedStopExitStrategy
from execute.strategy.manual_entry import ManualEntryStrategy

COMMAND_CHANNEL = 'execution_commands'
PINNED_SET_KEY = 'execution_pinned_tickers'
DEFAULT_INTERVAL = '1m'
DEFAULT_ACCOUNT_BALANCE = 10000
DEFAULT_QUANTITY = 1666.667
DEFAULT_RISK_PERCENT = 1
DEFAULT_REWARD_PERCENT = 2

redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)


def load_tickers() -> list[str]:
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'tickers_config.json',
    )
    with open(config_path, 'r') as f:
        return [item['ticker'].lower() for item in json.load(f)]


class ExecutionController:
    def __init__(self) -> None:
        self.redis_client = redis_client
        self.tickers = load_tickers()
        self.trades: dict[str, Trade] = {}
        self.kline_clients: dict[str, Kline] = {}
        self.kline_tasks: dict[str, asyncio.Task] = {}
        self.pubsub = self.redis_client.pubsub(ignore_subscribe_messages=True)

    def get_trade(self, ticker: str) -> Trade:
        if ticker not in self.trades:
            entry_strategy = ManualEntryStrategy(
                account_balance=DEFAULT_ACCOUNT_BALANCE,
                quantity=DEFAULT_QUANTITY,
                risk_percent=DEFAULT_RISK_PERCENT,
                reward_percent=DEFAULT_REWARD_PERCENT,
            )
            trade = Trade(
                ticker=ticker,
                account_balance=DEFAULT_ACCOUNT_BALANCE,
                quantity=DEFAULT_QUANTITY,
                risk_percent=DEFAULT_RISK_PERCENT,
                reward_percent=DEFAULT_REWARD_PERCENT,
                entry_strategy=entry_strategy,
                exit_strategy=FixedStopExitStrategy(),
                execution_service=ExecutionService(),
            )
            trade.start()
            self.trades[ticker] = trade
        return self.trades[ticker]

    async def start_kline(self, ticker: str) -> None:
        if ticker in self.kline_tasks:
            return

        client = Kline(symbol=ticker, interval=DEFAULT_INTERVAL, candle_buffer_size=-1)
        self.kline_clients[ticker] = client
        self.kline_tasks[ticker] = asyncio.create_task(client.listen())
        print(f'[{ticker}] Started Kline listener.')

    async def stop_kline(self, ticker: str) -> None:
        client = self.kline_clients.pop(ticker, None)
        task = self.kline_tasks.pop(ticker, None)
        if client:
            client.stop()
        if task:
            try:
                await asyncio.wait_for(task, timeout=3)
            except TimeoutError:
                task.cancel()
        print(f'[{ticker}] Stopped Kline listener.')

    async def pin_ticker(self, ticker: str) -> None:
        trade = self.get_trade(ticker)
        trade.pin()
        self.redis_client.sadd(PINNED_SET_KEY, ticker)
        await self.start_kline(ticker)

    async def unpin_ticker(self, ticker: str) -> None:
        trade = self.trades.get(ticker)
        if not trade:
            return
        if trade.has_active_trade():
            print(f'[{ticker}] Cannot unpin while trade is active.')
            return

        trade.unpin()
        trade.shutdown()
        trade.clear_status()
        self.trades.pop(ticker, None)
        self.redis_client.srem(PINNED_SET_KEY, ticker)
        await self.stop_kline(ticker)

    async def handle_command(self, command: dict) -> None:
        ticker = str(command.get('ticker', '')).lower()
        action = command.get('action')

        if not ticker or ticker not in self.tickers:
            print(f'Ignored command with unknown ticker: {command}')
            return

        if action == 'pin_ticker':
            await self.pin_ticker(ticker)
            return

        trade = self.trades.get(ticker)
        if not trade:
            print(f'[{ticker}] No runtime trade found for action {action}.')
            return

        if action == 'unpin_ticker':
            await self.unpin_ticker(ticker)
        elif action == 'place_limit_order':
            side = str(command.get('side', 'long')).lower()
            limit_price = command.get('limit_price')
            limit_price = float(limit_price) if limit_price not in (None, '') else None
            initiated_by = str(command.get('initiated_by', 'manual')).lower()
            control_mode = str(command.get('control_mode', 'manual')).lower()
            ok, message = trade.submit_entry(
                side,
                limit_price,
                initiated_by='automated' if initiated_by == 'automated' else 'manual',
                control_mode='automated' if control_mode == 'automated' else 'manual',
            )
            print(f'[{ticker}] {message}')
            if ok:
                await self.start_kline(ticker)
        elif action == 'cancel_order':
            _, message = trade.cancel_order()
            print(f'[{ticker}] {message}')
        elif action == 'close_position':
            _, message = trade.close_position()
            print(f'[{ticker}] {message}')
        elif action == 'modify_stop':
            stop_price = command.get('stop_price')
            stop_price = float(stop_price) if stop_price not in (None, '') else None
            if stop_price is None:
                print(f'[{ticker}] Missing stop_price for modify_stop.')
            else:
                _, message = trade.modify_stop(stop_price)
                print(f'[{ticker}] {message}')
        elif action == 'release_manual_control':
            _, message = trade.release_manual_control()
            print(f'[{ticker}] {message}')
        else:
            print(f'Ignored unknown action: {command}')

    async def run(self) -> None:
        self.pubsub.subscribe(COMMAND_CHANNEL)
        for ticker in self.redis_client.smembers(PINNED_SET_KEY):
            if ticker in self.tickers:
                await self.pin_ticker(ticker)
        print('🚀 Execution controller listening for commands...')

        while True:
            message = self.pubsub.get_message(timeout=1.0)
            if message and message.get('type') == 'message':
                try:
                    command = json.loads(message['data'])
                except (ValueError, json.JSONDecodeError):
                    print(f'Invalid command payload: {message["data"]}')
                else:
                    await self.handle_command(command)
            await asyncio.sleep(0.1)


async def main():
    controller = ExecutionController()
    await controller.run()

if __name__ == "__main__":
    asyncio.run(main())
