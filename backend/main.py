from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Claims Agent API is running ✅"}
