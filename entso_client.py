"""
entso_client.py
---------------
Επικοινωνία με το ENTSO-E Transparency Platform REST API.
Περιέχει:
  - CATALOG          : λεξικό με όλα τα διαθέσιμα datasets
  - COUNTRIES        : λεξικό χωρών → EIC code
  - fetch()          : κάνει το HTTP request και επιστρέφει XML
  - parse()          : μετατρέπει το XML σε pandas DataFrame
  - get_data()       : συνδυάζει fetch + parse (κύρια συνάρτηση)
  - check_availability() : ελέγχει αν υπάρχουν δεδομένα για χώρα/dataset
"""

import re
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime, timezone, timedelta
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
#   "annual"       : (προαιρετικό) True αν το dataset επιστρέφει ετήσια δεδομένα
#                    → το periodStart/End θα snapαριστεί αυτόματα σε αρχή/τέλος έτους

CATALOG = {

    # --- ΤΙΜΕΣ ---
    "dam_prices": {
        "label"        : "DAM Prices (EUR/MWh)",
        "group"        : "Τιμές",
        "documentType" : "A44",   # Price Document
        "processType"  : "A01",   # Day Ahead
        "domain_param" : "in_Domain",
        "domain_param2": "out_Domain",   # DAM Prices χρειάζεται και τα 2
        "value_col"    : "Price_EUR_MWh",
    },
    "intraday_prices": {
        "label"        : "Intraday Prices (EUR/MWh)",
        "group"        : "Τιμές",
        "documentType" : "A44",
        "processType"  : "A18",   # Intraday total
        "domain_param" : "in_Domain",
        "domain_param2": "out_Domain",
        "value_col"    : "Price_EUR_MWh",
    },
    "imbalance_prices": {
        "label"        : "Imbalance Prices (EUR/MWh)",
        "group"        : "Τιμές",
        "documentType" : "A85",   # Imbalance prices
        "processType"  : "A16",   # Realised
        "domain_param" : "controlArea_Domain",
        "value_col"    : "Price_EUR_MWh",
    },
    "afrr_contracted_prices": {
        "label"        : "aFRR Contracted Prices (EUR/MW)",
        "group"        : "Τιμές",
        "documentType" : "A89",   # Contracted reserve prices
        "processType"  : "A51",   # aFRR
        "domain_param" : "controlArea_Domain",
        "value_col"    : "Price_EUR_MW",
    },
    "mfrr_contracted_prices": {
        "label"        : "mFRR Contracted Prices (EUR/MW)",
        "group"        : "Τιμές",
        "documentType" : "A89",
        "processType"  : "A47",   # mFRR
        "domain_param" : "controlArea_Domain",
        "value_col"    : "Price_EUR_MW",
    },
    "mfrr_activated_prices": {
        "label"        : "mFRR Activated Prices (EUR/MWh)",
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
        "documentType" : "A71",   # Generation installed capacity per type
        "processType"  : "A33",   # Year Ahead
        "domain_param" : "in_Domain",
        "value_col"    : "Capacity_MW",
        "annual"       : True,    # Επιστρέφει ετήσια δεδομένα — το periodStart/End
                                  # snap-αρεται αυτόματα σε αρχή/τέλος έτους στο fetch()
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
        "processType"  : "A16",   # Realised
        "domain_param" : "in_Domain",
        "domain_param2": "out_Domain",  # Απαιτείται για bilateral flows
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
# Χρησιμοποιούμε τους κωδικούς BZN (Bidding Zone) για τιμές/φορτίο
# και CTA (Control Area) για reserves/imbalance.
# Όλοι οι κωδικοί είναι 16 χαρακτήρες.

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
    Παράδειγμα: datetime(2024,6,1,0,0) → "202405312100" (UTC+3 καλοκαίρι)

    Γιατί χρειάζεται: το API δέχεται ΠΑΝΤΑ UTC, ο χρήστης βλέπει τοπική ώρα.
    Αν το datetime έχει ήδη tzinfo (π.χ. αν ο χρήστης επέλεξε UTC),
    χρησιμοποιείται ως έχει χωρίς επιπλέον μετατροπή.
    """
    if dt_local.tzinfo is None:
        dt_local = LOCAL_TZ.localize(dt_local)
    dt_utc = dt_local.astimezone(pytz.utc)
    return dt_utc.strftime("%Y%m%d%H%M")


def _snap_to_year(dt_from: datetime, dt_to: datetime):
    """
    Για datasets με ετήσια ανάλυση (installed_capacity),
    το ENTSO-E API απαιτεί periodStart/End να καλύπτουν ολόκληρα έτη.
    Επιστρέφει (snap_from, snap_to) που καλύπτουν ΟΛΟΚΛΗΡΑ τα έτη
    από dt_from.year έως dt_to.year.
    """
    year_from = dt_from.year
    year_to   = dt_to.year if dt_to > dt_from else dt_from.year

    snap_from = datetime(year_from, 1, 1, 0, 0)
    snap_to   = datetime(year_to + 1, 1, 1, 0, 0)
    return snap_from, snap_to


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
      dt_from     : ημερομηνία έναρξης (datetime) — περνιέται ΩΣ ΕΧΕΙ
      dt_to       : ημερομηνία λήξης   (datetime) — περνιέται ΩΣ ΕΧΕΙ
      api_token   : το προσωπικό token του χρήστη

    Σημείωση: το +1 ημέρα (exclusive upper bound) γίνεται στο get_data()
    ΠΡΙΝ καλέσει το fetch(), ώστε το check_availability() να μπορεί
    να καλεί fetch() απευθείας χωρίς ανεπιθύμητη μετατόπιση.
    """
    ds = CATALOG[dataset_key]

    # Για ετήσια datasets, snap-άρουμε σε αρχή/τέλος έτους
    if ds.get("annual"):
        dt_from, dt_to = _snap_to_year(dt_from, dt_to)

    params = {
        "securityToken" : api_token,
        "documentType"  : ds["documentType"],
        "processType"   : ds["processType"],
        ds["domain_param"] : eic_code,
        "periodStart"   : to_utc_str(dt_from),
        "periodEnd"     : to_utc_str(dt_to),
    }

    # Ορισμένα datasets χρειάζονται δεύτερο domain parameter (π.χ. DAM, cross-border)
    if "domain_param2" in ds:
        params[ds["domain_param2"]] = eic_code

    # Μικρή αναμονή ώστε να μην ξεπεράσουμε το rate limit (max 400 req/min)
    time.sleep(REQUEST_DELAY_SEC)

    response = requests.get(BASE_URL, params=params, timeout=30)
    
    print(f"[DEBUG] {dataset_key} | HTTP {response.status_code}")
    print(f"[DEBUG] URL: {response.url}")
    print(f"[DEBUG] BODY: {response.text[:500]}")
    
    return response


# ============================================================
# ΚΥΡΙΑ ΣΥΝΑΡΤΗΣΗ 2: parse()
# ============================================================

def parse(response: requests.Response, dataset_key: str,
          country_name: str) -> pd.DataFrame:
    """
    Μετατρέπει XML απάντηση του ENTSO-E σε pandas DataFrame.

    Επιστρέφει DataFrame με στήλες:
      - Timestamp (UTC)   : χρόνος σε UTC (naive datetime, χωρίς tzinfo)
      - Timestamp (Local) : χρόνος σε τοπική ώρα Ελλάδας (naive datetime)
      - <value_col>       : π.χ. Load_MW, Price_EUR_MWh κ.λπ.
      - Country           : όνομα χώρας
      - Dataset           : label dataset
      - PsrType           : (μόνο για generation datasets) κωδικός τεχνολογίας

    Αν δεν υπάρχουν δεδομένα ή συμβεί σφάλμα, επιστρέφει κενό DataFrame.
    """
    ds        = CATALOG[dataset_key]
    value_col = ds["value_col"]

    if response.status_code != 200:
        return pd.DataFrame()

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        return pd.DataFrame()

    # Ανίχνευση XML namespace αυτόματα
    # Παράδειγμα root tag: {urn:iec62325.351:tc57wg16:451-6:...}GL_MarketDocument
    ns        = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    ns_prefix = f"{{{ns}}}" if ns else ""

    # Έλεγχος αν το API επέστρεψε Acknowledgement (error) αντί για δεδομένα
    # Συμβαίνει όταν δεν υπάρχουν δεδομένα: status code 200 αλλά XML με <Reason>
    reason_elem = root.find(f".//{ns_prefix}Reason/{ns_prefix}text")
    if reason_elem is not None:
        return pd.DataFrame()

    rows = []

    for ts in root.findall(f"{ns_prefix}TimeSeries"):

        # PsrType: κωδικός τεχνολογίας — π.χ. "B16" (Solar), "B01" (Biomass)
        # Υπάρχει μόνο στα generation datasets
        psr_type = None
        psr_elem = ts.find(f".//{ns_prefix}psrType")
        if psr_elem is not None:
            psr_type = psr_elem.text

        # curveType: A01 = Fixed (κάθε position πάντα υπάρχει)
        #            A03 = Variable (γράφεται μόνο όταν αλλάζει → forward-fill)
        curve_elem = ts.find(f"{ns_prefix}curveType")
        curve_type = curve_elem.text if curve_elem is not None else "A01"

        for period in ts.findall(f"{ns_prefix}Period"):

            # Αρχή περιόδου
            start_elem = period.find(f"{ns_prefix}timeInterval/{ns_prefix}start")
            if start_elem is None:
                continue
            start_utc = datetime.strptime(start_elem.text, "%Y-%m-%dT%H:%MZ")
            start_utc = start_utc.replace(tzinfo=timezone.utc)

            # Resolution
            res_elem       = period.find(f"{ns_prefix}resolution")
            resolution_min = _parse_resolution(
                res_elem.text if res_elem is not None else "PT60M"
            )

            # Τέλος περιόδου — FIX: αν λείπει, το παραλείπουμε (δεν κρασάρουμε)
            end_elem = period.find(f"{ns_prefix}timeInterval/{ns_prefix}end")
            if end_elem is None:
                continue
            end_utc = datetime.strptime(end_elem.text, "%Y-%m-%dT%H:%MZ")
            end_utc = end_utc.replace(tzinfo=timezone.utc)

            total_minutes   = int((end_utc - start_utc).total_seconds() / 60)
            total_positions = total_minutes // resolution_min

            if total_positions <= 0:
                continue

            # Διαβάζουμε τα Points σε λεξικό {position: τιμή}
            points_in_xml = {}
            for point in period.findall(f"{ns_prefix}Point"):
                pos_elem = point.find(f"{ns_prefix}position")

                # Ψάχνουμε για "price.amount" ή "quantity" με loop
                # (ET.find() δεν χειρίζεται αξιόπιστα την τελεία στο "price.amount")
                val_elem = None
                for child in point:
                    local_tag = child.tag.split("}")[-1]
                    if local_tag in ("price.amount", "quantity"):
                        val_elem = child
                        break

                if pos_elem is None or val_elem is None:
                    continue

                try:
                    points_in_xml[int(pos_elem.text)] = float(val_elem.text)
                except (ValueError, TypeError):
                    continue

            # Forward-fill για A03 (Variable curve):
            # Διατρέχουμε ΟΛΕΣ τις positions, όχι μόνο αυτές που υπάρχουν στο XML
            last_val = None
            for pos in range(1, total_positions + 1):

                if pos in points_in_xml:
                    last_val = points_in_xml[pos]
                elif curve_type == "A03":
                    pass        # last_val κρατά την προηγούμενη τιμή (forward-fill)
                else:
                    last_val = None   # A01: πραγματικά missing

                if last_val is None:
                    continue

                offset_minutes = (pos - 1) * resolution_min
                ts_utc   = start_utc + pd.Timedelta(minutes=offset_minutes)
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


# ============================================================
# ΒΟΗΘΗΤΙΚΗ ΣΥΝΑΡΤΗΣΗ: _parse_resolution()
# ============================================================

def _parse_resolution(res_str: str) -> int:
    """
    Μετατρέπει ISO 8601 duration string σε λεπτά.
    Παραδείγματα: "PT60M"→60, "PT1H"→60, "PT15M"→15, "P1D"→1440, "P1Y"→525600
    """
    res_str = res_str.strip()
    _map = {
        "PT15M" : 15,
        "PT30M" : 30,
        "PT45M" : 45,
        "PT60M" : 60,
        "PT1H"  : 60,
        "P1D"   : 1440,
        "P7D"   : 10080,
        "P1M"   : 43200,    # προσέγγιση (~30 ημέρες)
        "P1Y"   : 525600,   # προσέγγιση (~365 ημέρες)
    }
    if res_str in _map:
        return _map[res_str]

    # Γενική περίπτωση: PTxxM
    m = re.search(r"PT(\d+)M", res_str)
    if m:
        return int(m.group(1))

    # Fallback
    return 60


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

    Best-effort λογική: αν μια χώρα δεν έχει δεδομένα για ένα dataset,
    απλώς δεν εμφανίζεται στο αποτέλεσμα — δεν κρασάρει.

    Σημείωση για dt_to:
    Το ENTSO-E API χρησιμοποιεί exclusive upper bound. Για να
    συμπεριληφθεί ολόκληρη η ημέρα dt_to, προσθέτουμε +1 ημέρα
    πριν το fetch(). Αυτό γίνεται ΜΟΝΟ εδώ — το check_availability()
    δεν το χρειάζεται γιατί ελέγχει ούτως ή άλλως dt_from+1day.
    """
    results = {}

    # +1 ημέρα: ο χρήστης επιλέγει "Έως 20/05" και εννοεί να
    # συμπεριληφθεί η 20η. Χωρίς αυτό, η τελευταία ημέρα κόβεται
    # λόγω UTC offset (π.χ. 20/05 00:00 Athens = 19/05 21:00 UTC).
    dt_to_api = dt_to + timedelta(days=1)

    for ds_key in dataset_keys:
        dfs = []

        for country in country_names:
            eic = COUNTRIES.get(country)
            if not eic:
                continue

            resp = fetch(ds_key, eic, dt_from, dt_to_api, api_token)
            try:
                df = parse(resp, ds_key, country)
            except Exception:
                df = pd.DataFrame()

            if not df.empty:
                dfs.append(df)

        results[ds_key] = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

    return results


# ============================================================
# ΚΥΡΙΑ ΣΥΝΑΡΤΗΣΗ 4: check_availability()
# ============================================================

def check_availability(dataset_keys: list, country_names: list,
                        dt_from: datetime, dt_to: datetime,
                        api_token: str) -> dict:
    """
    Ελέγχει διαθεσιμότητα δεδομένων για κάθε (dataset, χώρα).
    Επιστρέφει: { (dataset_key, country_name): "ok" | "partial" | "unavailable" }

    Κάνει ένα δοκιμαστικό request μόνο για την πρώτη ημέρα (για ταχύτητα).
    """
    availability  = {}
    dt_check_end  = dt_from + timedelta(days=1)

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
                    availability[(ds_key, country)] = "ok" if not df.empty else "partial"
                except Exception:
                    availability[(ds_key, country)] = "unavailable"
            else:
                availability[(ds_key, country)] = "unavailable"

    return availability
