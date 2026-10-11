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
            for item in root.findall('.//item')[:5]: # Csak a 5 legfrissebb hír
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else ""
                pubDate = item.find('pubDate').text if item.find('pubDate') is not None else ""
                pubDate = pubDate.replace(" GMT", "") # Dátum tisztítása
                news.append({'title': title, 'link': link, 'date': pubDate})
            return news
    except:
        return []

# ==========================================
# 4. DAYTRADE MOTOR (MULTI-TIMEFRAME)
# ==========================================
def run_daytrade_scan(tickers, interval, fast_ema, slow_ema, period):
    results = []
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period=period, interval=interval)
            if hist.empty or len(hist) < slow_ema + 5: continue # Biztosítjuk, hogy legyen elég gyertya az EMA-hoz
            
            current_price = hist['Close'].iloc[-1]
            
            # Dinamikus RSI számítása (14)
            delta = hist['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            rsi = rsi if pd.notna(rsi) else 50
            
            # Dinamikus Momentum EMÁ-k (felhasználó által választott idősíknak megfelelően)
            ema_f = hist['Close'].ewm(span=fast_ema, adjust=False).mean().iloc[-1]
            ema_s = hist['Close'].ewm(span=slow_ema, adjust=False).mean().iloc[-1]
            
            # --- DAYTRADE LOGIKA / SZIGNÁLOK ---
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
            continue
            
    return pd.DataFrame(results)

# ==========================================
# 5. HOSSZÚ TÁVÚ SZKENNER
# ==========================================
@st.cache_data(ttl=86400) 
def get_index_tickers(index_name):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        if index_name == "BUX (Magyarország)":
            return ["OTP.BD", "MOL.BD", "MTELEKOM.BD", "RICHTER.BD", "OPUS.BD"]
        elif index_name == "S&P 500 (USA)":
            url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            html = requests.get(url, headers=headers).text
            return [t.replace('.', '-') for t in pd.read_html(io.StringIO(html))[0]['Symbol'].tolist()] 
        elif index_name == "DAX (Németország)":
            return ["ADS.DE", "ALV.DE", "BAS.DE", "BAYN.DE", "BMW.DE", "DTG.DE", "SAP.DE", "SIE.DE", "VOW3.DE"]
    except: return []

def run_quant_scan(tickers, progress_bar):
    results = []
    total = len(tickers)
    for i, ticker in enumerate(tickers):
        progress_bar.progress((i + 1) / total)
        try:
            info = yf.Ticker(ticker).info
            results.append({
                'Ticker': ticker, 'Név': info.get('shortName', ticker), 'Ország': info.get('country', 'N/A'),
                'Méret_B': info.get('marketCap', 0) / 1e9, 'FCF_Yield': "N/A", 'EV_Sales': info.get('enterpriseToRevenue', 0),
                'ROE': info.get('returnOnEquity', 0), 'Debt_Eq': info.get('debtToEquity', 0), 'PEG': info.get('pegRatio', 0),
                'Növekedés': info.get('revenueGrowth', 0), 'RSI': "50", 'RS_vs_SPY': "N/A",
                'Long_Score': 10, 'Med_Score': 10, 'Short_Score': 10
            })
        except: continue
    return pd.DataFrame(results)

def generate_mega_prompt(row, timeframe):
    return f"**Lépj a világ egyik legjobb hedge fund menedzserének szerepébe!**\nKérlek adj elemzést: {row['Név']} ({row['Ticker']}) - {timeframe} időtávra."

# ==========================================
# 6. STREAMLIT FELÜLET & TERMINÁL
# ==========================================
init_db()

st.title("⚡ Pro Quant Terminal")
st.markdown("*A te személyes, napon belüli kereskedési és makro-elemző asztalod.*")

# Automata frissítés kapcsoló a Sidebarban
auto_refresh = st.sidebar.toggle("🔄 Élő Terminál Mód (Auto-frissítés 60mp)", value=False)
if auto_refresh:
    st.sidebar.success("Az Élő Terminál aktív! Az oldal 60 másodpercenként frissül.")

tab1, tab2, tab3 = st.tabs(["⚡ ÉLŐ DAYTRADE & HÍREK", "🔭 Globális Piac Szkenner", "🗄️ Történelem"])

# ==========================================
# TAB 1: A DAYTRADE TERMINÁL
# ==========================================
with tab1:
    col1, col2 = st.columns([1.5, 1]) 
    
    with col1:
        st.subheader("🎯 Napon Belüli Szignálok")
        
        # IDŐSÍK VÁLASZTÓ (Radio Button)
        tf_selection = st.radio("Válassz Idősíkot és Stratégiát:", 
                                ["1 perces (EMA 20/50)", "5 perces (EMA 20/50)", "15 perces (EMA 9/21)", "1 órás (EMA 9/21)"], 
                                horizontal=True)
                                
        # Paraméterek beállítása a választás alapján
        if "1 perces" in tf_selection:
            tf_interval, tf_fast_ema, tf_slow_ema, tf_period = "1m", 20, 50, "5d"
        elif "5 perces" in tf_selection:
            tf_interval, tf_fast_ema, tf_slow_ema, tf_period = "5m", 20, 50, "5d"
        elif "15 perces" in tf_selection:
            tf_interval, tf_fast_ema, tf_slow_ema, tf_period = "15m", 9, 21, "5d"
        else:
            tf_interval, tf_fast_ema, tf_slow_ema, tf_period = "60m", 9, 21, "1mo"
        
        # Watchlist bemenet
        default_tickers = "GC=F, SPY, QQQ, TSLA, NVDA, AAPL"
        user_tickers = st.text_input("Figyelt Tickerek (Vesszővel elválasztva):", value=default_tickers)
        tickers_list = [t.strip() for t in user_tickers.split(',') if t.strip()]
        
        if st.button("🔄 Szignálok Frissítése", use_container_width=True) or auto_refresh:
            with st.spinner(f"Élő adatok betöltése ({tf_selection})..."):
                df_daytrade = run_daytrade_scan(tickers_list, tf_interval, tf_fast_ema, tf_slow_ema, tf_period)
                if not df_daytrade.empty:
                    # Színes táblázat formázás
                    def highlight_signals(s):
                        if 'LONG' in s: return 'background-color: #004d00; color: white'
                        if 'SHORT' in s: return 'background-color: #4d0000; color: white'
                        return ''
                    
                    styled_df = df_daytrade.style.map(highlight_signals, subset=['DAYTRADE SZIGNÁL'])
                    st.dataframe(styled_df, hide_index=True, use_container_width=True)
                else:
                    st.error("Nem sikerült letölteni az adatokat.")

    with col2:
        st.subheader("📰 Hírfolyam")
        
        if st.button("🔄 Hírek Frissítése", use_container_width=True) or auto_refresh:
            
            # Dinamikus cégspecifikus hírek (A watchlist első eleme alapján)
            if tickers_list:
                primary_ticker = tickers_list[0].replace("=F", "") # Eltávolítjuk a határidős =F jelzést a kereséshez
                st.markdown(f"#### 🎯 Fókusz: {primary_ticker}")
                target_news = fetch_terminal_news(f"{primary_ticker} stock financial news")
                for n in target_news:
                    st.markdown(f"- [{n['title']}]({n['link']})")
                st.divider()

            # Arany hírek
            st.markdown("#### 🥇 Arany Piac (Gold)")
            gold_news = fetch_terminal_news("gold market finance OR gold price")
            for n in gold_news:
                st.markdown(f"- [{n['title']}]({n['link']})")
            st.divider()
            
            # Makro hírek
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
    selected_index = st.selectbox("Vizsgálandó piac:", ["S&P 500 (USA)", "DAX (Németország)", "BUX (Magyarország)"])
    
    if st.button("🚀 Szkennelés Indítása (Hosszú táv)", type="primary"):
        tickers_to_scan = get_index_tickers(selected_index)
        if tickers_to_scan:
            prog = st.progress(0)
            df_scan = run_quant_scan(tickers_to_scan[:50], prog) 
            if not df_scan.empty:
                st.success("Kész!")
                st.dataframe(df_scan, hide_index=True, use_container_width=True)

# ==========================================
# TAB 3: TÖRTÉNELEM
# ==========================================
with tab3:
    st.header("🗄️ Történelmi Adatbázis")
    df_history = get_scan_history()
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True)
    else:
        st.info("Még nincs mentett szkennelés.")

# ==========================================
# 7. AUTOMATA FRISSÍTÉS CIKLUS
# ==========================================
if auto_refresh:
    time.sleep(60) 
    st.rerun()
