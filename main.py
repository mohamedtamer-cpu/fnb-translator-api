import os
import json
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Initialize FastAPI and Groq
app = FastAPI(title="Food AI & Translation API")
client = Groq(api_key=GROQ_API_KEY)

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "data/database.json"
RULES_FILE = "data/rules.txt"

# --- DATABASE & RULES FUNCTIONS ---
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                return {}
    return {}

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as file:
        json.dump(db, file, indent=4, ensure_ascii=False)

def load_rules():
    """Bte-read malaf el rules 3ashan tb3to lel AI"""
    if os.path.exists(RULES_FILE):
        with open(RULES_FILE, "r", encoding="utf-8") as file:
            return file.read().strip()
    return ""

# Initialize DB in memory
data_db = load_db()

# --- HELPER FUNCTION: Ensure item exists in DB ---
def ensure_db_entry(text_key, original_text, category):
    if text_key not in data_db:
        data_db[text_key] = {
            "original_text": original_text,
            "category": category,
            "translations": {},
            "descriptions": {}
        }

# ==========================================
# ENDPOINT 1: TRANSLATION (Multiple Languages)
# ==========================================
@app.get("/api/translate")
def translate_text(
    text: str, 
    category: str, 
    languages: str # e.g., "en,fr,ar"
):
    text_key = text.strip().lower()
    cat_key = category.strip().lower()
    
    target_langs = [lang.strip().lower() for lang in languages.split(",") if lang.strip()]
    ensure_db_entry(text_key, text, category)
    
    results = {}
    missing_langs = []

    # 1. Local Search First
    for lang in target_langs:
        if lang in data_db[text_key]["translations"]:
            results[lang] = data_db[text_key]["translations"][lang]
        else:
            missing_langs.append(lang)

    # 2. Ask Groq for missing languages
    if missing_langs:
        missing_langs_str = ", ".join(missing_langs)
        custom_rules = load_rules() # Bnes7ab el rules hna
        
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": f"""You are a highly accurate culinary translator. 
Translate the text '{text}' (Context/Category: '{category}') into the following languages: {missing_langs_str}.

CRITICAL SYSTEM RULES:
{custom_rules}

IMPORTANT JSON FORMAT: Ensure you return ONLY a valid JSON object. Do not include any extra text."""
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            
            ai_output = json.loads(response.choices[0].message.content)
            
            # Da by-handle rule raqam 4 (law el AI ba3at el format b-esm el akla aw flat)
            if text in ai_output and isinstance(ai_output[text], dict):
                ai_translations = ai_output[text]
            elif text_key in ai_output and isinstance(ai_output[text_key], dict):
                ai_translations = ai_output[text_key]
            else:
                ai_translations = ai_output

            # Save to DB and add to results
            for lang, trans in ai_translations.items():
                lang_lower = lang.lower()
                # n-check law el language code mawgoud w n-save
                if lang_lower in missing_langs:
                    data_db[text_key]["translations"][lang_lower] = trans
                    results[lang_lower] = trans
            
            save_db(data_db)
            
        except Exception as e:
            return {"status": "error", "message": "Groq AI failed during translation", "details": str(e)}

    return {
        "status": "success",
        "text": text,
        "category": category,
        "translations": results
    }

# ==========================================
# ENDPOINT 2: DESCRIPTION
# ==========================================
@app.get("/api/describe")
def describe_text(
    text: str, 
    category: str, 
    tone: str
):
    text_key = text.strip().lower()
    tone_key = tone.strip().lower()
    
    ensure_db_entry(text_key, text, category)

    # 1. Local Search
    if tone_key in data_db[text_key]["descriptions"]:
        return {
            "status": "success",
            "source": "local_database",
            "text": text,
            "category": category,
            "tone": tone,
            "description": data_db[text_key]["descriptions"][tone_key]
        }

    # 2. Ask Groq AI
    custom_rules = load_rules()

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": f"""You are an elite copywriter. 
Write a short, elegant description (max 30 words) for the item '{text}' which belongs to the category '{category}'. 
The tone MUST be exactly: '{tone}'. 

APPLY THESE RULES IF RELEVANT:
{custom_rules}

Return ONLY the description text. No quotes, no extra chat."""
                }
            ],
            temperature=0.75,
            max_tokens=100
        )
        
        ai_description = response.choices[0].message.content.strip()
        
        # 3. Save to DB
        data_db[text_key]["descriptions"][tone_key] = ai_description
        save_db(data_db)

        return {
            "status": "success",
            "source": "groq_ai",
            "text": text,
            "category": category,
            "tone": tone,
            "description": ai_description
        }

    except Exception as e:
        return {
            "status": "error",
            "message": "Groq AI failed during description generation",
            "details": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)