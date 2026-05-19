from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
import io, json, csv, os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
router = APIRouter(prefix="/api", tags=["Groq Extraction"])

# تفعيل الـ Client الخاص بـ Groq
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

@router.post("/groq-menu")
async def extract_groq_menu(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        filename = file.filename.lower()
        extracted_data = {}

        prompt = (
            "Extract menu items as a JSON object with a root key 'items'. "
            "Each item must have these keys: 'category', 'name', 'description', and 'pricing'."
        )

        if filename.endswith('.pdf'):
            import pdfplumber
            with pdfplumber.open(io.BytesIO(contents)) as pdf:
                text = "".join([page.extract_text() for page in pdf.pages])
            
            # استدعاء نموذج Groq
            chat_completion = groq_client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a highly accurate data extraction assistant that responds only in JSON."
                    },
                    {
                        "role": "user",
                        "content": f"{prompt}\n\nText: {text}"
                    }
                ],
                model="llama3-8b-8192", # أو أي نموذج آخر تفضله
                response_format={"type": "json_object"}
            )
            
            extracted_data = json.loads(chat_completion.choices[0].message.content)
        else:
            raise HTTPException(status_code=400, detail=f"File {filename} is not supported.")

        # تجهيز ملف الـ CSV
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(["Category", "Name", "Description", "Pricing", "Modifiers"])
        
        for item in extracted_data.get("items", []):
            writer.writerow([
                item.get("category", ""),
                item.get("name", ""),
                item.get("description", ""),
                item.get("pricing", ""),
                ""
            ])

        csv_buffer.seek(0)
        output = csv_buffer.getvalue()

        return StreamingResponse(
            iter([output]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=groq_menu_extracted.csv"}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))