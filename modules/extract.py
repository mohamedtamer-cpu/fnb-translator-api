# modules/extract.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from openai import OpenAI
import pypdf, io, json, csv, os
from dotenv import load_dotenv

load_dotenv()
router = APIRouter(prefix="/api", tags=["Extraction"])
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@router.post("/menu")
async def extract_menu(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        filename = file.filename.lower()
        extracted_data = {}

        if filename.endswith('.pdf'):
            pdf_reader = pypdf.PdfReader(io.BytesIO(contents))
            text = "".join([p.extract_text() for p in pdf_reader.pages])
            prompt = f"Extract menu items as JSON. Keys: category, name, description, pricing. Text: {text}"
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            extracted_data = json.loads(response.choices[0].message.content)

        elif filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
            import base64
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
            extracted_data = json.loads(response.choices[0].message.content)
        else:
            raise HTTPException(status_code=400, detail=f"File {filename} is not supported. Use PDF, PNG, or JPG.")

        # --- Safe Parsing for Lists and Dictionaries ---
        items = []
        if isinstance(extracted_data, list):
            items = extracted_data
        elif isinstance(extracted_data, dict):
            # Check common root keys like "items", "menu", or get values if keys are categories
            items = extracted_data.get("items", []) or extracted_data.get("menu", [])
            if not items:
                items = list(extracted_data.values())

        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        
        # Write CSV Headers
        writer.writerow(["Category", "Name", "Description", "Pricing"])
        
        # Write rows safely
        for item in items:
            # Handle potential nested lists/dicts safely
            if isinstance(item, dict):
                writer.writerow([
                    item.get("category", ""),
                    item.get("name", ""),
                    item.get("description", ""),
                    item.get("pricing", "")
                ])

        csv_buffer.seek(0)
        output = csv_buffer.getvalue()

        # Return as a downloadable CSV file
        return StreamingResponse(
            iter([output]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=menu_extracted.csv"}
        )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))