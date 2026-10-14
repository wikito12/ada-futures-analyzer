import datetime as dt
import math
import requests
import pandas as pd
import streamlit as st

PRODUCT_ID = 'ADA-30OCT26-CDE'
BASE = 'https://api.coinbase.com/api/v3/brokerage/market/products'
CONTRACT_SIZE = 1000
INTERVALS = {'5 minutes': ('FIVE_MINUTE', 300), '15 minutes': ('FIFTEEN_MINUTE', 900), '1 hour': ('ONE_HOUR', 3600), '4 hours': ('FOUR_HOUR', 14400)}

st.set_page_config(page_title='Nano ADA Futures • Verified Signals', layout='wide')
st.title('Nano ADA Futures • Verified Signals')
st.caption('Read-only analytics • Coinbase futures candles only • No orders sent')

@st.cache_data(ttl=60, show_spinner=False)
def product():
    r = requests.get(f'{BASE}/{PRODUCT_ID}', timeout=15)
    r.raise_for_status()
    p = r.json()
    if p.get('product_id') != PRODUCT_ID or p.get('product_type') != 'FUTURE':
        raise ValueError('Coinbase product identity/type did not match the expected futures contract.')
    detail = p.get('future_product_details') or {}
    if str(detail.get('contract_size')) != str(CONTRACT_SIZE) or not str(detail.get('contract_expiry', '')).startswith('2026-10-30'):
        raise ValueError('Coinbase contract size or expiration did not match.')
    return p

@st.cache_data(ttl=60, show_spinner=False)
def candles(granularity, seconds):
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    # 180 bars per request; comfortably below Coinbase's candle-count limit.
    params = {'start': now - 180 * seconds, 'end': now, 'granularity': granularity}
    r = requests.get(f'{BASE}/{PRODUCT_ID}/candles', params=params, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if 'candles' not in payload or not isinstance(payload['candles'], list):
        raise ValueError('Coinbase returned no valid candles collection.')
    frame = pd.DataFrame(payload['candles'])
    required = {'start', 'open', 'high', 'low', 'close', 'volume'}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError('No usable futures OHLCV data returned.')
    for name in required:
        frame[name] = pd.to_numeric(frame[name], errors='coerce')
    frame = frame.dropna(subset=list(required)).sort_values('start').drop_duplicates('start')
    frame = frame[(frame['low'] > 0) & (frame['high'] >= frame['low']) & (frame['close'] > 0)]
    # Exclude current incomplete candle.
    frame = frame[frame['start'] + seconds <= now]
    if len(frame) < 55:
        raise ValueError(f'Only {len(frame)} completed bars received; at least 55 required.')
    frame['time'] = pd.to_datetime(frame['start'], unit='s', utc=True)
    return frame.reset_index(drop=True)

def rsi(close, period=14):
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = up / down.replace(0, float('nan'))
    result = 100 - 100 / (1 + rs)
    result = result.mask((down == 0) & (up > 0), 100)
    result = result.mask((up == 0) & (down > 0), 0)
    return result.fillna(50)

def analyze(frame):
    close = frame['close']
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    momentum = rsi(close)
    tr = pd.concat([frame['high'] - frame['low'], (frame['high'] - close.shift()).abs(), (frame['low'] - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    price = float(close.iloc[-1]); e20 = float(ema20.iloc[-1]); e50 = float(ema50.iloc[-1]); r = float(momentum.iloc[-1]); a = float(atr.iloc[-1])
    signal = 'WAIT'
    if price > e20 > e50 and 52 <= r <= 72:
        signal = 'LONG setup'
    elif price < e20 < e50 and 28 <= r <= 48:
        signal = 'SHORT setup'
    stop = target = None
    if math.isfinite(a) and a > 0 and signal != 'WAIT':
        stop = price - 1.5 * a if signal.startswith('LONG') else price + 1.5 * a
        target = price + 3 * a if signal.startswith('LONG') else price - 3 * a
    return signal, price, e20, e50, r, a, stop, target

st.info('Contract: ADA 30 OCT 26 | Coinbase ID: ADA-30OCT26-CDE | 1 contract = 1,000 ADA')
try:
    p = product()
    st.success('Verified Coinbase FUTURE product and October 30, 2026 expiration.')
    st.caption(f"Coinbase product status: {p.get('status', 'unknown')}; displayed product price: {p.get('price', 'unknown')} USD")
except Exception as exc:
    st.error(f'Contract verification failed. Signals disabled. {exc}')
    st.stop()

interval = st.selectbox('Chart timeframe', list(INTERVALS), index=2)
granularity, seconds = INTERVALS[interval]
try:
    df = candles(granularity, seconds)
    signal, price, ema20, ema50, strength, atr, stop, target = analyze(df)
except Exception as exc:
    st.error(f'Unable to verify {interval} futures candles. Signals disabled. {exc}')
    st.stop()

st.subheader(signal)
a, b, c = st.columns(3)
a.metric('Last completed candle close', f'${price:.4f}')
b.metric('RSI (14)', f'{strength:.1f}')
c.metric('ATR (14)', f'${atr:.5f}')
st.line_chart(df.set_index('time')[['close']], y_label='USD per ADA')
st.caption(f'Latest completed candle: {df.iloc[-1]["time"]:%Y-%m-%d %H:%M} UTC | {len(df)} verified bars')
st.write(f'EMA20: ${ema20:.4f} | EMA50: ${ema50:.4f}')
if stop is not None:
    st.write(f'Illustrative stop: ${stop:.4f} | illustrative 2:1 target: ${target:.4f}')
    st.caption(f'Illustrative price movement per contract: stop ${abs(price-stop)*CONTRACT_SIZE:.2f}; target ${abs(target-price)*CONTRACT_SIZE:.2f}, before fees, slippage, and commissions.')
else:
    st.write('No qualifying trend/momentum setup; no stop or target suggested.')
st.warning('Educational technical signals only—not investment advice or an instruction to trade. Futures carry substantial risk. Data may be delayed or unavailable. The app never submits orders.')
with st.expander('Signal methodology'):
    st.write('LONG: close > EMA20 > EMA50 and RSI 52–72. SHORT: close < EMA20 < EMA50 and RSI 28–48. Otherwise WAIT. ATR-based illustrative 1.5× stop and 3× target. Uses only completed candles.')
