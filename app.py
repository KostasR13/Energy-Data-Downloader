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

    /* Download button — πράσινο χρώμα */
    [data-testid="stDownloadButton"] > button {
        background-color: #1D9E75;
        color: white;
        border: none;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background-color: #157a5a;
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

tab_entso, tab_admie = st.tabs(["  ENTSO-E", "  ΑΔΜΗΕ"])


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
    st.subheader("Χώρες")

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

            with st.spinner("Ελέγχω διαθεσιμότητα..."):
                availability = entso_check(
                    dataset_keys  = selected_datasets,
                    country_names = selected_countries,
                    dt_from       = dt_from,
                    dt_to         = dt_to,
                    api_token     = ENTSO_TOKEN,
                )

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
    st.subheader("📋 Προεπισκόπηση Δεδομένων")

    if st.button("▶ Προεπισκόπηση Δεδομένων", key="entso_fetch",
                 type="primary", use_container_width=True):

        if not selected_countries:
            st.warning("Επίλεξε τουλάχιστον μία χώρα.")
        elif not selected_datasets:
            st.warning("Επίλεξε τουλάχιστον μία κατηγορία.")
        else:
            with st.spinner("Ανάκτηση δεδομένων από ENTSO-E..."):
                results = entso_get_data(
                    dataset_keys  = selected_datasets,
                    country_names = selected_countries,
                    dt_from       = dt_from,
                    dt_to         = dt_to,
                    api_token     = ENTSO_TOKEN,
                )

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

            with st.spinner("Ελέγχω διαθεσιμότητα..."):
                avail = admie_check(selected_filetypes, admie_from_str, admie_to_str)

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
    st.subheader("📋 Προεπισκόπηση Δεδομένων")

    if st.button("▶ Προεπισκόπηση Δεδομένων", key="admie_fetch",
                 type="primary", use_container_width=True):

        if not selected_filetypes:
            st.warning("Επίλεξε τουλάχιστον έναν τύπο δεδομένων.")
        else:
            with st.spinner("Ανάκτηση δεδομένων από ΑΔΜΗΕ..."):
                admie_results = admie_get_data(
                    filetype_keys = selected_filetypes,
                    date_from     = admie_from_str,
                    date_to       = admie_to_str,
                )

            st.session_state["admie_results"]   = admie_results
            st.session_state["admie_filetypes"] = selected_filetypes

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
