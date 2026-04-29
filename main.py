from fastapi import FastAPI, Form, HTTPException
import json
import os
import time
import re
from groq import Groq

# --- 1. Setup ---
app = FastAPI(title="FastAPI F&B Translator", version="1.0")
client = Groq(api_key="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")

os.makedirs("data", exist_ok=True)
MEMORY_FILE = os.path.join("data", "translation_memory.json")
RULES_FILE = os.path.join("data", "rules.txt")

if not os.path.exists(RULES_FILE):
    with open(RULES_FILE, "w", encoding="utf-8") as f:
        f.write("""CRITICAL LANGUAGE PURITY RULES (ABSOLUTE PRIORITY):
1. STRICT ISOLATION: NEVER mix languages! A language code must contain ONLY characters from that language.
2. ARABIC PURITY: The "ar" translation MUST contain ONLY Arabic letters (أ-ي). DO NOT leave any English words, letters, or Latin characters inside the Arabic translation under any circumstances.
3. LATIN PURITY: The "en", "fr", "de", "es", and "it" translations MUST contain ONLY Latin letters.

LOCALIZATION & FORMAT RULES:
1. NO LITERAL TRANSLATION: Translate the "meaning" and "vibe".
2. KEEP IT SIMPLE: EXACTLY a VALID JSON object. No extra descriptions.
3. IGNORE UI TEXT: Ignore any remaining website junk.
""")

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return {}

# --- 2. Clean API Endpoint ---
@app.post("/translate")
def translate_menu(
    text_data: str = Form(..., description="Enter Here"),
    arabic: bool = Form(True, description="عربي (ar)"),
    english: bool = Form(True, description="إنجليزي (en)"),
    french: bool = Form(False, description="فرنساوي (fr)"),
    german: bool = Form(False, description="ألماني (de)"),
    spanish: bool = Form(False, description="إسباني (es)"),
    italian: bool = Form(False, description="إيطالي (it)")
):
    target_codes = []
    if arabic: target_codes.append("ar")
    if english: target_codes.append("en")
    if french: target_codes.append("fr")
    if german: target_codes.append("de")
    if spanish: target_codes.append("es")
    if italian: target_codes.append("it")

    if not text_data.strip(): raise HTTPException(status_code=400, detail="حط كلام الأول!")
    if not target_codes: raise HTTPException(status_code=400, detail="اختار لغة واحدة على الأقل!")

    memory = load_memory()
    raw_lines = [line.strip() for line in text_data.split('\n') if line.strip()]
    
    cached_items = []
    new_items = []
    
    for line in raw_lines:
        
        if line in memory and all(lang in memory[line] for lang in target_codes):
            cached_items.append(line)
        else:
            new_items.append(line)

    if not new_items:
        return {
            "status": "success",
            "report": {
                "Total_Items": len(raw_lines),
                "From_JSON_Memory_🟢": len(cached_items),
                "From_AI_API_🔴": 0
            },
            "data": {item: {lang: memory[item][lang] for lang in target_codes if lang in memory[item]} for item in raw_lines}
        }

    text_to_send = "\n".join(new_items)
    with open(RULES_FILE, "r", encoding="utf-8") as f: external_rules = f.read()

    system_prompt = f"Translate to EXACT language codes: {target_codes}.\n\n{external_rules}"

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"LOCALIZE THESE ITEMS:\n{text_to_send[:12000]}"}],
                response_format={"type": "json_object"}, temperature=0.1 
            )
            final_json = json.loads(response.choices[0].message.content)
            
            for key, value in final_json.items():
                if key not in memory:
                    memory[key] = {}
                memory[key].update(value)
                
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(memory, f, ensure_ascii=False, indent=4)
            
            complete_response = {}
            for item in raw_lines:
                complete_response[item] = {lang: memory[item][lang] for lang in target_codes if lang in memory[item]}
            
            return {
                "status": "success",
                "report": {
                    "Total_Items": len(raw_lines),
                    "From_JSON_Memory_🟢": len(cached_items),
                    "From_AI_API_🔴": len(new_items)
                },
                "data": complete_response
            }
            
        except Exception as e:
            if "429" in str(e): time.sleep(10); continue
            raise HTTPException(status_code=500, detail=str(e))