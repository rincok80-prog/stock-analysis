import os
import math
import time
import json
import threading
import requests
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder='static', static_url_path='')

# Global ML Model and Data
model_lock = threading.Lock()
is_model_trained = False
trained_model = None
model_feature_means = []
model_feature_stds = []

# List of active stocks for scanner (cached)
active_stocks_cache = []
active_stocks_lock = threading.Lock()

# Global index trend cache (Shanghai Composite Index)
index_data_cache = {}

# Standard A-Share Stock Categories
def get_limit_up_rate(code):
    if code.startswith('688') or code.startswith('30'):
        return 0.20
    elif code.startswith('8') or code.startswith('43') or code.startswith('87') or code.startswith('88'):
        return 0.30
    else:
        return 0.10

# ----------------- Short-term Explosive Power Scoring Engine -----------------
def calculate_explosive_score(stock):
    float_cap = stock.get('float_market_cap', 0) / 100000000.0 # Convert to Billion (亿)
    cap_score = 0
    cap_analysis = ""
    
    if 2.0 <= float_cap <= 10.0:
        cap_score = 30
        cap_analysis = "流通盘仅 {:.1f} 亿，盘小轻量，游资拉升阻力极低".format(float_cap)
    elif 1.0 <= float_cap < 2.0 or 10.0 < float_cap <= 20.0:
        cap_score = 20
        cap_analysis = "流通盘 {:.1f} 亿，盘子适中，弹性良好，易拉升".format(float_cap)
    elif 20.0 < float_cap <= 50.0:
        cap_score = 10
        cap_analysis = "流通盘 {:.1f} 亿，中型股，短期爆发需较强资金推力".format(float_cap)
    else:
        cap_score = 5
        if float_cap < 1.0:
            cap_analysis = "流通盘仅 {:.1f} 亿，小微盘筹码极少，谨防流动性陷阱".format(float_cap)
        else:
            cap_analysis = "流通盘高达 {:.1f} 亿，权重过重，短期连板暴涨难度大".format(float_cap)

    vol_ratio = stock.get('volume_ratio', 1.0)
    vol_score = 0
    vol_analysis = ""
    if vol_ratio >= 2.0:
        vol_score = 25
        vol_analysis = "量比达 {:.2f}，买盘极其急迫，资金强攻".format(vol_ratio)
    elif 1.5 <= vol_ratio < 2.0:
        vol_score = 18
        vol_analysis = "量比 {:.2f}，温和放量突破平台".format(vol_ratio)
    elif 1.0 <= vol_ratio < 1.5:
        vol_score = 10
        vol_analysis = "量比 {:.2f}，成交量正常".format(vol_ratio)
    else:
        vol_score = 0
        vol_analysis = "量比 {:.2f}，量能缩减，交投清淡".format(vol_ratio)

    turnover = stock.get('turnover_rate', 0.0)
    turnover_score = 0
    turnover_analysis = ""
    if 8.0 <= turnover <= 25.0:
        turnover_score = 25
        turnover_analysis = "换手率 {:.2f}%，交投极度活跃，主力洗牌吸筹".format(turnover)
    elif 4.0 <= turnover < 8.0:
        turnover_score = 15
        turnover_analysis = "换手率 {:.2f}%，资金运作开始活跃".format(turnover)
    elif turnover > 25.0:
        turnover_score = 12
        turnover_analysis = "换手率 {:.2f}%，爆量过载，防主力高位筹码松动派发".format(turnover)
    elif 1.0 <= turnover < 4.0:
        turnover_score = 5
        turnover_analysis = "换手率 {:.2f}%，缩量调整状态".format(turnover)
    else:
        turnover_score = 0
        turnover_analysis = "换手率 {:.2f}%，缺乏换手，处于冬眠状态".format(turnover)

    pct_chg = stock.get('pct_change', 0.0)
    ret_score = 0
    ret_analysis = ""
    if 4.0 <= pct_chg <= 9.5:
        ret_score = 20
        ret_analysis = "今日大涨 {:.2f}%，启动大阳线突破".format(pct_chg)
    elif pct_chg > 9.5:
        ret_score = 18
        ret_analysis = "封死涨停板，多头惯性极强，具备强连板溢价".format(pct_chg)
    elif 1.0 <= pct_chg < 4.0:
        ret_score = 10
        ret_analysis = "今日小幅上攻 {:.2f}%".format(pct_chg)
    elif pct_chg < 0:
        ret_score = -10
        ret_analysis = "今日回调下跌 {:.2f}%".format(pct_chg)
    else:
        ret_score = 0
        ret_analysis = "今日平盘震荡"

    total_score = cap_score + vol_score + turnover_score + ret_score
    total_score = min(max(total_score, 0), 100)
    
    diagnosis = f"该股{cap_analysis}；{vol_analysis}；{turnover_analysis}；{ret_analysis}。"
    
    return total_score, diagnosis, {
        'cap_score': cap_score,
        'vol_score': vol_score,
        'turnover_score': turnover_score,
        'ret_score': ret_score,
        'float_cap_billion': float_cap,
        'diagnosis': diagnosis
    }

# Fetch Float Market Cap f117 for a single stock
def fetch_float_cap(secid):
    url = f"http://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f117"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        r = requests.get(url, headers=headers, timeout=3)
        return r.json().get('data', {}).get('f117', 0.0)
    except Exception:
        return 0.0

# ----------------- Pure Python ML Model: L2 Logistic Regression -----------------
class PureLogisticRegression:
    def __init__(self, lr=0.06, epochs=180, l2=0.015):
        self.lr = lr
        self.epochs = epochs
        self.l2 = l2
        self.weights = None
        self.bias = 0.0
        self.means = []
        self.stds = []

    def fit(self, X, y):
        n_samples = len(X)
        if n_samples == 0:
            return
        n_features = len(X[0])
        self.weights = [0.0] * n_features
        self.bias = 0.0

        # Calculate Z-score parameters
        self.means = [sum(X[i][j] for i in range(n_samples)) / n_samples for j in range(n_features)]
        self.stds = []
        for j in range(n_features):
            variance = sum((X[i][j] - self.means[j])**2 for i in range(n_samples)) / n_samples
            self.stds.append(math.sqrt(variance) if variance > 1e-6 else 1.0)

        # Scale features
        X_scaled = []
        for i in range(n_samples):
            X_scaled.append([(X[i][j] - self.means[j]) / self.stds[j] for j in range(n_features)])

        # Handle class imbalance
        n_pos = sum(y)
        n_neg = n_samples - n_pos
        w_pos = (n_neg / n_pos) if n_pos > 0 else 1.0
        w_neg = 1.0

        # Gradient Descent
        for _ in range(self.epochs):
            for i in range(n_samples):
                z = sum(X_scaled[i][j] * self.weights[j] for j in range(n_features)) + self.bias
                z = max(min(z, 50.0), -50.0)
                pred = 1.0 / (1.0 + math.exp(-z))
                error = pred - y[i]
                
                sample_weight = w_pos if y[i] == 1 else w_neg

                for j in range(n_features):
                    grad = (error * X_scaled[i][j] * sample_weight) + (self.l2 * self.weights[j])
                    self.weights[j] -= self.lr * grad
                self.bias -= self.lr * error * sample_weight

    def predict_proba(self, x):
        if not self.weights or len(x) != len(self.weights):
            return 0.5
        x_scaled = [(x[j] - self.means[j]) / self.stds[j] for j in range(len(x))]
        z = sum(x_scaled[j] * self.weights[j] for j in range(len(x))) + self.bias
        z = max(min(z, 50.0), -50.0)
        return 1.0 / (1.0 + math.exp(-z))

# ----------------- Pure Python Financial Indicator Engine -----------------
def calc_ma(closes, period):
    ma = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        ma[i] = sum(closes[i - period + 1 : i + 1]) / period
    return ma

def calc_ema(closes, period):
    ema = [None] * len(closes)
    if not closes:
        return ema
    ema[0] = closes[0]
    alpha = 2.0 / (period + 1.0)
    for i in range(1, len(closes)):
        ema[i] = closes[i] * alpha + ema[i-1] * (1.0 - alpha)
    return ema

def calc_macd(closes, fast=12, slow=26, signal=9):
    n = len(closes)
    dif = [None] * n
    dea = [None] * n
    macd_hist = [None] * n

    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)

    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            dif[i] = ema_fast[i] - ema_slow[i]

    first_dif_idx = -1
    for i in range(n):
        if dif[i] is not None:
            first_dif_idx = i
            break

    if first_dif_idx != -1:
        dea[first_dif_idx] = dif[first_dif_idx]
        alpha = 2.0 / (signal + 1.0)
        for i in range(first_dif_idx + 1, n):
            dea[i] = dif[i] * alpha + dea[i-1] * (1.0 - alpha)

    for i in range(n):
        if dif[i] is not None and dea[i] is not None:
            macd_hist[i] = 2.0 * (dif[i] - dea[i])

    return dif, dea, macd_hist

def calc_kdj(highs, lows, closes, period=9, fk=3, fd=3):
    n = len(closes)
    k_vals = [50.0] * n
    d_vals = [50.0] * n
    j_vals = [50.0] * n

    for i in range(period - 1, n):
        lowest_low = min(lows[i - period + 1 : i + 1])
        highest_high = max(highs[i - period + 1 : i + 1])
        close_price = closes[i]

        if highest_high != lowest_low:
            rsv = (close_price - lowest_low) / (highest_high - lowest_low) * 100.0
        else:
            rsv = 50.0

        prev_k = k_vals[i-1] if i > 0 else 50.0
        prev_d = d_vals[i-1] if i > 0 else 50.0

        k_vals[i] = (2.0 / fk) * prev_k + (1.0 / fk) * rsv
        d_vals[i] = (2.0 / fd) * prev_d + (1.0 / fd) * k_vals[i]
        j_vals[i] = 3.0 * k_vals[i] - 2.0 * d_vals[i]

    return k_vals, d_vals, j_vals

def calc_rsi(closes, period=14):
    n = len(closes)
    rsi = [None] * n
    if n <= 1:
        return rsi

    gains = [0.0] * (n - 1)
    losses = [0.0] * (n - 1)
    for i in range(1, n):
        diff = closes[i] - closes[i-1]
        if diff > 0:
            gains[i-1] = diff
        else:
            losses[i-1] = -diff

    if n > period:
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        if avg_loss == 0:
            rsi[period] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[period] = 100.0 - (100.0 / (1.0 + rs))

        for i in range(period + 1, n):
            avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
            if avg_loss == 0:
                rsi[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    return rsi

def calc_boll(closes, period=20, width=2):
    n = len(closes)
    mid = [None] * n
    upper = [None] * n
    lower = [None] * n

    ma = calc_ma(closes, period)
    for i in range(period - 1, n):
        mid[i] = ma[i]
        variance = sum((closes[j] - mid[i])**2 for j in range(i - period + 1, i + 1)) / period
        std_dev = math.sqrt(variance)
        upper[i] = mid[i] + width * std_dev
        lower[i] = mid[i] - width * std_dev

    return mid, upper, lower

def calc_atr(highs, lows, closes, period=14):
    n = len(closes)
    tr = [0.0] * n
    atr = [None] * n
    if n == 0:
        return atr

    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        h_l = highs[i] - lows[i]
        h_pc = abs(highs[i] - closes[i-1])
        l_pc = abs(lows[i] - closes[i-1])
        tr[i] = max(h_l, h_pc, l_pc)

    if n >= period:
        atr[period - 1] = sum(tr[:period]) / period
        for i in range(period, n):
            atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period

    return atr

# ----------------- Feature Extraction & Labeling (23 Dimensions) -----------------
def extract_all_features(klines, code, current_float_cap=0.0, latest_close=1.0, index_data_dict=None):
    closes = [k['close'] for k in klines]
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]
    volumes = [k['volume'] for k in klines]
    turnover_rates = [k['turnover_rate'] for k in klines]

    n = len(closes)
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)

    dif, dea, macd_hist = calc_macd(closes)
    k_vals, d_vals, j_vals = calc_kdj(highs, lows, closes)
    rsi14 = calc_rsi(closes, 14)
    rsi6 = calc_rsi(closes, 6)
    mid, upper, lower = calc_boll(closes)
    atr = calc_atr(highs, lows, closes)

    limit_rate = get_limit_up_rate(code)

    # Pre-calculate limit-up days
    is_limit_up = [False] * n
    for i in range(1, n):
        prev_close = closes[i-1]
        limit_p = round(prev_close * (1 + limit_rate), 2)
        if closes[i] >= limit_p - 0.01:
            is_limit_up[i] = True

    # Pre-calculate recent 10-day limit-up counts
    limit_up_counts = [0] * n
    for i in range(n):
        count = 0
        for idx in range(max(0, i - 9), i + 1):
            if is_limit_up[idx]:
                count += 1
        limit_up_counts[i] = count

    # Pre-calculate volume MA5
    vol_ma5 = [0.0] * n
    for i in range(4, n):
        vol_ma5[i] = sum(volumes[i-4 : i+1]) / 5.0

    cur_price = latest_close if latest_close > 0.0 else closes[-1]

    all_features = {}
    for t in range(30, n):
        pct_1d = (closes[t] - closes[t-1]) / closes[t-1] * 100.0 if t > 0 else 0.0
        pct_3d = (closes[t] - closes[t-3]) / closes[t-3] * 100.0 if t >= 3 else 0.0
        pct_5d = (closes[t] - closes[t-5]) / closes[t-5] * 100.0 if t >= 5 else 0.0
        pct_10d = (closes[t] - closes[t-10]) / closes[t-10] * 100.0 if t >= 10 else 0.0

        v_ma5 = vol_ma5[t]
        vol_ratio = volumes[t] / v_ma5 if v_ma5 > 0.0 else 1.0

        dist5 = (closes[t] - ma5[t]) / ma5[t] * 100.0 if ma5[t] else 0.0
        dist10 = (closes[t] - ma10[t]) / ma10[t] * 100.0 if ma10[t] else 0.0
        dist20 = (closes[t] - ma20[t]) / ma20[t] * 100.0 if ma20[t] else 0.0
        
        ma_align = 1.0 if (ma5[t] and ma10[t] and ma20[t] and ma5[t] > ma10[t] > ma20[t]) else 0.0

        macd_cross_3d = 0.0
        for idx in range(max(0, t - 2), t + 1):
            if idx > 0 and dif[idx] is not None and dea[idx] is not None and dif[idx-1] is not None and dea[idx-1] is not None:
                if dif[idx] >= dea[idx] and dif[idx-1] < dea[idx-1]:
                    macd_cross_3d = 1.0
                    break

        boll_pos_val = (closes[t] - lower[t]) / (upper[t] - lower[t]) if (upper[t] and lower[t] and upper[t] != lower[t]) else 0.5
        boll_w_val = (upper[t] - lower[t]) / mid[t] if (upper[t] and lower[t] and mid[t]) else 0.0
        atr_pct_val = atr[t] / closes[t] * 100.0 if (atr[t] and closes[t]) else 0.0

        # Dynamic Free-Float Market Cap (Billion RMB)
        float_cap_t = (current_float_cap * (closes[t] / cur_price)) / 100000000.0 if cur_price > 0.0 else 0.0

        # Align index data
        date = klines[t]['date']
        idx_pct_1d = 0.0
        idx_pct_5d = 0.0
        idx_ma_align = 0.0
        if index_data_dict and date in index_data_dict:
            idx_pct_1d = index_data_dict[date]['pct_1d']
            idx_pct_5d = index_data_dict[date]['pct_5d']
            idx_ma_align = index_data_dict[date]['ma_align']

        features = [
            pct_1d,
            pct_3d,
            pct_5d,
            pct_10d,
            vol_ratio,
            turnover_rates[t] if turnover_rates[t] is not None else 1.0,
            float(limit_up_counts[t]),
            ma_align,
            dist5,
            dist10,
            dist20,
            macd_hist[t] if macd_hist[t] is not None else 0.0,
            macd_cross_3d,
            j_vals[t] if j_vals[t] is not None else 50.0,
            rsi6[t] if rsi6[t] is not None else 50.0,
            rsi14[t] if rsi14[t] is not None else 50.0,
            boll_pos_val,
            boll_w_val,
            atr_pct_val,
            float_cap_t,
            idx_pct_1d,
            idx_pct_5d,
            idx_ma_align
        ]
        all_features[t] = features
        
    return all_features

FEATURE_NAMES = [
    "今日涨跌幅", "3日涨跌幅", "5日涨跌幅", "10日涨跌幅", 
    "量比", "换手率", "近10日涨停天数", "均线多头", 
    "偏离5日均线", "偏离10日均线", "偏离20日均线", "MACD柱值", 
    "MACD最近金叉", "KDJ-J值", "RSI-6值", "RSI-14值",
    "BOLL通道位置", "BOLL通道宽度", "ATR波动率",
    "流通市值(亿)", "大盘今日涨跌幅", "大盘5日涨跌幅", "大盘趋势"
]

def check_limit_up_days(klines, start_idx, end_idx, code):
    limit_rate = get_limit_up_rate(code)
    for idx in range(start_idx, min(end_idx + 1, len(klines))):
        if idx > 0:
            prev_close = klines[idx-1]['close']
            limit_price = round(prev_close * (1.0 + limit_rate), 2)
            if klines[idx]['close'] >= limit_price - 0.01:
                return True
    return False

# ----------------- Pattern Setup Matching -----------------
def match_setups(klines, code):
    closes = [k['close'] for k in klines]
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]
    opens = [k['open'] for k in klines]
    volumes = [k['volume'] for k in klines]
    
    t = len(closes) - 1
    if t < 25:
        return []

    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    dif, dea, macd_hist = calc_macd(closes)
    k_vals, d_vals, j_vals = calc_kdj(highs, lows, closes)
    rsi6 = calc_rsi(closes, 6)

    matched = []

    # 1. 龙回头 (Dragon Returns)
    limit_rate = get_limit_up_rate(code)
    limit_ups = 0
    recent_high = -1.0
    for idx in range(t - 10, t):
        if idx > 0:
            prev_close = closes[idx-1]
            limit_price = round(prev_close * (1.0 + limit_rate), 2)
            if closes[idx] >= limit_price - 0.01:
                limit_ups += 1
            if closes[idx] > recent_high:
                recent_high = closes[idx]

    if limit_ups >= 2 and recent_high > 0:
        pullback_pct = (recent_high - closes[t]) / recent_high * 100.0
        dist_to_ma10 = abs(closes[t] - ma10[t]) / ma10[t] * 100.0 if ma10[t] else 999.0
        dist_to_ma20 = abs(closes[t] - ma20[t]) / ma20[t] * 100.0 if ma20[t] else 999.0
        
        if pullback_pct >= 8.0 and (dist_to_ma10 < 3.0 or dist_to_ma20 < 3.0) and closes[t] >= opens[t]:
            matched.append({
                "name": "龙回头战法",
                "score": 85,
                "desc": "前期龙头股洗盘回踩！10天内出现过至少2次涨停，目前已从高点回撤超过8%且在10日或20日均线附近企稳翻红，属于典型主力缩量洗盘后二次启航信号。",
                "risk": "若跌破20日均线应坚决止损。"
            })

    # 2. 放量突破 (Volume Breakout)
    period_high_20 = max(closes[t-20 : t]) if t >= 20 else 99999.0
    vol_ma5 = sum(volumes[t-5 : t]) / 5.0
    vol_ratio = volumes[t] / vol_ma5 if vol_ma5 > 0.0 else 1.0
    
    if closes[t] >= period_high_20 * 0.98 and vol_ratio > 2.0 and (closes[t] - closes[t-1])/closes[t-1]*100.0 > 4.0:
        matched.append({
            "name": "放量突破平台",
            "score": 90,
            "desc": "股价放量突破前期整理平台！当前价格接近20日新高，且今日成交量达到5日均量的2.0倍以上，大阳线穿透，资金抢筹明显。",
            "risk": "谨防假突破，若明日回踩平台下沿则失效。"
        })

    # 3. 双叉共振 (MACD + KDJ Double Gold Cross)
    macd_cross = False
    if dif[t] is not None and dea[t] is not None and dif[t-1] is not None and dea[t-1] is not None:
        if (dif[t] >= dea[t] and dif[t-1] < dea[t-1]) or (t > 1 and dif[t-1] >= dea[t-1] and dif[t-2] < dea[t-2]):
            macd_cross = True
            
    kdj_cross = False
    if k_vals[t] is not None and d_vals[t] is not None:
        if (k_vals[t] >= d_vals[t] and k_vals[t-1] < d_vals[t-1]) or (t > 1 and k_vals[t-1] >= d_vals[t-1] and k_vals[t-2] < d_vals[t-2]):
            kdj_cross = True

    if macd_cross and kdj_cross and k_vals[t] < 75:
        matched.append({
            "name": "金叉共振战法",
            "score": 80,
            "desc": "技术指标双重金叉共振！MACD指标与KDJ指标同时在低位或中位发出金叉买入信号，指标底背离修复，短线多头力量占优。",
            "risk": "震荡市中金叉可能反复，需配合成交量放大验证。"
        })

    # 4. 超跌反弹 (Oversold Rebound)
    drop_10d = (closes[t] - closes[t-10]) / closes[t-10] * 100.0 if t >= 10 else 0.0
    if drop_10d <= -15.0 and (j_vals[t] < 5.0 or rsi6[t] < 20.0) and closes[t] > closes[t-1]:
        matched.append({
            "name": "超跌反弹金身",
            "score": 75,
            "desc": "极度超跌底背离反弹！股价10天内累计下跌超15%，短线指标J值或RSI-6进入极度超卖区后今日首次翻红收阳，报复性反弹一触即发。",
            "risk": "属于左侧交易，反弹高度取决于量能，切忌盲目重仓。"
        })

    # 5. 红三兵 (Three Red Soldiers)
    if closes[t] > opens[t] and closes[t-1] > opens[t-1] and closes[t-2] > opens[t-2]:
        if closes[t] > closes[t-1] > closes[t-2]:
            chg1 = (closes[t] - closes[t-1])/closes[t-1]*100.0
            chg2 = (closes[t-1] - closes[t-2])/closes[t-2]*100.0
            chg3 = (closes[t-2] - closes[t-3])/closes[t-3]*100.0 if t >= 3 else 2.0
            if 0.5 <= chg1 <= 5.5 and 0.5 <= chg2 <= 5.5 and 0.5 <= chg3 <= 5.5:
                matched.append({
                    "name": "红三兵战法",
                    "score": 70,
                    "desc": "红三兵稳健上攻！连续3个交易日收出温和阳线，重心逐日抬高，通常为底部启动或上升途中的突破信号。",
                    "risk": "如若在高位出现则可能属于诱多，在低位或盘整期出现可信度极高。"
                })

    return matched

# ----------------- EastMoney API Request Helpers -----------------
def fetch_kline_data(secid, limit=300):
    url = f"http://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&beg=20200101&end=20500101"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'http://quote.eastmoney.com/'
    }
    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code != 200:
            return None
        data = r.json()
        klines_raw = data.get('data', {}).get('klines', [])
        if not klines_raw:
            return None
        
        klines = []
        for kl in klines_raw[-limit:]:
            parts = kl.split(',')
            if len(parts) < 11:
                continue
            klines.append({
                'date': parts[0],
                'open': float(parts[1]),
                'close': float(parts[2]),
                'high': float(parts[3]),
                'low': float(parts[4]),
                'volume': float(parts[5]),
                'turnover': float(parts[6]),
                'amplitude': float(parts[7]),
                'pct_change': float(parts[8]),
                'change_amount': float(parts[9]),
                'turnover_rate': float(parts[10]) if parts[10] != '-' else 0.0
            })
        return klines
    except Exception as e:
        print(f"Error fetching kline for {secid}: {e}")
        return None

def build_index_data_dict():
    kl = fetch_kline_data("1.000001", limit=500)
    if not kl:
        return {}
    closes = [k['close'] for k in kl]
    n = len(closes)
    ma5 = calc_ma(closes, 5)
    ma20 = calc_ma(closes, 20)
    
    idx_dict = {}
    for i in range(20, n):
        date = kl[i]['date']
        pct_1d = kl[i]['pct_change']
        pct_5d = (closes[i] - closes[i-5]) / closes[i-5] * 100.0 if i >= 5 else 0.0
        ma_align = 1.0 if (ma5[i] and ma20[i] and ma5[i] > ma20[i]) else 0.0
        idx_dict[date] = {
            'pct_1d': pct_1d,
            'pct_5d': pct_5d,
            'ma_align': ma_align
        }
    return idx_dict

# ----------------- Global Model Background Training -----------------
def background_train_model():
    global trained_model, is_model_trained, index_data_cache
    print("Background training thread started...", flush=True)

    # 1. Fetch Index Data
    index_data_cache = build_index_data_dict()
    print(f"Fetched index K-line. Total aligned market days: {len(index_data_cache)}", flush=True)

    # 2. Fetch A-Share Stock list with codes, current prices, and free-float caps f21
    url = 'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=80&po=1&np=1&fltt=2&invt=2&fid=f6&fs=m:0+t:6,m:1+t:2,m:0+t:80,m:1+t:23,m:0+t:81+s:2048&fields=f2,f12,f13,f14,f21'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=5)
        diff_list = r.json().get('data', {}).get('diff', [])
        if not diff_list:
            print("Failed to fetch active stock list for training.", flush=True)
            return
        
        global active_stocks_cache
        with active_stocks_lock:
            active_stocks_cache = [{
                'code': x['f12'], 
                'market': x['f13'], 
                'name': x['f14'],
                'price': float(x['f2']) if x.get('f2') != '-' and x.get('f2') is not None else 1.0,
                'float_market_cap': float(x['f21']) if x.get('f21') != '-' and x.get('f21') is not None else 0.0
            } for x in diff_list]

        print(f"Fetched {len(active_stocks_cache)} active stocks. Building training dataset...", flush=True)

        X_train = []
        y_train = []

        stock_klines = {}
        
        def download_worker(stock):
            secid = f"{stock['market']}.{stock['code']}"
            kl = fetch_kline_data(secid, limit=250)
            if kl and len(kl) >= 40:
                stock_klines[stock['code']] = kl

        pool = []
        for stock in active_stocks_cache:
            t = threading.Thread(target=download_worker, args=(stock,))
            pool.append(t)
            t.start()
            if len(pool) >= 15:
                for pt in pool:
                    pt.join()
                pool = []
        for pt in pool:
            pt.join()

        print(f"Downloaded K-lines for {len(stock_klines)} stocks. Processing features...", flush=True)

        for code, klines in stock_klines.items():
            # Find the stock detail config in cache
            s_config = next((s for s in active_stocks_cache if s['code'] == code), {})
            s_float_cap = s_config.get('float_market_cap', 0.0)
            s_price = s_config.get('price', 1.0)
            
            try:
                all_feats = extract_all_features(klines, code, current_float_cap=s_float_cap, latest_close=s_price, index_data_dict=index_data_cache)
                n_days = len(klines)
                
                for t in range(30, n_days - 3):
                    feat = all_feats[t]
                    hit_limit = check_limit_up_days(klines, t+1, t+3, code)
                    label = 1 if hit_limit else 0
                    
                    X_train.append(feat)
                    y_train.append(label)
            except Exception:
                continue

        n_samples = len(X_train)
        n_pos = sum(y_train)
        print(f"Dataset compiled. Total samples: {n_samples}, Positives (hit limit-up in next 3 days): {n_pos} ({n_pos/n_samples*100.0:.2f}%)", flush=True)

        if n_samples > 100:
            lr_model = PureLogisticRegression(lr=0.06, epochs=180, l2=0.015)
            lr_model.fit(X_train, y_train)
            
            with model_lock:
                trained_model = lr_model
                is_model_trained = True
            
            print("Pure Python Machine Learning model trained successfully with 23 features!", flush=True)
            for name, weight in zip(FEATURE_NAMES, lr_model.weights):
                print(f"  Feature: {name} | Weight: {weight:.4f}", flush=True)
        else:
            print("Insufficient data samples to train model.", flush=True)

    except Exception as e:
        print(f"Error in background training: {e}", flush=True)

def init_training():
    t = threading.Thread(target=background_train_model)
    t.daemon = True
    t.start()

# ----------------- Flask API Endpoints -----------------

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    
    url = f"https://searchapi.eastmoney.com/api/suggest/get?input={q}&type=14"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        r = requests.get(url, headers=headers, timeout=3)
        data = r.json()
        raw_suggestions = data.get("QuotationCodeTable", {}).get("Data", [])
        
        results = []
        for sug in raw_suggestions:
            results.append({
                'code': sug.get('Code'),
                'name': sug.get('Name'),
                'pinyin': sug.get('PinYin'),
                'market': sug.get('MktNum'),
                'quote_id': sug.get('QuoteID')
            })
        return jsonify(results)
    except Exception as e:
        print(f"Search API error: {e}")
        q_lower = q.lower()
        results = []
        with active_stocks_lock:
            for s in active_stocks_cache:
                if q_lower in s['code'].lower() or q_lower in s['name'].lower():
                    results.append({
                        'code': s['code'],
                        'name': s['name'],
                        'pinyin': '',
                        'market': str(s['market']),
                        'quote_id': f"{s['market']}.{s['code']}"
                    })
        return jsonify(results[:10])

@app.route('/api/kline')
def api_kline():
    code = request.args.get('code', '').strip()
    market = request.args.get('market', '').strip()
    if not code or not market:
        return jsonify({'error': 'Missing code or market'}), 400

    secid = f"{market}.{code}"
    klines = fetch_kline_data(secid, limit=350)
    
    if not klines or len(klines) < 30:
        return jsonify({'error': 'Failed to load stock K-line data or history too short'}), 404

    closes = [k['close'] for k in klines]
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]
    
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma30 = calc_ma(closes, 30)

    dif, dea, macd_hist = calc_macd(closes)
    k_vals, d_vals, j_vals = calc_kdj(highs, lows, closes)
    rsi6 = calc_rsi(closes, 6)
    rsi12 = calc_rsi(closes, 12)
    mid, upper, lower = calc_boll(closes)

    t_latest = len(klines) - 1
    latest_bar = klines[-1]

    # Fetch real-time float market cap f117 for calculations
    f117_val = fetch_float_cap(secid)
    
    # Check if index data dict is ready, otherwise rebuild it
    global index_data_cache
    if not index_data_cache:
        index_data_cache = build_index_data_dict()

    # Compile the 23-dimensional feature array for the loaded stock
    all_feats = extract_all_features(klines, code, current_float_cap=f117_val, latest_close=latest_bar['close'], index_data_dict=index_data_cache)
    features_latest = all_feats[t_latest]
    
    prob = 0.5
    feature_importances = []
    
    with model_lock:
        if is_model_trained and trained_model:
            prob = trained_model.predict_proba(features_latest)
            for i, name in enumerate(FEATURE_NAMES):
                x_val = features_latest[i]
                mean_val = trained_model.means[i]
                std_val = trained_model.stds[i]
                x_scaled = (x_val - mean_val) / std_val
                weight = trained_model.weights[i]
                contrib = x_scaled * weight
                feature_importances.append({
                    'name': name,
                    'val': x_val,
                    'weight': weight,
                    'contrib': contrib
                })
            feature_importances.sort(key=lambda x: abs(x['contrib']), reverse=True)

    if not is_model_trained:
        # Fallback scoring model
        score = 50.0
        if (ma5[t_latest] and ma10[t_latest] and ma5[t_latest] > ma10[t_latest]): score += 10
        if macd_hist[t_latest] and macd_hist[t_latest] > 0: score += 10
        if j_vals[t_latest] and 20 < j_vals[t_latest] < 80: score += 5
        if rsi6[t_latest] and 50 < rsi6[t_latest] < 80: score += 5
        
        vol_ratio = features_latest[4] 
        if vol_ratio > 1.8: score += 10
        elif vol_ratio < 0.6: score -= 10
        
        prob = min(max(score / 100.0, 0.05), 0.95)
        for i, name in enumerate(FEATURE_NAMES):
            feature_importances.append({
                'name': name,
                'val': features_latest[i],
                'weight': 0.1 if i % 2 == 0 else -0.1,
                'contrib': 0.1 if i % 2 == 0 else -0.1
            })

    matched_setups_list = match_setups(klines, code)

    pos_factors = []
    neg_factors = []
    
    pct_chg = features_latest[0]
    if pct_chg > 5.0:
        pos_factors.append(f"今日股价强势大涨 {pct_chg:.2f}%，多头动能爆发")
    elif pct_chg < -5.0:
        neg_factors.append(f"今日股价大跌 {pct_chg:.2f}%，短线面临抛压")

    vol_ratio = features_latest[4]
    if vol_ratio > 2.0:
        pos_factors.append(f"今日异常放量（量比 {vol_ratio:.2f}），资金关注度极高")
    elif vol_ratio < 0.5:
        neg_factors.append(f"今日严重缩量（量比 {vol_ratio:.2f}），资金观望情绪浓厚")

    k_latest, d_latest, j_latest = k_vals[t_latest], d_vals[t_latest], j_vals[t_latest]
    if j_latest < 10:
        pos_factors.append(f"KDJ-J值极度超卖 ({j_latest:.1f})，存在强烈的技术性反弹需求")
    elif j_latest > 95:
        neg_factors.append(f"KDJ-J值进入严重超买区 ({j_latest:.1f})，需警惕短线见顶冲高回落")

    boll_pos = features_latest[16]
    if boll_pos > 0.95:
        pos_factors.append("股价向上突破BOLL上轨，突破拉升行情展开")
    elif boll_pos < 0.05:
        neg_factors.append("股价向下砸穿BOLL下轨，空头过度宣泄")

    dif_val, dea_val, hist_val = dif[t_latest], dea[t_latest], macd_hist[t_latest]
    if dif_val is not None and dea_val is not None:
        if dif_val > dea_val and hist_val > 0:
            pos_factors.append("MACD处于多头区域（DIF > DEA），且红色能量柱持续放大")
        elif dif_val < dea_val and hist_val < 0:
            neg_factors.append("MACD处于空头死叉区（DIF < DEA），绿色柱体压制股价")

    limit_ups_10d = int(features_latest[6])
    if limit_ups_10d >= 1:
        pos_factors.append(f"近10个交易日内出现过 {limit_ups_10d} 次涨停，极具妖股基因与炒作弹性")

    if not pos_factors:
        pos_factors.append("技术均线处于合理区间，筹码结构平稳")
    if not neg_factors:
        neg_factors.append("未见明显量价背离，跟随大盘震荡调整")

    stock_eval = {
        'code': code,
        'market': market,
        'price': latest_bar['close'],
        'pct_change': latest_bar['pct_change'],
        'turnover_rate': latest_bar['turnover_rate'],
        'volume_ratio': features_latest[4],
        'float_market_cap': f117_val
    }
    
    exp_score, exp_diag, exp_details = calculate_explosive_score(stock_eval)

    cur_ma5 = ma5[t_latest] if ma5[t_latest] else latest_bar['close']
    cur_ma20 = ma20[t_latest] if ma20[t_latest] else latest_bar['close']
    
    if prob >= 0.70:
        buy_advice = f"该股当前机器学习多维指标评级为【强势拉升/多头掌控】。短线买入策略：建议分批低吸建仓。最佳左侧买点在5日线（均线支撑位约 {cur_ma5:.2f} 元）企稳时，或者在股价日内放量突破今日最高点时顺势追击。防守位建议设定在今日最低价下方，跌破坚决止损。"
        timing_analysis = "极短线上涨窗口已经彻底打开。主力资金筹码结构极其强悍，量比换手出现多头共振。预计未来 1-3 个交易日内极易迎来向上封板（涨停）冲刺或加速大阳线，是短线追随游资主升浪的黄金交易时间。"
    elif prob >= 0.40:
        buy_advice = f"该股当前评级为【缩量洗盘/主力蓄势】。买入建议：建议采取“底仓试错+突破加仓”的稳健操作。可在股价回调至20日均线强支撑位（约 {cur_ma20:.2f} 元）获得支撑时逢低吸纳，或者在股价向上放量突破前期整理平台阻力位时，顺势分批追入。"
        timing_analysis = "短线爆发的时机取决于【日内成交量是否能够再次翻倍放大】。当前处于缩量洗盘的中后段，多空双方趋于平衡。技术上需静待KDJ低位交叉或MACD能量柱由绿转红。若日内量比突发放大至 1.5 以上，通常为洗盘结束启动信号，拉升窗口预计在 3-5 个交易日内到来。"
    else:
        buy_advice = f"该股当前评级为【常态调整/筹码松散】。买入建议：短线面临调整或主力派发抛压，建议以防守、持币观望为主，切勿盲目进行左侧抄底。阻力重重，耐心等待日K线重新收复并稳固站上20日均线（多空分水阻力位约 {cur_ma20:.2f} 元）之上，且成交量极度萎缩筑底后，再考虑试错买入。"
        timing_analysis = "目前上涨时机尚未成熟，短线大概率继续维持缩量震荡、寻底或宽幅洗盘格局。上方套牢盘偏厚，主力需要 5-8 个交易日甚至更长的时间进行震荡洗筹以清理浮筹。上涨契机需等待成交量达到阶段“地量”且KDJ/RSI等指标在超卖区出现底背离共振后，才能迎来超跌反弹动能。"

    response_data = {
        'klines': klines,
        'indicators': {
            'ma5': ma5,
            'ma10': ma10,
            'ma20': ma20,
            'ma30': ma30,
            'macd': {
                'dif': dif,
                'dea': dea,
                'hist': macd_hist
            },
            'kdj': {
                'k': k_vals,
                'd': d_vals,
                'j': j_vals
            },
            'rsi': {
                'rsi6': rsi6,
                'rsi12': rsi12
            },
            'boll': {
                'mid': mid,
                'upper': upper,
                'lower': lower
            }
        },
        'prediction': {
            'probability': prob,
            'is_trained': is_model_trained,
            'factors': {
                'positive': pos_factors,
                'negative': neg_factors
            },
            'feature_importances': feature_importances[:6],
            'explosive_score': exp_score,
            'explosive_diagnosis': exp_diag,
            'explosive_details': exp_details,
            'buy_advice': buy_advice,
            'timing_analysis': timing_analysis
        },
        'matched_setups': matched_setups_list
    }
    
    return jsonify(response_data)

@app.route('/api/scanner')
def api_scanner():
    stocks_to_scan = []
    with active_stocks_lock:
        stocks_to_scan = list(active_stocks_cache)
        
    if not stocks_to_scan:
        url = 'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=40&po=1&np=1&fltt=2&invt=2&fid=f6&fs=m:0+t:6,m:1+t:2,m:0+t:80,m:1+t:23,m:0+t:81+s:2048&fields=f12,f13,f14'
        try:
            r = requests.get(url, timeout=4)
            diff_list = r.json().get('data', {}).get('diff', [])
            stocks_to_scan = [{'code': x['f12'], 'market': x['f13'], 'name': x['f14']} for x in diff_list]
        except Exception:
            return jsonify({'error': 'Failed to load scan target list'}), 500

    results = []
    results_lock = threading.Lock()
    threads = []
    
    scan_targets = stocks_to_scan[:40]

    def scan_worker(stock):
        secid = f"{stock['market']}.{stock['code']}"
        klines = fetch_kline_data(secid, limit=60)
        if not klines or len(klines) < 30:
            return
        
        t_latest = len(klines) - 1
        
        # Get float market cap config from cache
        s_config = next((s for s in active_stocks_cache if s['code'] == stock['code']), {})
        s_float_cap = s_config.get('float_market_cap', 0.0)
        s_price = s_config.get('price', 1.0)
        
        global index_data_cache
        if not index_data_cache:
            index_data_cache = build_index_data_dict()

        all_feats = extract_all_features(klines, stock['code'], current_float_cap=s_float_cap, latest_close=s_price, index_data_dict=index_data_cache)
        features = all_feats[t_latest]
        
        prob = 0.5
        with model_lock:
            if is_model_trained and trained_model:
                prob = trained_model.predict_proba(features)
            else:
                score = 50.0
                closes = [k['close'] for k in klines]
                ma5 = calc_ma(closes, 5)
                ma10 = calc_ma(closes, 10)
                if ma5[t_latest] and ma10[t_latest] and ma5[t_latest] > ma10[t_latest]: score += 10
                pct_chg = features[0]
                if pct_chg > 4.0: score += 15
                vol_ratio = features[4]
                if vol_ratio > 1.8: score += 15
                prob = min(max(score / 100.0, 0.05), 0.95)

        setups = match_setups(klines, stock['code'])
        strategy_matched = setups[0]['name'] if setups else "常规走势"

        latest_close = klines[-1]['close']
        pct_change = klines[-1]['pct_change']

        with results_lock:
            results.append({
                'code': stock['code'],
                'market': stock['market'],
                'name': stock['name'],
                'price': latest_close,
                'pct_change': pct_change,
                'probability': prob,
                'strategy': strategy_matched
            })

    for s in scan_targets:
        t = threading.Thread(target=scan_worker, args=(s,))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()

    results.sort(key=lambda x: x['probability'], reverse=True)
    return jsonify(results)

@app.route('/api/leaderboard')
def api_leaderboard():
    url = 'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=80&po=1&np=1&fltt=2&invt=2&fid=f6&fs=m:0+t:6,m:1+t:2,m:0+t:80,m:1+t:23,m:0+t:81+s:2048&fields=f2,f3,f12,f13,f14,f8,f10,f21'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        r = requests.get(url, headers=headers, timeout=5)
        diff_list = r.json().get('data', {}).get('diff', [])
        
        results = []
        for x in diff_list:
            price = x.get('f2')
            if price == '-' or price is None:
                continue
                
            stock_dict = {
                'code': x.get('f12'),
                'market': x.get('f13'),
                'name': x.get('f14'),
                'price': float(price),
                'pct_change': float(x.get('f3', 0.0)) if x.get('f3') != '-' else 0.0,
                'turnover_rate': float(x.get('f8', 0.0)) if x.get('f8') != '-' else 0.0,
                'volume_ratio': float(x.get('f10', 0.0)) if x.get('f10') != '-' else 1.0,
                'float_market_cap': float(x.get('f21', 0.0)) if x.get('f21') != '-' else 0.0
            }
            
            score, diagnosis, details = calculate_explosive_score(stock_dict)
            
            results.append({
                'code': stock_dict['code'],
                'market': stock_dict['market'],
                'name': stock_dict['name'],
                'price': stock_dict['price'],
                'pct_change': stock_dict['pct_change'],
                'volume_ratio': stock_dict['volume_ratio'],
                'turnover_rate': stock_dict['turnover_rate'],
                'float_market_cap_billion': details['float_cap_billion'],
                'explosive_score': score,
                'diagnosis': diagnosis
            })
            
        results.sort(key=lambda x: (x['explosive_score'], x['turnover_rate']), reverse=True)
        return jsonify(results[:15])
    except Exception as e:
        print(f"Error in leaderboard API: {e}")
        return jsonify({'error': 'Failed to load leaderboard data'}), 500

@app.route('/api/favorites_quotes')
def api_favorites_quotes():
    secids = request.args.get('secids', '').strip()
    if not secids:
        return jsonify([])
    
    url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?secids={secids}&fields=f2,f3,f12,f13,f14&fltt=2"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        r = requests.get(url, headers=headers, timeout=5)
        diff_list = r.json().get('data', {}).get('diff', [])
        
        if isinstance(diff_list, dict):
            diff_list = [diff_list]
            
        results = []
        for x in diff_list:
            if not x:
                continue
            price = x.get('f2')
            if price == '-' or price is None:
                continue
            results.append({
                'code': x.get('f12'),
                'market': x.get('f13'),
                'name': x.get('f14'),
                'price': float(price),
                'pct_change': float(x.get('f3', 0.0)) if x.get('f3') != '-' else 0.0
            })
        return jsonify(results)
    except Exception as e:
        print(f"Error in favorites quotes API: {e}")
        return jsonify({'error': 'Failed to load favorites quotes'}), 500

init_training()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
