# modules/groq_extract.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
import os, io, csv, json, base64
import pdfplumber
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
router = APIRouter(prefix="/api", tags=["Extraction"])
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def json_to_csv(all_items):
    """Converts the extracted JSON list of items into a CSV string."""
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["Category", "Name", "Description", "Pricing"])
    
    for item in all_items:
        if isinstance(item, dict):
            writer.writerow([
                item.get("category", ""),
                item.get("name", ""),
                item.get("description", ""),
                item.get("pricing", "")
            ])
            
    csv_buffer.seek(0)
    return csv_buffer.getvalue()

@router.post("/menu-groq")
async def extract_menu_groq(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        filename = file.filename.lower()
        all_extracted_items = []
        
        prompt = (
            "You are a professional menu data extraction assistant. \n"
            "INSTRUCTIONS:\n"
            "1. Read the provided menu layout, including categories and their items.\n"
            "2. Extract the 'category', 'name', 'description', and 'pricing' fields exactly as they are written.\n"
            "3. Output strictly as a JSON object with a root key 'items'."
        )

        # 1. Handle PDF files (Text-only payload for Groq)
        if filename.endswith('.pdf'):
            with pdfplumber.open(io.BytesIO(contents)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if not text: 
                        continue
                    
                    response = client.chat.completions.create(
                        messages=[{"role": "user", "content": f"{prompt}\n\nMenu Text:\n{text}"}],
                        model="llama-3.3-70b-versatile",
                        temperature=0.0,
                        response_format={"type": "json_object"}
                    )
                    
                    page_data = json.loads(response.choices[0].message.content)
                    items = page_data.get("items", []) or page_data.get("menu", [])
                    
                    if isinstance(items, list):
                        all_extracted_items.extend(items)

        # 2. Handle Image files (PNG, JPG, JPEG, WEBP)
        elif filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
            # Encode image to base64
            encoded_file = base64.b64encode(contents).decode("utf-8")
            
            # Use a model that supports vision/multimodal capabilities if needed, 
            # or pass the prompt and base64 string as a pure string representation if using Llama.
            response = client.chat.completions.create(
                messages=[{
                    "role": "user",
                    "content": f"{prompt}\n\n[Base64 Image Data]: data:image/jpeg;base64,{encoded_file}"
                }],
                model="llama-3.3-70b-versatile", 
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            
            data = json.loads(response.choices[0].message.content)
            items = data.get("items", []) or data.get("menu", [])
            all_extracted_items.extend(items)

        else:
            raise HTTPException(status_code=400, detail="Please upload a valid PDF or image file.")

        # Convert JSON data to CSV
        csv_output = json_to_csv(all_extracted_items)

        return StreamingResponse(
            iter([csv_output]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=extracted_menu.csv"}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))