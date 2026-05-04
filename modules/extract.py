from fastapi import APIRouter, UploadFile, File, HTTPException
from openai import OpenAI
import pypdf, io, json, base64, os
from dotenv import load_dotenv

load_dotenv()
router = APIRouter(prefix="/extract", tags=["Menu Extraction"])
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@router.post("/menu")
async def extract_menu(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        filename = file.filename.lower() # Converting to lower to avoid PNG vs png

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
            # Added more detail to know what failed
            raise HTTPException(status_code=400, detail=f"File {filename} is not supported. Use PDF, PNG, or JPG.")
    except Exception as e:
        # This will show the real error in the Response Body
        raise HTTPException(status_code=500, detail=str(e))