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
    print("[FATAL] Missing EMAIL_SENDER or EMAIL_APP_PASSWORD env vars.")

# ----------------------
# Paths & Constants
# ----------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "downloaded_manga")
HISTORY_FILE = os.path.join(BASE_DIR, "sent_history.json")

IMAGES_TO_DOWNLOAD = 10 
BASE_HASHTAGS = "#manga #manhwa #newmanga #mangarecommendation #mangadex #fyp #anime #otaku #hiddenmanga"

# Gmail limit is 25MB. Encoding adds ~33% overhead.
# We set a safe limit of 18MB for raw files to ensure we don't crash.
MAX_EMAIL_SIZE_BYTES = 18 * 1024 * 1024  # 18 MB

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
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("[WARN] History file is corrupted. Starting fresh.")
            return []
    return []

def save_history(sent_id):
    history = load_history()
    if sent_id not in history:
        history.append(sent_id)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f)
        print(f"[INFO] Saved {sent_id} to history.")

def get_fresh_trending_manga():
    print("[INFO] Step 1: Searching for NEW & TRENDING Manga/Manhwa...")
    history = load_history()
    thirty_days_ago = datetime.datetime.now() - timedelta(days=30)
    date_str = thirty_days_ago.strftime("%Y-%m-%dT%H:%M:%S")

    url = "https://api.mangadex.org/manga"
    headers = {"User-Agent": "MangaDailyBot/1.0 (github.com/sholyeom-cloud/manga-job)"}
    params = {
        "limit": 50,
        "order[followedCount]": "desc",
        "createdAtSince": date_str,
        "includes[]": "cover_art",
        "originalLanguage[]": ["ja", "ko"],
        "contentRating[]": ["safe", "suggestive"]
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"[ERROR] MangaDex API Error: {resp.status_code}")
            return None

        data = resp.json()
        for manga in data.get("data", []):
            manga_id = manga["id"]
            if manga_id not in history:
                title_attr = manga["attributes"]["title"]
                title = title_attr.get("en") or next(iter(title_attr.values()), "Unknown Title")
                tags = manga["attributes"].get("tags", [])
                genres = [t["attributes"]["name"]["en"] for t in tags if t["type"] == "tag"]
                desc = manga["attributes"]["description"].get("en", "")
                
                print(f"[INFO] Found fresh manga: {title}")
                return {
                    "id": manga_id, "title": title, "genres": genres,
                    "desc": desc[:250] + "..." if desc else "No description."
                }
        print("[INFO] No new manga found (all top results in history).")
        return None
    except Exception as e:
        print(f"[CRITICAL ERROR] Failed in get_fresh_trending_manga: {e}")
        return None

def get_first_chapter(manga_id):
    print(f"[INFO] Step 2: Finding first chapter for ID {manga_id}...")
    url = "https://api.mangadex.org/chapter"
    headers = {"User-Agent": "MangaDailyBot/1.0"}
    params = {"manga": manga_id, "translatedLanguage[]": "en", "order[chapter]": "asc", "limit": 100}
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        data = resp.json()
        for chapter in data.get("data", []):
            ch_num = chapter["attributes"].get("chapter", "")
            if ch_num == "1" or ch_num == "0" or (ch_num and ch_num.replace('.', '', 1).isdigit()):
                print(f"[INFO] Found Chapter {ch_num} (ID: {chapter['id']})")
                return chapter
        print("[WARN] No suitable Chapter 1 found.")
        return None
    except Exception as e:
        print(f"[ERROR] Failed in get_first_chapter: {e}")
        return None

def download_images(chapter, folder):
    print("[INFO] Step 3: Downloading images...")
    chapter_id = chapter["id"]
    url = f"https://api.mangadex.org/at-home/server/{chapter_id}"
    headers = {"User-Agent": "MangaDailyBot/1.0"}

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return []

        data = resp.json()
        base_url = data["baseUrl"]
        hash_code = data["chapter"]["hash"]
        files = data["chapter"]["data"]
        
        os.makedirs(folder, exist_ok=True)
        downloaded_paths = []

        count = 0
        for i, filename in enumerate(files):
            if count >= IMAGES_TO_DOWNLOAD:
                break
            
            img_url = f"{base_url}/data/{hash_code}/{filename}"
            ext = filename.split(".")[-1]
            local_path = os.path.join(folder, f"page_{i+1:02d}.{ext}")
            
            # Retry logic
            for _ in range(2):
                try:
                    r = requests.get(img_url, headers=headers, timeout=30)
                    if r.status_code == 200:
                        with open(local_path, "wb") as f:
                            f.write(r.content)
                        downloaded_paths.append(local_path)
                        count += 1
                        break
                except:
                    time.sleep(1)

        print(f"[INFO] Successfully downloaded {len(downloaded_paths)} images.")
        return downloaded_paths
    except Exception as e:
        print(f"[ERROR] Failed in download_images: {e}")
        return []

def send_email(manga_info, image_paths):
    print("[INFO] Step 4: preparing Email...")
    
    # --- SIZE CHECK LOGIC START ---
    loaded_images = []
    total_size = 0
    
    print("[INFO] loading images to check size...")
    for path in image_paths:
        try:
            with open(path, "rb") as f:
                img_data = f.read()
                size = len(img_data)
                filename = os.path.basename(path)
                loaded_images.append({"name": filename, "data": img_data, "size": size, "path": path})
                total_size += size
        except Exception as e:
            print(f"[WARN] Failed to load {path}: {e}")

    print(f"[INFO] Initial Total Size: {total_size / 1024 / 1024:.2f} MB")

    # While total size > 18MB, remove the last image
    while total_size > MAX_EMAIL_SIZE_BYTES and len(loaded_images) > 0:
        removed_img = loaded_images.pop() # Removes the last one added
        total_size -= removed_img["size"]
        print(f"[WARN] ⚠️ Email too large! Removed {removed_img['name']}. New size: {total_size / 1024 / 1024:.2f} MB")

    if not loaded_images:
        print("[ERROR] All images were too big! Cannot send email.")
        return False
    # --- SIZE CHECK LOGIC END ---

    genre_tags = " ".join([f"#{g.replace(' ', '')}" for g in manga_info['genres']])
    title_tag = "#" + "".join(e for e in manga_info['title'] if e.isalnum())
    final_hashtags = f"{BASE_HASHTAGS} {genre_tags} {title_tag}"
    joke = random.choice(JOKES)
    
    subject = f"📈 New & Trending: {manga_info['title']}"
    body = (f"🔥 FRESH TRENDING MANGA 🔥\n\nTitle: {manga_info['title']}\n"
            f"Description: {manga_info['desc']}\n\n"
            f"Images Attached: {len(loaded_images)} (Some may be removed to fit email limits)\n\n"
            f"--- TIKTOK CAPTION ---\n\n"
            f"New Manga Alert! 🚨 {manga_info['title']} 📚\n\n{final_hashtags}\n\n"
            f"-------------------------\nBot Joke: {joke}")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.set_content(body)

    # Attach only the images that fit
    for img in loaded_images:
        subtype = img["name"].split(".")[-1].lower()
        if subtype == "jpg": subtype = "jpeg"
        msg.add_attachment(img["data"], maintype="image", subtype=subtype, filename=img["name"])

    try:
        print(f"[INFO] Sending email with size approx {total_size / 1024 / 1024:.2f} MB...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        print("[SUCCESS] Email SENT successfully!")
        return True
    except Exception as e:
        print(f"[ERROR] Email FAILED to send: {e}")
        return False

def main():
    print("--- 🚀 STARTING MANGA BOT 🚀 ---")
    manga = get_fresh_trending_manga()
    
    if manga:
        chapter = get_first_chapter(manga["id"])
        if chapter:
            folder = os.path.join(DOWNLOAD_FOLDER, "temp_chapter")
            images = download_images(chapter, folder)
            
            if images:
                if send_email(manga, images):
                    save_history(manga["id"])
                else:
                    print("[FAIL] Process finished but Email failed.")
            else:
                print("[FAIL] No images downloaded.")
        else:
            print("[FAIL] No chapter found.")
    else:
        print("[FAIL] No new manga found.")

    print("--- 🏁 BOT FINISHED 🏁 ---")

if __name__ == "__main__":
    main()
