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

        prompt = (
            "Extract menu items as a JSON object with a root key 'items'. "
            "Each item must have these keys: 'category', 'name', 'description', 'pricing', and 'modifiers'. "
            "IMPORTANT RULES: "
            "1. If the item has a single price, put it in 'pricing' and leave 'modifiers' empty. "
            "2. If the item has multiple prices (e.g., different sizes like S/M/L), set 'pricing' to null, "
            "and put the prices in 'modifiers' as a list of objects, e.g., [{'size': 'S', 'price': 15}, {'size': 'M', 'price': 20}]."
        )

        if filename.endswith('.pdf'):
            pdf_reader = pypdf.PdfReader(io.BytesIO(contents))
            text = "".join([p.extract_text() for p in pdf_reader.pages])
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a highly accurate data extraction assistant."},
                    {"role": "user", "content": f"{prompt}\n\nText: {text}"}
                ],
                response_format={"type": "json_object"}
            )
            extracted_data = json.loads(response.choices[0].message.content)

        elif filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
            import base64
            img_base64 = base64.b64encode(contents).decode("utf-8")
            
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

        items = []
        if isinstance(extracted_data, list):
            items = extracted_data
        elif isinstance(extracted_data, dict):
            items = extracted_data.get("items", []) or extracted_data.get("menu", [])
            if not items:
                items = list(extracted_data.values())

        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        
        writer.writerow(["Category", "Name", "Description", "Pricing", "Modifiers"])
        
        for item in items:
            if isinstance(item, dict):
                pricing = item.get("pricing", "")
                modifiers = item.get("modifiers", [])
                
                modifier_string = ""
                
                if modifiers and isinstance(modifiers, list):
                    mod_parts = []
                    for mod in modifiers:
                        if isinstance(mod, dict):
                            size = mod.get("size", mod.get("name", ""))
                            price = mod.get("price", "")
                            mod_parts.append(f"{size}: {price}")
                    modifier_string = " | ".join(mod_parts)
                    pricing = ""
                
                if pricing is None:
                    pricing = ""

                writer.writerow([
                    item.get("category", ""),
                    item.get("name", ""),
                    item.get("description", ""),
                    pricing,
                    modifier_string
                ])

        csv_buffer.seek(0)
        output = csv_buffer.getvalue()

        return StreamingResponse(
            iter([output]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=menu_extracted.csv"}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))