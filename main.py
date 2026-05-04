# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from modules import translate, describe, extract

app = FastAPI(
    title="FNB Translator API",
    version="1.0",
    description="API for high-end culinary translations and descriptions"
)

# Enable CORS for frontend compatibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registering all Routers
app.include_router(translate.router)
app.include_router(describe.router)
app.include_router(extract.router)

@app.get("/")
def root():
    return {"message": "FNB Translator API is active and running smoothly"}