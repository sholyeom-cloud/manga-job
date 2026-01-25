import os
import time
import json
import requests
import smtplib
import random
import datetime
from datetime import timedelta
from email.message import EmailMessage

# ----------------------
# Config
# ----------------------
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", EMAIL_SENDER)

if not EMAIL_SENDER or not EMAIL_APP_PASSWORD:
    raise SystemExit("[FATAL] Missing EMAIL_SENDER or EMAIL_APP_PASSWORD env vars.")

# ----------------------
# Paths & Constants
# ----------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "downloaded_manga")
HISTORY_FILE = os.path.join(BASE_DIR, "sent_history.json")

IMAGES_TO_DOWNLOAD = 10 
BASE_HASHTAGS = "#manga #manhwa #newmanga #mangarecommendation #mangadex #fyp #anime #otaku #hiddenmanga"

JOKES = [
    "Why don't manga characters ever get lost? Because they always follow the plot!",
    "Why did the manga character bring a ladder? To reach the top of the story!",
    "Why do action heroes always scream before fighting? To boost their *plot power level*!",
    "Why did the reincarnated slime get promoted? Because he *absorbed* all the experience!",
    "What do you call an overpowered farmer in an isekai? The final boss with a hoe!",
]

# ----------------------
# Logic
# ----------------------
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_history(sent_id):
    history = load_history()
    if sent_id not in history:
        history.append(sent_id)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f)

def get_fresh_trending_manga():
    print("[INFO] Searching for NEW & TRENDING Manga/Manhwa...")
    history = load_history()
    thirty_days_ago = datetime.datetime.now() - timedelta(days=30)
    date_str = thirty_days_ago.strftime("%Y-%m-%dT%H:%M:%S")

    url = "https://api.mangadex.org/manga"
    params = {
        "limit": 50,
        "order[followedCount]": "desc",
        "createdAtSince": date_str,
        "includes[]": "cover_art",
        "originalLanguage[]": ["ja", "ko"],
        "contentRating[]": ["safe", "suggestive"]
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        for manga in data.get("data", []):
            manga_id = manga["id"]
            if manga_id not in history:
                title = manga["attributes"]["title"].get("en") or next(iter(manga["attributes"]["title"].values()))
                genres = [t["attributes"]["name"]["en"] for t in manga["attributes"]["tags"] if t["type"] == "tag"]
                return {
                    "id": manga_id, "title": title, "genres": genres,
                    "desc": manga["attributes"]["description"].get("en", "")[:250] + "..."
                }
        return None
    except Exception:
        return None

def get_first_chapter(manga_id):
    url = "https://api.mangadex.org/chapter"
    params = {"manga": manga_id, "translatedLanguage[]": "en", "order[chapter]": "asc", "limit": 100}
    try:
        resp = requests.get(url, params=params, timeout=30)
        data = resp.json()
        for chapter in data.get("data", []):
            ch_num = chapter["attributes"].get("chapter", "")
            if ch_num == "1" or ch_num == "0" or (ch_num and ch_num.replace('.', '', 1).isdigit()):
                return chapter
        return None
    except Exception:
        return None

def download_images(chapter, folder):
    chapter_id = chapter["id"]
    url = f"https://api.mangadex.org/at-home/server/{chapter_id}"
    try:
        resp = requests.get(url, timeout=30)
        data = resp.json()
        base_url = data["baseUrl"]
        hash_code = data["chapter"]["hash"]
        files = data["chapter"]["data"]
        os.makedirs(folder, exist_ok=True)
        downloaded_paths = []

        for i, filename in enumerate(files[:IMAGES_TO_DOWNLOAD]):
            img_url = f"{base_url}/data/{hash_code}/{filename}"
            ext = filename.split(".")[-1]
            local_path = os.path.join(folder, f"page_{i+1:02d}.{ext}")
            r = requests.get(img_url, timeout=30)
            if r.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(r.content)
                downloaded_paths.append(local_path)
        return downloaded_paths
    except Exception:
        return []

def send_email(manga_info, image_paths):
    genre_tags = " ".join([f"#{g.replace(' ', '')}" for g in manga_info['genres']])
    title_tag = "#" + "".join(e for e in manga_info['title'] if e.isalnum())
    final_hashtags = f"{BASE_HASHTAGS} {genre_tags} {title_tag}"
    joke = random.choice(JOKES)
    
    subject = f"📈 New & Trending: {manga_info['title']}"
    body = (f"🔥 FRESH TRENDING MANGA 🔥\n\nTitle: {manga_info['title']}\n"
            f"Description: {manga_info['desc']}\n\n--- TIKTOK CAPTION ---\n\n"
            f"New Manga Alert! 🚨 {manga_info['title']} 📚\n\n{final_hashtags}\n\n"
            f"-------------------------\nBot Joke: {joke}")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.set_content(body)

    for filepath in image_paths:
        with open(filepath, "rb") as f:
            file_name = os.path.basename(filepath)
            subtype = file_name.split(".")[-1].lower()
            if subtype == "jpg": subtype = "jpeg"
            msg.add_attachment(f.read(), maintype="image", subtype=subtype, filename=file_name)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception:
        return False

def main():
    manga = get_fresh_trending_manga()
    if manga:
        chapter = get_first_chapter(manga["id"])
        if chapter:
            folder = os.path.join(DOWNLOAD_FOLDER, "temp_chapter")
            images = download_images(chapter, folder)
            if images and send_email(manga, images):
                save_history(manga["id"])

if __name__ == "__main__":
    main()
