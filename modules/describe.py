# modules/describe.py
from fastapi import APIRouter
import os, json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
router = APIRouter(prefix="/api", tags=["Description"])
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

DB_PATH = "data/database.json"

def load_db():
    if not os.path.exists(DB_PATH): 
        return {}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f: 
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_db(data):
    os.makedirs("data", exist_ok=True)
    with open(DB_PATH, "w", encoding="utf-8") as f: 
        json.dump(data, f, indent=4, ensure_ascii=False)

@router.get("/describe")
def describe_text(text: str, category: str, tone: str):
    db = load_db()
    
    # BULLETPROOF NORMALIZATION (Fixes double spaces)
    text_key = " ".join(text.split()).lower()
    tone_key = tone.strip().lower()

    if text_key in db and "descriptions" in db[text_key] and tone_key in db[text_key]["descriptions"]:
        return {
            "status": "success", 
            "source": "local_db", 
            "description": db[text_key]["descriptions"][tone_key]
        }

    prompt = f"Elite copywriter. Write a {tone} description for '{text}' in category '{category}'. Max 25 words. Plain text only."
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": prompt}]
    )
    
    desc = response.choices[0].message.content.strip()
    
    if text_key not in db: 
        db[text_key] = {
            "original_text": " ".join(text.split()), # Cleaned original text
            "category": category,
            "translations": {},
            "descriptions": {}
        }
    
    db[text_key]["descriptions"][tone_key] = desc
    save_db(db)
    
    return {
        "status": "success", 
        "source": "groq_ai", 
        "description": desc
    }