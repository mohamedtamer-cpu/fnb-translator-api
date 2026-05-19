from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl
from modules.talabat_scraper import MenuScraper, deduplicate

router = APIRouter(prefix="/api", tags=["Scraping"])

# Input validation schema
class ScrapeRequest(BaseModel):
    url: HttpUrl

@router.post("/scrape")
async def scrape_menu(payload: ScrapeRequest):
    try:
        url_str = str(payload.url)
        
        # Instantiating your exact class with the incoming URL
        scraper = MenuScraper(url_str)
        
        # Executing your exact run method
        raw_items = await scraper.run()
        
        # Using your exact deduplication filter
        final_items = deduplicate(raw_items)
        
        if not final_items:
            raise HTTPException(status_code=404, detail="No menu items could be extracted from this URL.")
            
        return {
            "status": "success",
            "platform": scraper.platform,
            "restaurant_id": scraper.rid,
            "total_items": len(final_items),
            "data": final_items
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping engine error: {str(e)}")