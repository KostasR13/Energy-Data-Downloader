"""
admie_client.py
---------------
Επικοινωνία με το ΑΔΜΗΕ File API (www.admie.gr).
Χωρίς token — το API είναι ανοιχτό.

Η λογική είναι τριών βημάτων:
  1. get_filetypes()        : "Τι filetypes υπάρχουν;" → 74 filetypes
  2. get_file_list()        : "Τι αρχεία υπάρχουν για αυτό το filetype + ημερομηνίες;"
  3. download_file()        : "Κατέβασε ένα αρχείο" → DataFrame

  + get_data()             : κύρια συνάρτηση — τα συνδυάζει όλα (παράλληλο κατέβασμα)
  + check_availability()   : γρήγορος έλεγχος αν υπάρχουν δεδομένα
  + deduplicate_by_timestamp() : αφαίρεση διπλών εγγραφών ανά STARTDATE

Αλλαγές v2:
  - Endpoint: getOperationMarketFilewRange (με 'w') αντί για getOperationMarketFile
    → 1 request για οποιοδήποτε εύρος, χωρίς chunking
  - download_file(): ρητά engine openpyxl/xlrd, dayfirst=True για σωστό parsing
  - deduplicate_by_timestamp(): νέα συνάρτηση για αφαίρεση διπλών ανά STARTDATE
  - get_data(): παράλληλο κατέβασμα με ThreadPoolExecutor (5x ταχύτερο)
  - Metadata: χρήση file_path για file_name (το file_name ήταν κενό στο API)
"""

import requests
import pandas as pd
import io
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# ΣΤΑΘΕΡΕΣ
# ============================================================

BASE_URL = "https://www.admie.gr"

# Endpoints
ENDPOINT_FILETYPES = f"{BASE_URL}/getFiletypeInfoEN"
# FilewRange (με 'w'): βρίσκει αρχεία που επικαλύπτονται μερικώς ή ολικώς
# με το ζητούμενο εύρος — 1 request για οποιοδήποτε εύρος, χωρίς chunking
ENDPOINT_FILE_LIST = f"{BASE_URL}/getOperationMarketFilewRange"

# Παράλληλα downloads
MAX_WORKERS = 5

# Καθυστέρηση μεταξύ requests (ευγενική χρήση του API)
REQUEST_DELAY_SEC = 0.3

HEADERS = {
    "User-Agent" : (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept"          : "application/json, text/plain, */*",
    "Accept-Language" : "el-GR,el;q=0.9,en;q=0.8",
    "Referer"         : "https://www.admie.gr/",
}


# ============================================================
# ΒΗΜΑ 1: get_filetypes()
# ============================================================

def get_filetypes() -> pd.DataFrame:
    """
    Καλεί το getFiletypeInfoEN και επιστρέφει DataFrame με όλα τα filetypes.

    Κάθε γραμμή = ένα filetype, με στήλες:
      - filetype       : το όνομα (π.χ. "BalancingEnergyProduct")
      - process        : η κατηγορία (π.χ. "Balancing Market Settlement")
      - data_type      : σύντομη περιγραφή
      - period_covered : χρονική κάλυψη ("DAY", "WEEK", "MONTH", "YEAR")
    """
    try:
        response = requests.get(ENDPOINT_FILETYPES, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
        df   = pd.DataFrame(data)
        cols = ["filetype", "process", "data_type", "period_covered"]
        df   = df[[c for c in cols if c in df.columns]]
        return df
    except Exception as e:
        print(f"[admie_client] get_filetypes error: {e}")
        return pd.DataFrame(columns=["filetype", "process", "data_type", "period_covered"])


def get_filetypes_grouped() -> dict:
    """
    Επιστρέφει τα filetypes ομαδοποιημένα ανά process (για το UI).

    Επιστρέφει λεξικό:
      { "Balancing Market Settlement": ["BalancingEnergyProduct", ...], ... }
    """
    df = get_filetypes()
    if df.empty:
        return {}
    grouped = {}
    for process, group_df in df.groupby("process"):
        grouped[process] = group_df["filetype"].tolist()
    return grouped


# ============================================================
# ΒΗΜΑ 2: get_file_list()
# ============================================================

def get_file_list(filetype: str, date_from: str, date_to: str) -> list:
    """
    Καλεί το getOperationMarketFilewRange και επιστρέφει λίστα αρχείων.

    Το FilewRange (με 'w') βρίσκει αρχεία που επικαλύπτονται μερικώς ή
    ολικώς με το ζητούμενο εύρος. Αντίθετα με το παλιό getOperationMarketFile
    που απαιτούσε ακριβή ταύτιση και chunking (1 request ανά εβδομάδα),
    εδώ κάνουμε 1 μόνο request για οποιοδήποτε εύρος.

    Παράδειγμα: 1/1/2024 → 31/12/2024 → 1 request → όλα τα αρχεία
    """
    params = {
        "dateStart"    : date_from,
        "dateEnd"      : date_to,
        "FileCategory" : filetype,
    }
    try:
        time.sleep(REQUEST_DELAY_SEC)
        response = requests.get(ENDPOINT_FILE_LIST, params=params, headers=HEADERS, timeout=15)
        response.raise_for_status()
        files = response.json()
        return files if isinstance(files, list) else []
    except Exception as e:
        print(f"[admie_client] get_file_list error ({filetype} {date_from}->{date_to}): {e}")
        return []


# ============================================================
# ΒΗΜΑ 3: download_file()
# ============================================================

def download_file(file_info: dict) -> pd.DataFrame:
    """
    Κατεβάζει ένα αρχείο από το URL που έδωσε το βήμα 2.
    Καλείται παράλληλα από το ThreadPoolExecutor στο get_data().

    Αναγνωρίζει αυτόματα αν είναι .xlsx (openpyxl) ή .xls (xlrd).
    Χρησιμοποιεί dayfirst=True για σωστό parsing ημερομηνιών DD/MM/YYYY.

    Παράμετρος:
      file_info : dict από το βήμα 2 (περιέχει file_path, file_fromdate κτλ.)
    """
    file_url  = file_info.get("file_path", "")
    # Το API επιστρέφει κενό file_name — παίρνουμε το όνομα από το URL
    file_name = file_url.split("/")[-1] if file_url else "unknown"

    if not file_url:
        return pd.DataFrame()

    try:
        time.sleep(REQUEST_DELAY_SEC)
        response = requests.get(file_url, headers=HEADERS, timeout=30)
        response.raise_for_status()

        content    = io.BytesIO(response.content)
        name_lower = file_name.lower()

        # Ρητή επιλογή engine ανά τύπο αρχείου
        if name_lower.endswith(".xlsx"):
            df = pd.read_excel(content, engine="openpyxl")
        elif name_lower.endswith(".xls"):
            df = pd.read_excel(content, engine="xlrd")
        elif name_lower.endswith(".csv"):
            df = pd.read_csv(content, sep=None, engine="python")
        else:
            try:
                df = pd.read_excel(content, engine="openpyxl")
            except Exception:
                content.seek(0)
                try:
                    df = pd.read_excel(content, engine="xlrd")
                except Exception:
                    content.seek(0)
                    df = pd.read_csv(content, sep=None, engine="python")

        if df.empty:
            return pd.DataFrame()

        # Μετατροπή STARTDATE/ENDDATE σε datetime
        # dayfirst=True: η μορφή είναι DD/MM/YYYY (ευρωπαϊκή σύμβαση ΑΔΜΗΕ)
        # Χωρίς αυτό το pandas μαντεύει λάθος: "01/11/2020" → 11 Ιανουαρίου
        for col in ("STARTDATE", "ENDDATE"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

        # Προσθέτουμε μεταδεδομένα πηγής
        df.insert(0, "file_name",   file_name)
        df.insert(1, "period_from", file_info.get("file_fromdate", ""))
        df.insert(2, "period_to",   file_info.get("file_todate", ""))
        df.insert(3, "published",   file_info.get("file_published", ""))

        return df

    except Exception as e:
        print(f"[admie_client] download_file error ({file_name}): {e}")
        return pd.DataFrame()


# ============================================================
# ΑΦΑΙΡΕΣΗ ΔΙΠΛΩΝ: deduplicate_by_timestamp()
# ============================================================

def deduplicate_by_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    """
    Αφαιρεί διπλές (ή τριπλές κτλ.) εγγραφές ανά STARTDATE.

    Γιατί χρειάζεται:
      Το API επιστρέφει ΟΛΕΣ τις εκδόσεις ενός αρχείου —
      αρχικές, αναθεωρήσεις (Recalc_), νέες μορφές κτλ.
      Αυτές έχουν επικαλυπτόμενες περιόδους στα metadata,
      οπότε δεν αρκεί φιλτράρισμα ανά period_from/to.
      Εδώ κρατάμε για κάθε STARTDATE μόνο την εγγραφή
      από το αρχείο με το πιο πρόσφατο 'published'.

    Παράδειγμα:
      20201026_IMBABE_01.xlsx  (published: 30/01/2023) → περιέχει 01/11/2020
      Recalc_..._20201101.xlsx (published: 31/12/2020) → περιέχει 01/11/2020
      → Κρατάμε από το 20201026_IMBABE (νεότερο published)

    Αν δεν υπάρχει στήλη STARTDATE (κάποια filetypes), επιστρέφει αναλλοίωτο.
    """
    if df.empty or "STARTDATE" not in df.columns:
        return df

    df = df.copy()

    # Μετατρέπουμε published σε datetime για σωστή σύγκριση
    df["_pub_dt"] = pd.to_datetime(
        df["published"], format="%d.%m.%Y %H:%M", errors="coerce"
    )

    # Βεβαιωνόμαστε ότι STARTDATE είναι datetime
    df["STARTDATE"] = pd.to_datetime(df["STARTDATE"], dayfirst=True, errors="coerce")

    # Ταξινόμηση: παλαιότερο published πρώτα
    df = df.sort_values(["STARTDATE", "_pub_dt"])

    # Για κάθε STARTDATE κρατάμε μόνο την τελευταία εγγραφή (νεότερο published)
    # keep="last" λειτουργεί για διπλές, τριπλές, οποιοδήποτε πλήθος
    df = df.drop_duplicates(subset=["STARTDATE"], keep="last")

    # Καθαρισμός και τελική ταξινόμηση
    df = df.drop(columns=["_pub_dt"])
    df = df.sort_values("STARTDATE")
    df = df.reset_index(drop=True)

    return df


# ============================================================
# ΚΥΡΙΑ ΣΥΝΑΡΤΗΣΗ: get_data()
# ============================================================

def get_data(filetype_keys: list, date_from: str, date_to: str) -> dict:
    """
    Κύρια συνάρτηση — καλείται από το Streamlit UI.

    Για κάθε filetype:
      1. Ζητά τη λίστα αρχείων (βήμα 2)
      2. Κατεβάζει παράλληλα κάθε αρχείο (βήμα 3)
      3. Συνδυάζει όλα τα DataFrames
      4. Αφαιρεί διπλές εγγραφές ανά STARTDATE

    Παράμετροι:
      filetype_keys : λίστα από filetype strings
      date_from     : "YYYY-MM-DD"
      date_to       : "YYYY-MM-DD"

    Επιστρέφει:
      { "BalancingEnergyProduct": DataFrame, "IMBABE": DataFrame, ... }
    """
    results = {}

    for filetype in filetype_keys:

        # Βήμα 2: Λίστα αρχείων
        files = get_file_list(filetype, date_from, date_to)

        if not files:
            results[filetype] = pd.DataFrame()
            continue

        # Βήμα 3: Παράλληλο κατέβασμα
        dfs = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(download_file, f): f for f in files}
            for future in as_completed(futures):
                df = future.result()
                if not df.empty:
                    dfs.append(df)

        if not dfs:
            results[filetype] = pd.DataFrame()
            continue

        # Βήμα 4: Συνένωση και αφαίρεση διπλών
        combined = pd.concat(dfs, ignore_index=True)
        combined = deduplicate_by_timestamp(combined)

        results[filetype] = combined

    return results


# ============================================================
# ΕΛΕΓΧΟΣ ΔΙΑΘΕΣΙΜΟΤΗΤΑΣ: check_availability()
# ============================================================

def check_availability(filetype_keys: list, date_from: str, date_to: str) -> dict:
    """
    Ελέγχει αν υπάρχουν αρχεία για κάθε filetype στο δοθέν εύρος.
    ΔΕΝ κατεβάζει τα αρχεία — μόνο ελέγχει αν υπάρχουν (βήμα 2 μόνο).

    Επιστρέφει:
      { "BalancingEnergyProduct": {"status": "ok", "count": 55},
        "IMBABE": {"status": "unavailable", "count": 0}, ... }
    """
    availability = {}

    for filetype in filetype_keys:
        files = get_file_list(filetype, date_from, date_to)

        if files:
            availability[filetype] = {
                "status" : "ok",
                "count"  : len(files),
            }
        else:
            availability[filetype] = {
                "status" : "unavailable",
                "count"  : 0,
            }

    return availability
