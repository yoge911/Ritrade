from datetime import datetime
import threading
import redis
import json
from execute.trade.PnL import PnLCalculator
from core_utils.format import format_timestamp

class Trade():

    def __init__(self, ticker, entry_price, account_balance, quantity, position_type='long', risk_percent = 1, reward_percent = 2 ):
        self.ticker = ticker
        self.status = 'open'
        self.entry_price = entry_price
        self.account_balance = account_balance
        self.quantity = quantity
        self.risk_percent = risk_percent
        self.reward_percent = reward_percent
        self.position_type = position_type
        self.eth_trade = None
        self.monitor_thread = None
        self.trade_start = None
        # Redis connection
        self.redis_client = redis.Redis(host='localhost', port=6379, db=0)

        self.begin()

        # start trade monitoring
        self.monitor_trade()

        

    def listen_price_updates(self):
        """Listen to Redis Pub/Sub for price updates for this ticker."""
        pubsub = self.redis_client.pubsub()
        pubsub.subscribe(f"{self.ticker}_event_channel")  # updated to match publisher
        print(f"[{self.ticker}] Listening for price updates on Redis channel.")

        for message in pubsub.listen():
            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                except (ValueError, json.JSONDecodeError):
                    print(f"[{self.ticker}] Invalid JSON: {message['data']}")
                    continue

                if data.get('event') == 'trade_closed':
                    print(f"[{self.ticker}] Received trade closed event.")
                    break  # or handle closure logic here

                elif 'live_price' in data:
                    current_price = float(data['live_price'])
                    timestamp = format_timestamp(data['event_time'])
                    result = self.eth_trade.check_price(current_price, timestamp)
                   
                    # print(f"[{self.ticker}]  Price: {current_price}, PnL: {result['floating_pnl']}  SL: {result['distance_to_sl']}, TP: {result['distance_to_tp']}")
                    print(result)
                    # write entire result to Redis
                    self.redis_client.hmset(f"{self.ticker}_status", result)

                    # Check if stop loss or take profit conditions are met
                    # if result['status'] in ('target_hit', 'stop_hit'):
                    #     self.close_trade()
                    #     pubsub.unsubscribe()
                    #     break

                else:
                    print(f"[{self.ticker}] Ignored unrecognized message: {data}")


    def begin(self):
        """
        Start the trade by executing the order.
        """
        self.trade_start = format_timestamp(int(datetime.now().timestamp()))
        print(f"[{self.ticker}] Starting trade...")


    def monitor_trade(self):
        """
        Monitor the trade and check if stop loss or take profit conditions are met.
        """
        self.eth_trade = PnLCalculator(self.ticker, self.entry_price , self.account_balance, self.quantity, self.risk_percent, self.reward_percent, self.position_type)        
        self.monitor_thread = threading.Thread(target=self.listen_price_updates)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()


    def execute_limit_order(self):
        """
        Execute a limit order to enter the trade.
        """
        # Placeholder for limit order execution logic
        pass


    def execute_market_order(self):
        """
        Execute a market order to enter the trade.
        """
        # Placeholder for market order execution logic
        pass


    def close_trade(self):
        """
        Close the trade and mark status.        
        """
        
        self.status = 'closed'
        print(f"[{self.ticker}] Trade closed.")

        # Optionally publish event to notify other systems
        self.redis_client.publish(f"{self.ticker}_event_channel", json.dumps({"event": "trade_closed"}))

    def autocontrol(self):
        """
        Automatically control the trade based on market conditions.
        """
        # Placeholder for auto-control logic
        pass
            # Check target or stop conditions
        # if self.position_type == 'long':
        #     if current_price >= self.target_price:
        #         status = 'target_hit'
        #     elif current_price <= self.stop_price:
        #         status = 'stop_hit'
        # else:  # short
        #     if current_price <= self.target_price:
        #         status = 'target_hit'
        #     elif current_price >= self.stop_price:
        #         status = 'stop_hit'

