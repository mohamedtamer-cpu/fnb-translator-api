cat << 'EOF' > main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from modules import translate, describe, extract, scraper

app = FastAPI(
    title="FNB Translator API",
    version="1.0",
    description="API for high-end culinary translations, descriptions, and extraction"
)

# Enable CORS for frontend compatibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registering all routers including the scraper
app.include_router(translate.router)
app.include_router(describe.router)
app.include_router(extract.router)
app.include_router(scraper.router)

@app.get("/", include_in_schema=False)
def root():
    return {"message": "API is active"}
EOF