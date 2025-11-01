from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from routers import upload

app = FastAPI()

app.include_router(upload.router)
app.mount("/files", StaticFiles(directory="uploads"), name="files")

@app.get("/")
def root():
    return {"message": "Claims Agent API running ✅"}
