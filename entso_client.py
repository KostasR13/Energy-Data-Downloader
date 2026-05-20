"""
entso_client.py
---------------
Επικοινωνία με το ENTSO-E Transparency Platform μέσω της βιβλιοθήκης entsoe-py.
Η βιβλιοθήκη χειρίζεται αυτόματα: XML parsing, year-limiting, rate limiting, retry.

Περιέχει:
  - CATALOG          : λεξικό με όλα τα διαθέσιμα datasets
  - COUNTRIES        : λεξικό χωρών → country code (για entsoe-py)
  - get_data()       : κύρια συνάρτηση — επιστρέφει DataFrames
  - check_availability() : ελέγχει αν υπάρχουν δεδομένα για χώρα/dataset
"""

import pandas as pd
import pytz
from datetime import datetime, timedelta
from entsoe import EntsoePandasClient
from entsoe.exceptions import NoMatchingDataError, InvalidBusinessParameterError

# ============================================================
# ΣΤΑΘΕΡΕΣ
# ============================================================

LOCAL_TZ = pytz.timezone("Europe/Athens")


# ============================================================
# CATALOG — Κατάλογος datasets
# ============================================================
# Κάθε dataset έχει:
#   "label"       : το όνομα που βλέπει ο χρήστης στο UI
#   "group"       : η ομάδα (για ομαδοποίηση στο UI)
#   "method"      : το όνομα της μεθόδου της EntsoePandasClient
#   "extra_params": επιπλέον παράμετροι που χρειάζεται η μέθοδος
#   "value_col"   : το όνομα που θα δώσουμε στη στήλη τιμών στο DataFrame

CATALOG = {

    # --- ΤΙΜΕΣ ---
    "dam_prices": {
        "label"        : "DAM Prices (EUR/MWh)",
        "group"        : "Τιμές",
        "method"       : "query_day_ahead_prices",
        "extra_params" : {},
        "value_col"    : "Price_EUR_MWh",
    },
    "intraday_prices": {
        "label"        : "Intraday Prices (EUR/MWh)",
        "group"        : "Τιμές",
        "method"       : "query_intraday_prices",
        "extra_params" : {"sequence": 1},
        "value_col"    : "Price_EUR_MWh",
    },
    "imbalance_prices": {
        "label"        : "Imbalance Prices (EUR/MWh)",
        "group"        : "Τιμές",
        "method"       : "query_imbalance_prices",
        "extra_params" : {},
        "value_col"    : "Price_EUR_MWh",
    },
    "afrr_contracted_prices": {
        "label"        : "aFRR Contracted Prices (EUR/MW)",
        "group"        : "Τιμές",
        "method"       : "query_contracted_reserve_prices",
        "extra_params" : {"process_type": "A51", "type_marketagreement_type": "A01"},
        "value_col"    : "Price_EUR_MW",
    },
    "mfrr_contracted_prices": {
        "label"        : "mFRR Contracted Prices (EUR/MW)",
        "group"        : "Τιμές",
        "method"       : "query_contracted_reserve_prices",
        "extra_params" : {"process_type": "A47", "type_marketagreement_type": "A01"},
        "value_col"    : "Price_EUR_MW",
    },
    "mfrr_activated_prices": {
        "label"        : "mFRR Activated Prices (EUR/MWh)",
        "group"        : "Τιμές",
        "method"       : "query_activated_balancing_energy_prices",
        "extra_params" : {"process_type": "A47"},
        "value_col"    : "Price_EUR_MWh",
    },

    # --- ΦΟΡΤΙΟ ---
    "actual_load": {
        "label"        : "Actual Load (MW)",
        "group"        : "Φορτίο",
        "method"       : "query_load",
        "extra_params" : {},
        "value_col"    : "Load_MW",
    },
    "load_forecast": {
        "label"        : "Load Forecast D-1 (MW)",
        "group"        : "Φορτίο",
        "method"       : "query_load_forecast",
        "extra_params" : {"process_type": "A01"},
        "value_col"    : "LoadForecast_MW",
    },

    # --- ΠΑΡΑΓΩΓΗ ---
    "generation_per_type": {
        "label"        : "Generation per Type (MW)",
        "group"        : "Παραγωγή",
        "method"       : "query_generation",
        "extra_params" : {},
        "value_col"    : "Generation_MW",
    },
    "wind_solar_forecast": {
        "label"        : "Wind & Solar Forecast (MW)",
        "group"        : "Παραγωγή",
        "method"       : "query_wind_and_solar_forecast",
        "extra_params" : {},
        "value_col"    : "Forecast_MW",
    },
    "installed_capacity": {
        "label"        : "Installed Capacity (MW)",
        "group"        : "Παραγωγή",
        "method"       : "query_installed_generation_capacity",
        "extra_params" : {},
        "value_col"    : "Capacity_MW",
    },

    # --- ΕΦΕΔΡΕΙΕΣ ---
    "fcr_contracted": {
        "label"        : "FCR Contracted (MW)",
        "group"        : "Εφεδρείες",
        "method"       : "query_contracted_reserve_amount",
        "extra_params" : {"process_type": "A52", "type_marketagreement_type": "A01"},
        "value_col"    : "Quantity_MW",
    },
    "afrr_contracted_qty": {
        "label"        : "aFRR Contracted Qty (MW)",
        "group"        : "Εφεδρείες",
        "method"       : "query_contracted_reserve_amount",
        "extra_params" : {"process_type": "A51", "type_marketagreement_type": "A01"},
        "value_col"    : "Quantity_MW",
    },
    "mfrr_activated_qty": {
        "label"        : "mFRR Activated Qty (MWh)",
        "group"        : "Εφεδρείες",
        "method"       : "query_activated_balancing_energy",
        "extra_params" : {"business_type": "A97"},
        "value_col"    : "Quantity_MWh",
    },

    # --- ΔΙΑΣΥΝΔΕΣΕΙΣ ---
    # Σημείωση: crossborder_flows και scheduled_exchanges χρειάζονται
    # χώρα προέλευσης ΚΑΙ χώρα προορισμού. Δεν υποστηρίζονται
    # στο τρέχον UI που επιλέγει μόνο 1 χώρα.
    # Αφαιρούνται προσωρινά για να μην μπερδεύει ο χρήστης.
}


# ============================================================
# COUNTRIES — Χώρες & country codes για entsoe-py
# ============================================================
# Η entsoe-py δέχεται απευθείας 2-γράμματους κωδικούς χωρών (ISO 3166-1)
# ή Area enums. Χρησιμοποιούμε strings για απλότητα.
# Για χώρες με πολλές bidding zones (π.χ. Νορβηγία, Δανία, Ιταλία, Σουηδία)
# χρησιμοποιούμε τους κωδικούς ζωνών που αναγνωρίζει η βιβλιοθήκη.

COUNTRIES = {
    "Albania"          : "AL",
    "Austria"          : "AT",
    "Belgium"          : "BE",
    "Bosnia & Herz."   : "BA",
    "Bulgaria"         : "BG",
    "Croatia"          : "HR",
    "Cyprus"           : "CY",
    "Czech Republic"   : "CZ",
    "Denmark (DK1)"    : "DK_1",
    "Denmark (DK2)"    : "DK_2",
    "Estonia"          : "EE",
    "Finland"          : "FI",
    "France"           : "FR",
    "Germany/Lux."     : "DE_LU",
    "Great Britain"    : "GB",
    "Greece"           : "GR",
    "Hungary"          : "HU",
    "Ireland (SEM)"    : "IE_SEM",
    "Italy (North)"    : "IT_NORTH",
    "Kosovo"           : "XK",
    "Latvia"           : "LV",
    "Lithuania"        : "LT",
    "Luxembourg"       : "LU",
    "Malta"            : "MT",
    "Moldova"          : "MD",
    "Montenegro"       : "ME",
    "Netherlands"      : "NL",
    "North Macedonia"  : "MK",
    "Norway (NO1)"     : "NO_1",
    "Norway (NO2)"     : "NO_2",
    "Poland"           : "PL",
    "Portugal"         : "PT",
    "Romania"          : "RO",
    "Serbia"           : "RS",
    "Slovakia"         : "SK",
    "Slovenia"         : "SI",
    "Spain"            : "ES",
    "Sweden (SE1)"     : "SE_1",
    "Sweden (SE2)"     : "SE_2",
    "Sweden (SE3)"     : "SE_3",
    "Sweden (SE4)"     : "SE_4",
    "Switzerland"      : "CH",
    "Turkey"           : "TR",
    "Ukraine"          : "UA",
}


# ============================================================
# ΒΟΗΘΗΤΙΚΕΣ ΣΥΝΑΡΤΗΣΕΙΣ
# ============================================================

def _make_timestamps(dt: datetime) -> pd.Timestamp:
    """
    Μετατρέπει datetime σε pd.Timestamp με timezone Ελλάδας.
    Η entsoe-py απαιτεί timezone-aware Timestamps.
    """
    if dt.tzinfo is None:
        return pd.Timestamp(dt, tz="Europe/Athens")
    # Αν έχει ήδη tzinfo (π.χ. UTC από το UI), κρατάμε ως έχει
    return pd.Timestamp(dt)


def _normalize_to_df(raw, value_col: str, country_name: str,
                     dataset_label: str) -> pd.DataFrame:
    """
    Μετατρέπει την έξοδο της entsoe-py (Series ή DataFrame) στο
    ομοιόμορφο format που περιμένει το υπόλοιπο σύστημα:

      Timestamp (UTC) | Timestamp (Local) | <value_col> | Country | Dataset
      (+ PsrType αν υπάρχει)

    Χειρίζεται:
      - Series: απλή χρονοσειρά (π.χ. DAM prices)
      - DataFrame με απλές στήλες (π.χ. actual load)
      - DataFrame με MultiIndex στήλες (π.χ. generation per type)
    """
    if raw is None or (hasattr(raw, 'empty') and raw.empty):
        return pd.DataFrame()

    rows = []

    # ── ΠΕΡΙΠΤΩΣΗ 1: Series (π.χ. DAM prices, intraday prices) ──
    if isinstance(raw, pd.Series):
        for ts, val in raw.items():
            if pd.isna(val):
                continue
            ts_utc   = ts.tz_convert("UTC").replace(tzinfo=None)
            ts_local = ts.tz_convert("Europe/Athens").replace(tzinfo=None)
            rows.append({
                "Timestamp (UTC)"   : ts_utc,
                "Timestamp (Local)" : ts_local,
                value_col           : float(val),
                "Country"           : country_name,
                "Dataset"           : dataset_label,
            })

    # ── ΠΕΡΙΠΤΩΣΗ 2: DataFrame ──
    elif isinstance(raw, pd.DataFrame):

        # MultiIndex columns (π.χ. generation_per_type):
        # στήλες: (B01, Actual Aggregated), (B16, Actual Aggregated), ...
        if isinstance(raw.columns, pd.MultiIndex):
            for ts, row_data in raw.iterrows():
                ts_utc   = ts.tz_convert("UTC").replace(tzinfo=None)
                ts_local = ts.tz_convert("Europe/Athens").replace(tzinfo=None)

                for (psr_type, sub_col), val in row_data.items():
                    # Κρατάμε μόνο "Actual Aggregated" (όχι "Actual Consumption")
                    if "Aggregated" not in str(sub_col):
                        continue
                    if pd.isna(val):
                        continue
                    rows.append({
                        "Timestamp (UTC)"   : ts_utc,
                        "Timestamp (Local)" : ts_local,
                        value_col           : float(val),
                        "Country"           : country_name,
                        "Dataset"           : dataset_label,
                        "PsrType"           : str(psr_type),
                    })

        else:
            # Απλό DataFrame — παίρνουμε την πρώτη αριθμητική στήλη ως τιμή
            numeric_cols = raw.select_dtypes(include="number").columns.tolist()
            if not numeric_cols:
                return pd.DataFrame()

            val_col = numeric_cols[0]

            for ts, row_data in raw.iterrows():
                val = row_data[val_col]
                if pd.isna(val):
                    continue
                ts_utc   = ts.tz_convert("UTC").replace(tzinfo=None)
                ts_local = ts.tz_convert("Europe/Athens").replace(tzinfo=None)
                rows.append({
                    "Timestamp (UTC)"   : ts_utc,
                    "Timestamp (Local)" : ts_local,
                    value_col           : float(val),
                    "Country"           : country_name,
                    "Dataset"           : dataset_label,
                })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.sort_values("Timestamp (UTC)", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def _query_single(client: EntsoePandasClient, ds_key: str,
                  country_code: str, start: pd.Timestamp,
                  end: pd.Timestamp):
    """
    Καλεί τη σωστή μέθοδο της entsoe-py για το dataset.
    Επιστρέφει το raw αποτέλεσμα (Series ή DataFrame) ή None αν δεν υπάρχουν δεδομένα.
    """
    ds     = CATALOG[ds_key]
    method = getattr(client, ds["method"])
    params = ds["extra_params"]

    try:
        return method(country_code, start=start, end=end, **params)
    except (NoMatchingDataError, InvalidBusinessParameterError):
        return None
    except Exception:
        return None


# ============================================================
# ΚΥΡΙΑ ΣΥΝΑΡΤΗΣΗ 1: get_data()
# ============================================================

def get_data(dataset_keys: list, country_names: list,
             dt_from: datetime, dt_to: datetime,
             api_token: str) -> dict[str, pd.DataFrame]:
    """
    Κύρια συνάρτηση — καλείται από το Streamlit UI.

    Κάνει query για κάθε συνδυασμό (dataset × χώρα) μέσω entsoe-py.
    Επιστρέφει λεξικό: { dataset_key: DataFrame με όλες τις χώρες }

    Η entsoe-py χειρίζεται αυτόματα:
      - Year limiting (σπάει >1 έτος σε chunks)
      - Rate limiting & retry
      - XML parsing
    """
    client = EntsoePandasClient(api_key=api_token)
    start  = _make_timestamps(dt_from)
    end    = _make_timestamps(dt_to + timedelta(days=1))  # exclusive upper bound

    results = {}

    for ds_key in dataset_keys:
        dfs = []

        for country in country_names:
            code = COUNTRIES.get(country)
            if not code:
                continue

            raw = _query_single(client, ds_key, code, start, end)
            df  = _normalize_to_df(
                raw,
                value_col    = CATALOG[ds_key]["value_col"],
                country_name = country,
                dataset_label= CATALOG[ds_key]["label"],
            )

            if not df.empty:
                dfs.append(df)

        results[ds_key] = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

    return results


# ============================================================
# ΚΥΡΙΑ ΣΥΝΑΡΤΗΣΗ 2: check_availability()
# ============================================================

def check_availability(dataset_keys: list, country_names: list,
                        dt_from: datetime, dt_to: datetime,
                        api_token: str) -> dict:
    """
    Ελέγχει διαθεσιμότητα δεδομένων για κάθε (dataset, χώρα).
    Επιστρέφει: { (dataset_key, country_name): "ok" | "partial" | "unavailable" }

    Κάνει δοκιμαστικό request μόνο για την πρώτη ημέρα (για ταχύτητα).
    """
    client        = EntsoePandasClient(api_key=api_token)
    start         = _make_timestamps(dt_from)
    end           = _make_timestamps(dt_from + timedelta(days=2))  # μόνο 1 ημέρα
    availability  = {}

    for ds_key in dataset_keys:
        for country in country_names:
            code = COUNTRIES.get(country)
            if not code:
                availability[(ds_key, country)] = "unavailable"
                continue

            raw = _query_single(client, ds_key, code, start, end)
            df  = _normalize_to_df(
                raw,
                value_col    = CATALOG[ds_key]["value_col"],
                country_name = country,
                dataset_label= CATALOG[ds_key]["label"],
            )

            if df.empty:
                availability[(ds_key, country)] = "unavailable"
            else:
                availability[(ds_key, country)] = "ok"

    return availability
