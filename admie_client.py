"""
admie_client.py
---------------
Επικοινωνία με το ΑΔΜΗΕ File API (www.admie.gr).
Χωρίς token — το API είναι ανοιχτό.

Η λογική είναι τριβήματος (3 βήματα):
  1. get_filetypes()        : "Τι filetypes υπάρχουν;" → λεξικό με 74 filetypes
  2. get_file_list()        : "Τι αρχεία υπάρχουν για αυτό το filetype + ημερομηνίες;"
  3. download_file()        : "Κατέβασε ένα αρχείο" → DataFrame

  + get_data()             : κύρια συνάρτηση — τα συνδυάζει όλα
  + check_availability()   : γρήγορος έλεγχος αν υπάρχουν δεδομένα
"""

import requests
import pandas as pd
import io
import time


# ============================================================
# ΣΤΑΘΕΡΕΣ
# ============================================================

BASE_URL = "https://www.admie.gr"

# Endpoints — τα 3 "σημεία επαφής" με το API
ENDPOINT_FILETYPES  = f"{BASE_URL}/getFiletypeInfoEN"           # βήμα 1
ENDPOINT_FILE_LIST  = f"{BASE_URL}/getOperationMarketFilewRange" # βήμα 2
# Χρησιμοποιούμε το FilewRange (με 'w') αντί για το getOperationMarketFile.
# Διαφορά: το FilewRange βρίσκει αρχεία που επικαλύπτονται ΜΕΡΙΚΩΣ ή ΟΛΙΚΩΣ
# με το ζητούμενο εύρος — χωρίς chunking, με 1 μόνο request για οποιοδήποτε εύρος.
# βήμα 3: το URL του αρχείου επιστρέφεται από το βήμα 2 (πεδίο "file_path")

# Καθυστέρηση μεταξύ requests (ευγενική χρήση του API)
REQUEST_DELAY_SEC = 0.3

# Το admie.gr μπλοκάρει requests χωρίς browser-like headers (επιστρέφει 403).
# Προσθέτουμε User-Agent και Referer για να μοιάζουμε με κανονικό browser.
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

    Αυτό καλείται μία φορά κατά την εκκίνηση της εφαρμογής.
    """
    try:
        response = requests.get(ENDPOINT_FILETYPES, headers=HEADERS, timeout=15)
        response.raise_for_status()   # πετάει exception αν status != 200

        data = response.json()        # JSON → Python list of dicts (αυτόματα!)

        df = pd.DataFrame(data)

        # Κρατάμε μόνο τις στήλες που μας χρειάζονται
        cols = ["filetype", "process", "data_type", "period_covered"]
        df = df[[c for c in cols if c in df.columns]]

        return df

    except Exception as e:
        # Αν αποτύχει, επιστρέφουμε κενό DataFrame — best-effort λογική
        print(f"[admie_client] get_filetypes error: {e}")
        return pd.DataFrame(columns=["filetype", "process", "data_type", "period_covered"])


def get_filetypes_grouped() -> dict:
    """
    Επιστρέφει τα filetypes ομαδοποιημένα ανά process (για το UI).
    
    Επιστρέφει λεξικό:
      { "Balancing Market Settlement": ["BalancingEnergyProduct", ...],
        "Day Ahead Market": [...],
        ... }
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
    ολικώς με το ζητούμενο εύρος ημερομηνιών. Αντίθετα με το παλιό
    getOperationMarketFile που απαιτούσε ακριβή ταύτιση και chunking
    (1 request ανά εβδομάδα), εδώ κάνουμε 1 μόνο request για οποιοδήποτε
    εύρος — γρηγορότερο και πιο αξιόπιστο.

    Παράδειγμα: 1/1/2024 -> 31/12/2024 (365 μέρες)
    → 1 request → λίστα με όλα τα αρχεία
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

def download_file(file_url: str, file_name: str) -> pd.DataFrame:
    """
    Κατεβάζει ένα αρχείο από το URL που έδωσε το βήμα 2.
    Αναγνωρίζει αυτόματα αν είναι Excel ή CSV και επιστρέφει DataFrame.

    Παράμετροι:
      file_url  : το πλήρες URL του αρχείου (πεδίο "file_path" από βήμα 2)
      file_name : το όνομα αρχείου (για να ξέρουμε αν είναι .xlsx ή .csv)
    """
    try:
        time.sleep(REQUEST_DELAY_SEC)
        response = requests.get(file_url, headers=HEADERS, timeout=30)
        response.raise_for_status()

        content = io.BytesIO(response.content)   # περιεχόμενο σε μνήμη (δεν αποθηκεύεται στο δίσκο)
        name_lower = file_name.lower()

        # Αναγνώριση μορφής βάσει ονόματος αρχείου
        if name_lower.endswith(".xlsx") or name_lower.endswith(".xls"):
            df = pd.read_excel(content)
        elif name_lower.endswith(".csv"):
            df = pd.read_csv(content, sep=None, engine="python")
        else:
            # Αν δεν ξέρουμε τη μορφή, δοκιμάζουμε Excel πρώτα, μετά CSV
            try:
                df = pd.read_excel(content)
            except Exception:
                content.seek(0)   # επιστρέφουμε στην αρχή του buffer
                df = pd.read_csv(content, sep=None, engine="python")

        return df

    except Exception as e:
        print(f"[admie_client] download_file error ({file_name}): {e}")
        return pd.DataFrame()


# ============================================================
# ΚΥΡΙΑ ΣΥΝΑΡΤΗΣΗ: get_data()
# ============================================================

def get_data(filetype_keys: list, date_from: str, date_to: str) -> dict:
    """
    Κύρια συνάρτηση — καλείται από το Streamlit UI.

    Για κάθε filetype:
      1. Ζητά τη λίστα αρχείων (βήμα 2)
      2. Κατεβάζει κάθε αρχείο (βήμα 3)
      3. Συνδυάζει όλα τα DataFrames του ίδιου filetype

    Παράμετροι:
      filetype_keys : λίστα από filetype strings (π.χ. ["BalancingEnergyProduct", "IMBABE"])
      date_from     : "YYYY-MM-DD"
      date_to       : "YYYY-MM-DD"

    Επιστρέφει:
      { "BalancingEnergyProduct": DataFrame, "IMBABE": DataFrame, ... }
    """
    results = {}

    for filetype in filetype_keys:

        # Βήμα 2: Λίστα αρχείων για αυτό το filetype και αυτές τις ημερομηνίες
        files = get_file_list(filetype, date_from, date_to)

        if not files:
            # Δεν βρέθηκαν αρχεία — best-effort: συνεχίζουμε
            results[filetype] = pd.DataFrame()
            continue

        dfs = []   # μία λίστα DataFrames, ένα ανά αρχείο

        for file_info in files:
            file_url  = file_info.get("file_path", "")
            file_name = file_info.get("file_name", "unknown")

            if not file_url:
                continue

            # Βήμα 3: Κατέβασμα και ανάγνωση αρχείου
            df = download_file(file_url, file_name)

            if df.empty:
                continue

            # Προσθέτουμε πληροφορίες πηγής στο DataFrame
            df["source_file"]  = file_name
            df["date_start"]   = file_info.get("date_start", "")
            df["date_end"]     = file_info.get("date_end", "")

            dfs.append(df)

        # Συνδυάζουμε όλα τα αρχεία του ίδιου filetype σε ένα DataFrame
        if dfs:
            results[filetype] = pd.concat(dfs, ignore_index=True)
        else:
            results[filetype] = pd.DataFrame()

    return results


# ============================================================
# ΕΛΕΓΧΟΣ ΔΙΑΘΕΣΙΜΟΤΗΤΑΣ: check_availability()
# ============================================================

def check_availability(filetype_keys: list, date_from: str, date_to: str) -> dict:
    """
    Ελέγχει αν υπάρχουν αρχεία για κάθε filetype στο δοθέν εύρος ημερομηνιών.
    ΔΕΝ κατεβάζει τα αρχεία — μόνο ελέγχει αν υπάρχουν (βήμα 2 μόνο).

    Επιστρέφει:
      { "BalancingEnergyProduct": "ok" | "unavailable",
        "IMBABE": "ok" | "unavailable", ... }
    """
    availability = {}

    for filetype in filetype_keys:
        files = get_file_list(filetype, date_from, date_to)

        if files:
            # Μετράμε πόσα αρχεία βρέθηκαν (χρήσιμο για το UI)
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
