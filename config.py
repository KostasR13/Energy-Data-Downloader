"""
config.py
---------
Κεντρικές ρυθμίσεις εφαρμογής.

Το token διαβάζεται από τα Streamlit Secrets (για cloud deployment)
ή από μεταβλητή περιβάλλοντος (για τοπική χρήση).

Για τοπική χρήση: δες το αρχείο .streamlit/secrets.toml
"""

import streamlit as st
import os

# Διαβάζουμε το token με σειρά προτεραιότητας:
# 1. Streamlit Secrets (Streamlit Cloud)
# 2. Μεταβλητή περιβάλλοντος (προαιρετικά)
# 3. Fallback κενό string (θα δώσει error στο API — αναμενόμενο)
try:
    ENTSO_TOKEN = st.secrets["ENTSO_TOKEN"]
except Exception:
    ENTSO_TOKEN = os.environ.get("ENTSO_TOKEN", "")

APP_TITLE   = "Ενεργειακά Δεδομένα"
APP_VERSION = "0.1.0"
