from fastapi import FastAPI
import uvicorn
from modules import translate, describe, extract

app = FastAPI(title="FnB AI API - Modular Version")

# Include all routers
app.include_router(translate.router)
app.include_router(describe.router)
app.include_router(extract.router)

@app.get("/")
def home():
    return {"status": "API is online", "version": "2.0.0"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)