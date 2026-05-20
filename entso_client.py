"""
entso_client.py
---------------
Επικοινωνία με το ENTSO-E Transparency Platform REST API.
Περιέχει:
  - CATALOG   : λεξικό με όλα τα διαθέσιμα datasets
  - COUNTRIES  : λεξικό χωρών → EIC code
  - fetch()    : κάνει το HTTP request και επιστρέφει XML
  - parse()    : μετατρέπει το XML σε pandas DataFrame
  - get_data() : συνδυάζει fetch + parse (κύρια συνάρτηση)
  - check_availability() : ελέγχει αν υπάρχουν δεδομένα για χώρα/dataset
"""

import requests
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime, timezone
import pytz
import time


# ============================================================
# ΣΤΑΘΕΡΕΣ
# ============================================================

BASE_URL = "https://web-api.tp.entsoe.eu/api"

# Ζώνη ώρας Ελλάδας — αλλάζουμε μόνο εδώ αν χρειαστεί
LOCAL_TZ = pytz.timezone("Europe/Athens")

# Rate limit: max 400 requests/λεπτό. Βάζουμε μικρή καθυστέρηση για ασφάλεια.
REQUEST_DELAY_SEC = 0.2


# ============================================================
# CATALOG — Κατάλογος datasets
# ============================================================
# Κάθε dataset έχει:
#   "label"        : το όνομα που βλέπει ο χρήστης στο UI
#   "group"        : η ομάδα (για ομαδοποίηση στο UI)
#   "documentType" : παράμετρος API — "τι είδους δεδομένα"
#   "processType"  : παράμετρος API — "σε ποια αγορά/διαδικασία"
#   "domain_param" : ποιο πεδίο του API δέχεται τον EIC code της χώρας
#   "value_col"    : το όνομα που θα δώσουμε στη στήλη τιμών στο DataFrame

CATALOG = {

    # --- ΤΙΜΕΣ ---
    "dam_prices": {
        "label"        : "DAM Prices (€/MWh)",
        "group"        : "Τιμές",
        "documentType" : "A44",   # Price Document
        "processType"  : "A01",   # Day Ahead
        "domain_param" : "in_Domain",
        "domain_param2": "out_Domain",   # DAM Prices χρειάζεται και τα 2
        "value_col"    : "Price_EUR_MWh",
    },
    "intraday_prices": {
        "label"        : "Intraday Prices (€/MWh)",
        "group"        : "Τιμές",
        "documentType" : "A44",
        "processType"  : "A18",   # Intraday total
        "domain_param" : "in_Domain",
        "domain_param2": "out_Domain",   # ίδια λογική με DAM
        "value_col"    : "Price_EUR_MWh",
    },
    "imbalance_prices": {
        "label"        : "Imbalance Prices (€/MWh)",
        "group"        : "Τιμές",
        "documentType" : "A85",   # Imbalance prices
        "processType"  : "A16",   # Realised
        "domain_param" : "controlArea_Domain",
        "value_col"    : "Price_EUR_MWh",
    },
    "afrr_contracted_prices": {
        "label"        : "aFRR Contracted Prices (€/MW)",
        "group"        : "Τιμές",
        "documentType" : "A89",   # Contracted reserve prices
        "processType"  : "A51",   # aFRR
        "domain_param" : "controlArea_Domain",
        "value_col"    : "Price_EUR_MW",
    },
    "mfrr_contracted_prices": {
        "label"        : "mFRR Contracted Prices (€/MW)",
        "group"        : "Τιμές",
        "documentType" : "A89",
        "processType"  : "A47",   # mFRR
        "domain_param" : "controlArea_Domain",
        "value_col"    : "Price_EUR_MW",
    },
    "mfrr_activated_prices": {
        "label"        : "mFRR Activated Prices (€/MWh)",
        "group"        : "Τιμές",
        "documentType" : "A84",   # Activated balancing prices
        "processType"  : "A47",
        "domain_param" : "controlArea_Domain",
        "value_col"    : "Price_EUR_MWh",
    },

    # --- ΦΟΡΤΙΟ ---
    "actual_load": {
        "label"        : "Actual Load (MW)",
        "group"        : "Φορτίο",
        "documentType" : "A65",   # System total load
        "processType"  : "A16",   # Realised
        "domain_param" : "outBiddingZone_Domain",
        "value_col"    : "Load_MW",
    },
    "load_forecast": {
        "label"        : "Load Forecast D-1 (MW)",
        "group"        : "Φορτίο",
        "documentType" : "A65",
        "processType"  : "A01",   # Day Ahead
        "domain_param" : "outBiddingZone_Domain",
        "value_col"    : "LoadForecast_MW",
    },

    # --- ΠΑΡΑΓΩΓΗ ---
    "generation_per_type": {
        "label"        : "Generation per Type (MW)",
        "group"        : "Παραγωγή",
        "documentType" : "A75",   # Actual generation per type
        "processType"  : "A16",
        "domain_param" : "in_Domain",
        "value_col"    : "Generation_MW",
    },
    "wind_solar_forecast": {
        "label"        : "Wind & Solar Forecast (MW)",
        "group"        : "Παραγωγή",
        "documentType" : "A69",   # Wind and solar forecast
        "processType"  : "A01",
        "domain_param" : "in_Domain",
        "value_col"    : "Forecast_MW",
    },
    "installed_capacity": {
        "label"        : "Installed Capacity (MW)",
        "group"        : "Παραγωγή",
        "documentType" : "A71",   # Generation installed capacity
        "processType"  : "A33",   # Year Ahead
        "domain_param" : "in_Domain",
        "value_col"    : "Capacity_MW",
    },

    # --- ΕΦΕΔΡΕΙΕΣ ---
    "fcr_contracted": {
        "label"        : "FCR Contracted (MW)",
        "group"        : "Εφεδρείες",
        "documentType" : "A81",   # Contracted reserves
        "processType"  : "A52",   # FCR
        "domain_param" : "controlArea_Domain",
        "value_col"    : "Quantity_MW",
    },
    "afrr_contracted_qty": {
        "label"        : "aFRR Contracted Qty (MW)",
        "group"        : "Εφεδρείες",
        "documentType" : "A81",
        "processType"  : "A51",
        "domain_param" : "controlArea_Domain",
        "value_col"    : "Quantity_MW",
    },
    "mfrr_activated_qty": {
        "label"        : "mFRR Activated Qty (MWh)",
        "group"        : "Εφεδρείες",
        "documentType" : "A83",   # Activated balancing quantities
        "processType"  : "A47",
        "domain_param" : "controlArea_Domain",
        "value_col"    : "Quantity_MWh",
    },

    # --- ΔΙΑΣΥΝΔΕΣΕΙΣ ---
    "crossborder_flows": {
        "label"        : "Cross-border Flows (MW)",
        "group"        : "Διασυνδέσεις",
        "documentType" : "A11",   # Aggregated energy data report
        "processType"  : "A16",
        "domain_param" : "in_Domain",   # + out_Domain χρειάζεται — βλ. fetch()
        "value_col"    : "Flow_MW",
    },
    "scheduled_exchanges": {
        "label"        : "Scheduled Exchanges (MW)",
        "group"        : "Διασυνδέσεις",
        "documentType" : "A09",   # Finalised schedule
        "processType"  : "A01",
        "domain_param" : "in_Domain",
        "value_col"    : "Schedule_MW",
    },
}


# ============================================================
# COUNTRIES — Χώρες & EIC codes
# ============================================================
# EIC (Energy Identification Code) = ο μοναδικός κωδικός κάθε χώρας/ζώνης.
# Χρησιμοποιούμε τους κωδικούς BZN (Bidding Zone) όπου υπάρχουν.

COUNTRIES = {
    "Albania"          : "10YAL-KESH-----5",
    "Austria"          : "10YAT-APG------L",
    "Belgium"          : "10YBE----------2",
    "Bosnia & Herz."   : "10YBA-JPCC-----D",
    "Bulgaria"         : "10YCA-BULGARIA-R",
    "Croatia"          : "10YHR-HEP------M",
    "Cyprus"           : "10YCY-1001A0003J",
    "Czech Republic"   : "10YCZ-CEPS-----N",
    "Denmark (DK1)"    : "10YDK-1--------W",
    "Denmark (DK2)"    : "10YDK-2--------M",
    "Estonia"          : "10Y1001A1001A39I",
    "Finland"          : "10YFI-1--------U",
    "France"           : "10YFR-RTE------C",
    "Germany/Lux."     : "10Y1001A1001A82H",
    "Great Britain"    : "10YGB----------A",
    "Greece"           : "10YGR-HTSO-----Y",
    "Hungary"          : "10YHU-MAVIR----U",
    "Ireland (SEM)"    : "10Y1001A1001A59C",
    "Italy (North)"    : "10YIT-GRTN-----B",
    "Kosovo"           : "10Y1001C--00100H",
    "Latvia"           : "10YLV-1001A00074",
    "Lithuania"        : "10YLT-1001A0008Q",
    "Luxembourg"       : "10YLU-CEGEDEL-NQ",
    "Malta"            : "10Y1001A1001A93C",
    "Moldova"          : "10Y1001A1001A990",
    "Montenegro"       : "10YCS-CG-TSO---S",
    "Netherlands"      : "10YNL----------L",
    "North Macedonia"  : "10YMK-MEPSO----8",
    "Norway (NO1)"     : "10YNO-1--------2",
    "Norway (NO2)"     : "10YNO-2--------T",
    "Poland"           : "10YPL-AREA-----S",
    "Portugal"         : "10YPT-REN------W",
    "Romania"          : "10YRO-TEL------P",
    "Serbia"           : "10YCS-SERBIATSOV",
    "Slovakia"         : "10YSK-SEPS-----K",
    "Slovenia"         : "10YSI-ELES-----O",
    "Spain"            : "10YES-REE------0",
    "Sweden (SE1)"     : "10Y1001A1001A44P",
    "Sweden (SE2)"     : "10Y1001A1001A45N",
    "Sweden (SE3)"     : "10Y1001A1001A46L",
    "Sweden (SE4)"     : "10Y1001A1001A47J",
    "Switzerland"      : "10YCH-SWISSGRIDZ",
    "Turkey"           : "10YTR-TEIAS----W",
    "Ukraine"          : "10Y1001C--00003F",
}


# ============================================================
# ΒΟΗΘΗΤΙΚΗ ΣΥΝΑΡΤΗΣΗ: Μετατροπή ώρας
# ============================================================

def to_utc_str(dt_local: datetime) -> str:
    """
    Μετατρέπει ένα datetime (ώρα Ελλάδας) σε string UTC για το API.
    Παράδειγμα: datetime(2024,1,1,0,0) → "202401010000" (αφαίρεση 2 ή 3 ωρών)

    Γιατί χρειάζεται: το API δέχεται ΠΑΝΤΑ UTC, ο χρήστης βλέπει τοπική ώρα.
    """
    # Προσθέτουμε πληροφορία ζώνης ώρας στο datetime (αν δεν έχει ήδη)
    if dt_local.tzinfo is None:
        dt_local = LOCAL_TZ.localize(dt_local)

    # Μετατροπή σε UTC
    dt_utc = dt_local.astimezone(pytz.utc)

    # Επιστρέφουμε σε μορφή που θέλει το API: YYYYMMDDHHmm
    return dt_utc.strftime("%Y%m%d%H%M")


# ============================================================
# ΚΥΡΙΑ ΣΥΝΑΡΤΗΣΗ 1: fetch()
# ============================================================

def fetch(dataset_key: str, eic_code: str, dt_from: datetime, dt_to: datetime,
          api_token: str) -> requests.Response:
    """
    Στέλνει ένα GET request στο ENTSO-E API και επιστρέφει το Response object.

    Παράμετροι:
      dataset_key : κλειδί από το CATALOG (π.χ. "actual_load")
      eic_code    : EIC code της χώρας (π.χ. "10YGR-HTSO-----Y")
      dt_from     : ημερομηνία έναρξης (datetime, τοπική ώρα)
      dt_to       : ημερομηνία λήξης   (datetime, τοπική ώρα)
      api_token   : το προσωπικό token του χρήστη
    """
    # Παίρνουμε τις παραμέτρους του dataset από τον CATALOG
    ds = CATALOG[dataset_key]

    # Φτιάχνουμε το dictionary των παραμέτρων που θα σταλούν στο URL
    params = {
        "securityToken" : api_token,
        "documentType"  : ds["documentType"],
        "processType"   : ds["processType"],
        ds["domain_param"] : eic_code,   # το πεδίο διαφέρει ανά dataset
        "periodStart"   : to_utc_str(dt_from),
        "periodEnd"     : to_utc_str(dt_to),
    }

    # Ορισμένα datasets (π.χ. DAM Prices) χρειάζονται δεύτερο domain parameter
    # π.χ. in_Domain + out_Domain με τον ίδιο EIC code
    if "domain_param2" in ds:
        params[ds["domain_param2"]] = eic_code

    # Μικρή αναμονή ώστε να μην ξεπεράσουμε το rate limit
    time.sleep(REQUEST_DELAY_SEC)

    print(f"[DEBUG] {dataset_key} | status={response.status_code} | {response.text[:300]}")  
    # Αποστολή GET request — η βιβλιοθήκη requests φτιάχνει αυτόματα το URL
    response = requests.get(BASE_URL, params=params, timeout=30)

    return response


# ============================================================
# ΚΥΡΙΑ ΣΥΝΑΡΤΗΣΗ 2: parse()
# ============================================================

def parse(response: requests.Response, dataset_key: str,
          country_name: str) -> pd.DataFrame:
    """
    Μετατρέπει XML απάντηση του ENTSO-E σε pandas DataFrame.

    Επιστρέφει DataFrame με στήλες:
      - Timestamp (τοπική ώρα Ελλάδας)
      - <value_col>  (π.χ. Load_MW, Price_EUR_MWh κ.λπ.)
      - Country
      - Dataset
      - PsrType (μόνο αν υπάρχει — π.χ. για generation per type)

    Αν δεν υπάρχουν δεδομένα, επιστρέφει κενό DataFrame.
    """
    ds = CATALOG[dataset_key]
    value_col = ds["value_col"]

    # Έλεγχος HTTP status
    if response.status_code != 200:
        return pd.DataFrame()   # κενό DataFrame → best-effort λογική

    # Parse του XML — αν το API επιστρέψει μη έγκυρο XML (π.χ. error page),
    # επιστρέφουμε κενό DataFrame αντί να κρασάρουμε
    try:
        root = ET.fromstring(response.content)
    except Exception:
        return pd.DataFrame()

    # Το ENTSO-E API χρησιμοποιεί XML namespaces (π.χ. {urn:iec62325.351...}).
    # Πρέπει να τα ανιχνεύσουμε αυτόματα για να βρούμε τα σωστά tags.
    # Παράδειγμα: το root tag είναι {urn:iec62325.351:tc57wg16:451-6:...}GL_MarketDocument
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    ns_prefix = f"{{{ns}}}" if ns else ""

    rows = []

    # Διατρέχουμε όλα τα TimeSeries blocks (ένα ανά τύπο παραγωγής ή ανά κατεύθυνση)
    for ts in root.findall(f"{ns_prefix}TimeSeries"):

        # PsrType: υπάρχει μόνο στα generation datasets — π.χ. "B16" (Solar)
        psr_type = None
        psr_elem = ts.find(f".//{ns_prefix}psrType")
        if psr_elem is not None:
            psr_type = psr_elem.text

        # Διαβάζουμε το curveType του TimeSeries (A01 ή A03)
        # A01 = Fixed blocks: κάθε position υπάρχει πάντα στο XML
        # A03 = Variable blocks: γράφεται μόνο όταν αλλάζει η τιμή → χρειάζεται forward-fill
        curve_elem = ts.find(f"{ns_prefix}curveType")
        curve_type = curve_elem.text if curve_elem is not None else "A01"

        # Κάθε TimeSeries έχει ένα ή περισσότερα Period blocks
        for period in ts.findall(f"{ns_prefix}Period"):

            # Βρίσκουμε την αρχή της χρονικής περιόδου
            start_elem = period.find(f"{ns_prefix}timeInterval/{ns_prefix}start")
            if start_elem is None:
                continue
            start_utc = datetime.strptime(start_elem.text, "%Y-%m-%dT%H:%MZ")
            start_utc = start_utc.replace(tzinfo=timezone.utc)

            # Resolution: πόση ώρα μεταξύ κάθε Point (π.χ. PT60M, PT15M)
            res_elem = period.find(f"{ns_prefix}resolution")
            resolution_min = _parse_resolution(res_elem.text if res_elem is not None else "PT60M")

            # Υπολογισμός συνολικών positions από το timeInterval
            # (χρειάζεται για το forward-fill του A03)
            end_elem = period.find(f"{ns_prefix}timeInterval/{ns_prefix}end")
            end_utc  = datetime.strptime(end_elem.text, "%Y-%m-%dT%H:%MZ")
            end_utc  = end_utc.replace(tzinfo=timezone.utc)
            total_minutes   = int((end_utc - start_utc).total_seconds() / 60)
            total_positions = total_minutes // resolution_min

            # Διαβάζουμε τα Points που υπάρχουν στο XML σε λεξικό {position: τιμή}
            points_in_xml = {}
            for point in period.findall(f"{ns_prefix}Point"):
                pos_elem = point.find(f"{ns_prefix}position")

                # Αναζήτηση τιμής — χρησιμοποιούμε loop αντί για find()
                # γιατί το ET.find() δεν χειρίζεται αξιόπιστα την τελεία στο "price.amount"
                val_elem = None
                for child in point:
                    local_tag = child.tag.split("}")[-1]
                    if local_tag in ("price.amount", "quantity"):
                        val_elem = child
                        break

                if pos_elem is None or val_elem is None:
                    continue

                points_in_xml[int(pos_elem.text)] = float(val_elem.text)

            # Διατρέχουμε ΟΛΑ τα positions (1 έως total_positions) με forward-fill:
            #   - αν το position υπάρχει στο XML → χρησιμοποίησέ το
            #   - αν ΔΕΝ υπάρχει και curveType=A03 → κράτα την προηγούμενη τιμή (forward-fill)
            #   - αν ΔΕΝ υπάρχει και curveType=A01 → πραγματικά missing, παράλειψε
            last_val = None
            for pos in range(1, total_positions + 1):

                if pos in points_in_xml:
                    last_val = points_in_xml[pos]
                elif curve_type == "A03":
                    pass   # last_val παραμένει η προηγούμενη τιμή
                else:
                    last_val = None   # A01: πραγματικά missing

                if last_val is None:
                    continue

                # Υπολογισμός timestamp: start + (position-1) * resolution
                offset_minutes = (pos - 1) * resolution_min
                ts_utc   = start_utc + pd.Timedelta(minutes=offset_minutes)

                # Μετατροπή UTC → τοπική ώρα για εμφάνιση
                ts_local = ts_utc.astimezone(LOCAL_TZ).replace(tzinfo=None)

                row = {
                    "Timestamp (UTC)"   : ts_utc.replace(tzinfo=None),
                    "Timestamp (Local)" : ts_local,
                    value_col           : last_val,
                    "Country"           : country_name,
                    "Dataset"           : ds["label"],
                }
                if psr_type:
                    row["PsrType"] = psr_type

                rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.sort_values("Timestamp (UTC)", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def _parse_resolution(res_str: str) -> int:
    """
    Μετατρέπει ISO 8601 duration string σε λεπτά.
    Παραδείγματα: "PT60M" → 60, "PT15M" → 15, "P1Y" → 525600
    """
    res_str = res_str.strip()
    if res_str == "PT60M" or res_str == "PT1H":
        return 60
    elif res_str == "PT30M":
        return 30
    elif res_str == "PT15M":
        return 15
    elif res_str == "P1D":
        return 1440
    elif res_str == "P7D":
        return 10080
    elif res_str == "P1M":
        return 43200   # προσέγγιση
    elif res_str == "P1Y":
        return 525600
    else:
        # Γενική περίπτωση: αναζητούμε αριθμό πριν το "M"
        import re
        m = re.search(r"(\d+)M", res_str)
        return int(m.group(1)) if m else 60


# ============================================================
# ΚΥΡΙΑ ΣΥΝΑΡΤΗΣΗ 3: get_data()
# ============================================================

def get_data(dataset_keys: list, country_names: list,
             dt_from: datetime, dt_to: datetime,
             api_token: str) -> dict[str, pd.DataFrame]:
    """
    Κύρια συνάρτηση — καλείται από το Streamlit UI.

    Κάνει fetch + parse για κάθε συνδυασμό (dataset × χώρα).
    Επιστρέφει λεξικό: { dataset_key: DataFrame με όλες τις χώρες }

    Η best-effort λογική εφαρμόζεται αυτόματα:
    αν μια χώρα δεν έχει δεδομένα, απλώς δεν εμφανίζεται στο DataFrame εκείνης.
    """
    results = {}   # dataset_key → DataFrame

    for ds_key in dataset_keys:
        dfs = []   # μία λίστα DataFrames, ένα ανά χώρα

        for country in country_names:
            eic = COUNTRIES.get(country)
            if not eic:
                continue   # άγνωστη χώρα — παράλειψη

            resp = fetch(ds_key, eic, dt_from, dt_to, api_token)
            try:
                df = parse(resp, ds_key, country)
            except Exception:
                df = pd.DataFrame()

            if not df.empty:
                dfs.append(df)

        # Συνδυάζουμε όλα τα DataFrames της ίδιας κατηγορίας
        if dfs:
            results[ds_key] = pd.concat(dfs, ignore_index=True)
        else:
            results[ds_key] = pd.DataFrame()   # κενό → best-effort

    return results


# ============================================================
# ΚΥΡΙΑ ΣΥΝΑΡΤΗΣΗ 4: check_availability()
# ============================================================

def check_availability(dataset_keys: list, country_names: list,
                        dt_from: datetime, dt_to: datetime,
                        api_token: str) -> dict:
    """
    Ελέγχει διαθεσιμότητα δεδομένων για κάθε (dataset, χώρα).
    Επιστρέφει λεξικό:
      { (dataset_key, country_name): "ok" | "partial" | "unavailable" }

    Χρησιμοποιείται για τον Πίνακα Διαθεσιμότητας στο UI.
    Κάνει ένα μικρό δοκιμαστικό request (μόνο 1 ημέρα) για ταχύτητα.
    """
    availability = {}

    # Ελέγχουμε μόνο την πρώτη ημέρα για ταχύτητα
    dt_check_end = dt_from + pd.Timedelta(days=1)

    for ds_key in dataset_keys:
        for country in country_names:
            eic = COUNTRIES.get(country)
            if not eic:
                availability[(ds_key, country)] = "unavailable"
                continue

            resp = fetch(ds_key, eic, dt_from, dt_check_end, api_token)

            if resp.status_code == 200:
                try:
                    df = parse(resp, ds_key, country)
                    if df.empty:
                        availability[(ds_key, country)] = "partial"
                    else:
                        availability[(ds_key, country)] = "ok"
                except Exception:
                    # Το API επέστρεψε 200 αλλά με μη έγκυρο XML
                    availability[(ds_key, country)] = "unavailable"
            else:
                availability[(ds_key, country)] = "unavailable"

    return availability
