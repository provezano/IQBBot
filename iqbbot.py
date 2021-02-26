import os
import math
import time
import random
import requests
import numpy as np
import pandas as pd
import threading
from threading import Timer
from multiprocessing import Process
from datetime import datetime, timedelta
#from IPython.display import clear_output
from iqoptionapi.stable_api import IQ_Option

def bollinger_bands(s, n=20, k=2.5):
    """get_bollinger_bands DataFrame
    s is series of values
    k is multiple of standard deviations
    n is rolling window
    """

    b = pd.concat([s, s.rolling(n).agg([np.mean, np.std])], axis=1)
    b['upper'] = b['mean'] + b['std'] * k
    b['lower'] = b['mean'] - b['std'] * k

    return b.drop('std', axis=1)

def ema(s, window):
    return pd.Series.ewm(s,span=window,min_periods=0,adjust=False,ignore_na=False).mean()[-1]

def remaining_seconds(minutes = 5):
    return (minutes-datetime.now().minute%minutes)*60 + 60-datetime.now().second%60

def is_asset_open(asset, all_opened_assets, mode='turbo'):
    return all_opened_assets[mode][asset]["open"]


def get_all_opened_assets(iqoapi):
    return iqoapi.get_all_open_time()


def get_all_profits(iqoapi):
    return iqoapi.get_all_profit()


def get_digital_profit(iqoapi, active, expiration):
    iqoapi.subscribe_strike_list(active, expiration)
    payout = iqoapi.get_digital_current_profit(active, expiration)
    while not payout:
        time.sleep(0.1)
        payout = iqoapi.get_digital_current_profit(active, expiration)
    iqoapi.unsubscribe_strike_list(active, expiration)
    return {'digital': math.floor(payout) / 100}

def get_expiration_time():
    expiration = 5
    minutes = float(((datetime.now()).strftime('%M.%S'))[1:])
    sec, min = math.modf(minutes)

    if min >= 5:
        min = min - 5

    if min == 0 and sec < 0.30:
        expiration = 5
    elif min == 0 and sec > 0.29:
        expiration = 4
    elif min == 1 and sec < 0.30:
        expiration = 4
    elif min == 1 and sec > 0.29:
        expiration = 3
    elif min == 2 and sec < 0.30:
        expiration = 3
    elif min == 2 and sec > 0.29:
        expiration = 2
    elif min == 3 and sec < 0.30:
        expiration = 2
    elif min == 3 and sec > 0.29:
        expiration = 1
    elif min == 4 and sec < 0.30:
        expiration = 1
    elif min == 4 and sec > 0.29:
        expiration = 5

    return expiration

def print_result(order_date, active, money, action, expiration, amount, wl, gale):
    print('--- --- --- --- ---')
    print('Datetime: ', order_date)
    print('Active:\t', active)
    print('Money:\t', money)
    print('Action:\t', action.capitalize())
    print('Exp.:\t', expiration)
    print('Amount:\t', amount)
    print('Result:\t', wl)
    print('Gale:\t', gale)
    print('--- --- --- --- ---')

def buy_digital(iqoapi, active, money, action, expiration):
    _, id = (iqoapi.buy_digital_spot(active, money, action, expiration))
    # order_date = datetime.now()
    #
    # if id != "error":
    #    while True:
    #        t = iqoapi.check_win_digital_v2(id)
    #        check, win = t if type(t) != dict else None, None
    #        if check:
    #            break
    #    if win is not None:
    #        if win < 0:
    #            print_result(order_date, active, money, action, expiration, win, 'Loss', False)
    #            return False, win
    #        else:
    #            print_result(order_date, active, money * 2, action, expiration, win, 'Win', False)
    #            return True, win
    # else:
    #    print("please try again")


def buy_turbo(iqoapi, active, money, action, expiration):
    _, trade_id = iqoapi.buy(money, active, action, expiration)
    # order_date = datetime.now()
    # while True:
    #    info = iqoapi.check_win_v3(trade_id)
    #    #print(info)
    #    if info is not None:
    #        if info < 0:
    #            print_result(order_date, active, money, action, expiration, info, 'Loss', False)
    #        else:
    #            print_result(order_date, active, money, action, expiration, info, 'Win', False)
    #        return True, info

def most_profit_mode(iqoapi, active, expiration, min_payout):
    _mpm = ['digital', False]

    all_opened_assets = get_all_opened_assets(iqoapi)
    opened = dict()
    for mode in ['turbo', 'digital']:
        opened[mode] = is_asset_open(active, all_opened_assets, mode)
    if opened['turbo'] or opened['digital']:
        profits = get_all_profits(iqoapi)
        if opened['digital']:
            if active in profits:
                profits[active].update(get_digital_profit(iqoapi, active, expiration))
            else:
                profits[active] = get_digital_profit(iqoapi, active, expiration)
        priority_mode_list = []
        for k, v in opened.items():
            if v:
                priority_mode_list.append([k, profits[active][k]])
        priority_mode_list = sorted(priority_mode_list, key=lambda x: x[1], reverse=True)
        if priority_mode_list:
            mode, best_payout = priority_mode_list[0]
            if best_payout >= min_payout:
                if mode == 'turbo':
                    _mpm[0], _mpm[1] = 'turbo', True
                else:
                    _mpm[0], _mpm[1] = 'digital', True
            else:
                # print(str(datetime.now()), "The payout for " + active + " is below " + str(float(best_payout) * 100) + "%")
                _mpm[0], _mpm[1] = 'payout', False
        else:
            # print(str(datetime.now()), active, "- Something went wrong. No items in your priority list :(")
            _mpm[0], _mpm[1] = 'error', False
    else:
        # print(str(datetime.now()), active + " is closed now. :(")
        _mpm[0], _mpm[1] = 'closed', False

    return _mpm[0], _mpm[1]

def telegram_bot_sendtext(bot_token, bot_chatID, bot_message):
    send_text = 'https://api.telegram.org/bot' + bot_token + '/sendMessage?chat_id=' + bot_chatID + '&parse_mode=Markdown&text=' + bot_message

    response = requests.get(send_text)

    return response.json()

def run_bbot(email, pwd, active, expiration_time=5, money=2, bb_std=2.1, bb_window=20, ema_window=100, acc_type='PRACTICE', bot_token = None, bot_chatID = None):
    primes = [17, 19, 23, 29, 31, 37, 41, 43, 47]

    # Connect to IQOption
    iqoapi = IQ_Option(email, pwd)
    iqoapi.connect()
    
    iqoapi.change_balance(acc_type)

    # Check if pair is active and get their payout
    mpm = most_profit_mode(iqoapi, active, expiration_time, 0.70)
    update_time = random.choice(primes[1:]) if mpm[0] in ('turbo', 'digital') else 17
    print("BBot [Active: {} Expiration: {} Type: {} Bet: {} Mode: {} UT: {}]".format(active, expiration_time, acc_type,
                                                                                     money, mpm[0], update_time))
    t_mpm = Timer(remaining_seconds(update_time), lambda: None)
    t_mpm.start()

    # Define the number of digits of price and indicators
    max_dict = 101
    size = expiration_time * 60

    #Get total of digits used by iq
    iqoapi.start_candles_stream(active, size, max_dict)
    candles = iqoapi.get_realtime_candles(active, size)
    frac, n = math.modf(candles[max(candles.keys())]['close'])
    nd = 7 - len(str(int(n)))
    ndi = 6 - len(str(int(n)))

    # Initialize several variables
    #order = [False]
    back_to_bb = True
    timer_trade = None

    # Initialize our infinite loop :D
    while True:
        # Check pair's status and its payout
        if not t_mpm.is_alive():
            old_status = mpm[0]
            mpm = most_profit_mode(iqoapi, active, expiration_time, 0.70)
            if mpm[0] != old_status:
                if mpm[0] in ('payout', 'error', 'closed'):
                    update_time = 17
                    print(" --- --- --- ")
                    print(str(datetime.now()), active, "- Something went wrong - Reason:", mpm[0])
                    print(" --- --- --- ")
                else:
                    update_time = random.choice(primes[1:])
                    print(" --- --- --- ")
                    print(str(datetime.now()), active, "- is open now! Trading in", mpm[0])
                    print(" --- --- --- ")

            t_mpm = Timer(remaining_seconds(update_time), lambda: None)  # Restart
            t_mpm.start()
            
        if mpm[1] and (not timer_trade or not timer_trade.is_alive()):
            candles=iqoapi.get_realtime_candles(active, size)
            
            df_time = pd.DataFrame([(datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S'), candles[ts]["close"], candles[ts]["max"], candles[ts]["min"]) for ts in sorted(candles.keys(), reverse=True)], columns=['from', 'close', 'max', 'min']).set_index('from')
            df_time = df_time.sort_index(ascending=False)
            
            df_time_close = df_time['close']
            #df_time_max = df_time['max']
            #df_time_min = df_time['min']

            curr_ema = ema(df_time_close.iloc[0:100], ema_window) # pegando valor corrente + 99
            bbands = bollinger_bands(df_time_close.iloc[0:20], bb_window, bb_std) 

            bb_hi = round(bbands.iloc[-1]['upper'], ndi)
            bb_lw = round(bbands.iloc[-1]['lower'], ndi)
            curr_price = df_time_close.iloc[0]

            #avg_max = np.mean(df_time_max[0:13])
            #avg_min = np.mean(df_time_min[0:13])

            if not back_to_bb and not timer_trade.is_alive():
                if bb_hi < curr_price < bb_lw:
                    back_to_bb = True

            #print(bb_hi, curr_price, bb_lw)
            #clear_output(wait=True)

            if back_to_bb and (not timer_trade or not timer_trade.is_alive()):
                if  curr_price > bb_hi and curr_ema > bb_hi:
                    signal = 'put'
                    
                    if mpm[0] == 'turbo':
                        threading.Thread(target=buy_turbo, args=(iqoapi, active, money, signal, get_expiration_time())).start()
                    elif mpm[0] == 'digital':
                        threading.Thread(target=buy_digital, args=(iqoapi, active, money, signal, expiration_time)).start()

                    back_to_bb = False
                    timer_trade = Timer(remaining_seconds(), lambda: None)
                    timer_trade.start()

                    text = "IQBBot2.2 Ativo: {} - {}\nTaxa: {}\nSinal: {}\nHorário: {}\nExpiração: {}".format(active, mpm[0], curr_price, signal,
                        datetime.now().strftime("%m/%d/%Y, %H:%M:%S"), expiration_time)
                    
                    if bot_token is not None and bot_chatID is not None: telegram_bot_sendtext(bot_token, bot_chatID, text)
                    
                    print(text)

                elif curr_price < bb_lw and curr_ema < bb_lw:
                    signal = 'call'
                    
                    if mpm[0] == 'turbo':
                        threading.Thread(target=buy_turbo, args=(iqoapi, active, money, signal, get_expiration_time())).start()
                    elif mpm[0] == 'digital':
                        threading.Thread(target=buy_digital, args=(iqoapi, active, money, signal, expiration_time)).start()

                    back_to_bb = False
                    timer_trade = Timer(remaining_seconds(), lambda: None)
                    timer_trade.start()

                    text = "IQBBot2.2 Ativo: {} - {}\nTaxa: {}\nSinal: {}\nHorário: {}\nExpiração: {}".format(active, mpm[0], curr_price, signal,
                        datetime.now().strftime("%m/%d/%Y, %H:%M:%S"), expiration_time)
                    
                    if bot_token is not None and bot_chatID is not None: telegram_bot_sendtext(bot_token, bot_chatID, text)
                    
                    print(text)
        
        time.sleep(.1)
    #break
    iqoapi.stop_candles_stream(active, size)
            
if __name__ == '__main__':
    os.environ['MKL_NUM_THREADS'] = '1'
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['MKL_DYNAMIC'] = 'FALSE'

    expiration = 5
    bb_std = 2.5
    bb_window = 20
    ema_window = 100
    money = 200
    acc_type = 'PRACTICE'
    email = None
    pwd = None
    bot_token = None
    bot_chatID = None

    actives = {expiration: (
        'EURAUD', 'EURCAD', 'EURCHF', 'EURGBP', 'EURJPY', 'EURNZD', 'EURUSD', 'AUDCHF', 'AUDJPY', 'AUDNZD', 'AUDUSD',
        'CADCHF', 'CADJPY', 'CHFJPY', 'GBPAUD', 'GBPCHF', 'GBPJPY', 'GBPNZD', 'GBPUSD', 'NZDUSD', 'USDCAD', 'USDCHF',
        'USDJPY', 'USDNOK')}

    print(" -------------------------------------------- ")
    print("  IQBBot - https://github.com/provezano/BBot ")
    print(" -------------------------------------------- \n\n")

    email = input("\tType your e-mail: ")
    pwd = input("\tType your password: ")
    
    opt = input('\tWhat type of your account? (1-Real / 2-Demo) ')
    while opt not in ('1', '2'):
        opt = input('\tWhat type of your account? (1-Real / 2-Demo) ')

    if int(opt) == 1:
        acc_type = 'REAL'
    else:
        acc_type = 'PRACTICE'

    money = float((input('\tWhich trading amount? R$ ' )).replace(',','.'))

    opt = input("\tDo you want to send alert messages to Telegram (Token and ChatID required)? (1: Yes / 2-No) ")
    while opt not in ('1', '2'):
        opt = input("\tDo you want to send alert messages to Telegram (Token and ChatID required)? (1: Yes / 2-No) ")

    if int(opt) == 1:
        bot_token = input("\tEnter the Token: ")
        bot_chatID = input("\tEnter the ChatID: ")

    
    print(" -------------------------------------------- ")
    print("\nDefault Settings")
    print(" -------------------------------------------- \n")

    print("Bollinger Bands Window Size: {}".format(bb_window))
    print("Bollinger Bands Standard Deviation: {}".format(bb_std))
    print("EMA Window Size: {}".format(ema_window))
    print("\nExpiration: {}".format(expiration))
    print("Trading Amount: {}".format(money))
    print("Account Type: {}".format(acc_type))

    print('\nInitializing BOT for each Currency Pair...\n')

    for expiration_time, active_list in actives.items():
        for active in active_list:
            Process(target=run_bbot, args=(email, pwd, active, expiration, money, bb_std, bb_window, ema_window, acc_type, bot_token, bot_chatID)).start()