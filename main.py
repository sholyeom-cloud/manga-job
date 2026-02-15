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
    # We don't raise SystemExit here so we can see the logs in GitHub Actions, 
    # but the email function will fail later.

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
    
    # IMPORTANT FIX: Added User-Agent so MangaDex doesn't block the bot
    headers = {
        "User-Agent": "MangaDailyBot/1.0 (github.com/sholyeom-cloud/manga-job)"
    }

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
            print(f"[ERROR] Response text: {resp.text}")
            return None

        data = resp.json()
        
        for manga in data.get("data", []):
            manga_id = manga["id"]
            if manga_id not in history:
                # Safe title extraction
                title_attr = manga["attributes"]["title"]
                title = title_attr.get("en") or next(iter(title_attr.values()), "Unknown Title")
                
                tags = manga["attributes"].get("tags", [])
                genres = [t["attributes"]["name"]["en"] for t in tags if t["type"] == "tag"]
                
                desc = manga["attributes"]["description"].get("en", "")
                if not desc:
                    desc = "No description available."
                
                print(f"[INFO] Found fresh manga: {title}")
                return {
                    "id": manga_id, "title": title, "genres": genres,
                    "desc": desc[:250] + "..."
                }
        
        print("[INFO] No new manga found (all 50 top results are already in history).")
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
            # Logic to find chapter 1, 0, or the first available number
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
            print(f"[ERROR] Failed to get image server: {resp.status_code}")
            return []

        data = resp.json()
        base_url = data["baseUrl"]
        hash_code = data["chapter"]["hash"]
        files = data["chapter"]["data"]
        
        os.makedirs(folder, exist_ok=True)
        downloaded_paths = []

        # Download up to limit
        count = 0
        for i, filename in enumerate(files):
            if count >= IMAGES_TO_DOWNLOAD:
                break
                
            img_url = f"{base_url}/data/{hash_code}/{filename}"
            ext = filename.split(".")[-1]
            local_path = os.path.join(folder, f"page_{i+1:02d}.{ext}")
            
            # Simple retry logic for images
            success = False
            for attempt in range(2):
                try:
                    r = requests.get(img_url, headers=headers, timeout=30)
                    if r.status_code == 200:
                        with open(local_path, "wb") as f:
                            f.write(r.content)
                        downloaded_paths.append(local_path)
                        success = True
                        count += 1
                        break
                except:
                    time.sleep(1)
            
            if not success:
                print(f"[WARN] Failed to download image {i+1}")

        print(f"[INFO] Successfully downloaded {len(downloaded_paths)} images.")
        return downloaded_paths
    except Exception as e:
        print(f"[ERROR] Failed in download_images: {e}")
        return []

def send_email(manga_info, image_paths):
    print("[INFO] Step 4: Sending Email...")
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
        try:
            with open(filepath, "rb") as f:
                file_name = os.path.basename(filepath)
                subtype = file_name.split(".")[-1].lower()
                if subtype == "jpg": subtype = "jpeg"
                msg.add_attachment(f.read(), maintype="image", subtype=subtype, filename=file_name)
        except Exception as e:
            print(f"[WARN] Could not attach {filepath}: {e}")

    try:
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
    
    # 1. Get Manga
    manga = get_fresh_trending_manga()
    
    if manga:
        # 2. Get Chapter
        chapter = get_first_chapter(manga["id"])
        if chapter:
            folder = os.path.join(DOWNLOAD_FOLDER, "temp_chapter")
            
            # 3. Download Images
            images = download_images(chapter, folder)
            
            if images:
                # 4. Send Email
                if send_email(manga, images):
                    # 5. Save History
                    save_history(manga["id"])
                else:
                    print("[FAIL] Process finished but Email failed.")
            else:
                print("[FAIL] Found manga/chapter, but no images downloaded.")
        else:
            print("[FAIL] Found manga, but no first chapter found.")
    else:
        print("[FAIL] No new trending manga found (or API error).")

    print("--- 🏁 BOT FINISHED 🏁 ---")

if __name__ == "__main__":
    main()
