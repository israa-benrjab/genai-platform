from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import uvicorn
import os
import uuid
import io
import re
from typing import List, Optional
from datetime import datetime, timedelta
from jose import JWTError, jwt

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

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance

app = FastAPI(title="GenAI Platform API")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Environment ---
VLLM_URL = os.getenv("VLLM_URL", "http://vllm-service.ai:8000")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant-service.data:6333")
COLLECTION_NAME = "documents"
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Groq API key (set via environment variable)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "REDACTED")

# --- JWT ---
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

fake_users_db = {
    "admin": {"username": "admin", "password": "admin123", "role": "admin"},
    "analyst": {"username": "analyst", "password": "analyst123", "role": "analyst"},
    "user": {"username": "user", "password": "user123", "role": "user"}
}

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

class SummarizeRequest(BaseModel):
    text: str
    max_tokens: Optional[int] = 200
    model: Optional[str] = "qwen"

class ChatRequest(BaseModel):
    query: str
    max_tokens: Optional[int] = 300
    model: Optional[str] = "qwen"

class TranslateRequest(BaseModel):
    text: str
    source_lang: str = "auto"
    target_lang: str = "en"
    model: Optional[str] = "qwen"

class ClassifyRequest(BaseModel):
    text: str
    model: Optional[str] = "qwen"

class ActionItemsRequest(BaseModel):
    text: str
    model: Optional[str] = "qwen"

class ReportsRequest(BaseModel):
    doc_ids: List[str]
    template: str = "executive"
    model: Optional[str] = "qwen"

class ValidatePromptRequest(BaseModel):
    prompt: str

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

def scan_for_pii(text: str) -> List[dict]:
    patterns = {
        "Email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        "API Key": r'(sk-[A-Za-z0-9]{20,})|(ghp_[A-Za-z0-9]{36})|(gsk_[A-Za-z0-9]{20,})',
        "Phone": r'\b(\+?\d{1,3}[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b',
        "IP Address": r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
    }
    detected = []
    for label, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if matches:
            detected.append({"type": label, "count": len(matches)})
    return detected

async def call_llm(prompt: str, model: str, max_tokens: int = 200, temperature: float = 0.3) -> str:
    if model.startswith("groq"):
        groq_model = model.replace("groq/", "")
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": groq_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(GROQ_URL, json=payload, headers=headers, timeout=60.0)
                response.raise_for_status()
                result = response.json()
                # Debug: print Groq response (visible in logs)
                print(f"[DEBUG] Groq response: {result}")
                # Extract content, fallback to reasoning if content empty
                message = result["choices"][0]["message"]
                content = message.get("content", "")
                if not content:
                    content = message.get("reasoning", "")
                return content.strip()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Groq error: {str(e)}")
    else:
        payload = {
            "model": "Qwen/Qwen2-0.5B-Instruct",
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(f"{VLLM_URL}/v1/completions", json=payload, timeout=60.0)
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["text"].strip()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"vLLM error: {str(e)}")

@app.post("/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = fake_users_db.get(form_data.username)
    if not user or user["password"] != form_data.password:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = create_access_token(data={"sub": user["username"], "role": user["role"]})
    return {"access_token": token, "token_type": "bearer", "role": user["role"]}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/models")
async def list_models():
    return {
        "models": [
            {"id": "qwen", "name": "Qwen 0.5B (Local)", "available": True, "context_length": 256, "type": "local"},
            {"id": "groq/openai/gpt-oss-20b", "name": "Groq GPT OSS 20B (Cloud)", "available": True, "context_length": 131072, "type": "cloud"}
        ]
    }

@app.get("/tasks")
async def list_tasks(current_user: dict = Depends(get_current_user)):
    role = current_user["role"]
    return {
        "summarize": {"name": "Summarize", "allowed": True},
        "translate": {"name": "Translate", "allowed": role in ["admin", "analyst", "user"]},
        "classify": {"name": "Classify", "allowed": role in ["admin", "analyst"]},
        "action-items": {"name": "Action Items", "allowed": role in ["admin", "analyst"]},
        "reports": {"name": "Reports", "allowed": role in ["admin", "analyst"]},
        "chat": {"name": "RAG Chat", "allowed": True},
        "upload": {"name": "Upload Documents", "allowed": True}
    }

@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    contents = await file.read()
    text = extract_text_from_file(contents, file.filename)
    if not text or text.startswith("Error"):
        raise HTTPException(status_code=400, detail="Could not extract text.")
    
    pii_results = scan_for_pii(text)
    if pii_results:
        print(f"[SECURITY] PII detected in {file.filename}: {pii_results}")
    
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
    return {
        "message": f"Uploaded {file.filename}",
        "chunks": len(chunks),
        "pii_detected": pii_results if pii_results else None
    }

@app.get("/documents")
async def list_documents(current_user: dict = Depends(get_current_user)):
    return {"documents": []}

@app.post("/summarize")
async def summarize(request: SummarizeRequest, current_user: dict = Depends(get_current_user)):
    prompt = f"Summarize concisely:\n\n{request.text}\n\nSummary:"
    result = await call_llm(prompt, request.model, max_tokens=request.max_tokens, temperature=0.3)
    return {"summary": result, "tokens_used": len(result.split())}

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
    result = await call_llm(prompt, request.model, max_tokens=request.max_tokens, temperature=0.2)
    return {"answer": result, "sources": sources, "tokens_used": len(result.split())}

@app.post("/translate")
async def translate(request: TranslateRequest, current_user: dict = Depends(get_current_user)):
    prompt = f"Translate the following text from {request.source_lang} to {request.target_lang}:\n\n{request.text}\n\nTranslation:"
    result = await call_llm(prompt, request.model, max_tokens=80, temperature=0.2)
    return {"translated_text": result}

@app.post("/classify")
async def classify(request: ClassifyRequest, current_user: dict = Depends(get_current_user)):
    prompt = f"Classify the following text into a single category (e.g., Financial, Legal, Technical, Marketing, General):\n\n{request.text}\n\nCategory:"
    result = await call_llm(prompt, request.model, max_tokens=100, temperature=0.1)
    return {"category": result.strip(), "confidence": 0.85}

@app.post("/action-items")
async def action_items(request: ActionItemsRequest, current_user: dict = Depends(get_current_user)):
    prompt = f"""Extract action items from the following text. List each action with an assignee and a due date if mentioned. Use the format:
- Action: <description> | Assignee: <name> | Due: <date>

Text:
{request.text}

Action Items:"""
    result = await call_llm(prompt, request.model, max_tokens=80, temperature=0.3)
    items = [{"task": result, "assignee": "Unknown", "due": "Not specified"}]
    return {"items": items}

@app.post("/reports")
async def reports(request: ReportsRequest, current_user: dict = Depends(get_current_user)):
    prompt = f"""Generate a {request.template} report based on the following document IDs: {', '.join(request.doc_ids)}. Provide a concise summary with key insights in bullet points if possible.

Report:"""
    result = await call_llm(prompt, request.model, max_tokens=150, temperature=0.3)
    return {"report": result}

@app.post("/prompts/validate")
async def validate_prompt(request: ValidatePromptRequest, current_user: dict = Depends(get_current_user)):
    prompt = request.prompt
    injections = [
        "ignore previous instructions",
        "system prompt",
        "you are now",
        "forget your training",
        "jailbreak",
        "pretend to be",
        "override",
        "disregard",
    ]
    lower_prompt = prompt.lower()
    for injection in injections:
        if injection in lower_prompt:
            raise HTTPException(status_code=403, detail=f"Security Alert: Prompt injection detected ({injection})")
    return {"status": "clean", "message": "Prompt is safe."}

@app.get("/admin/users")
async def admin_users(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return {"users": [
        {"username": "admin", "role": "admin", "active": True},
        {"username": "analyst", "role": "analyst", "active": True},
        {"username": "user", "role": "user", "active": True}
    ]}

@app.get("/admin/usage")
async def admin_usage(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return {"usage": [{"date": datetime.utcnow().strftime("%Y-%m-%d"), "tokens": 100}]}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
