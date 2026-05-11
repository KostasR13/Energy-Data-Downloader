"""
app.py
------
Κύρια Streamlit εφαρμογή.
Εκκίνηση: streamlit run app.py
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import io

from config import ENTSO_TOKEN, APP_TITLE
from entso_client import CATALOG, COUNTRIES, get_data as entso_get_data, check_availability as entso_check
from admie_client  import get_filetypes_grouped, get_data as admie_get_data, check_availability as admie_check
from exporter      import export_entso, export_admie


# ============================================================
# LOADING SCREEN HTML — εμφανίζεται κατά έλεγχο & ανάκτηση
# ============================================================
# Χρησιμοποιούμε st.empty() + components.html() αντί για spinner
# ώστε να μπορούμε να δείξουμε custom SVG animation.
# Η συνάρτηση show_loading() επιστρέφει το placeholder,
# που το καθαρίζουμε με .empty() μόλις τελειώσει η κλήση.

def show_loading(subtitle: str = "") -> "st.empty":
    """
    Εμφανίζει το loading screen (WT + BESS) και επιστρέφει
    το st.empty() placeholder ώστε να το καθαρίσεις μετά:

        ph = show_loading("DAM Prices · Ελλάδα")
        κάνε_την_κλήση_σου()
        ph.empty()
    """
    ph = st.empty()
    ph.markdown(f"""
<div style="display:flex;justify-content:center;padding:16px 0;">
<div style="display:flex;flex-direction:column;align-items:center;gap:16px;
            padding:28px 24px;background:#0e1117;border:0.5px solid #333;
            border-radius:12px;min-width:340px;">
<style>
  @keyframes rot  {{ from{{transform:rotate(0deg)}} to{{transform:rotate(360deg)}} }}
  .ld-spin {{ transform-origin:90px 80px; animation:rot 3s linear infinite; }}
  @keyframes fd {{
    0%  {{ transform:translateX(0);    opacity:0; }}
    10% {{ opacity:1; }} 90%{{opacity:1;}}
    100%{{ transform:translateX(70px); opacity:0; }}
  }}
  .ld-fd1{{animation:fd 1.6s linear infinite;}}
  .ld-fd2{{animation:fd 1.6s linear infinite;animation-delay:.53s;}}
  .ld-fd3{{animation:fd 1.6s linear infinite;animation-delay:1.06s;}}
  @keyframes ld-dots{{0%{{content:''}}25%{{content:'.'}}50%{{content:'..'}}75%{{content:'...'}}}}
  .ld-dots::after{{content:'';animation:ld-dots 1.5s steps(4,end) infinite;}}
  .ld-cdim{{ opacity:0.12; transition:opacity 0.15s ease; }}
  .ld-con {{ opacity:1;    transition:opacity 0.15s ease; }}
</style>
<svg width="380" height="220" viewBox="0 0 460 268" xmlns="http://www.w3.org/2000/svg">
  <!-- Wind Turbine -->
  <polygon points="86,92 94,92 99,240 81,240" fill="#D3D1C7" stroke="#B4B2A9" stroke-width="0.5"/>
  <rect x="79" y="69" width="22" height="22" rx="5" fill="#B4B2A9" stroke="#888780" stroke-width="0.8"/>
  <line x1="79" y1="80" x2="101" y2="80" stroke="#888780" stroke-width="0.5"/>
  <rect x="74" y="236" width="32" height="8" rx="2" fill="#B4B2A9"/>
  <g class="ld-spin">
    <path d="M 87,80 C 84,64 82,42 86,4 C 88,1 92,1 94,4 C 98,42 96,64 93,80 Z" fill="#1D9E75" stroke="#0F6E56" stroke-width="0.5"/>
    <path d="M 87,80 C 84,64 82,42 86,4 C 88,1 92,1 94,4 C 98,42 96,64 93,80 Z" fill="#1D9E75" stroke="#0F6E56" stroke-width="0.5" transform="rotate(120 90 80)"/>
    <path d="M 87,80 C 84,64 82,42 86,4 C 88,1 92,1 94,4 C 98,42 96,64 93,80 Z" fill="#1D9E75" stroke="#0F6E56" stroke-width="0.5" transform="rotate(240 90 80)"/>
  </g>
  <circle cx="90" cy="80" r="8" fill="#5F5E5A" stroke="#444441" stroke-width="1"/>
  <circle cx="90" cy="80" r="3" fill="#2C2C2A"/>
  <!-- Cable -->
  <line x1="100" y1="240" x2="170" y2="240" stroke="#B4B2A9" stroke-width="2.5" stroke-dasharray="4,3"/>
  <circle class="ld-fd1" cx="102" cy="240" r="3.5" fill="#1D9E75"/>
  <circle class="ld-fd2" cx="102" cy="240" r="3.5" fill="#1D9E75"/>
  <circle class="ld-fd3" cx="102" cy="240" r="3.5" fill="#1D9E75"/>
  <!-- BESS % label -->
  <text id="ld-pct" x="285" y="100" text-anchor="middle" font-size="13" font-weight="600" fill="#EF9F27" font-family="sans-serif">0%</text>
  <!-- BESS terminals -->
  <rect x="330" y="102" width="12" height="9" rx="3" fill="#888780"/>
  <rect x="347" y="102" width="12" height="9" rx="3" fill="#888780"/>
  <rect x="364" y="102" width="12" height="9" rx="3" fill="#888780"/>
  <!-- BESS body -->
  <rect x="170" y="112" width="230" height="128" rx="4" fill="#D3D1C7" stroke="#888780" stroke-width="1.5"/>
  <rect id="ld-s1" x="200" y="114" width="37" height="124" rx="2" fill="#1D9E75" class="ld-cdim"/>
  <rect id="ld-s2" x="241" y="114" width="37" height="124" rx="2" fill="#1D9E75" class="ld-cdim"/>
  <rect id="ld-s3" x="282" y="114" width="37" height="124" rx="2" fill="#1D9E75" class="ld-cdim"/>
  <rect id="ld-s4" x="323" y="114" width="37" height="124" rx="2" fill="#1D9E75" class="ld-cdim"/>
  <rect id="ld-s5" x="364" y="114" width="34" height="124" rx="2" fill="#1D9E75" class="ld-cdim"/>
  <line x1="198" y1="112" x2="198" y2="240" stroke="#888780" stroke-width="1"   opacity="0.7"/>
  <line x1="239" y1="112" x2="239" y2="240" stroke="#888780" stroke-width="1.2" opacity="0.8"/>
  <line x1="280" y1="112" x2="280" y2="240" stroke="#888780" stroke-width="1.2" opacity="0.8"/>
  <line x1="321" y1="112" x2="321" y2="240" stroke="#888780" stroke-width="1.2" opacity="0.8"/>
  <line x1="362" y1="112" x2="362" y2="240" stroke="#888780" stroke-width="1.2" opacity="0.8"/>
  <!-- Door -->
  <rect x="174" y="122" width="22" height="90" rx="1" fill="#B4B2A9" stroke="#888780" stroke-width="0.8"/>
  <rect x="174" y="132" width="3" height="6" rx="1" fill="#888780"/>
  <rect x="174" y="194" width="3" height="6" rx="1" fill="#888780"/>
  <rect x="193" y="162" width="2" height="12" rx="1" fill="#888780"/>
  <polygon points="183,148 177,160 189,160" fill="none" stroke="#BA7517" stroke-width="1.1"/>
  <text x="183" y="158" text-anchor="middle" font-size="8" fill="#BA7517">!</text>
  <!-- Lightning bolt -->
  <polygon points="254,122 242,156 251,156 239,190 268,150 257,150 270,122" fill="#EF9F27" opacity="0.9"/>
  <!-- BESS label -->
  <text x="345" y="196" text-anchor="middle" font-size="22" font-weight="700" fill="#EF9F27" opacity="0.9" font-family="sans-serif">BESS</text>
  <!-- Base -->
  <rect x="166" y="240" width="238" height="8" rx="2" fill="#B4B2A9"/>
  <rect x="178" y="236" width="14" height="6" rx="1" fill="#888780"/>
  <rect x="376" y="236" width="14" height="6" rx="1" fill="#888780"/>
</svg>
<div style="font-size:14px;color:#aaa;">Ανάκτηση δεδομένων<span class="ld-dots"></span></div>
{"<div style='font-size:11px;color:#666;'>" + subtitle + "</div>" if subtitle else ""}
</div>
</div>
<script>
(function(){{
  const DUR=5000;
  const lbl=document.getElementById('ld-pct');
  const segs=[1,2,3,4,5].map(i=>document.getElementById('ld-s'+i));
  if(!lbl||!segs[0]) return;
  function frame(now){{
    const t=(now%DUR)/DUR;
    let p=0;
    if(t<0.78) p=t/0.78;
    else if(t<0.92) p=1;
    else p=0;
    lbl.textContent=Math.round(p*100)+'%';
    segs.forEach((s,i)=>{{
      const on=p>=(i+1)*0.2;
      s.className.baseVal=on?'ld-con':'ld-cdim';
    }});
    requestAnimationFrame(frame);
  }}
  requestAnimationFrame(frame);
}})();
</script>
""", unsafe_allow_html=True)
    return ph


# ============================================================
# 1. ΡΥΘΜΙΣΕΙΣ ΣΕΛΙΔΑΣ
# ============================================================
# Αυτό πρέπει να είναι η ΠΡΩΤΗ εντολή Streamlit στο αρχείο.

st.set_page_config(
    page_title = APP_TITLE,
    page_icon  = "⚡",
    layout     = "wide",       # full width — χωρίς sidebar
)

# Κρύβουμε το default Streamlit menu και footer για καθαρότερη εμφάνιση
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer     {visibility: hidden;}
    header     {visibility: hidden;}

    /* Μεγαλύτερος τίτλος tabs */
    .stTabs [data-baseweb="tab"] {
        font-size: 18px;
        font-weight: 600;
        padding: 10px 30px;
    }

    /* Κουμπί λήψης — κολλητό κάτω-κάτω */
    .download-bar {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: #0e1117;
        border-top: 1px solid #333;
        padding: 12px 40px;
        z-index: 999;
    }

    /* Download button — κόκκινο χρώμα */
    [data-testid="stDownloadButton"] > button {
        background-color: #ff4b4b;
        color: white;
        border: none;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background-color: #cc3a3a;
        color: white;
        border: none;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# 2. ΤΙΤΛΟΣ
# ============================================================

st.title("⚡ " + APP_TITLE)
st.caption("Ανάκτηση ενεργειακών δεδομένων από ENTSO-E Transparency Platform & ΑΔΜΗΕ")

st.divider()


# ============================================================
# 3. TABS
# ============================================================

tab_entso, tab_admie = st.tabs(["🌍  ENTSO-E", "🇬🇷  ΑΔΜΗΕ"])


# ════════════════════════════════════════════════════════════
# TAB 1: ENTSO-E
# ════════════════════════════════════════════════════════════

with tab_entso:

    # ── 3.1 ΧΡΟΝΙΚΟ ΕΥΡΟΣ ───────────────────────────────────
    st.subheader("📅 Χρονικό εύρος")

    col_from, col_to, col_tz = st.columns([2, 2, 1])

    with col_from:
        entso_date_from = st.date_input(
            "Από",
            value = date.today() - timedelta(days=7),
            key   = "entso_from",
        )

    with col_to:
        entso_date_to = st.date_input(
            "Έως",
            value = date.today(),
            key   = "entso_to",
        )

    with col_tz:
        entso_tz = st.selectbox(
            "Ζώνη ώρας εισόδου",
            options = ["Ώρα Ελλάδας", "UTC"],
            key     = "entso_tz",
        )

    # Μετατροπή date → datetime
    dt_from = datetime.combine(entso_date_from, datetime.min.time())
    dt_to   = datetime.combine(entso_date_to,   datetime.min.time())

    # Αν ο χρήστης εισήγαγε UTC, προσθέτουμε tzinfo=UTC
    # ώστε η to_utc_str() να μην κάνει εκ νέου μετατροπή
    if entso_tz == "UTC":
        import pytz
        dt_from = pytz.utc.localize(dt_from)
        dt_to   = pytz.utc.localize(dt_to)

    if dt_from >= dt_to:
        st.error("⚠️ Η ημερομηνία 'Από' πρέπει να είναι πριν την 'Έως'.")
        st.stop()

    st.divider()

    # ── 3.2 ΕΠΙΛΟΓΗ ΧΩΡΩΝ ───────────────────────────────────
    st.subheader("🌍 Χώρες")

    # Grid χωρών — αρχικοποίηση session_state (default: μόνο Ελλάδα)
    country_list = list(COUNTRIES.keys())
    for country in country_list:
        if f"c_{country}" not in st.session_state:
            st.session_state[f"c_{country}"] = (country == "Greece")

    # Κουμπιά γρήγορης επιλογής
    col_all, col_none, col_counter = st.columns([1, 1, 6])

    with col_all:
        if st.button("Όλες", key="entso_all"):
            for country in country_list:
                st.session_state[f"c_{country}"] = True
            st.rerun()

    with col_none:
        if st.button("Καμία", key="entso_none"):
            for country in country_list:
                st.session_state[f"c_{country}"] = False
            st.rerun()

    # Grid χωρών — 8 στήλες
    selected_countries = []
    N_COLS = 8
    rows = [country_list[i:i+N_COLS] for i in range(0, len(country_list), N_COLS)]

    for row in rows:
        cols = st.columns(N_COLS)
        for i, country in enumerate(row):
            with cols[i]:
                # Χρησιμοποιούμε key= που δείχνει στο session_state
                if st.checkbox(country, key=f"c_{country}"):
                    selected_countries.append(country)

    with col_counter:
        st.caption(f"✔ {len(selected_countries)} / {len(COUNTRIES)} επιλεγμένες")

    st.divider()

    # ── 3.3 ΕΠΙΛΟΓΗ ΚΑΤΗΓΟΡΙΩΝ ──────────────────────────────
    st.subheader("📊 Κατηγορίες δεδομένων")

    # Ομαδοποίηση datasets ανά group (από τον CATALOG)
    groups = {}
    for key, ds in CATALOG.items():
        groups.setdefault(ds["group"], []).append((key, ds["label"]))

    selected_datasets = []

    # Εμφανίζουμε τις ομάδες σε 2 columns για εξοικονόμηση χώρου
    group_items = list(groups.items())
    half = len(group_items) // 2 + len(group_items) % 2
    col_left, col_right = st.columns(2)

    for i, (group_name, datasets) in enumerate(group_items):
        target_col = col_left if i < half else col_right
        with target_col:
            st.markdown(f"**{group_name}**")
            for ds_key, ds_label in datasets:
                if st.checkbox(ds_label, key=f"ds_{ds_key}"):
                    selected_datasets.append(ds_key)

    st.divider()

    # ── 3.4 ΠΙΝΑΚΑΣ ΔΙΑΘΕΣΙΜΟΤΗΤΑΣ ──────────────────────────
    st.subheader("🔍 Διαθεσιμότητα δεδομένων")

    if not selected_countries:
        st.info("Επίλεξε τουλάχιστον μία χώρα για να ελέγξεις τη διαθεσιμότητα.")
    elif not selected_datasets:
        st.info("Επίλεξε τουλάχιστον μία κατηγορία δεδομένων.")
    else:
        if st.button("🔎 Έλεγχος διαθεσιμότητας", key="entso_check"):

            _ph = show_loading(f"{', '.join(selected_countries[:3])}")
            availability = entso_check(
                dataset_keys  = selected_datasets,
                country_names = selected_countries,
                dt_from       = dt_from,
                dt_to         = dt_to,
                api_token     = ENTSO_TOKEN,
            )
            _ph.empty()

            # Φτιάχνουμε πίνακα: γραμμές=χώρες, στήλες=datasets
            badge = {"ok": "✅", "partial": "⚠️", "unavailable": "—"}
            labels = {k: CATALOG[k]["label"] for k in selected_datasets}

            table_data = {}
            for country in selected_countries:
                table_data[country] = {
                    labels[ds]: badge.get(availability.get((ds, country), "unavailable"), "—")
                    for ds in selected_datasets
                }

            avail_df = pd.DataFrame(table_data).T
            avail_df.index.name = "Χώρα"
            st.dataframe(avail_df, use_container_width=True)

    st.divider()

    # ── 3.5 ΑΝΑΚΤΗΣΗ & ΠΡΟΕΠΙΣΚΟΠΗΣΗ ────────────────────────
    st.subheader("📋 Δεδομένα")

    if st.button("▶ Ανάκτηση & Λήψη Excel", key="entso_fetch",
                 type="primary", use_container_width=True):

        if not selected_countries:
            st.warning("Επίλεξε τουλάχιστον μία χώρα.")
        elif not selected_datasets:
            st.warning("Επίλεξε τουλάχιστον μία κατηγορία.")
        else:
            _ph = show_loading(f"{', '.join(selected_countries[:3])} · {entso_date_from} → {entso_date_to}")
            results = entso_get_data(
                dataset_keys  = selected_datasets,
                country_names = selected_countries,
                dt_from       = dt_from,
                dt_to         = dt_to,
                api_token     = ENTSO_TOKEN,
            )
            _ph.empty()

            # Αποθηκεύουμε τα αποτελέσματα στο session_state
            # ώστε να μην χαθούν όταν ο χρήστης πατήσει "Λήψη"
            st.session_state["entso_results"]  = results
            st.session_state["entso_datasets"] = selected_datasets
            st.session_state["entso_countries_sel"] = selected_countries

    # Προεπισκόπηση — εμφανίζεται μόνο αν υπάρχουν αποτελέσματα
    if "entso_results" in st.session_state:
        results  = st.session_state["entso_results"]
        ds_keys  = st.session_state["entso_datasets"]
        countries= st.session_state["entso_countries_sel"]

        # Tabs προεπισκόπησης — ένα tab ανά dataset + Info
        ds_labels = [CATALOG[k]["label"] for k in ds_keys if not results.get(k, pd.DataFrame()).empty]
        tab_labels = ds_labels + ["ℹ️ Info"]

        if ds_labels:
            preview_tabs = st.tabs(tab_labels)

            for i, ds_key in enumerate([k for k in ds_keys if not results.get(k, pd.DataFrame()).empty]):
                with preview_tabs[i]:
                    df = results[ds_key]
                    st.caption(f"{len(df)} εγγραφές")
                    st.dataframe(pd.concat([df.head(5), df.tail(5)]), use_container_width=True)

            # Tab Info
            with preview_tabs[-1]:
                st.markdown(f"**Πηγή:** ENTSO-E Transparency Platform")
                st.markdown(f"**Περίοδος:** {entso_date_from} → {entso_date_to}")
                st.markdown(f"**Χώρες:** {', '.join(countries)}")
                st.markdown(f"**Κατηγορίες:** {', '.join([CATALOG[k]['label'] for k in ds_keys])}")
        else:
            st.warning("Δεν βρέθηκαν δεδομένα για τις επιλεγμένες παραμέτρους.")
            st.stop()

        st.divider()

        # ── 3.6 ΛΗΨΗ EXCEL ── εμφανίζεται μόνο αν υπάρχουν δεδομένα
        xlsx_bytes = export_entso(
            results       = results,
            dataset_keys  = ds_keys,
            country_names = countries,
            dt_from       = dt_from,
            dt_to         = dt_to,
        )

        st.download_button(
            label     = "⬇️ Λήψη Excel",
            data      = xlsx_bytes,
            file_name = f"ENTSO-E_{entso_date_from}_{entso_date_to}.xlsx",
            mime      = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width = True,
        )


# ════════════════════════════════════════════════════════════
# TAB 2: ΑΔΜΗΕ
# ════════════════════════════════════════════════════════════

with tab_admie:

    # ── 4.1 ΧΡΟΝΙΚΟ ΕΥΡΟΣ ───────────────────────────────────
    st.subheader("📅 Χρονικό εύρος")

    col_from2, col_to2 = st.columns(2)

    with col_from2:
        admie_date_from = st.date_input(
            "Από",
            value = date.today() - timedelta(days=7),
            key   = "admie_from",
        )

    with col_to2:
        admie_date_to = st.date_input(
            "Έως",
            value = date.today(),
            key   = "admie_to",
        )

    if admie_date_from >= admie_date_to:
        st.error("⚠️ Η ημερομηνία 'Από' πρέπει να είναι πριν την 'Έως'.")
        st.stop()

    # Μορφή που θέλει το ΑΔΜΗΕ API: "YYYY-MM-DD"
    admie_from_str = admie_date_from.strftime("%Y-%m-%d")
    admie_to_str   = admie_date_to.strftime("%Y-%m-%d")

    st.divider()

    # ── 4.2 ΕΠΙΛΟΓΗ FILETYPES ───────────────────────────────
    st.subheader("📂 Κατηγορίες δεδομένων")

    # Φορτώνουμε τα filetypes από το API (με caching για ταχύτητα)
    # st.cache_data: αποθηκεύει το αποτέλεσμα ώστε να μην καλεί το API κάθε φορά
    @st.cache_data(ttl=3600)   # ανανεώνεται κάθε 1 ώρα
    def load_admie_filetypes():
        return get_filetypes_grouped()

    with st.spinner("Φόρτωση κατηγοριών ΑΔΜΗΕ..."):
        admie_groups = load_admie_filetypes()

    selected_filetypes = []

    if not admie_groups:
        st.warning("Δεν ήταν δυνατή η σύνδεση με το ΑΔΜΗΕ API. Δοκίμασε αργότερα.")
    else:
        for process_name, filetypes in admie_groups.items():
            st.markdown(
                f"<p style='color:#ff4b4b; font-weight:700; font-size:15px; "
                f"margin-top:12px; margin-bottom:4px; border-bottom:1px solid #333; "
                f"padding-bottom:4px;'>▸ {process_name}</p>",
                unsafe_allow_html=True,
            )
            cols = st.columns(6)
            for i, ft in enumerate(filetypes):
                with cols[i % 6]:
                    if st.checkbox(ft, key=f"ft_{ft}"):
                        selected_filetypes.append(ft)

    st.divider()

    # ── 4.3 ΠΙΝΑΚΑΣ ΔΙΑΘΕΣΙΜΟΤΗΤΑΣ ──────────────────────────
    st.subheader("🔍 Διαθεσιμότητα δεδομένων")

    if not selected_filetypes:
        st.info("Επίλεξε τουλάχιστον έναν τύπο δεδομένων.")
    else:
        if st.button("🔎 Έλεγχος διαθεσιμότητας", key="admie_check"):

            _ph = show_loading(f"{', '.join(selected_filetypes[:3])} · {admie_from_str} → {admie_to_str}")
            avail = admie_check(selected_filetypes, admie_from_str, admie_to_str)
            _ph.empty()

            avail_rows = []
            for ft, info in avail.items():
                avail_rows.append({
                    "Filetype"       : ft,
                    "Διαθεσιμότητα"  : "✅ Διαθέσιμο" if info["status"] == "ok" else "— Μη διαθέσιμο",
                    "Αρχεία"         : info["count"],
                })

            st.dataframe(pd.DataFrame(avail_rows), use_container_width=True, hide_index=True)

    st.divider()

    # ── 4.4 ΑΝΑΚΤΗΣΗ & ΠΡΟΕΠΙΣΚΟΠΗΣΗ ────────────────────────
    st.subheader("📋 Δεδομένα")

    # ⚠️ Έλεγχος συμβατότητας session_state:
    # Αν ο χρήστης άλλαξε filetypes ή ημερομηνίες μετά την τελευταία ανάκτηση,
    # τα αποθηκευμένα αποτελέσματα δεν αντιστοιχούν πλέον στην τρέχουσα επιλογή.
    # Καθαρίζουμε αυτόματα για να αποφύγουμε crash στην export.
    if "admie_results" in st.session_state:
        saved_fts   = set(st.session_state.get("admie_filetypes", []))
        saved_dates = st.session_state.get("admie_saved_dates", ("", ""))
        current_dates = (admie_from_str, admie_to_str)

        if set(selected_filetypes) != saved_fts or current_dates != saved_dates:
            # Η επιλογή άλλαξε — τα αποθηκευμένα δεδομένα δεν ισχύουν πια
            del st.session_state["admie_results"]
            del st.session_state["admie_filetypes"]
            st.session_state.pop("admie_saved_dates", None)
            st.info("ℹ️ Η επιλογή σου άλλαξε. Κάνε νέα ανάκτηση δεδομένων.")

    if st.button("▶ Ανάκτηση & Λήψη Excel", key="admie_fetch",
                 type="primary", use_container_width=True):

        if not selected_filetypes:
            st.warning("Επίλεξε τουλάχιστον έναν τύπο δεδομένων.")
        else:
            _ph = show_loading(f"{', '.join(selected_filetypes[:3])} · {admie_from_str} → {admie_to_str}")
            admie_results = admie_get_data(
                filetype_keys = selected_filetypes,
                date_from     = admie_from_str,
                date_to       = admie_to_str,
            )
            _ph.empty()

            # Αποθηκεύουμε και την τρέχουσα επιλογή για μελλοντικό validation
            st.session_state["admie_results"]     = admie_results
            st.session_state["admie_filetypes"]   = selected_filetypes
            st.session_state["admie_saved_dates"] = (admie_from_str, admie_to_str)

    # Προεπισκόπηση
    if "admie_results" in st.session_state:
        admie_results = st.session_state["admie_results"]
        ft_keys       = st.session_state["admie_filetypes"]

        available_fts = [ft for ft in ft_keys if not admie_results.get(ft, pd.DataFrame()).empty]
        tab_labels    = available_fts + ["ℹ️ Info"]

        if available_fts:
            preview_tabs = st.tabs(tab_labels)

            for i, ft in enumerate(available_fts):
                with preview_tabs[i]:
                    df = admie_results[ft]
                    st.caption(f"{len(df)} εγγραφές")
                    # Ασφαλής προεπισκόπηση: αν λιγότερες από 10 εγγραφές, δείχνουμε όλες
                    if len(df) <= 10:
                        st.dataframe(df, use_container_width=True)
                    else:
                        st.dataframe(pd.concat([df.head(5), df.tail(5)]), use_container_width=True)

            with preview_tabs[-1]:
                st.markdown(f"**Πηγή:** ΑΔΜΗΕ File API")
                st.markdown(f"**Περίοδος:** {admie_date_from} → {admie_date_to}")
                st.markdown(f"**Filetypes:** {', '.join(ft_keys)}")
        else:
            st.warning("Δεν βρέθηκαν δεδομένα για τις επιλεγμένες παραμέτρους.")
            st.stop()

        st.divider()

        # ── 4.5 ΛΗΨΗ EXCEL ── εμφανίζεται μόνο αν υπάρχουν δεδομένα
        try:
            xlsx_bytes = export_admie(
                results       = admie_results,
                filetype_keys = ft_keys,
                dt_from       = admie_from_str,
                dt_to         = admie_to_str,
            )

            st.download_button(
                label     = "⬇️ Λήψη Excel",
                data      = xlsx_bytes,
                file_name = f"ADMIE_{admie_date_from}_{admie_date_to}.xlsx",
                mime      = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width = True,
            )
        except Exception as e:
            st.error(f"⚠️ Σφάλμα κατά τη δημιουργία του Excel: {e}")
            st.info("Δοκίμασε να κάνεις νέα ανάκτηση δεδομένων.")
