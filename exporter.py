"""
exporter.py
-----------
Μετατρέπει τα DataFrames σε Excel αρχείο με πολλά sheets.

Λογική sheets:
  • 1 χώρα,  πολλές κατηγορίες → 1 sheet, στήλες ανά κατηγορία
  • Πολλές χώρες, πολλές κατηγορίες → 1 sheet ανά κατηγορία, στήλες ανά χώρα
  • ΑΔΜΗΕ → 1 sheet ανά filetype (πάντα 1 χώρα: GR)
  • Πάντα υπάρχει sheet "Info" στο τέλος

Κύριες συναρτήσεις:
  export_entso(results, dataset_keys, country_names, dt_from, dt_to) -> bytes
  export_admie(results, filetype_keys, dt_from, dt_to)               -> bytes
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
    χωρίς τους χαρακτήρες: / ? * [ ] : '
    Επίσης δεν επιτρέπεται το ' στην αρχή ή στο τέλος.
    """
    # Χαρακτήρες που απαγορεύει το Excel σε ονόματα sheet
    for ch in "/\\?*[]:":
        name = name.replace(ch, "-")
    # Αφαιρούμε single quote από αρχή/τέλος (απαγορεύεται από Excel)
    name = name.strip("'")
    # Αν το όνομα έμεινε κενό, δίνουμε default
    if not name:
        name = "Sheet"
    return name[:max_len]


def _make_info_sheet(source: str, dt_from, dt_to,
                     items: list, extra: dict = None) -> pd.DataFrame:
    """
    Φτιάχνει το περιεχόμενο του sheet 'Info'.
    Επιστρέφει DataFrame με 2 στήλες: Παράμετρος | Τιμή.
    Δέχεται dt_from/dt_to είτε ως datetime είτε ως string (ΑΔΜΗΕ).
    """
    def _fmt(dt):
        if isinstance(dt, datetime):
            return dt.strftime("%d/%m/%Y %H:%M")
        return str(dt)

    rows = [
        ("Πηγή δεδομένων", source),
        ("Από",            _fmt(dt_from)),
        ("Έως",            _fmt(dt_to)),
        ("Δεδομένα",       ", ".join(items)),
        ("Εξαγωγή",        datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
    ]

    if extra:
        for key, val in extra.items():
            rows.append((key, str(val)))

    return pd.DataFrame(rows, columns=["Παράμετρος", "Τιμή"])


def _pivot_for_sheet(df: pd.DataFrame, value_col: str,
                     country_col: str = "Country") -> pd.DataFrame:
    """
    Μετατρέπει long-format DataFrame σε wide-format για το Excel.

    Long:  Timestamp | Country | Value
    Wide:  Timestamp | Greece  | Germany | ...

    Για datasets με PsrType (π.χ. generation_per_type), προσθέτει
    στήλες ανά συνδυασμό Country+PsrType αντί να χάνει δεδομένα.
    """
    if df.empty or country_col not in df.columns or "Timestamp (UTC)" not in df.columns:
        return df

    try:
        has_psr = "PsrType" in df.columns and df["PsrType"].notna().any()

        if has_psr:
            # Συνδυάζουμε Country + PsrType σε μία στήλη για τον άξονα στηλών
            # ώστε να μην χαθεί καμία τιμή
            df = df.copy()
            df["_col"] = df[country_col] + " | " + df["PsrType"].fillna("")
            col_axis = "_col"
        else:
            col_axis = country_col

        pivot = df.pivot_table(
            index="Timestamp (UTC)",
            columns=col_axis,
            values=value_col,
            aggfunc="sum",    # sum αντί για first: σωστό για MW quantities
        ).reset_index()

        pivot.columns.name = None
        return pivot

    except Exception:
        return df


def _pivot_local_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Φτιάχνει στήλες τοπικής ώρας ανά χώρα.

    Αποτέλεσμα:
      Timestamp (UTC) | Local (Greece) | Local (Germany) | ...
    """
    if df.empty or "Country" not in df.columns or "Timestamp (Local)" not in df.columns:
        return pd.DataFrame()

    countries = sorted(df["Country"].unique())
    result = None

    for country in countries:
        sub = (df[df["Country"] == country]
               [["Timestamp (UTC)", "Timestamp (Local)"]]
               .drop_duplicates("Timestamp (UTC)")
               .rename(columns={"Timestamp (Local)": f"Local ({country})"}))

        if result is None:
            result = sub
        else:
            result = pd.merge(result, sub, on="Timestamp (UTC)", how="outer")

    return result if result is not None else pd.DataFrame()


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
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:

        if len(country_names) <= 1:
            # ΣΕΝΑΡΙΟ Α: 1 χώρα → 1 sheet με στήλες ανά κατηγορία
            _write_single_country_sheet(writer, results, dataset_keys, country_names)
        else:
            # ΣΕΝΑΡΙΟ Β: πολλές χώρες → 1 sheet ανά κατηγορία
            _write_multi_country_sheets(writer, results, dataset_keys)

        # Sheet Info — πάντα στο τέλος
        labels = [CATALOG[k]["label"] for k in dataset_keys if k in CATALOG]
        info_df = _make_info_sheet(
            source  = "ENTSO-E Transparency Platform",
            dt_from = dt_from,
            dt_to   = dt_to,
            items   = labels,
            extra   = {"Χώρες": ", ".join(country_names)},
        )
        info_df.to_excel(writer, sheet_name="Info", index=False)

    buffer.seek(0)
    return buffer.read()


def _write_single_country_sheet(writer, results: dict, dataset_keys: list,
                                 country_names: list):
    """
    Σενάριο Α: 1 χώρα, πολλές κατηγορίες.
    Γράφει 1 sheet: Timestamp (UTC) | Timestamp (Local) | κατηγορία1 | κατηγορία2 | ...

    Για datasets με PsrType (π.χ. generation_per_type) που έχουν
    πολλαπλές γραμμές ανά timestamp, γράφουμε ΧΩΡΙΣΤΟ sheet
    αντί να μπερδέψουμε το merge.
    """
    country = country_names[0] if country_names else "Data"
    combined = None       # το κύριο sheet (datasets χωρίς PsrType)
    psr_datasets = []     # datasets με PsrType → χωριστά sheets

    for ds_key in dataset_keys:
        df = results.get(ds_key, pd.DataFrame())
        if df.empty:
            continue

        label     = CATALOG[ds_key]["label"]
        value_col = CATALOG[ds_key]["value_col"]

        has_psr = "PsrType" in df.columns and df["PsrType"].notna().any()

        if has_psr:
            # Γράφουμε χωριστό sheet για αυτό το dataset
            psr_datasets.append((ds_key, label, value_col, df))
            continue

        # Απλό dataset: κρατάμε μόνο τις στήλες που χρειαζόμαστε
        sub = (df[["Timestamp (UTC)", "Timestamp (Local)", value_col]]
               .drop_duplicates("Timestamp (UTC)")
               .rename(columns={value_col: label}))

        if combined is None:
            combined = sub
        else:
            combined = pd.merge(
                combined, sub,
                on=["Timestamp (UTC)", "Timestamp (Local)"],
                how="outer",
            )

    # Γράφουμε το κύριο sheet
    if combined is not None and not combined.empty:
        combined.sort_values("Timestamp (UTC)", inplace=True)
        combined.to_excel(writer, sheet_name=_safe_sheet_name(country), index=False)

    # Γράφουμε χωριστά sheets για PsrType datasets
    for ds_key, label, value_col, df in psr_datasets:
        # Pivot: Timestamp (UTC) | B01 | B16 | ...
        pivot = df.pivot_table(
            index="Timestamp (UTC)",
            columns="PsrType",
            values=value_col,
            aggfunc="sum",
        ).reset_index()
        pivot.columns.name = None

        # Προσθέτουμε τοπική ώρα
        local_col = (df[["Timestamp (UTC)", "Timestamp (Local)"]]
                     .drop_duplicates("Timestamp (UTC)"))
        pivot = pd.merge(local_col, pivot, on="Timestamp (UTC)", how="right")
        pivot.sort_values("Timestamp (UTC)", inplace=True)

        sheet_name = _safe_sheet_name(f"{country} - {label}")
        pivot.to_excel(writer, sheet_name=sheet_name, index=False)


def _write_multi_country_sheets(writer, results: dict, dataset_keys: list):
    """
    Σενάριο Β: πολλές χώρες, 1 sheet ανά κατηγορία.
    Δομή: Timestamp (UTC) | Local (χώρα1) | Local (χώρα2) | ... | τιμή_χώρα1 | τιμή_χώρα2 | ...
    """
    for ds_key in dataset_keys:
        df = results.get(ds_key, pd.DataFrame())
        if df.empty:
            continue

        label     = CATALOG[ds_key]["label"]
        value_col = CATALOG[ds_key]["value_col"]

        # Pivot τιμών
        value_pivot = _pivot_for_sheet(df, value_col, country_col="Country")

        # Pivot τοπικής ώρας (μία στήλη ανά χώρα)
        local_pivot = _pivot_local_timestamps(df)

        if local_pivot is not None and not local_pivot.empty:
            wide_df = pd.merge(local_pivot, value_pivot, on="Timestamp (UTC)", how="outer")
        else:
            wide_df = value_pivot

        wide_df.sort_values("Timestamp (UTC)", inplace=True)
        wide_df.to_excel(writer, sheet_name=_safe_sheet_name(label), index=False)


# ============================================================
# ΕΞΑΓΩΓΗ ΑΔΜΗΕ
# ============================================================

def export_admie(results: dict, filetype_keys: list,
                 dt_from: str, dt_to: str) -> bytes:
    """
    Δημιουργεί Excel αρχείο από τα αποτελέσματα του admie_client.get_data().

    Για το ΑΔΜΗΕ: πάντα 1 χώρα (GR) → 1 sheet ανά filetype.

    Παράμετροι:
      results      : { filetype: DataFrame } από admie_client.get_data()
      filetype_keys: λίστα filetypes που επιλέχθηκαν
      dt_from/dt_to: "YYYY-MM-DD" strings
    """
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:

        for filetype in filetype_keys:
            df = results.get(filetype, pd.DataFrame())
            sheet_name = _safe_sheet_name(filetype)

            if df.empty:
                # Κενό sheet ώστε ο χρήστης να ξέρει ότι ζητήθηκε
                empty = pd.DataFrame({"Σημείωση": ["Δεν βρέθηκαν δεδομένα για αυτό το filetype."]})
                empty.to_excel(writer, sheet_name=sheet_name, index=False)
                continue

            # Αφαιρούμε τεχνικές στήλες που δεν χρειάζεται να βλέπει ο χρήστης
            cols_to_drop = [c for c in ["source_file"] if c in df.columns]
            df = df.drop(columns=cols_to_drop)

            df.to_excel(writer, sheet_name=sheet_name, index=False)

        # Sheet Info — πάντα στο τέλος
        info_df = _make_info_sheet(
            source  = "ΑΔΜΗΕ File API",
            dt_from = dt_from,
            dt_to   = dt_to,
            items   = filetype_keys,
        )
        info_df.to_excel(writer, sheet_name="Info", index=False)

    buffer.seek(0)
    return buffer.read()
