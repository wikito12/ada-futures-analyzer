import datetime as dt
import math
import requests
import pandas as pd
import streamlit as st

PRODUCT_ID = 'ADA-30OCT26-CDE'
BASE = 'https://api.coinbase.com/api/v3/brokerage/market/products'
CONTRACT_SIZE = 1000
TICK = 0.0001
INTERVALS = {'5 minutes': ('FIVE_MINUTE', 300), '15 minutes': ('FIFTEEN_MINUTE', 900), '1 hour': ('ONE_HOUR', 3600), '4 hours': ('FOUR_HOUR', 14400)}
st.set_page_config(page_title='Nano ADA Futures • Signal Lab 2.0', layout='wide')
st.title('Nano ADA Futures • Signal Lab 2.0')
st.caption('Read-only • Coinbase futures candles only • No orders placed')

@st.cache_data(ttl=60, show_spinner=False)
def product():
    r = requests.get(f'{BASE}/{PRODUCT_ID}', timeout=15)
    r.raise_for_status()
    p = r.json()
    detail = p.get('future_product_details') or {}
    if p.get('product_id') != PRODUCT_ID or p.get('product_type') != 'FUTURE':
        raise ValueError('Product identity or futures type mismatch.')
    if str(detail.get('contract_size')) != str(CONTRACT_SIZE) or not str(detail.get('contract_expiry', '')).startswith('2026-10-30'):
        raise ValueError('Contract size or expiry mismatch.')
    return p

@st.cache_data(ttl=60, show_spinner=False)
def candles(granularity, seconds, bucket):
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    # Request 290 completed bars; API may return fewer, particularly for illiquid products.
    params = {'start': now - 291 * seconds, 'end': now, 'granularity': granularity}
    r = requests.get(f'{BASE}/{PRODUCT_ID}/candles', params=params, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload.get('candles'), list):
        raise ValueError('Missing candles array.')
    df = pd.DataFrame(payload['candles'])
    cols = ['start', 'open', 'high', 'low', 'close', 'volume']
    if df.empty or not set(cols).issubset(df.columns):
        raise ValueError('No usable OHLCV candles.')
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=cols).sort_values('start').drop_duplicates('start')
    df = df[(df.low > 0) & (df.high >= df.low) & (df.close > 0) & (df.start + seconds <= now)]
    if len(df) < 60:
        raise ValueError(f'Insufficient completed candles: {len(df)} (need 60).')
    df['time'] = pd.to_datetime(df.start, unit='s', utc=True)
    return df.reset_index(drop=True)

def indicators(df):
    x = df.copy()
    c = x.close
    x['ema20'] = c.ewm(span=20, adjust=False).mean()
    x['ema50'] = c.ewm(span=50, adjust=False).mean()
    change = c.diff()
    up = change.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    down = (-change.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    x['rsi'] = (100 - 100 / (1 + up / down.replace(0, float('nan')))).fillna(50)
    x.loc[(down == 0) & (up > 0), 'rsi'] = 100
    x.loc[(up == 0) & (down > 0), 'rsi'] = 0
    prev = c.shift()
    tr = pd.concat([(x.high-x.low), (x.high-prev).abs(), (x.low-prev).abs()], axis=1).max(axis=1)
    x['atr'] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    plus = 100 * (x.high.diff().where(lambda s: (s > (-x.low.diff())) & (s > 0), 0).ewm(alpha=1/14, adjust=False).mean() / x.atr.replace(0, float('nan')))
    minus = 100 * ((-x.low.diff()).where(lambda s: (s > x.high.diff()) & (s > 0), 0).ewm(alpha=1/14, adjust=False).mean() / x.atr.replace(0, float('nan')))
    dx = 100 * (plus-minus).abs() / (plus+minus).replace(0, float('nan'))
    x['adx'] = dx.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    # Rolling session VWAP anchored to UTC day, not an exchange-specific session.
    typical = (x.high+x.low+x.close)/3
    day = x.time.dt.floor('D')
    vol = x.volume.clip(lower=0)
    x['vwap'] = (typical*vol).groupby(day).cumsum() / vol.groupby(day).cumsum().replace(0, float('nan'))
    x['relvol'] = vol / vol.shift(1).rolling(20, min_periods=15).mean().replace(0, float('nan'))
    x['resistance'] = x.high.shift(1).rolling(20, min_periods=15).max()
    x['support'] = x.low.shift(1).rolling(20, min_periods=15).min()
    return x

def direction(x):
    v = x.iloc[-1]
    if v.close > v.ema20 > v.ema50 and v.rsi >= 50:
        return 'BULLISH'
    if v.close < v.ema20 < v.ema50 and v.rsi <= 50:
        return 'BEARISH'
    return 'NEUTRAL'

def tick_round(value):
    return round(round(value/TICK)*TICK, 4)

st.info('ADA 30 OCT 26 | Coinbase product ADA-30OCT26-CDE | 1 contract = 1,000 ADA')
try:
    p = product()
    st.success('Coinbase FUTURE contract identity and October 30, 2026 expiry verified.')
except Exception as e:
    st.error(f'Contract verification failed; signals disabled: {e}')
    st.stop()

if st.button('Refresh analysis'):
    candles.clear()
    product.clear()

now = dt.datetime.now(dt.timezone.utc)
frames, problems = {}, {}
for label, (gran, sec) in INTERVALS.items():
    try:
        raw = candles(gran, sec, int(now.timestamp())//60)
        last_end = dt.datetime.fromtimestamp(int(raw.start.iloc[-1]+sec), tz=dt.timezone.utc)
        age = (now-last_end).total_seconds()
        # Allow 2 intervals for late or sparse candles, but never label them live.
        if age > 2*sec:
            raise ValueError(f'STALE data: latest candle ended {last_end:%Y-%m-%d %H:%M} UTC ({age/60:.0f} min ago)')
        frames[label] = indicators(raw)
    except Exception as e:
        problems[label] = str(e)

for label, err in problems.items():
    st.warning(f'{label}: {err}')

if '1 hour' not in frames or '15 minutes' not in frames:
    st.error('1-hour and 15-minute verified, fresh futures candles are required. Signals disabled.')
    st.stop()

hour, quarter = frames['1 hour'], frames['15 minutes']
h, q = hour.iloc[-1], quarter.iloc[-1]
ht, qt = direction(hour), direction(quarter)
context = direction(frames['4 hours']) if '4 hours' in frames else 'UNAVAILABLE'
price = float(q.close)
atr = float(q.atr)
valid = all(math.isfinite(float(v)) for v in [q.adx, q.rsi, q.atr]) and atr > 0
adx_good = valid and q.adx >= 20
vol_good = pd.notna(q.relvol) and q.relvol >= 1.15
vwap_up = pd.notna(q.vwap) and price > q.vwap
vwap_down = pd.notna(q.vwap) and price < q.vwap
near_up = pd.notna(q.resistance) and 0 <= q.resistance-price <= max(atr*0.8, TICK)
near_down = pd.notna(q.support) and 0 <= price-q.support <= max(atr*0.8, TICK)
break_up = pd.notna(q.resistance) and price > q.resistance
break_down = pd.notna(q.support) and price < q.support
long_confirmed = (ht == 'BULLISH' and qt == 'BULLISH' and adx_good and vol_good and vwap_up and break_up and q.rsi < 75)
short_confirmed = (ht == 'BEARISH' and qt == 'BEARISH' and adx_good and vol_good and vwap_down and break_down and q.rsi > 25)
if long_confirmed:
    signal, stage = 'LONG setup', 'CONFIRMED'
elif short_confirmed:
    signal, stage = 'SHORT setup', 'CONFIRMED'
elif near_up and ht != 'BEARISH':
    signal, stage = 'WAIT', 'BREAKOUT WATCH — upside'
elif near_down and ht != 'BULLISH':
    signal, stage = 'WAIT', 'BREAKOUT WATCH — downside'
else:
    signal, stage = 'WAIT', 'NO CONFIRMED SETUP'

# Heuristic condition score, NOT a probability of winning.
long_score = (25 if ht == 'BULLISH' else 0) + (20 if qt == 'BULLISH' else 0) + (15 if adx_good else 0) + (15 if vol_good else 0) + (10 if vwap_up else 0) + (15 if break_up else 0)
short_score = (25 if ht == 'BEARISH' else 0) + (20 if qt == 'BEARISH' else 0) + (15 if adx_good else 0) + (15 if vol_good else 0) + (10 if vwap_down else 0) + (15 if break_down else 0)
score = long_score if signal.startswith('LONG') else short_score if signal.startswith('SHORT') else max(long_score, short_score)

st.subheader(f'{signal} — {stage}')
st.metric('Condition score (not win probability)', f'{score}/100')
a,b,c = st.columns(3)
a.metric('15m last close', f'${price:.4f}')
b.metric('15m RSI', f'{q.rsi:.1f}')
c.metric('15m ADX', f'{q.adx:.1f}' if pd.notna(q.adx) else 'N/A')
st.write(f'4-hour context: **{context}** | 1-hour trend: **{ht}** | 15-minute trend: **{qt}**')
st.write(f'15m VWAP (UTC-day): **${q.vwap:.4f}**' if pd.notna(q.vwap) else '15m VWAP: unavailable (no volume)')
st.write(f'15m relative volume: **{q.relvol:.2f}×**' if pd.notna(q.relvol) else '15m relative volume: unavailable')
st.write(f'20-bar resistance: **${q.resistance:.4f}** | support: **${q.support:.4f}**')
st.caption('Early breakout watch is not an entry signal. Confirmed means rule conditions passed, not that a profitable trade is assured.')

if signal != 'WAIT':
    if signal.startswith('LONG'):
        stop = tick_round(price-1.5*atr)
        target = tick_round(price+3*atr)
    else:
        stop = tick_round(price+1.5*atr)
        target = tick_round(price-3*atr)
    if target > 0 and stop > 0:
        st.write(f'Illustrative entry reference **${price:.4f}** | stop **${stop:.4f}** | target **${target:.4f}**')
        st.caption(f'Approx. risk per contract ${abs(stop-price)*CONTRACT_SIZE:.2f}; target movement ${abs(target-price)*CONTRACT_SIZE:.2f}; excludes fees, slippage, and gaps.')
else:
    st.write('No stop/target suggested until confirmation.')

selected = st.selectbox('Inspect chart timeframe', list(frames), index=list(frames).index('15 minutes'))
chart = frames[selected]
st.line_chart(chart.set_index('time')[['close','ema20','ema50']], y_label='USD per ADA')
sec = INTERVALS[selected][1]
last_end = dt.datetime.fromtimestamp(int(chart.start.iloc[-1]+sec), tz=dt.timezone.utc)
st.caption(f'Last completed {selected} candle ended {last_end:%Y-%m-%d %H:%M} UTC • {len(chart)} candles • checked at {now:%Y-%m-%d %H:%M} UTC')
with st.expander('Method and limitations'):
    st.write('1h and 15m trend: close relative to EMA20/EMA50 with RSI confirmation. Confirmed breakout requires 15m close beyond prior 20-bar range, 1h/15m trend alignment, ADX ≥20, relative volume ≥1.15, and UTC-day VWAP alignment. Watch flags price within 0.8 ATR of a range boundary, subject to 1h trend. Score sums rule conditions; it is not calibrated to historical win probabilities.')
    st.write('4h context is informational. 5m is chart-only. Candle availability can be sparse; stale data disables the required timeframe. Signals are evaluated on completed candles and may lag the market. No backtest or live performance validation has been performed.')
st.warning('Educational, experimental analytics only. Futures are high-risk. This app never places trades. Validate with historical out-of-sample testing before relying on signals.')
