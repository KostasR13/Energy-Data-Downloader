"""
exporter.py
-----------
Μετατρέπει τα DataFrames σε Excel αρχείο με πολλά sheets.

Λογική sheets (αποφασίστηκε στο UI design):
  • 1 χώρα,  πολλές κατηγορίες → 1 sheet, στήλες ανά κατηγορία
  • Πολλές χώρες, πολλές κατηγορίες → 1 sheet ανά κατηγορία, στήλες ανά χώρα
  • ΑΔΜΗΕ → 1 sheet ανά filetype (πάντα 1 χώρα: GR)
  • Πάντα υπάρχει sheet "Info" στο τέλος

Κύρια συνάρτηση:
  export_entso(results, dataset_keys, country_names, dt_from, dt_to) → bytes
  export_admie(results, filetype_keys, dt_from, dt_to)               → bytes

Και οι δύο επιστρέφουν bytes που το Streamlit κατεβάζει απευθείας.
"""

import pandas as pd
import io
from datetime import datetime
from entso_client import CATALOG


# ============================================================
# ΒΟΗΘΗΤΙΚΕΣ ΣΥΝΑΡΤΗΣΕΙΣ
# ============================================================

def _safe_sheet_name(name: str, max_len: int = 31) -> str:
    """
    Το Excel επιτρέπει ονόματα sheets μέχρι 31 χαρακτήρες,
    χωρίς τους χαρακτήρες: / \ ? * [ ]
    """
    for ch in r"/\?*[]":
        name = name.replace(ch, "-")
    return name[:max_len]


def _make_info_sheet(source: str, dt_from: datetime, dt_to: datetime,
                     items: list, extra: dict = None) -> pd.DataFrame:
    """
    Φτιάχνει το περιεχόμενο του sheet "Info".
    Επιστρέφει DataFrame με 2 στήλες: Παράμετρος | Τιμή
    """
    rows = [
        ("Πηγή δεδομένων",  source),
        ("Από",             dt_from.strftime("%d/%m/%Y %H:%M") if isinstance(dt_from, datetime) else str(dt_from)),
        ("Έως",             dt_to.strftime("%d/%m/%Y %H:%M")   if isinstance(dt_to,   datetime) else str(dt_to)),
        ("Δεδομένα",        ", ".join(items)),
        ("Εξαγωγή",         datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
    ]

    # Προαιρετικά επιπλέον πεδία (π.χ. χώρες)
    if extra:
        for key, val in extra.items():
            rows.append((key, str(val)))

    return pd.DataFrame(rows, columns=["Παράμετρος", "Τιμή"])


def _pivot_for_sheet(df: pd.DataFrame, value_col: str, country_col: str = "Country") -> pd.DataFrame:
    """
    Μετατρέπει ένα "μακρύ" DataFrame (long format) σε "φαρδύ" (wide format).

    Long format:
      Timestamp | Country | Value
      2024-01-01 | GR     | 5200
      2024-01-01 | DE     | 45000

    Wide format (αυτό που βλέπει ο χρήστης στο Excel):
      Timestamp | GR    | DE
      2024-01-01 | 5200 | 45000

    Γιατί χρειάζεται: είναι πολύ πιο εύκολο να διαβάσεις στο Excel.
    """
    if df.empty or country_col not in df.columns or "Timestamp (UTC)" not in df.columns:
        return df

    try:
        pivot = df.pivot_table(
            index="Timestamp (UTC)",  # γραμμές = χρόνος UTC (κοινό για όλες τις χώρες)
            columns=country_col,      # στήλες = χώρες
            values=value_col,         # τιμές
            aggfunc="first"           # αν υπάρχουν διπλότυπα, παίρνουμε την πρώτη
        ).reset_index()

        pivot.columns.name = None     # αφαιρούμε το όνομα "Country" από τον άξονα στηλών
        return pivot

    except Exception:
        # Αν το pivot αποτύχει, επιστρέφουμε το original df
        return df


# ============================================================
# ΕΞΑΓΩΓΗ ENTSO-E
# ============================================================

def export_entso(results: dict, dataset_keys: list, country_names: list,
                 dt_from: datetime, dt_to: datetime) -> bytes:
    """
    Δημιουργεί Excel αρχείο από τα αποτελέσματα του entso_client.get_data().

    Παράμετροι:
      results       : { dataset_key: DataFrame } από entso_client.get_data()
      dataset_keys  : λίστα dataset keys που επιλέχθηκαν
      country_names : λίστα χωρών που επιλέχθηκαν
      dt_from/dt_to : χρονικό εύρος (datetime)

    Επιστρέφει: bytes (περιεχόμενο .xlsx αρχείου)
    """

    # Γράφουμε σε buffer μνήμης — δεν αποθηκεύουμε στο δίσκο
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:

        # ── ΛΟΓΙΚΗ SHEETS ──────────────────────────────────────
        if len(country_names) <= 1:
            # ΣΕΝΑΡΙΟ Α: 1 χώρα, πολλές κατηγορίες
            # → 1 sheet με στήλες ανά κατηγορία
            _write_single_country_sheet(writer, results, dataset_keys, country_names)
        else:
            # ΣΕΝΑΡΙΟ Β: πολλές χώρες, πολλές κατηγορίες
            # → 1 sheet ανά κατηγορία, στήλες ανά χώρα
            _write_multi_country_sheets(writer, results, dataset_keys)

        # ── SHEET INFO ─────────────────────────────────────────
        labels = [CATALOG[k]["label"] for k in dataset_keys if k in CATALOG]
        info_df = _make_info_sheet(
            source   = "ENTSO-E Transparency Platform",
            dt_from  = dt_from,
            dt_to    = dt_to,
            items    = labels,
            extra    = {"Χώρες": ", ".join(country_names)},
        )
        info_df.to_excel(writer, sheet_name="Info", index=False)

    buffer.seek(0)
    return buffer.read()


def _write_single_country_sheet(writer, results: dict, dataset_keys: list,
                                  country_names: list):
    """
    Σενάριο Α: Γράφει 1 sheet με timestamp + μία στήλη ανά κατηγορία.
    """
    # Μαζεύουμε όλα τα DataFrames και τα ενώνουμε στο Timestamp
    combined = None

    for ds_key in dataset_keys:
        df = results.get(ds_key, pd.DataFrame())
        if df.empty:
            continue

        label     = CATALOG[ds_key]["label"]
        value_col = CATALOG[ds_key]["value_col"]

        # Κρατάμε UTC, Local και value_col, μετονομάζουμε value_col → label
        sub = df[["Timestamp (UTC)", "Timestamp (Local)", value_col]].copy()
        sub = sub.rename(columns={value_col: label})

        if combined is None:
            combined = sub
        else:
            # Ενώνουμε βάσει UTC (κοινό σημείο αναφοράς) — outer join = best effort
            combined = pd.merge(combined, sub, on=["Timestamp (UTC)", "Timestamp (Local)"], how="outer")

    if combined is not None and not combined.empty:
        combined.sort_values("Timestamp (UTC)", inplace=True)
        country = country_names[0] if country_names else "Data"
        sheet_name = _safe_sheet_name(country)
        combined.to_excel(writer, sheet_name=sheet_name, index=False)


def _pivot_local_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Φτιάχνει στήλες τοπικής ώρας ανά χώρα.

    Αποτέλεσμα:
      Timestamp (UTC) | Local (Greece) | Local (Germany) | ...
    """
    if df.empty or "Country" not in df.columns:
        return pd.DataFrame()

    countries = df["Country"].unique()
    result = None

    for country in sorted(countries):
        sub = df[df["Country"] == country][["Timestamp (UTC)", "Timestamp (Local)"]].drop_duplicates()
        sub = sub.rename(columns={"Timestamp (Local)": f"Local ({country})"})

        if result is None:
            result = sub
        else:
            result = pd.merge(result, sub, on="Timestamp (UTC)", how="outer")

    return result if result is not None else pd.DataFrame()


def _write_multi_country_sheets(writer, results: dict, dataset_keys: list):
    """
    Σενάριο Β: Γράφει 1 sheet ανά κατηγορία.
    Δομή: Timestamp (UTC) | Local (χώρα1) | Local (χώρα2) | ... | τιμή χώρα1 | τιμή χώρα2 | ...
    """
    for ds_key in dataset_keys:
        df = results.get(ds_key, pd.DataFrame())
        if df.empty:
            continue

        label     = CATALOG[ds_key]["label"]
        value_col = CATALOG[ds_key]["value_col"]

        # Pivot τιμών: Timestamp UTC (γραμμές) × Country (στήλες)
        value_pivot = _pivot_for_sheet(df, value_col, country_col="Country")

        # Pivot τοπικής ώρας: μία στήλη ανά χώρα
        local_pivot = _pivot_local_timestamps(df)

        # Ενώνουμε: UTC | τοπικές ώρες | τιμές
        if local_pivot is not None and not local_pivot.empty:
            wide_df = pd.merge(local_pivot, value_pivot, on="Timestamp (UTC)", how="outer")
        else:
            wide_df = value_pivot

        sheet_name = _safe_sheet_name(label)
        wide_df.to_excel(writer, sheet_name=sheet_name, index=False)


# ============================================================
# ΕΞΑΓΩΓΗ ΑΔΜΗΕ
# ============================================================

def export_admie(results: dict, filetype_keys: list,
                 dt_from: str, dt_to: str) -> bytes:
    """
    Δημιουργεί Excel αρχείο από τα αποτελέσματα του admie_client.get_data().

    Για το ΑΔΜΗΕ: πάντα 1 χώρα (GR), οπότε 1 sheet ανά filetype.

    Παράμετροι:
      results      : { filetype: DataFrame } από admie_client.get_data()
      filetype_keys: λίστα filetypes που επιλέχθηκαν
      dt_from/dt_to: "YYYY-MM-DD" strings
    """
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:

        for filetype in filetype_keys:
            df = results.get(filetype, pd.DataFrame())

            if df.empty:
                # Γράφουμε κενό sheet ώστε ο χρήστης να ξέρει ότι ζητήθηκε
                # αλλά δεν υπήρχαν δεδομένα
                empty = pd.DataFrame({"Σημείωση": ["Δεν βρέθηκαν δεδομένα για αυτό το filetype."]})
                empty.to_excel(writer, sheet_name=_safe_sheet_name(filetype), index=False)
                continue

            # Αφαιρούμε τεχνικές στήλες που δεν χρειάζεται να βλέπει ο χρήστης
            cols_to_drop = [c for c in ["source_file"] if c in df.columns]
            df = df.drop(columns=cols_to_drop)

            sheet_name = _safe_sheet_name(filetype)
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        # ── SHEET INFO ─────────────────────────────────────────
        info_df = _make_info_sheet(
            source  = "ΑΔΜΗΕ File API",
            dt_from = dt_from,
            dt_to   = dt_to,
            items   = filetype_keys,
        )
        info_df.to_excel(writer, sheet_name="Info", index=False)

    buffer.seek(0)
    return buffer.read()
