"""
Real-Time Multi-Factor Algorithmic Trading System (Paper Trading)

This system implements a momentum-based trading strategy with automated
portfolio rebalancing for educational purposes.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import time
import schedule
from datetime import datetime, timezone, timedelta
import json
import logging
import matplotlib.pyplot as plt

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading.log'),
        logging.StreamHandler()
    ]
)


class LiveDataManager:
    """Manages real-time market data fetching"""

    def __init__(self, tickers):
        self.tickers = tickers
        self.latest_prices = {}

    def is_market_open(self):
        """
        Approximate US stock market hours (UTC, timezone-aware)
        Market hours: 9:30 AM - 4:00 PM EST = 14:30 - 21:00 UTC
        """
        now = datetime.now(timezone.utc)
        weekday = now.weekday()  # Monday = 0

        # Closed on weekends
        if weekday >= 5:
            return False

        # US Market hours: 14:30–21:00 UTC
        market_open = now.replace(hour=14, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=21, minute=0, second=0, microsecond=0)

        return market_open <= now <= market_close

    def get_live_prices(self):
        """
        Fetch current live prices for all tickers
        Returns: dict of {ticker: price}
        """
        logging.info("Fetching live prices...")

        try:
            data = yf.download(
                tickers=self.tickers,
                period="1d",
                interval="5m",
                progress=False
            )

            prices = {}
            for ticker in self.tickers:
                try:
                    if len(self.tickers) == 1:
                        prices[ticker] = data["Close"].dropna().iloc[-1]
                    else:
                        prices[ticker] = data["Close"][ticker].dropna().iloc[-1]
                except Exception as e:
                    logging.warning(f"No price data for {ticker}: {e}")

            self.latest_prices = prices
            logging.info(f"✓ Fetched prices for {len(prices)} tickers")
            return prices

        except Exception as e:
            logging.error(f"Error fetching live prices: {e}")
            return self.latest_prices

    def update_live_prices(self):
        """Alias for get_live_prices() for backwards compatibility"""
        return self.get_live_prices()

    def get_historical_data(self, period='1y', interval='1d'):
        """
        Fetch historical price data for factor calculation

        Args:
            period: Time period (e.g., '1y', '6mo', '3mo')
            interval: Data interval (e.g., '1d', '1h')

        Returns:
            DataFrame with historical prices
        """
        logging.info(f"Fetching historical data ({period})...")

        try:
            data = yf.download(
                tickers=self.tickers,
                period=period,
                interval=interval,
                progress=False
            )

            if len(self.tickers) == 1:
                prices = data["Close"].to_frame()
                prices.columns = [self.tickers[0]]
            else:
                prices = data["Close"]

            logging.info(f"✓ Retrieved {len(prices)} days of historical data")
            return prices

        except Exception as e:
            logging.error(f"Error fetching historical data: {e}")
            return None


class PortfolioManager:
    """Manages current portfolio state"""

    def __init__(self, initial_capital=100000):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = {}  # {ticker: shares}
        self.trade_history = []
        self.portfolio_value_history = []

    def get_current_positions(self):
        """Return current positions"""
        return self.positions.copy()

    def get_portfolio_value(self, current_prices):
        """Calculate total portfolio value"""
        position_value = sum(
            shares * current_prices.get(ticker, 0)
            for ticker, shares in self.positions.items()
        )
        total_value = self.cash + position_value
        return total_value

    def execute_trade(self, ticker, shares, price, timestamp):
        """
        Execute a trade (buy or sell)

        shares > 0: Buy
        shares < 0: Sell
        """
        cost = shares * price

        # Update cash
        self.cash -= cost

        # Update positions
        if ticker in self.positions:
            self.positions[ticker] += shares
        else:
            self.positions[ticker] = shares

        # Remove zero positions
        if self.positions.get(ticker, 0) == 0:
            del self.positions[ticker]

        # Record trade
        trade = {
            'timestamp': str(timestamp),
            'ticker': ticker,
            'shares': shares,
            'price': price,
            'cost': cost,
            'cash_after': self.cash
        }
        self.trade_history.append(trade)

        logging.info(f"{'BUY' if shares > 0 else 'SELL'} {abs(shares)} shares of {ticker} @ ${price:.2f}")

    def rebalance_portfolio(self, target_positions, current_prices):
        """
        Rebalance portfolio to match target positions

        target_positions: {ticker: target_weight (-1 to 1)}
        current_prices: {ticker: current_price}
        """
        timestamp = datetime.now(timezone.utc)
        total_value = self.get_portfolio_value(current_prices)

        trades_executed = 0

        # Calculate target shares for each position
        target_shares = {}
        for ticker, weight in target_positions.items():
            if ticker not in current_prices or current_prices[ticker] == 0:
                continue

            target_value = total_value * weight
            target_shares[ticker] = int(target_value / current_prices[ticker])

        # Calculate trades needed
        all_tickers = set(self.positions.keys()) | set(target_shares.keys())

        for ticker in all_tickers:
            current_shares = self.positions.get(ticker, 0)
            target_share = target_shares.get(ticker, 0)

            shares_to_trade = target_share - current_shares

            if shares_to_trade != 0 and ticker in current_prices:
                self.execute_trade(
                    ticker=ticker,
                    shares=shares_to_trade,
                    price=current_prices[ticker],
                    timestamp=timestamp
                )
                trades_executed += 1

        logging.info(f"✓ Rebalancing complete: {trades_executed} trades executed")

        # Record portfolio value
        new_value = self.get_portfolio_value(current_prices)
        self.portfolio_value_history.append({
            'timestamp': str(timestamp),
            'value': new_value,
            'return': (new_value / self.initial_capital - 1) * 100
        })

    def save_state(self, filename='portfolio_state.json'):
        """Save portfolio state to file"""
        state = {
            'cash': self.cash,
            'positions': self.positions,
            'trade_history': self.trade_history,
            'portfolio_value_history': self.portfolio_value_history
        }

        with open(filename, 'w') as f:
            json.dump(state, f, indent=2, default=str)

        logging.info(f"✓ Portfolio state saved to {filename}")

    def load_state(self, filename='portfolio_state.json'):
        """Load portfolio state from file"""
        try:
            with open(filename, 'r') as f:
                state = json.load(f)

            self.cash = state['cash']
            self.positions = state['positions']
            self.trade_history = state['trade_history']
            self.portfolio_value_history = state['portfolio_value_history']

            logging.info(f"✓ Portfolio state loaded from {filename}")
        except FileNotFoundError:
            logging.warning(f"No saved state found at {filename}")


class LiveStrategyEngine:
    """Real-time strategy execution engine"""

    def __init__(self, tickers, initial_capital=100000, rebalance_frequency='monthly'):
        self.tickers = tickers
        self.data_manager = LiveDataManager(tickers)
        self.portfolio = PortfolioManager(initial_capital)
        self.rebalance_frequency = rebalance_frequency
        self.last_rebalance = None

    def calculate_signals(self):
        """Calculate trading signals based on current data"""
        logging.info("Calculating signals...")

        # Get historical data for factor calculation
        prices = self.data_manager.get_historical_data(period='1y')

        if prices is None or prices.empty:
            logging.error("No historical data available")
            return {}

        # Calculate momentum (simple 3-month for demo)
        momentum_3m = prices / prices.shift(63) - 1
        momentum_score = momentum_3m.iloc[-1]

        # Rank stocks
        ranked = momentum_score.rank(pct=True)

        # Generate signals
        signals = {}
        for ticker in self.tickers:
            if ticker not in ranked:
                continue

            rank = ranked[ticker]

            if rank >= 0.8:  # Top 20%
                signals[ticker] = 0.05  # 5% position
            elif rank <= 0.2:  # Bottom 20%
                signals[ticker] = -0.05  # -5% short position
            else:
                signals[ticker] = 0  # No position

        logging.info(f"✓ Signals calculated: {len([s for s in signals.values() if s != 0])} active positions")
        return signals

    def should_rebalance(self):
        """Check if it's time to rebalance"""
        if self.last_rebalance is None:
            return True

        now = datetime.now(timezone.utc)

        if self.rebalance_frequency == 'daily':
            return True
        elif self.rebalance_frequency == 'weekly':
            days_since = (now - self.last_rebalance).days
            return days_since >= 7
        elif self.rebalance_frequency == 'monthly':
            # Rebalance on first trading day of month
            return now.month != self.last_rebalance.month

        return False

    def run_trading_cycle(self):
        """Execute one trading cycle"""
        logging.info("="*60)
        logging.info("RUNNING TRADING CYCLE")
        logging.info("="*60)

        # Check if market is open
        if not self.data_manager.is_market_open():
            logging.info("Market is closed. Skipping cycle.")
            return

        # Get current prices
        current_prices = self.data_manager.get_live_prices()

        if not current_prices:
            logging.error("Failed to fetch current prices")
            return

        # Log current portfolio value
        portfolio_value = self.portfolio.get_portfolio_value(current_prices)
        pnl = (portfolio_value / self.portfolio.initial_capital - 1) * 100
        logging.info(f"Portfolio Value: ${portfolio_value:,.2f} (PnL: {pnl:+.2f}%)")

        # Check if we should rebalance
        if self.should_rebalance():
            logging.info("Rebalancing portfolio...")

            # Calculate new signals
            signals = self.calculate_signals()

            if signals:
                # Execute rebalancing
                self.portfolio.rebalance_portfolio(signals, current_prices)
                self.last_rebalance = datetime.now(timezone.utc)
            else:
                logging.warning("No signals generated, skipping rebalancing")
        else:
            logging.info("No rebalancing needed at this time")

        # Save state
        self.portfolio.save_state()

        logging.info("="*60)

    def start_live_trading(self, check_interval_minutes=60):
        """
        Start live trading loop

        check_interval_minutes: How often to check for rebalancing
        """
        logging.info("="*60)
        logging.info("STARTING LIVE TRADING SYSTEM")
        logging.info("="*60)
        logging.info(f"Tickers: {len(self.tickers)}")
        logging.info(f"Initial Capital: ${self.portfolio.initial_capital:,.2f}")
        logging.info(f"Rebalance Frequency: {self.rebalance_frequency}")
        logging.info(f"Check Interval: {check_interval_minutes} minutes")
        logging.info("="*60)

        # Schedule trading cycle
        schedule.every(check_interval_minutes).minutes.do(self.run_trading_cycle)

        # Run first cycle immediately
        self.run_trading_cycle()

        # Main loop
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        except KeyboardInterrupt:
            logging.info("\n" + "="*60)
            logging.info("SHUTTING DOWN LIVE TRADING SYSTEM")
            logging.info("="*60)
            self.portfolio.save_state()

            # Print final summary
            current_prices = self.data_manager.get_live_prices()
            if current_prices:
                final_value = self.portfolio.get_portfolio_value(current_prices)
                final_pnl = (final_value / self.portfolio.initial_capital - 1) * 100

                logging.info(f"Final Portfolio Value: ${final_value:,.2f}")
                logging.info(f"Total PnL: {final_pnl:+.2f}%")
                logging.info(f"Total Trades: {len(self.portfolio.trade_history)}")


def plot_equity_curve(portfolio_manager):
    """Plot the equity curve showing portfolio value over time"""
    if not portfolio_manager.portfolio_value_history:
        print("No portfolio history to plot")
        return

    df = pd.DataFrame(portfolio_manager.portfolio_value_history)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    plt.figure(figsize=(12, 6))
    plt.plot(df['timestamp'], df['value'])
    plt.title("Equity Curve (Portfolio Value Over Time)")
    plt.xlabel("Time")
    plt.ylabel("Portfolio Value ($)")
    plt.grid(True)
    plt.tight_layout()
    plt.show()


def calculate_performance_metrics(portfolio_manager):
    """Calculate and display performance metrics"""
    if not portfolio_manager.portfolio_value_history:
        print("No portfolio history available")
        return

    df = pd.DataFrame(portfolio_manager.portfolio_value_history)

    total_return = df['return'].iloc[-1]
    max_value = df['value'].max()
    min_value = df['value'].min()

    print("="*60)
    print("PERFORMANCE METRICS")
    print("="*60)
    print(f"Initial Capital: ${portfolio_manager.initial_capital:,.2f}")
    print(f"Current Value: ${df['value'].iloc[-1]:,.2f}")
    print(f"Total Return: {total_return:.2f}%")
    print(f"Max Value: ${max_value:,.2f}")
    print(f"Min Value: ${min_value:,.2f}")
    print(f"Total Trades: {len(portfolio_manager.trade_history)}")
    print("="*60)


def run_live_paper_trading():
    """Run live paper trading system"""

    # Configuration
    tickers = [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA', 'NVDA', 'JPM',
        'V', 'JNJ', 'WMT', 'PG', 'MA', 'UNH', 'HD', 'BAC'
    ]

    initial_capital = 100000
    rebalance_frequency = 'monthly'  # 'daily', 'weekly', or 'monthly'
    check_interval = 60  # Check every 60 minutes

    # Initialize engine
    engine = LiveStrategyEngine(
        tickers=tickers,
        initial_capital=initial_capital,
        rebalance_frequency=rebalance_frequency
    )

    # Start live trading
    engine.start_live_trading(check_interval_minutes=check_interval)


if __name__ == "__main__":
    # For paper trading (no real money)
    run_live_paper_trading()
