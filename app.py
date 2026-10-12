import streamlit as st
import yfinance as yf
import pandas as pd
import sqlite3
from datetime import datetime
import requests
import io
import urllib.request
import xml.etree.ElementTree as ET
import time

# ==========================================
# 1. ALAPBEÁLLÍTÁSOK (Terminál Nézet)
# ==========================================
st.set_page_config(page_title="Pro Quant Terminal", layout="wide", page_icon="⚡")

# ==========================================
# 2. ADATBÁZIS (Történelmi Szkennelések)
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
# 3. HÍR-TERMINÁL (RSS BÁNYÁSZAT)
# ==========================================
def fetch_terminal_news(topic):
    """Élő hírek letöltése a Google News globális hálózatából"""
    url = f"https://news.google.com/rss/search?q={topic.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            xml_data = resp.read()
            root = ET.fromstring(xml_data)
            news = []
            for item in root.findall('.//item')[:5]:
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else ""
                pubDate = item.find('pubDate').text if item.find('pubDate') is not None else ""
                pubDate = pubDate.replace(" GMT", "") 
                news.append({'title': title, 'link': link, 'date': pubDate})
            return news
    except:
        return []

# ==========================================
# 4. DAYTRADE MOTOR (MULTI-TIMEFRAME)
# ==========================================
def run_daytrade_scan(tickers, interval, fast_ema, slow_ema, period):
    results = []
    failed_tickers = []
    
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period=period, interval=interval)
            
            # Üres (NaN) adatok kiszűrése
            if not hist.empty:
                hist = hist.dropna(subset=['Close'])
                
            # Ha az üres adatok kiszűrése után nem marad elég gyertya a mozgóátlaghoz
            if hist.empty or len(hist) < slow_ema + 1:
                failed_tickers.append(f"{t} (Nincs elég gyertya)")
                continue
            
            current_price = hist['Close'].iloc[-1]
            
            delta = hist['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            rsi = rsi if pd.notna(rsi) else 50
            
            ema_f = hist['Close'].ewm(span=fast_ema, adjust=False).mean().iloc[-1]
            ema_s = hist['Close'].ewm(span=slow_ema, adjust=False).mean().iloc[-1]
            
            signal = "⚪ SEMLEGES"
            if rsi < 30 and current_price > ema_s:
                signal = "🟢 LONG (Pattanás várható)"
            elif rsi < 30 and current_price < ema_s:
                signal = "🟢 ERŐS LONG (Extrém túladott)"
            elif rsi > 70 and current_price < ema_s:
                signal = "🔴 SHORT (Ellenállásba ütközött)"
            elif rsi > 70 and current_price > ema_s:
                signal = "🔴 ERŐS SHORT (Extrém túlvett)"
            elif ema_f > ema_s:
                signal = "📈 Enyhe Long Trend"
            elif ema_f < ema_s:
                signal = "📉 Enyhe Short Trend"
                
            results.append({
                "Eszköz": t.upper(),
                "Ár": f"{current_price:.2f}",
                "RSI": f"{rsi:.1f}",
                f"Trend (EMA {fast_ema}/{slow_ema})": "Bika 🐂" if ema_f > ema_s else "Medve 🐻",
                "DAYTRADE SZIGNÁL": signal
            })
        except Exception:
            failed_tickers.append(f"{t} (Letöltési hiba)")
            continue
            
    return pd.DataFrame(results), failed_tickers

# ==========================================
# 5. HOSSZÚ TÁVÚ SZKENNER (A TELJES MOTOR)
# ==========================================
@st.cache_data(ttl=86400) 
def get_index_tickers(index_name):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
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
    except Exception as e:
        return []

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
        status_text.text(f"Adatok letöltése és elemzése: {ticker} ({i+1}/{total})")
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
                'Hungary': 1.3, 'United States': 1.0, 'Germany': 0.8, 'China': 0.7, 'Netherlands': 1.1,
                'United Kingdom': 0.9 
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
# 6. MEGA-PROMPT GENERÁTOR
# ==========================================
def generate_mega_prompt(row, timeframe):
    prompt = f"""
**Kérlek, lépj a világ egyik legjobb, makro-vezérelt hedge fund portfóliómenedzserének szerepébe!**
Kérlek adj egy mély elemzést a következő vállalatról, **{timeframe}** befektetési időtávra:

- **Cég:** {row['Név']} ({row['Ticker']}) - Székhely: {row['Ország']}
- **Méret:** {row['Méret_B']:.1f} Mrd USD

**Fundamentumok:**
- FCF Hozam: {row['FCF_Yield']}
- EV/Sales: {row['EV_Sales']}
- ROE: {row['ROE']}
- Adósság/Saját Tőke: {row['Debt_Eq']}

**Aszimmetria és Momentum:**
- Bevételnövekedés: {row['Növekedés']}
- PEG Ráta: {row['PEG']}
- RSI (14): {row['RSI']}
- Relatív erő (SPY-hoz képest): {row['RS_vs_SPY']}

Kérlek, értékeld a cég vizesárkát, a buborékkockázatot, a méretéből adódó növekedési potenciált és az országa/szektora adta makro-hátszelet!
"""
    return prompt.strip()

# ==========================================
# 7. STREAMLIT FELÜLET & TERMINÁL
# ==========================================
init_db()

st.title("⚡ Pro Quant Terminal")
st.markdown("*A te személyes, napon belüli kereskedési és makro-elemző asztalod.*")

# Automata frissítés kapcsoló a Sidebarban
auto_refresh = st.sidebar.toggle("🔄 Élő Terminál Mód (Auto-frissítés 30mp)", value=False)
if auto_refresh:
    st.sidebar.success("Az Élő Terminál aktív! Az oldal 30 másodpercenként frissül.")

tab1, tab2, tab3 = st.tabs(["⚡ ÉLŐ DAYTRADE & HÍREK", "🔭 Globális Piac Szkenner", "🗄️ Történelem"])

# ==========================================
# TAB 1: A DAYTRADE TERMINÁL
# ==========================================
with tab1:
    col1, col2 = st.columns([1.5, 1]) 
    
    with col1:
        st.subheader("🎯 Napon Belüli Szignálok")
        
        # IDŐSÍK VÁLASZTÓ (Bugfixált, 5 napos limit az 1 és 5 percesekhez)
        tf_selection = st.radio("Válassz Idősíkot és Stratégiát:", 
                                ["1 perces (EMA 20/50)", "5 perces (EMA 20/50)", "15 perces (EMA 9/21)", "1 órás (EMA 9/21)"], 
                                horizontal=True)
                                
        if "1 perces" in tf_selection:
            tf_interval, tf_fast_ema, tf_slow_ema, tf_period = "1m", 20, 50, "5d"
        elif "5 perces" in tf_selection:
            tf_interval, tf_fast_ema, tf_slow_ema, tf_period = "5m", 20, 50, "5d"
        elif "15 perces" in tf_selection:
            tf_interval, tf_fast_ema, tf_slow_ema, tf_period = "15m", 9, 21, "1mo"
        else:
            tf_interval, tf_fast_ema, tf_slow_ema, tf_period = "60m", 9, 21, "3mo"
        
        default_tickers = "GC=F, SPY, QQQ, TSLA, NVDA, AAPL"
        user_tickers = st.text_input("Figyelt Tickerek (Vesszővel elválasztva):", value=default_tickers)
        tickers_list = [t.strip() for t in user_tickers.split(',') if t.strip()]
        
        if st.button("🔄 Szignálok Frissítése", use_container_width=True) or auto_refresh:
            with st.spinner(f"Élő adatok betöltése ({tf_selection})..."):
                df_daytrade, failed_tickers = run_daytrade_scan(tickers_list, tf_interval, tf_fast_ema, tf_slow_ema, tf_period)
                
                if not df_daytrade.empty:
                    def highlight_signals(s):
                        if 'LONG' in s: return 'background-color: #004d00; color: white'
                        if 'SHORT' in s: return 'background-color: #4d0000; color: white'
                        return ''
                    
                    styled_df = df_daytrade.style.map(highlight_signals, subset=['DAYTRADE SZIGNÁL'])
                    st.dataframe(styled_df, hide_index=True, use_container_width=True)
                else:
                    st.error("Nem sikerült letölteni egyetlen ticker adatát sem ezen az idősíkon.")
                
                if failed_tickers:
                    st.warning(f"⚠️ A következő eszközöknél nem volt elég kereskedési adat a kért idősíkon, így az algoritmus biztonsági okokból kihagyta őket: {', '.join(failed_tickers)}")

    with col2:
        st.subheader("📰 Hírfolyam")
        if st.button("🔄 Hírek Frissítése", use_container_width=True) or auto_refresh:
            if tickers_list:
                primary_ticker = tickers_list[0].replace("=F", "").replace("=X", "")
                st.markdown(f"#### 🎯 Fókusz: {primary_ticker}")
                target_news = fetch_terminal_news(f"{primary_ticker} stock financial news")
                for n in target_news:
                    st.markdown(f"- [{n['title']}]({n['link']})")
                st.divider()

            st.markdown("#### 🥇 Arany Piac (Gold)")
            gold_news = fetch_terminal_news("gold market finance OR gold price")
            for n in gold_news:
                st.markdown(f"- [{n['title']}]({n['link']})")
            st.divider()
            
            st.markdown("#### 🌍 Globális Makro")
            macro_news = fetch_terminal_news("global stock market OR federal reserve interest rates")
            for n in macro_news:
                st.markdown(f"- [{n['title']}]({n['link']})")

# ==========================================
# TAB 2: A HOSSZÚ TÁVÚ SZKENNER
# ==========================================
with tab2:
    st.subheader("🔭 Globális Piac Szkenner (Értékalapú)")
    st.write("Makro-kiválasztás és értékeltség alapú hosszú távú kereső.")
    selected_index = st.selectbox("Vizsgálandó piac:", ["S&P 500 (USA)", "DAX (Németország)", "BUX (Magyarország)", "FTSE 100 (Egyesült Királyság)", "Nikkei 225 (Japán)", "SSE 50 (Kína)"])
    
    if st.button("🚀 Szkennelés Indítása (Hosszú táv)", type="primary"):
        tickers_to_scan = get_index_tickers(selected_index)
        if tickers_to_scan:
            prog = st.progress(0)
            status_text = st.empty()
            df_scan = run_quant_scan(selected_index, tickers_to_scan, prog, status_text) 
            if not df_scan.empty:
                status_text.success("✅ Szkennelés kész! Eredmények mentve az adatbázisba.")
                save_scan_results(df_scan, selected_index)
                st.session_state['last_scan'] = df_scan
            else:
                status_text.error("Hiba történt a szkennelés során.")

    if 'last_scan' in st.session_state and not st.session_state['last_scan'].empty:
        st.subheader("💡 Top Eredmények és AI Promptok")
        df_show = st.session_state['last_scan']
        
        long_top = df_show.sort_values(by='Long_Score', ascending=False).head(3)
        med_top = df_show.sort_values(by='Med_Score', ascending=False).head(3)
        short_top = df_show.sort_values(by='Short_Score', ascending=False).head(3)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.write("**Hosszú Táv (Top 3)**")
            for _, row in long_top.iterrows():
                with st.expander(f"🥇 {row['Név']} ({row['Ticker']})"):
                    st.write(f"FCF Hozam: {row['FCF_Yield']} | ROE: {row['ROE']}")
                    st.code(generate_mega_prompt(row, "Hosszú táv (5-10 év)"), language="markdown")
        
        with col2:
            st.write("**Közép Táv (Top 3)**")
            for _, row in med_top.iterrows():
                with st.expander(f"🔥 {row['Név']} ({row['Ticker']})"):
                    st.write(f"Növekedés: {row['Növekedés']} | PEG: {row['PEG']}")
                    st.code(generate_mega_prompt(row, "Közép táv (1-5 év)"), language="markdown")

        with col3:
            st.write("**Rövid Táv (Top 3)**")
            for _, row in short_top.iterrows():
                with st.expander(f"⚡ {row['Név']} ({row['Ticker']})"):
                    st.write(f"RSI: {row['RSI']} | RS vs SPY: {row['RS_vs_SPY']}")
                    st.code(generate_mega_prompt(row, "Rövid táv (1-6 hónap)"), language="markdown")

# ==========================================
# TAB 3: TÖRTÉNELEM
# ==========================================
with tab3:
    st.header("🗄️ Történelmi Adatbázis")
    df_history = get_scan_history()
    
    if not df_history.empty:
        col1, col2 = st.columns(2)
        with col1:
            dates = df_history['scan_date'].unique().tolist()
            sel_dates = st.multiselect("Dátum(ok):", dates, default=dates[:1])
        with col2:
            indices = df_history['index_name'].unique().tolist()
            sel_indices = st.multiselect("Piac(ok):", indices, default=indices)
            
        if sel_dates and sel_indices:
            filtered_df = df_history[(df_history['scan_date'].isin(sel_dates)) & (df_history['index_name'].isin(sel_indices))]
            st.dataframe(filtered_df, use_container_width=True)
            
            st.download_button(
                label="📥 Adataid letöltése Excelbe (CSV)",
                data=filtered_df.to_csv(index=False).encode('utf-8'),
                file_name=f"quant_scan_{datetime.now().strftime('%Y%m%d')}.csv",
                mime='text/csv'
            )
    else:
        st.info("Még nem futtattál le egyetlen szkennelést sem.")

# ==========================================
# 8. AUTOMATA FRISSÍTÉS CIKLUS
# ==========================================
if auto_refresh:
    time.sleep(30) 
    st.rerun()
