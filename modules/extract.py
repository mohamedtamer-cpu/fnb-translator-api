# modules/extract.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from openai import OpenAI
import pypdf, io, json, base64, os
from dotenv import load_dotenv

load_dotenv()
router = APIRouter(prefix="/api", tags=["Extraction"])
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DB_PATH = "data/database.json"

# --- Utilities ---
def load_db():
    if not os.path.exists(DB_PATH): 
        return {}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f: 
            return json.load(f)
    except json.JSONDecodeError:
        return {}

# --- Endpoints ---

# 1. Get single item info from local database
@router.get("/extract")
def get_item_from_db(text: str):
    db = load_db()
    # Normalize text: remove extra spaces and lowercase
    text_key = " ".join(text.split()).lower()
    
    if text_key in db:
        return {
            "status": "success",
            "source": "local_db",
            "data": db[text_key]
        }
    
    return {
        "status": "success",
        "source": "not_found",
        "message": "Item not found in local database",
        "data": {
            "original_text": text,
            "category": "unknown",
            "translations": {},
            "descriptions": {}
        }
    }

# 2. Extract full menu from File (PDF/Image) using OpenAI
@router.post("/menu")
async def extract_menu(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        filename = file.filename.lower()

        if filename.endswith('.pdf'):
            pdf_reader = pypdf.PdfReader(io.BytesIO(contents))
            text = "".join([p.extract_text() for p in pdf_reader.pages])
            prompt = f"Extract menu items as JSON. Keys: category, name, description, pricing. Text: {text}"
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)

        elif filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
            img_base64 = base64.b64encode(contents).decode("utf-8")
            prompt = "Extract menu items from this image as JSON with keys: category, name, description, pricing."
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                    ]
                }],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        else:
            raise HTTPException(status_code=400, detail=f"File {filename} is not supported. Use PDF, PNG, or JPG.")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))