import streamlit as st
import yfinance as yf
import pandas as pd
import sqlite3
from datetime import datetime
import requests
import io

# ==========================================
# 1. ALAPBEÁLLÍTÁSOK (Mobilra optimalizálva)
# ==========================================
st.set_page_config(page_title="Quant Market Scanner", layout="wide", page_icon="🔭")

# ==========================================
# 2. ADATBÁZIS INICIALIZÁLÁS (Csak a memória)
# ==========================================
def init_db():
    conn = sqlite3.connect('quant_history.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scan_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  scan_date TEXT, index_name TEXT, ticker TEXT, name TEXT, country TEXT,
                  market_cap_b REAL, price REAL, fcf_yield TEXT, ev_sales TEXT, roe TEXT,
                  debt_eq TEXT, peg TEXT, growth TEXT, rsi TEXT, rs_vs_spy TEXT,
                  long_score REAL, med_score REAL, short_score REAL)''')
    conn.commit()
    conn.close()

def save_scan_results(df, index_name):
    if df.empty: return
    conn = sqlite3.connect('quant_history.db')
    df['scan_date'] = datetime.now().strftime("%Y-%m-%d %H:%M")
    df['index_name'] = index_name
    
    db_cols = {
        'scan_date':'scan_date', 'index_name':'index_name', 'Ticker':'ticker', 'Név':'name', 
        'Ország':'country', 'Méret_B':'market_cap_b', 'Ár':'price', 'FCF_Yield':'fcf_yield', 
        'EV_Sales':'ev_sales', 'ROE':'roe', 'Debt_Eq':'debt_eq', 'PEG':'peg', 'Növekedés':'growth', 
        'RSI':'rsi', 'RS_vs_SPY':'rs_vs_spy', 'Long_Score':'long_score', 'Med_Score':'med_score', 'Short_Score':'short_score'
    }
    df_db = df.rename(columns=db_cols)
    df_db.to_sql('scan_history', conn, if_exists='append', index=False)
    conn.close()

def get_scan_history():
    conn = sqlite3.connect('quant_history.db')
    df = pd.read_sql_query("SELECT * FROM scan_history ORDER BY scan_date DESC", conn)
    conn.close()
    return df

# ==========================================
# 3. PIACI INDEX LETÖLTŐ
# ==========================================
@st.cache_data(ttl=86400) 
def get_index_tickers(index_name):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        if index_name == "BUX (Magyarország)":
            return ["OTP.BD", "MOL.BD", "MTELEKOM.BD", "RICHTER.BD", "OPUS.BD", "4IG.BD", "ALTEO.BD", "AUTOWALLIS.BD", "ANY.BD", "CIGPANNONIA.BD", "MASTERPLAST.BD", "PANNERGY.BD", "WABERERS.BD", "ZWACK.BD"]
        elif index_name == "S&P 500 (USA)":
            url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            html = requests.get(url, headers=headers).text
            tables = pd.read_html(io.StringIO(html)) 
            tickers = tables[0]['Symbol'].tolist()
            return [t.replace('.', '-') for t in tickers] 
        elif index_name == "DAX (Németország)":
            url = 'https://en.wikipedia.org/wiki/DAX'
            html = requests.get(url, headers=headers).text
            tables = pd.read_html(io.StringIO(html))
            for df in tables:
                if 'Ticker' in df.columns or 'Ticker symbol' in df.columns:
                    col = 'Ticker' if 'Ticker' in df.columns else 'Ticker symbol'
                    tickers = df[col].dropna().astype(str).tolist()
                    return [t if t.endswith('.DE') else f"{t}.DE" for t in tickers]
            return []
        elif index_name == "FTSE 100 (Egyesült Királyság)":
            url = 'https://en.wikipedia.org/wiki/FTSE_100_Index'
            html = requests.get(url, headers=headers).text
            tables = pd.read_html(io.StringIO(html))
            for df in tables:
                if 'Ticker' in df.columns or 'EPIC' in df.columns:
                    col = 'Ticker' if 'Ticker' in df.columns else 'EPIC'
                    tickers = df[col].dropna().astype(str).tolist()
                    return [t.replace('.', '-') + ".L" for t in tickers if t != 'nan']
            return []
        elif index_name == "Nikkei 225 (Japán)":
            return ["7203.T", "6758.T", "8306.T", "6861.T", "9984.T", "8035.T", "7974.T", "9983.T", "7267.T", "6501.T", "8001.T", "8031.T", "8316.T", "4063.T", "6981.T", "4568.T", "8053.T", "8411.T", "6098.T", "4519.T", "6367.T", "6902.T", "7741.T", "8002.T", "8766.T", "9432.T", "7269.T", "9433.T"]
        elif index_name == "SSE 50 (Kína)":
            return ["600519.SS", "601398.SS", "601288.SS", "601988.SS", "600036.SS", "601318.SS", "601857.SS", "601088.SS", "600900.SS", "601166.SS", "600028.SS", "601328.SS", "600276.SS", "600030.SS", "603259.SS", "601012.SS", "601816.SS", "601628.SS", "601688.SS", "600887.SS", "600104.SS", "600809.SS", "601138.SS", "601211.SS", "601601.SS"]
    except Exception:
        return []

# ==========================================
# 4. KVANTITATÍV PIACI SZKENNER (A MOTOR)
# ==========================================
def calculate_rsi(data, window=14):
    if len(data) < window: return 50
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs)).iloc[-1]
    return rsi if pd.notna(rsi) else 50

def run_quant_scan(index_name, tickers, progress_bar, status_text):
    results = []
    try:
        spy_hist = yf.Ticker("SPY").history(period="6mo")
        spy_6m_return = (spy_hist['Close'].iloc[-1] - spy_hist['Close'].iloc[0]) / spy_hist['Close'].iloc[0] if len(spy_hist) > 0 else 0.05
    except: spy_6m_return = 0.05

    total = len(tickers)
    for i, ticker in enumerate(tickers):
        status_text.text(f"Adatok bányászata: {ticker} ({i+1}/{total})")
        progress_bar.progress((i + 1) / total)
        
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            hist = stock.history(period="6mo")
            if hist.empty or len(hist) < 50: continue
            
            name = info.get('shortName', ticker)
            country = info.get('country', 'Unknown')
            current_price = hist['Close'].iloc[-1]
            ma_50 = hist['Close'].rolling(window=50).mean().iloc[-1]
            rsi = calculate_rsi(hist)
            stock_6m_return = (current_price - hist['Close'].iloc[0]) / hist['Close'].iloc[0]
            
            ev = info.get('enterpriseValue', 0)
            fcf = info.get('freeCashflow', 0)
            market_cap = info.get('marketCap', 0)
            market_cap_billions = market_cap / 1_000_000_000 if market_cap else 0
            
            fcf_yield = (fcf / ev) if (ev and ev > 0) else 0
            ev_to_sales = info.get('enterpriseToRevenue', 999)
            roe = info.get('returnOnEquity', 0)
            debt_to_equity = info.get('debtToEquity', 999) 
            peg = info.get('pegRatio', 999)
            growth = info.get('revenueGrowth', 0)
            
            long_score, med_score, short_score = 0, 0, 0
            
            if ev_to_sales is not None and ev_to_sales > 15: long_score -= 5 
            if debt_to_equity is not None and debt_to_equity > 200: long_score -= 3
            if fcf_yield is not None and fcf_yield > 0.04: long_score += 3
            if roe is not None and roe > 0.15: long_score += 2 
            if ev_to_sales is not None and 0 < ev_to_sales < 5: long_score += 2
            
            if peg is not None and 0 < peg < 1.2: med_score += 3 
            if growth is not None and growth > 0.10: med_score += 2
            
            if market_cap_billions > 0 and market_cap_billions < 20 and growth is not None and growth > 0.15:
                med_score += 4; long_score += 2
            elif market_cap_billions > 1000 and growth is not None and growth < 0.10:
                med_score -= 2
                
            if stock_6m_return > spy_6m_return: med_score += 2; short_score += 2
            if rsi < 35: short_score += 4 
            if current_price > ma_50 and rsi > 50: short_score += 2 
            
            MACRO_MATRIX = {
                'Hungary': 1.3, 'United States': 1.0, 'Germany': 0.8, 'China': 0.7, 'Netherlands': 1.1, 'United Kingdom': 0.9 
            }
            cm = MACRO_MATRIX.get(country, 1.0)
            long_score *= cm; med_score *= cm; short_score *= cm
            
            results.append({
                'Ticker': ticker, 'Név': name, 'Ország': country, 'Méret_B': market_cap_billions, 'Ár': current_price,
                'FCF_Yield': f"{fcf_yield*100:.1f}%" if fcf_yield != 0 else "N/A",
                'EV_Sales': f"{ev_to_sales:.1f}" if ev_to_sales != 999 else "N/A",
                'ROE': f"{roe*100:.1f}%" if roe != 0 else "N/A",
                'Debt_Eq': f"{debt_to_equity:.1f}%" if debt_to_equity != 999 else "N/A",
                'PEG': peg if peg != 999 else "N/A",
                'Növekedés': f"{growth*100:.1f}%" if growth is not None else "N/A",
                'RSI': f"{rsi:.1f}",
                'RS_vs_SPY': "Igen" if stock_6m_return > spy_6m_return else "Nem",
                'Long_Score': long_score, 'Med_Score': med_score, 'Short_Score': short_score
            })
        except Exception:
            continue
            
    return pd.DataFrame(results)

# ==========================================
# 5. MEGA-PROMPT GENERÁTOR
# ==========================================
def generate_mega_prompt(row, timeframe):
    return f"**Lépj a világ egyik legjobb, makro-vezérelt hedge fund menedzserének szerepébe!**\nKérlek adj mély elemzést a következő vállalatról, **{timeframe}** befektetési időtávra:\n\n- **Cég:** {row['Név']} ({row['Ticker']})\n- **Méret:** {row['Méret_B']:.1f} Mrd USD\n\n**Fundamentumok:**\n- FCF Hozam: {row['FCF_Yield']} | EV/Sales: {row['EV_Sales']} | ROE: {row['ROE']} | Adósság/Tőke: {row['Debt_Eq']}\n\n**Aszimmetria és Momentum:**\n- Növekedés: {row['Növekedés']} | PEG Ráta: {row['PEG']} | RSI (14): {row['RSI']} | RS vs SPY: {row['RS_vs_SPY']}\n\nÉrtékeld a cég vizesárkát, buborékkockázatát, növekedési potenciálját és makro-hátszelét!"

# ==========================================
# 6. STREAMLIT FELÜLET
# ==========================================
init_db()

st.title("🔭 Quant Market Scanner")
st.markdown("*" "Keresd meg az aszimmetrikus belépési pontokat a világ legnagyobb piacain." "*")

tab1, tab2 = st.tabs(["📡 Új Piac Szkennelése", "🗄️ Történelmi Adatbázis"])

with tab1:
    st.write("Válaszd ki az indexet, és a motor letölti, majd kielemzi az összes komponenst.")
    selected_index = st.selectbox("Vizsgálandó piac:", ["BUX (Magyarország)", "S&P 500 (USA)", "DAX (Németország)", "FTSE 100 (Egyesült Királyság)", "Nikkei 225 (Japán)", "SSE 50 (Kína)"])
    
    if st.button("🚀 Szkennelés Indítása", type="primary", use_container_width=True):
        tickers_to_scan = get_index_tickers(selected_index)
        
        if not tickers_to_scan:
            st.error("Hiba a komponensek letöltésekor.")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            df_scan = run_quant_scan(selected_index, tickers_to_scan, progress_bar, status_text)
            
            if not df_scan.empty:
                status_text.success("✅ Szkennelés kész!")
                save_scan_results(df_scan, selected_index)
                st.session_state['last_scan'] = df_scan
            else:
                status_text.error("Hiba történt.")

    if 'last_scan' in st.session_state and not st.session_state['last_scan'].empty:
        st.subheader("💡 Top Eredmények és AI Promptok")
        df_show = st.session_state['last_scan']
        
        long_top = df_show.sort_values(by='Long_Score', ascending=False).head(3)
        med_top = df_show.sort_values(by='Med_Score', ascending=False).head(3)
        short_top = df_show.sort_values(by='Short_Score', ascending=False).head(3)
        
        st.markdown("### 🥇 Hosszú Táv (Érték & Vizesárok)")
        for _, row in long_top.iterrows():
            with st.expander(f"{row['Név']} ({row['Ticker']}) - Score: {row['Long_Score']:.1f}"):
                st.code(generate_mega_prompt(row, "Hosszú táv (5-10 év)"), language="markdown")
                
        st.markdown("### 🔥 Közép Táv (Növekedés & GARP)")
        for _, row in med_top.iterrows():
            with st.expander(f"{row['Név']} ({row['Ticker']}) - Score: {row['Med_Score']:.1f}"):
                st.code(generate_mega_prompt(row, "Közép táv (1-5 év)"), language="markdown")

        st.markdown("### ⚡ Rövid Táv (Túladottság & Momentum)")
        for _, row in short_top.iterrows():
            with st.expander(f"{row['Név']} ({row['Ticker']}) - Score: {row['Short_Score']:.1f}"):
                st.code(generate_mega_prompt(row, "Rövid táv (1-6 hónap)"), language="markdown")

with tab2:
    st.header("🗄️ Történelmi Adatbázis")
    df_history = get_scan_history()
    
    if not df_history.empty:
        dates = df_history['scan_date'].unique().tolist()
        sel_dates = st.multiselect("Dátum(ok):", dates, default=dates[:1])
        if sel_dates:
            filtered_df = df_history[df_history['scan_date'].isin(sel_dates)]
            st.dataframe(filtered_df, use_container_width=True)
    else:
        st.info("Még nincs mentett szkennelés.")