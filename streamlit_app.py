import streamlit as st
import pandas as pd
import json, io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

st.set_page_config(page_title="Gestionare Fișe Proiecte", layout="wide")

# ---------- CONFIG ----------
# Se vor adăuga în st.secrets:
# - "gcp_service_account" : JSON string cu conținutul cheii (vezi instrucțiuni)
# - "drive_folder_id" : id-ul folderului din Drive
# (setează-le în Streamlit Cloud -> Settings -> Secrets)
FOLDER_ID = st.secrets.get("drive_folder_id", "")

@st.cache_data(ttl=300)
def init_drive_service():
    sa_json = st.secrets.get("gcp_service_account", None)
    if sa_json is None:
        st.error("Lipstă st.secrets['gcp_service_account'] - configurează cheia service account în Streamlit secrets.")
        st.stop()
    service_account_info = json.loads(sa_json)
    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
    drive_service = build("drive", "v3", credentials=creds)
    return drive_service

drive_service = init_drive_service()

# ---------- DRIVE helpers ----------
def list_files_in_folder(folder_id, mime_type=None):
    files = []
    page_token = None
    q = f"'{folder_id}' in parents and trashed=false"
    if mime_type:
        q += f" and mimeType='{mime_type}'"
    while True:
        res = drive_service.files().list(q=q, fields="nextPageToken, files(id,name,modifiedTime,mimeType)", pageToken=page_token).execute()
        files.extend(res.get('files', []))
        page_token = res.get('nextPageToken')
        if not page_token:
            break
    return files

def download_csv_file(file_id):
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    return pd.read_csv(fh)

# ---------- UI ----------
st.title("📑 Gestionare Fișe Proiecte (Hibrid)")

menu = st.sidebar.radio("Funcționalitate", [
    "1. Generare listă proiecte (citire CSV)",
    "2. Comisii de raport (din CSV)",
    "3. Verificare fișe Google Drive"
])

st.sidebar.markdown("---")
st.sidebar.write("Date din folder Drive:")
st.sidebar.write(FOLDER_ID or "❗ drive_folder_id nu este setat în secrets")

# ---------- 1. Lista proiecte ----------
if menu.startswith("1"):
    st.header("1. Generare / Vizualizare listă proiecte")
    st.write("Alege un fișier CSV (rezultatul scrapingului) din folderul Drive:")

    csv_files = list_files_in_folder(FOLDER_ID, mime_type="text/csv")
    if not csv_files:
        st.info("Nu s-au găsit fișiere CSV în folderul Drive.")
    else:
        # sort after modifiedTime desc
        csv_files = sorted(csv_files, key=lambda x: x.get('modifiedTime',''), reverse=True)
        options = [f"{f['name']}  —  ({f['modifiedTime']})" for f in csv_files]
        sel = st.selectbox("Alege fișier CSV", options)
        idx = options.index(sel)
        file_meta = csv_files[idx]
        df = download_csv_file(file_meta['id'])
        st.write(f"📄 Fișier: **{file_meta['name']}** — modificat: {file_meta['modifiedTime']}")
        st.dataframe(df, use_container_width=True)

        # export local download
        csv_bytes = df.to_csv(index=False).encode('utf-8')
        st.download_button("Descarcă CSV", csv_bytes, file_name=file_meta['name'], mime="text/csv")

        # lista simplificata (numere proiect)
        st.subheader("Listă simplificată (numere identificare)")
        # Presupunem că coloana cu numărul se numește "Numar" sau "NumarProiect"
        for c in ["Numar", "NumarProiect", "Număr", "Nr. înregistrare", "Numar_proiect"]:
            if c in df.columns:
                id_col = c
                break
        else:
            id_col = None

        if id_col:
            lista_simpla = df[id_col].astype(str).tolist()
            st.text("\n".join(lista_simpla))
        else:
            st.info("Coloana cu numărul proiectului nu a fost găsită automat. Selectează manual coloana:")
            col = st.selectbox("Selectează coloana de identificare", df.columns.tolist())
            lista_simpla = df[col].astype(str).tolist()
            st.text("\n".join(lista_simpla))

# ---------- 2. Comisii de raport ----------
elif menu.startswith("2"):
    st.header("2. Generare listă comisii de raport")
    st.write("Poți: 1) introduce manual lista de numere (un pe linie) sau 2) alege un CSV din Drive și selecta rânduri.")

    mode = st.radio("Sursă", ["Introdu manual", "Alege CSV din Drive"])
    projektes = []
    if mode == "Introdu manual":
        raw = st.text_area("Introdu numere de proiect (un per linie)", height=200)
        projektes = [r.strip() for r in raw.splitlines() if r.strip()]
    else:
        csv_files = list_files_in_folder(FOLDER_ID, mime_type="text/csv")
        if not csv_files:
            st.info("Nu s-au găsit CSV în folder.")
        else:
            csv_files = sorted(csv_files, key=lambda x: x.get('modifiedTime',''), reverse=True)
            options = [f['name'] for f in csv_files]
            choice = st.selectbox("Alege CSV", options)
            file_meta = next(f for f in csv_files if f['name']==choice)
            df = download_csv_file(file_meta['id'])
            st.dataframe(df, use_container_width=True)
            # ghid: presupunem coloana "Comisii raport" sau similar
            if st.button("Extrage toate comisiile de raport din CSV"):
                # caută o coloană ce pare a conține comisii
                for cand in ["Comisii raport", "Comisii_raport", "Comisii", "ComisiiRaport"]:
                    if cand in df.columns:
                        st.success(f"Found column: {cand}")
                        out_df = df[[cand]].copy()
                        out_df['Numar'] = df[df.columns[0]].astype(str)  # prima coloană ca identificator fallback
                        st.dataframe(out_df, use_container_width=True)
                        st.download_button("Descarcă CSV comisii", out_df.to_csv(index=False).encode('utf-8'),
                                             file_name="comisii_raport.csv", mime="text/csv")
                        break
                else:
                    st.warning("Nu am găsit o coloană care să conțină comisiile. Poți selecta manual coloana ce conține comisiile.")
                    col = st.selectbox("Selectează coloana cu comisii", df.columns.tolist())
                    out_df = df[[col]].copy()
                    st.dataframe(out_df, use_container_width=True)
                    st.download_button("Descarcă CSV comisii", out_df.to_csv(index=False).encode('utf-8'),
                                             file_name="comisii_raport_custom.csv", mime="text/csv")

# ---------- 3. Verificare fișe Google Drive ----------
elif menu.startswith("3"):
    st.header("3. Verificare existență fișe în Drive")
    st.write("Introdu lista de numere de proiect (unul per linie). Aplicația va verifica dacă există fișiere în folderul Drive care conțin acele numere în nume.")

    raw = st.text_area("Introdu numere de proiect (un per linie)", height=200)
    proiecte = [r.strip() for r in raw.splitlines() if r.strip()]

    if st.button("Verifică fișe"):
        all_files = list_files_in_folder(FOLDER_ID)
        names = [f['name'] for f in all_files]
        prezente = []
        lipsa = []
        for p in proiecte:
            found = [n for n in names if p in n]
            if found:
                prezente.append((p, found))
            else:
                lipsa.append(p)
        st.subheader("✅ Proiecte cu fișă (match în nume fișier)")
        for p,files in prezente:
            st.write(f"- {p} → {', '.join(files)}")
        st.subheader("⚠️ Proiecte fără fișă")
        for p in lipsa:
            st.write(f"- {p}")
        # Download lists
        st.download_button("Descarcă listă proiecte fără fișă", "\n".join(lipsa).encode('utf-8'),
                                 file_name="proiecte_fara_fisa.txt", mime="text/plain")
