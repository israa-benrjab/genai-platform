from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import uvicorn
import os
import uuid
import io
from typing import List
from datetime import datetime, timedelta
from jose import JWTError, jwt

# Document processing (optional)
try:
    import pypdf
except ImportError:
    pypdf = None
try:
    import docx
except ImportError:
    docx = None
try:
    import pandas as pd
except ImportError:
    pd = None
try:
    from pptx import Presentation
except ImportError:
    Presentation = None
try:
    from PIL import Image
except ImportError:
    Image = None

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance

app = FastAPI(title="GenAI Platform API")

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuration ---
VLLM_URL = os.getenv("VLLM_URL", "http://vllm-service.ai:8000")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant-service.data:6333")
COLLECTION_NAME = "documents"
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# --- JWT Config ---
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# --- Fake user DB (plaintext passwords for demo) ---
fake_users_db = {
    "admin": {
        "username": "admin",
        "password": "admin123",
        "role": "admin"
    },
    "analyst": {
        "username": "analyst",
        "password": "analyst123",
        "role": "analyst"
    },
    "user": {
        "username": "user",
        "password": "user123",
        "role": "user"
    }
}

# --- JWT helper functions ---
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = fake_users_db.get(username)
    if user is None:
        raise credentials_exception
    return user

# --- Initialization ---
print("Loading Embedding Model...")
embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
print("Embedding Model loaded.")

print("Connecting to Qdrant...")
qdrant_client = QdrantClient(url=QDRANT_URL)
try:
    qdrant_client.get_collection(COLLECTION_NAME)
except:
    qdrant_client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE)
    )
print("Qdrant ready.")

# --- Pydantic Models ---
class SummarizeRequest(BaseModel):
    text: str
    max_tokens: int = 200

class ChatRequest(BaseModel):
    query: str
    max_tokens: int = 300

# --- Helper Functions ---
def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    ext = filename.split('.')[-1].lower()
    text = ""
    try:
        if ext == "txt":
            text = file_bytes.decode('utf-8')
        elif ext == "pdf" and pypdf:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages:
                text += page.extract_text() + "\n"
        elif ext == "docx" and docx:
            doc = docx.Document(io.BytesIO(file_bytes))
            for para in doc.paragraphs:
                text += para.text + "\n"
        else:
            text = "Unsupported file type."
    except Exception as e:
        text = f"Error: {str(e)}"
    return text

def chunk_text(text: str, chunk_size: int = 500) -> List[str]:
    words = text.split()
    return [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]

# --- Auth Endpoint ---
@app.post("/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = fake_users_db.get(form_data.username)
    if not user or user["password"] != form_data.password:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"], "role": user["role"]},
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "role": user["role"]}

# --- Health & Protected Endpoints ---
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/summarize")
async def summarize(request: SummarizeRequest, current_user: dict = Depends(get_current_user)):
    prompt = f"Summarize concisely:\n\n{request.text}\n\nSummary:"
    payload = {
        "model": "Qwen/Qwen2-0.5B-Instruct",   # <--- FIXED for vLLM
        "prompt": prompt,
        "max_tokens": request.max_tokens,
        "temperature": 0.3
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{VLLM_URL}/v1/completions", json=payload, timeout=60.0)
            response.raise_for_status()
            result = response.json()
            summary = result["choices"][0]["text"].strip()
            return {"summary": summary, "tokens_used": len(summary.split())}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    contents = await file.read()
    text = extract_text_from_file(contents, file.filename)
    if not text or text.startswith("Error"):
        raise HTTPException(status_code=400, detail="Could not extract text.")
    chunks = chunk_text(text)
    embeddings = embedding_model.encode(chunks)
    points = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=emb.tolist(),
            payload={"filename": file.filename, "chunk_index": i, "text": chunk}
        ))
    qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
    return {"message": f"Uploaded {file.filename}", "chunks": len(chunks)}

@app.post("/chat")
async def chat(request: ChatRequest, current_user: dict = Depends(get_current_user)):
    query_emb = embedding_model.encode([request.query])[0]
    
    async with httpx.AsyncClient() as client:
        search_payload = {
            "vector": query_emb.tolist(),
            "limit": 3,
            "with_payload": True,
            "with_vector": False
        }
        try:
            response = await client.post(
                f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points/search",
                json=search_payload,
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()
            search_results = result.get("result", [])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Qdrant search failed: {str(e)}")
    
    context = ""
    sources = []
    for i, res in enumerate(search_results):
        payload = res.get("payload", {})
        chunk_text = payload.get("text", "")
        filename = payload.get("filename", "unknown")
        context += f"Source {i+1} ({filename}): {chunk_text}\n"
        sources.append({"filename": filename, "score": res.get("score", 0)})
    
    prompt = f"""Use context to answer. If irrelevant, say don't know. Cite sources as [Source X].

Context:
{context}

Query: {request.query}

Answer:"""
    payload = {
        "model": "Qwen/Qwen2-0.5B-Instruct",   # <--- FIXED for vLLM
        "prompt": prompt,
        "max_tokens": request.max_tokens,
        "temperature": 0.2
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{VLLM_URL}/v1/completions", json=payload, timeout=60.0)
            response.raise_for_status()
            result = response.json()
            answer = result["choices"][0]["text"].strip()
            return {"answer": answer, "sources": sources, "tokens_used": len(answer.split())}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM call failed: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
