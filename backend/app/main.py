from unicodedata import category
from fastapi import FastAPI
from fastapi import HTTPException
import uvicorn
from typing import Optional
import debugpy

from app.routers import companies
from app.schemas import AnalysisResponse, Company, Multipliers

app = FastAPI(title='Graham Analyzer')
app.include_router(companies.router)



@app.get('/health')
def health_check():
    return {'status': 'ok'}






#if __name__ == "__main__":
 #   debugpy.listen(("0.0.0.0", 5678))
   # print("Waiting for debugger attach...")
  #  debugpy.wait_for_client()
    

 #   uvicorn.run(app, host="0.0.0.0", port=8000)
