import io, math, time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title='Nano ADA Futures | Signal Lab', page_icon='📈', layout='wide')
st.markdown("""<style>
.block-container {padding-top:1rem; padding-bottom:5rem; max-width:980px}
[data-testid="stMetric"] {background:rgba(128,128,128,.08); border-radius:12px; padding:12px}
@media(max-width:640px){
 .block-container {padding-left:0.8rem;padding-right:0.8rem;padding-top:0.5rem}
 h1 {font-size:1.55rem!important} h2 {font-size:1.2rem!important}
 [data-testid="stHorizontalBlock"] {flex-wrap:wrap!important;gap:.45rem!important}
 [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {min-width:42%!important; flex:1 1 42%!important}
 button {min-height:44px}
}
</style>""", unsafe_allow_html=True)
st.title('📱 Nano ADA Futures • Signal Lab')
st.caption('iPhone-friendly research dashboard • Monthly Coinbase ADA futures • No orders are sent')
MULTIPLIER=1000
GRAN={'5m':'FIVE_MINUTE','15m':'FIFTEEN_MINUTE','1h':'ONE_HOUR','4h':'FOUR_HOUR'}
SECONDS={'5m':300,'15m':900,'1h':3600,'4h':14400}

def load_public(product,tf):
    now=int(time.time()); span=SECONDS[tf]*300
    url=f'https://api.coinbase.com/api/v3/brokerage/market/products/{product}'
    s=requests.Session(); s.headers.update({'User-Agent':'ADA-Futures-SignalLab/1.0'})
    info=s.get(url,timeout=12); info.raise_for_status(); meta=info.json().get('product',info.json())
    # Fail closed: spot and perpetual products are never accepted as monthly futures.
    kind=str(meta.get('product_type','')).upper()
    details=meta.get('future_product_details') or {}
    if kind!='FUTURE' or not details:
        raise ValueError('Coinbase did not identify this product as a futures instrument with futures details. Refusing to analyze spot or unknown product as monthly ADA futures.')
    exp=str(details.get('contract_expiry') or details.get('expiration_time') or '')
    if not exp:
        raise ValueError('Futures expiration not returned; cannot verify monthly contract. Use verified futures OHLCV CSV instead.')
    if 'ADA' not in str(meta.get('product_id',product)).upper():
        raise ValueError('Product does not appear to be ADA futures.')
    if 'PERP' in str(meta).upper() or 'PERPETUAL' in str(meta).upper():
        raise ValueError('Perpetual product rejected; select monthly ADA futures.')
    try:
        expiry=pd.to_datetime(exp,utc=True)
        if expiry<=pd.Timestamp.now(tz='UTC'): raise ValueError('Contract expired.')
    except ValueError: raise
    except Exception: raise ValueError('Cannot parse expiration timestamp.')
    res=s.get(url+'/candles',params={'start':str(now-span),'end':str(now),'granularity':GRAN[tf],'limit':350},timeout=15)
    res.raise_for_status(); data=res.json().get('candles',[])
    df=pd.DataFrame(data)
    if df.empty: raise ValueError('No candles returned for the exact futures contract.')
    df=df.rename(columns={'start':'timestamp'})
    return clean(df),exp

def clean(df):
    df=df.copy(); df.columns=[str(c).strip().lower() for c in df.columns]
    if 'start' in df.columns and 'timestamp' not in df.columns: df=df.rename(columns={'start':'timestamp'})
    required=['timestamp','open','high','low','close','volume']
    if any(c not in df for c in required): raise ValueError('Required CSV columns: '+', '.join(required))
    ts=df['timestamp']
    if pd.api.types.is_numeric_dtype(ts) or (ts.astype(str).str.fullmatch(r'\d{10,13}').all()):
        vals=pd.to_numeric(ts); df['timestamp']=pd.to_datetime(vals,unit='ms' if vals.max()>1e11 else 's',utc=True)
    else: df['timestamp']=pd.to_datetime(ts,utc=True,errors='coerce')
    for c in required[1:]: df[c]=pd.to_numeric(df[c],errors='coerce')
    df=df.dropna(subset=required).drop_duplicates('timestamp').sort_values('timestamp')
    df=df[(df.high>=df.low)&(df.high>=df[['open','close']].max(axis=1))&(df.low<=df[['open','close']].min(axis=1))&(df.volume>=0)&(df.close>0)]
    return df.set_index('timestamp')

def analyze(df):
    if len(df)<210: return {'signal':'WAIT','reason':f'Only {len(df)} bars; need at least 210 completed candles.'}
    x=df.copy(); c=x.close
    x['ema20']=c.ewm(span=20,adjust=False).mean(); x['ema50']=c.ewm(span=50,adjust=False).mean(); x['ema200']=c.ewm(span=200,adjust=False).mean()
    delta=c.diff(); gains=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); losses=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    rs=gains/losses.replace(0,np.nan); x['rsi']=100-100/(1+rs)
    macd=c.ewm(span=12,adjust=False).mean()-c.ewm(span=26,adjust=False).mean(); hist=macd-macd.ewm(span=9,adjust=False).mean()
    x['hist']=hist; tr=pd.concat([(x.high-x.low),(x.high-c.shift()).abs(),(x.low-c.shift()).abs()],axis=1).max(axis=1)
    x['atr']=tr.ewm(alpha=1/14,adjust=False).mean(); x['vol_avg']=x.volume.rolling(20).mean()
    z=x.iloc[-1]; prev=x.iloc[-2]
    if any(pd.isna(z[k]) for k in ['rsi','atr','vol_avg']): return {'signal':'WAIT','reason':'Insufficient indicator history.'}
    trend=1 if z.close>z.ema20>z.ema50>z.ema200 else -1 if z.close<z.ema20<z.ema50<z.ema200 else 0
    momentum=1 if 52<=z.rsi<=72 and z.hist>0 and z.hist>=prev.hist else -1 if 28<=z.rsi<=48 and z.hist<0 and z.hist<=prev.hist else 0
    breakout=1 if z.close>x.high.iloc[-21:-1].max() else -1 if z.close<x.low.iloc[-21:-1].min() else 0
    volume_confirm=z.volume>=1.2*z.vol_avg
    atr_pct=z.atr/z.close
    score=trend*45+momentum*30+breakout*(15 if volume_confirm else 5)
    if not volume_confirm: score*=0.85
    reason=[]
    if not 0.002<=atr_pct<=0.10: reason.append('ATR volatility outside configured range')
    if not volume_confirm: reason.append('volume confirmation missing')
    if trend==0: reason.append('EMA trend not aligned')
    if momentum==0: reason.append('RSI/MACD momentum not aligned')
    signal='LONG' if score>=60 and trend==1 and momentum==1 and volume_confirm else 'SHORT' if score<=-60 and trend==-1 and momentum==-1 and volume_confirm else 'WAIT'
    if not 0.002<=atr_pct<=0.10: signal='WAIT'
    return {'signal':signal,'score':round(score,1),'price':float(z.close),'atr':float(z.atr),'rsi':float(z.rsi),'atr_pct':atr_pct,'data':x,'reason':'; '.join(reason) or 'Conditions aligned'}

st.header('Connect futures data')
mode=st.radio('Choose', ['Automatic: verified Coinbase futures','Verified futures CSV'])
product=st.text_input('Exact Coinbase futures product ID',placeholder='Enter ID from Coinbase product listing',help='Do not enter ADA-USD spot or an unverified symbol.')
expiry=st.text_input('Contract expiration (UTC)',placeholder='YYYY-MM-DD',help='Required for CSV source; confirm from Coinbase contract details.')
refresh=st.button('Refresh data')
if refresh: st.cache_data.clear()
@st.cache_data(ttl=60,show_spinner=False)
def cached_fetch(p,tf): return load_public(p,tf)

frames={}; verified=False; source=''; exp_value=''
if mode.startswith('Automatic'):
    if not product: st.info('Enter the exact monthly ADA futures product ID to try the public Coinbase API. This dashboard will not substitute spot data.')
    else:
        for tf in GRAN:
            try:
                frames[tf],exp_value=cached_fetch(product,tf)
            except Exception as e:
                st.warning(f'{tf}: {e}')
        verified=len(frames)>0
        source='Coinbase public futures endpoint (verified product metadata)' if verified else ''
else:
    upload=st.file_uploader('Upload futures OHLCV CSV',type='csv')
    tf_csv=st.selectbox('CSV candle timeframe',list(GRAN))
    st.caption('CSV must contain timestamp,open,high,low,close,volume. Use only the exact monthly futures contract.')
    confirmed=st.checkbox('I verified this CSV is the monthly Coinbase ADA futures contract, not spot or perpetual')
    if upload and confirmed and product and expiry:
        try:
            if pd.to_datetime(expiry,utc=True)<=pd.Timestamp.now(tz='UTC'): raise ValueError('Contract is expired.')
            frames[tf_csv]=clean(pd.read_csv(upload)); verified=True; exp_value=expiry; source='User-confirmed futures CSV'
        except Exception as e: st.error(str(e))
    elif upload: st.warning('Provide product ID, expiration and confirmation before analysis.')

st.divider()
st.subheader('Market status')
if verified:
    st.success(f'Source: {source} | Product: {product} | Expiration: {exp_value}')
    st.caption('Automatic API candles are refreshed on request or after 60 seconds on rerun. CSV data does not auto-refresh.')
else: st.error('NO VERIFIED FUTURES DATA — signals disabled. No live futures feed is connected.')

results={tf:analyze(df) for tf,df in frames.items()}
cols=st.columns(4)
for col,tf in zip(cols,GRAN):
    r=results.get(tf)
    with col:
        st.metric(tf, r['signal'] if r else 'UNAVAILABLE', f"Score {r['score']:+.1f}" if r and 'score' in r else None)
        if r: st.caption(r.get('reason',''))

st.subheader('Signal decision')
if '1h' in results and '4h' in results:
    a,b=results['1h'],results['4h']
    signal=a['signal'] if a['signal']==b['signal'] and a['signal']!='WAIT' else 'WAIT'
    st.markdown(f'### {signal}')
    st.caption('Requires agreement between 1-hour and 4-hour signals; 5m/15m are entry context only.')
else: st.markdown('### WAIT'); st.caption('Requires verified 1-hour and 4-hour candles.')

view=st.selectbox('Chart timeframe',list(frames) or list(GRAN))
if view in frames:
    r=results[view]; df=r.get('data',frames[view]); st.line_chart(df[['close']+[x for x in ['ema20','ema50','ema200'] if x in df]].tail(120))
    st.dataframe(df.tail(20).iloc[::-1],use_container_width=True)

st.subheader('Contract risk calculator')
c1,c2,c3=st.columns(3)
with c1: side=st.selectbox('Direction',['LONG','SHORT']); count=st.number_input('Contracts',min_value=1,max_value=10000,value=1,step=1)
with c2: entry=st.number_input('Entry price ($/ADA)',min_value=0.0001,value=0.2500,step=0.0001,format='%.4f'); stop=st.number_input('Stop price ($/ADA)',min_value=0.0001,value=0.2450,step=0.0001,format='%.4f')
with c3: target=st.number_input('Target price ($/ADA)',min_value=0.0001,value=0.2600,step=0.0001,format='%.4f'); fee=st.number_input('Fee per contract per side ($)',min_value=0.0,value=0.0,step=0.05)
sgn=1 if side=='LONG' else -1
risk=(entry-stop)*sgn*MULTIPLIER*count+2*fee*count
reward=(target-entry)*sgn*MULTIPLIER*count-2*fee*count
if (entry-stop)*sgn<=0 or (target-entry)*sgn<=0: st.error('Invalid stop or target direction for this position.')
else:
    a,b,c,d=st.columns(4)
    a.metric('Notional exposure',f'${entry*MULTIPLIER*count:,.2f}')
    b.metric('Estimated stop loss',f'${risk:,.2f}')
    c.metric('Net target P/L',f'${reward:,.2f}')
    d.metric('Reward / risk',f'{reward/risk:.2f}:1' if risk>0 else 'N/A')
st.caption('Illustrative only: assumes exact fills; excludes slippage, margin, liquidation and other charges. No trading orders are placed.')
st.subheader('Method and limitations')
st.write('Directional score combines EMA trend (45), RSI/MACD momentum (30), breakout (up to 15) and volume confirmation. A signal requires score magnitude >= 60, matching trend/momentum, volume confirmation, acceptable ATR, and agreement across 1h/4h. Scores are NOT probabilities. Thresholds are unvalidated and must be backtested on historical monthly futures data.')
st.write('Futures contracts expire. Verify the product ID and expiration every month; never splice different expirations into a backtest without explicit roll rules. Only completed candles should be used in production. This research prototype does not currently detect incomplete candles, market closures, spreads or live margin requirements; do not use it to execute trades.')
