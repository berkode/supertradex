# Crypto-bot following Supertrend usign ATR-AverageTrueRange to calculate buy and sell check_buy_sell_signals
# Using CCXT for supported exchanges and markets
# This is the supertrend extended version
import os, sys, time
# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.append(project_root)

import ccxt
import pandas as pd
pd.set_option('display.max_rows', None)
import warnings
warnings.filterwarnings('ignore')
from config.settings import Settings
from data.token_database import TokenDatabase
from web.models import Coin
from dotenv import load_dotenv

load_dotenv("config/.env")

# Initialize components (assuming settings are loaded)
settings = Settings()
# TokenDatabase reads settings internally now
db = TokenDatabase()

#True Range
def tr(data):
    data['previous_close'] = data['close'].shift(1)
    data['high-low'] = abs(data['high'] - data['low'])
    data['high-pc'] = abs(data['high'] - data['previous_close'])
    data['low-pc'] = abs(data['low'] - data['previous_close'])
    tr = data[['high-low', 'high-pc', 'low-pc']].max(axis=1)
    return tr

#Average True Range
def atr(data, period=14):
    data['tr'] = tr(data)
    atr = data['tr'].rolling(period).mean()
    return atr


def supertrend(df, period, atr_multiplier):
    hl2 = (df['high'] + df['low']) / 2
    df['atr'] = atr(df, period)
    df['upperband'] = hl2 + (atr_multiplier * df['atr'])
    df['lowerband'] = hl2 - (atr_multiplier * df['atr'])
    df['in_uptrend'] = True

    for current in range(1, len(df.index)):
        previous = current - 1

        if df['close'][current] > df['upperband'][previous]:
            df['in_uptrend'][current] = True
        elif df['close'][current] < df['lowerband'][previous]:
            df['in_uptrend'][current] = False
        else:
            df['in_uptrend'][current] = df['in_uptrend'][previous]

            if df['in_uptrend'][current] and df['lowerband'][current] < df['lowerband'][previous]:
                df['lowerband'][current] = df['lowerband'][previous]

            if not df['in_uptrend'][current] and df['upperband'][current] > df['upperband'][previous]:
                df['upperband'][current] = df['upperband'][previous]
    return df


def spot_positions():
    data_columns = ['free', 'used', 'total']
    positions = pd.DataFrame(exchange.fetch_balance(), columns=data_columns)
    time.sleep(0.1)
    for columns in data_columns:
        positions = positions.astype(dtype= {columns:"float64"})
    positions = positions.loc[positions['free'] > 0]
    return positions


def buy_check():
    global buy_position
    pair_exchange = 1
    buy_price = 0
    wallet = 0
    
    positions = spot_positions()
    if pair in positions.index:
        wallet = positions.loc[pair, 'free']
        #print(pair,"is in spot wallet of free amount",wallet)
        if pair == fiat:
            pair_exchange = 1
            buy_price = fiat_limit
            baseprice = fiat_base
        else:
            pair_exchange = exchange.fetch_ticker(pairfiat)['last']
            buy_price = fiat_limit/pair_exchange
            baseprice = fiat_base/pair_exchange
        if wallet < buy_price:
            buy_price = wallet
        if buy_price < baseprice:
            buy_price = 0
            buy_position = False
    else:
        #print(pair,"not in wallet")
        buy_position = False
        
    buy_price = buy_price/exchange.fetch_ticker(coinpair)['last']
    #print(coin, "BUY amount is", buy_price, "coins")
    #print("Buy position is", buy_position)
    return buy_price, buy_position


def sell_check():
    global sell_position
    sell_price = 0
    wallet = 0
    
    positions = spot_positions()
    if coinname in positions.index:
        wallet = positions.loc[coinname, 'free']
        #print(coin,"is in spot wallet of free amount",wallet)
        if coinname == fiat:
            coin_exchange = 1
            sell_price = fiat_limit
            baseprice = fiat_base
        else:
            # check coin price compared to USD limit value
            coin_exchange = exchange.fetch_ticker(coinfiat)['last']
            sell_price = fiat_limit/coin_exchange
            baseprice = fiat_base/coin_exchange
            # check if available value is smaller than base USD, so don't trade
        if wallet < sell_price:
            sell_price = wallet
        if sell_price < baseprice:
            sell_price = 0
            sell_position = False
    else:
        #print(coin,"not in wallet")
        sell_position = False
    
    #print(coin, "SELL amount is", sell_price, "coins")
    #print("Sell position is", sell_position)
    return sell_price, sell_position


def check_buy_sell_signals(df):
    global buy_position
    global sell_position
    price = 0
    last_row_index = len(df.index) - 1
    previous_row_index = last_row_index - 1
       
    #print(coinpair, timeframe, 'uptrend:', df['in_uptrend'][last_row_index], 'Close:', df['close'][last_row_index])
    #print(coinpair, "Checking for buy and sell signals")
    #print(df)
    print(df.tail(2))
    
    if not df['in_uptrend'][previous_row_index] and df['in_uptrend'][last_row_index]:
        price, buy_position = buy_check()
        if buy_position:
            print(coinpair, "- BUY - changed to uptrend")
            order = exchange.create_market_buy_order(coinpair, price)
            time.sleep(0.1)
            #print(order)
            buy_position = False
            sell_position = True
        else:
            print(coinpair, "- Nothing to buy, already bought or no funds available")
    
    if df['in_uptrend'][previous_row_index] and not df['in_uptrend'][last_row_index]:
        price, sell_position = sell_check()
        if sell_position:
            print(coinpair, "- SELL - changed to downtrend")
            order = exchange.create_market_sell_order(coinpair, price)
            time.sleep(0.1)
            #print(order)
            sell_position = False
            buy_position = True
        else:
            print(coinpair, "- Nothing to sell, already sold or no funds available")

    return(df['close'][last_row_index], df['in_uptrend'][previous_row_index], df['in_uptrend'][last_row_index], buy_position, sell_position)


def update_database(coin, updated):
    print('Previous data: ', coin, coin.close_price, coin.uptrend_previous, coin.uptrend_last)
    coin.close_price, coin.uptrend_previous, coin.uptrend_last, coin.buy_position, coin.sell_position = updated
    print('Updating data: ', coin, coin.close_price, coin.uptrend_previous, coin.uptrend_last)
    
    # Update coin data in database
    try:
        session = db.Session()
        coin_model = session.query(Coin).filter(Coin.symbol == coin.symbol).first()
        if coin_model:
            coin_model.close_price = coin.close_price
            coin_model.uptrend_previous = coin.uptrend_previous
            coin_model.uptrend_last = coin.uptrend_last
            coin_model.buy_position = coin.buy_position
            coin_model.sell_position = coin.sell_position
            coin_model.trend_change = coin.uptrend_previous != coin.uptrend_last
            coin_model.strategy_running = True
            session.merge(coin_model)
            session.commit()
        session.close()
    except Exception as e:
        print(f"Error updating database: {e}")
        if session:
            session.rollback()
            session.close()
    
    print('Updated data: ', coin, coin.close_price, coin.uptrend_previous, coin.uptrend_last, coin.buy_position, coin.sell_position, coin.trend_change, coin.strategy_running)
    return(coin)
        

def strategy(coin):
    global coinname
    global coinpair
    global coinfiat
    global pairfiat
    global fiat
    global exchange
    global timeframe 
    global fiat_limit
    global fiat_base
    global atr_multiplier
    global buy_position
    global sell_position
    global pair
    global runperiod
    global period
 
    coinname, pair, timeframe, fiat_limit = coin.coin, coin.pair, coin.timeframe, coin.fiat_limit
    print('supertrendx:', coin, coinname, pair, timeframe, fiat_limit)
    
    fiat = 'USDT'
    apiKey = os.getenv('BINANCE_API_KEY')
    secret = os.getenv('BINANCE_SECRET_KEY')
    
    exchange = ccxt.binance({"apiKey": apiKey, "secret": secret})
    
    # Timeframe of the indicator bars and the period that we are looking at as limit > period
    # input_options = {"1":"30m", "2":"4h", "3":"15m", "4":"1h", "5":"1d", "6":"1w"}
    # timeframe=input_options.get(response)

    # we define trade quantity as amount in first pair, limiting with a USD value and above a base value
    # if available coin value in wallet is greater than the USD value, USD value is traded
    # otherwise available coin value is traded
    # prompt = ("Enter max limit in ", fiat, ": ")
    # input_options = {"1":"1000", "2":"300", "3":"500", "4":"750", "5":"2500", "6":"3500"}
    # response = userinput.GetStringChoice(prompt, **input_options)
    # fiat_limit = int(input_options.get(response))
    #fiat_limit_options = {"30m":"200", "4h":"250", "15m":"0", "1h":"0", "1d":"0", "1w":"0"}
    #fiat_limit = int(fiat_limit_options.get(timeframe))
    fiat_base = 180

    # define ATR AverageTrueRange period and multiplier to calculate average data
    # for example 30min candles during 2 weeks average would be a period of 672 = 14days / 30min timeframe
    # limit_options = {"30m":672, "4h":540, "15m":672, "1h":720, "1d":180}
    # limit = int(limit_options.get(timeframe))
    period_options = {"15m":5, "30m":7, "1h":10, "4h":14, "1d":30}
    period = int(period_options.get(timeframe))
    atr_multiplier = 3

    # define run period in seconds to fetch data
    runperiod = 15

    # set that you dont hold the coin pair in your account so you dont buy or sell multiple times
    buy_position = True
    sell_position = True

    # load all the coin pairs supported by the exchange
    markets = exchange.load_markets()
    
    # define coin pair and check if in exchange    
    coinpair = coinname+'/'+pair
    coinfiat = coinname+'/'+fiat
    pairfiat = pair+'/'+fiat
    
    # check if coin pair fiat are same and all pairs exist in the exchange
    if (coinname == pair):
        sys.exit("Coin and pair can not be the same")
    elif coinpair not in markets:
        sys.exit("Exchange does not have coin/pair")
    elif (coinname != fiat) and (coinfiat not in markets):
        sys.exit("Exchange does not have coin/fiat")
    elif (pair != fiat) and (pairfiat not in markets):
        sys.exit("Exchange does not have pair/fiat")
    else:
        print(coinpair," in ",exchange, ". Checking ", timeframe, " timeframes. Trade limit of ",fiat_limit,fiat, sep='')

    try:
        bars = exchange.fetch_ohlcv(coinpair, timeframe, limit=720)
        df = pd.DataFrame(bars[:-1], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        supertrend_data = supertrend(df, period, atr_multiplier)    
        updated = check_buy_sell_signals(supertrend_data)
        coin = update_database(coin, updated)
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        sys.exit("Exchange error!")
    
    return coin