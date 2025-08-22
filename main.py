# (Full script - copy this entire block)
import os
import time
import json
import requests
import smtplib
import random
import datetime as dt
from email.message import EmailMessage

# ----------------------
# Config from environment (set via GitHub Secrets)
# ----------------------
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", EMAIL_SENDER)

# Safety checks
if not EMAIL_SENDER or not EMAIL_APP_PASSWORD:
    raise SystemExit("[FATAL] Missing EMAIL_SENDER or EMAIL_APP_PASSWORD env vars.")

# Time zone for "run only at this local hour" guard
#TZ = os.getenv("TZ", "Europe/Ljubljana")         # local zone for logs / guard
#RUN_LOCAL_HOUR = int(os.getenv("RUN_LOCAL_HOUR", "9"))  # 9 = 09:00 local

os.environ["TZ"] = "UTC"

try:
    time.tzset()  # works on Linux runners
except Exception:
    pass

# ----------------------
# Paths & constants
# ----------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Put downloads in workspace but keep them OUT of git (see .gitignore)
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "downloaded_manga")
PROGRESS_FILE = os.path.join(BASE_DIR, "progress.json")

HARDCODED_MANGA_TITLE = "Igyou Atama-San To Ningen-Chan"
MIN_IMAGES_TO_DOWNLOAD = 15

TIKTOK_HASHTAGS = (
    "FOLOW OR LIKE IF YOU WANT MORE "
    "#manga #anime #mangadex #mangareader #otaku #animeedit "
    "#mangacollection #fyp #foryoupage #mangarecomandation #isekai #romance #actionmanga"
)

JOKES = [
    "Why don't manga characters ever get lost? Because they always follow the plot!",
    "Why did the manga character bring a ladder? To reach the top of the story!",
    "Why do action heroes always scream before fighting? To boost their *plot power level*!",
    "Why did the reincarnated slime get promoted? Because he *absorbed* all the experience!",
    "What do you call an overpowered farmer in an isekai? The final boss with a hoe!",
]

# ----------------------
# Progress helpers
# ----------------------
def save_progress(chapter_num, page_num):
    data = {"chapter_num": chapter_num, "page_num": page_num}
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"[INFO] Progress saved: chapter {chapter_num}, page {page_num}")

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("chapter_num", "1"), int(data.get("page_num", 0))
    return "1", 0

# ----------------------
# MangaDex API helpers
# ----------------------
def search_manga(title):
    print(f"[INFO] Searching manga: {title}")
    url = f"https://api.mangadex.org/manga?title={title}&limit=1"
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        print(f"[ERROR] search_manga: {resp.status_code} {resp.text}")
        return None
    data = resp.json()
    if data.get("data"):
        manga = data["data"][0]
        manga_id = manga["id"]
        manga_title = (
            manga["attributes"]["title"].get("en")
            or next(iter(manga["attributes"]["title"].values()))
        )
        return manga_id, manga_title
    print("[WARN] No manga found")
    return None

def get_all_chapters(manga_id):
    print(f"[INFO] Fetching all chapters for ID: {manga_id}")
    chapters, offset, limit = [], 0, 100
    while True:
        url = (
            "https://api.mangadex.org/chapter"
            f"?manga={manga_id}&order[chapter]=asc&limit={limit}&offset={offset}&translatedLanguage[]=en"
        )
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"[ERROR] get_all_chapters: {resp.status_code} {resp.text}")
            break
        data = resp.json()
        chapters.extend(data.get("data", []))
        total = data.get("total", 0)
        offset += limit
        if offset >= total:
            break
    # Keep only numeric chapters
    filtered = [
        c for c in chapters
        if (c["attributes"].get("chapter") or "").replace('.', '', 1).isdigit()
    ]
    filtered.sort(key=lambda c: float(c["attributes"]["chapter"]))
    return filtered

def download_chapter_images(chapter, folder, start_page=0):
    chapter_id = chapter["id"]
    chapter_num = chapter["attributes"].get("chapter") or "Unknown"
    print(f"[INFO] Downloading chapter {chapter_num} (start page {start_page+1})")

    url = f"https://api.mangadex.org/at-home/server/{chapter_id}"
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        print(f"[ERROR] get server: {resp.status_code} {resp.text}")
        return []

    data = resp.json()
    base_url, ch = data.get("baseUrl"), data.get("chapter")
    if not base_url or not ch:
        print("[ERROR] Incomplete at-home data")
        return []

    hash_code, data_files = ch.get("hash"), ch.get("data")
    if not hash_code or not data_files:
        print("[ERROR] Missing hash or file list")
        return []

    os.makedirs(folder, exist_ok=True)
    downloaded = []
    for i, file_name in enumerate(data_files[start_page:], start=start_page+1):
        img_url = f"{base_url}/data/{hash_code}/{file_name}"
        filename = f"chapter_{chapter_num}_page_{i}.{file_name.split('.')[-1]}"
        filepath = os.path.join(folder, filename)
        try:
            r = requests.get(img_url, stream=True, timeout=30)
            r.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            downloaded.append(filepath)
            print(f"[OK] {filename}")
        except Exception as e:
            print(f"[FAIL] {filename}: {e}")
        if len(downloaded) >= MIN_IMAGES_TO_DOWNLOAD:
            break
    return downloaded

# ----------------------
# Email sender
# ----------------------
def send_email(subject, body, attachments):
    joke = random.choice(JOKES)
    full_body = f"{body}\n\nJoke of the day:\n{joke}\n\nHashtags:\n{TIKTOK_HASHTAGS}"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.set_content(full_body)

    for filepath in attachments:
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            fname = os.path.basename(filepath)
            subtype = fname.split(".")[-1].lower()
            if subtype == "jpg":
                subtype = "jpeg"
            msg.add_attachment(data, maintype="image", subtype=subtype, filename=fname)
        except Exception as e:
            print(f"[WARN] Could not attach {filepath}: {e}")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        print("[INFO] Email sent successfully")
    except Exception as e:
        print(f"[ERROR] Email failed: {e}")

# ----------------------
# Main
# ----------------------
def main():
    # Run-at-local-hour guard so we can schedule two UTC times (DST-safe)
    #now = dt.datetime.now()
    #if now.hour != RUN_LOCAL_HOUR:
       # print(f"[INFO] Skipping run: local hour {now.hour} != {RUN_LOCAL_HOUR}")
        #return

    manga = search_manga(HARDCODED_MANGA_TITLE)
    if not manga:
        return
    manga_id, manga_title = manga
    print(f"[INFO] Found manga: {manga_title}")

    chapters = get_all_chapters(manga_id)
    if not chapters:
        print("[WARN] No chapters found")
        return

    last_chapter, last_page = load_progress()
    print(f"[INFO] Resuming from chapter {last_chapter}, page {last_page+1}")

    downloaded = []
    for chapter in chapters:
        ch_str = chapter["attributes"].get("chapter")
        if not ch_str or not ch_str.replace(".", "", 1).isdigit():
            continue
        ch_num = float(ch_str)

        if ch_num < float(last_chapter):
            continue

        start_page = 0
        if ch_num == float(last_chapter):
            start_page = last_page + 1

        folder = os.path.join(DOWNLOAD_FOLDER, f"{manga_title}_Chapter_{ch_str}")
        files = download_chapter_images(chapter, folder, start_page)
        downloaded.extend(files)

        if files:
            save_progress(ch_str, start_page + len(files) - 1)

        if len(downloaded) >= MIN_IMAGES_TO_DOWNLOAD:
            break

    if downloaded:
        subject = f"{manga_title} - {len(downloaded)} new images"
        body = f"Downloaded {len(downloaded)} pages starting from chapter {last_chapter}."
        send_email(subject, body, downloaded)
    else:
        print("[INFO] Nothing new downloaded")

if __name__ == "__main__":
    main()
