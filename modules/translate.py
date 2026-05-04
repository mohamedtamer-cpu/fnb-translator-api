# modules/translate.py
from fastapi import APIRouter
import os, json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
router = APIRouter(prefix="/api", tags=["Translation"])
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

DB_PATH = "data/database.json"
RULES_PATH = "data/rules.txt"

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

def get_rules():
    if not os.path.exists(RULES_PATH): 
        return ""
    with open(RULES_PATH, "r", encoding="utf-8") as f: 
        return f.read()

@router.get("/translate")
def translate_text(text: str, category: str, languages: str):
    db = load_db()
    
    # BULLETPROOF NORMALIZATION (Fixes double spaces)
    text_key = " ".join(text.split()).lower()
    
    langs_list = [l.strip() for l in languages.split(",")]
    
    if text_key not in db:
        db[text_key] = {
            "original_text": " ".join(text.split()), # Cleaned original text
            "category": category,
            "translations": {},
            "descriptions": {}
        }
    
    missing = [l for l in langs_list if l not in db[text_key]["translations"]]
    
    if not missing:
        return {
            "status": "success", 
            "source": "local_db", 
            "translations": {l: db[text_key]["translations"][l] for l in langs_list}
        }

    rules = get_rules()
    prompt = f"""You are a high-end culinary translator. Translate '{text}' ({category}) into these languages: {missing}.

RULES:
1. ARABIC: Use ONLY Arabic characters. NO English letters inside the Arabic text.
2. NO LITERAL TRANSLATION: Translate the vibe (e.g., 'Ice Matcha' -> 'أيس ماتشا منعش' or 'ماتشا بارد' and NEVER 'شاي أخضر مجمد').
3. CULINARY TRANSLITERATION: Keep global terms in their common phonetic name.
4. OUTPUT: Return ONLY a valid JSON object."""
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": prompt}],
        response_format={"type": "json_object"}
    )
    
    new_trans = json.loads(response.choices[0].message.content)
    db[text_key]["translations"].update(new_trans)
    save_db(db)
    
    return {
        "status": "success", 
        "source": "groq_ai", 
        "translations": {l: db[text_key]["translations"].get(l, "") for l in langs_list}
    }