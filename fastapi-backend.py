from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import httpx
import uvicorn
import os
import uuid
import io
import re
import traceback
import json
import asyncio
from pathlib import Path
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

# Optional Azure Blob Storage
try:
    from azure.storage.blob import BlobServiceClient
except ImportError:
    BlobServiceClient = None

app = FastAPI(title="GenAI Platform API")

from prometheus_fastapi_instrumentator import Instrumentator

# Instrument the app and expose /metrics endpoint
Instrumentator().instrument(app).expose(app)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Environment ---
VLLM_URL = os.getenv("VLLM_URL", "http://vllm-service.ai:8000")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant-service.data:6333")
COLLECTION_NAME = "documents"
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is not set")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# Azure Blob Storage (optional)
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "uploaded-docs")

# --- Fake users with roles ---
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

# --- Role-based access helper ---
def require_role(required_roles: List[str]):
    def role_checker(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in required_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return role_checker

# --- File Storage Setup (for processed files) ---
UPLOAD_DIR = Path("/app/uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
METADATA_FILE = UPLOAD_DIR / "metadata.json"

def load_metadata():
    if METADATA_FILE.exists():
        with open(METADATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_metadata(data):
    with open(METADATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

uploaded_files_metadata = load_metadata()

# --- History Storage Setup (per user) ---
HISTORY_DIR = Path("/app/history")
HISTORY_DIR.mkdir(exist_ok=True)

def load_user_history(username: str) -> List[dict]:
    file_path = HISTORY_DIR / f"{username}.json"
    if file_path.exists():
        with open(file_path, "r") as f:
            return json.load(f)
    return []

def save_user_history(username: str, history: List[dict]):
    file_path = HISTORY_DIR / f"{username}.json"
    with open(file_path, "w") as f:
        json.dump(history, f, indent=2)

def log_action(username: str, action: str, details: dict):
    history = load_user_history(username)
    history.append({
        "id": str(uuid.uuid4()),
        "action": action,
        "details": details,
        "timestamp": datetime.utcnow().isoformat()
    })
    save_user_history(username, history)

# --- Load embedding model and connect to Qdrant ---
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

# --- Azure Blob Storage helper ---
def upload_to_azure_blob(file_bytes: bytes, filename: str) -> bool:
    if not AZURE_STORAGE_CONNECTION_STRING or not BlobServiceClient:
        return False
    try:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
        blob_client = container_client.get_blob_client(filename)
        blob_client.upload_blob(file_bytes, overwrite=True)
        return True
    except Exception as e:
        print(f"[ERROR] Azure Blob upload failed: {e}")
        return False

# --- Request Models ---
class SummarizeRequest(BaseModel):
    text: str
    max_tokens: Optional[int] = 300
    model: Optional[str] = "qwen"
    summary_length: Optional[str] = "standard"
    output_format: Optional[str] = "bullets"

class ChatRequest(BaseModel):
    query: str
    max_tokens: Optional[int] = 500
    model: Optional[str] = "qwen"
    doc_ids: Optional[List[str]] = None

class TranslateRequest(BaseModel):
    text: str
    source_lang: str = "auto"
    target_lang: str = "en"
    max_tokens: Optional[int] = 300
    model: Optional[str] = "qwen"

class ClassifyRequest(BaseModel):
    text: str
    model: Optional[str] = "qwen"

class ActionItemsRequest(BaseModel):
    text: str
    max_tokens: Optional[int] = 200
    model: Optional[str] = "qwen"

class ReportsRequest(BaseModel):
    doc_ids: List[str]
    template: str = "executive"
    max_tokens: Optional[int] = 500
    model: Optional[str] = "qwen"

class ValidatePromptRequest(BaseModel):
    prompt: str

# --- Helper functions ---
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
        if not GROQ_API_KEY:
            raise HTTPException(status_code=500, detail="GROQ_API_KEY is not set.")
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
                message = result["choices"][0]["message"]
                content = message.get("content", "")
                if not content:
                    content = message.get("reasoning", "")
                return content.strip()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Groq error: {str(e)}")
    else:
        # Local Llama 3.2 1B (served by llama-cpp-python)
        # NOTE: No 'model' field is sent because llama-cpp-python rejects it.
        payload = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{VLLM_URL}/v1/completions",
                    json=payload,
                    timeout=300.0
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["text"].strip()
            except Exception as e:
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"Local LLM error: {str(e)}")

# --- ENDPOINTS ---

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
            {"id": "qwen", "name": "Llama 3.2 1B (Local)", "available": True, "context_length": 1024, "type": "local"},
            {"id": "groq/openai/gpt-oss-20b", "name": "Groq GPT OSS 20B (Cloud)", "available": True, "context_length": 131072, "type": "cloud"}
        ]
    }

@app.get("/tasks")
async def list_tasks(current_user: dict = Depends(get_current_user)):
    role = current_user["role"]
    return {
        "summarize": {"name": "Summarize", "allowed": role in ["admin", "analyst", "user"]},
        "translate": {"name": "Translate", "allowed": role in ["admin", "analyst", "user"]},
        "classify": {"name": "Classify", "allowed": role in ["admin", "analyst"]},
        "action-items": {"name": "Action Items", "allowed": role in ["admin", "analyst"]},
        "reports": {"name": "Reports", "allowed": role in ["admin", "analyst"]},
        "chat": {"name": "RAG Chat", "allowed": True},
        "upload": {"name": "Upload Documents", "allowed": True}
    }

# --- Document Upload for RAG (with owner) ---
@app.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_role(["admin", "analyst", "user"]))
):
    contents = await file.read()
    text = extract_text_from_file(contents, file.filename)
    if not text or text.startswith("Error"):
        raise HTTPException(status_code=400, detail="Could not extract text.")
    
    if AZURE_STORAGE_CONNECTION_STRING and BlobServiceClient:
        try:
            upload_to_azure_blob(contents, file.filename)
        except Exception as e:
            print(f"[WARNING] Azure Blob upload failed: {e}")

    pii_results = scan_for_pii(text)
    if pii_results:
        print(f"[SECURITY] PII detected in {file.filename}: {pii_results}")
    
    chunks = chunk_text(text)
    embeddings = embedding_model.encode(chunks)
    points = []
    doc_id = str(uuid.uuid4())
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=emb.tolist(),
            payload={
                "doc_id": doc_id,
                "filename": file.filename,
                "chunk_index": i,
                "text": chunk,
                "owner": current_user["username"]
            }
        ))
    qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
    log_action(current_user["username"], "upload_document", {"filename": file.filename, "chunks": len(chunks)})
    return {
        "message": f"Uploaded {file.filename}",
        "doc_id": doc_id,
        "chunks": len(chunks),
        "pii_detected": pii_results if pii_results else None
    }

@app.get("/documents")
async def list_documents(current_user: dict = Depends(require_role(["admin", "analyst", "user"]))):
    try:
        results = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            limit=1000,
            with_payload=True,
            with_vectors=False
        )
        points = results[0]
        filtered_points = []
        for point in points:
            owner = point.payload.get("owner")
            if current_user["role"] == "admin" or owner == current_user["username"]:
                filtered_points.append(point)
        
        doc_map = {}
        for point in filtered_points:
            payload = point.payload
            doc_id = payload.get("doc_id")
            filename = payload.get("filename")
            if doc_id and doc_id not in doc_map:
                doc_map[doc_id] = {
                    "doc_id": doc_id,
                    "filename": filename,
                    "chunk_count": 0
                }
            if doc_id in doc_map:
                doc_map[doc_id]["chunk_count"] += 1
        return {"documents": list(doc_map.values())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not fetch documents: {str(e)}")

@app.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, current_user: dict = Depends(require_role(["admin", "analyst", "user"]))):
    try:
        qdrant_client.delete(
            collection_name=COLLECTION_NAME,
            points_selector={"filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]}}
        )
        log_action(current_user["username"], "delete_document", {"doc_id": doc_id})
        return {"message": f"Document {doc_id} deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- TYPED TEXT ENDPOINTS ---

@app.post("/summarize")
async def summarize(
    request: SummarizeRequest,
    current_user: dict = Depends(require_role(["admin", "analyst", "user"]))
):
    length_map = {
        "brief": "Provide a very short summary (1–2 sentences).",
        "standard": "Provide a concise summary with 3–5 main points.",
        "comprehensive": "Provide a detailed, comprehensive summary covering all key aspects."
    }
    length_instruction = length_map.get(request.summary_length, "Provide a concise summary with 3–5 main points.")
    
    if request.output_format == "bullets":
        format_instruction = "Use bullet points."
    else:
        format_instruction = "Write as a single executive paragraph."

    prompt = f"""You are an expert summarizer. {length_instruction} {format_instruction}

Text:
{request.text}

Summary:"""
    result = await call_llm(prompt, request.model, max_tokens=request.max_tokens, temperature=0.3)
    log_action(current_user["username"], "summarize", {"text_preview": request.text[:100], "tokens_used": len(result.split())})
    return {"summary": result, "tokens_used": len(result.split())}

@app.post("/translate")
async def translate(
    request: TranslateRequest,
    current_user: dict = Depends(require_role(["admin", "analyst", "user"]))
):
    prompt = f"""You are a professional translator. Translate the following text from {request.source_lang} to {request.target_lang}.

IMPORTANT RULES:
- Output ONLY the translated text. No explanations, no greetings, no disclaimers.
- If the source language is 'auto', detect the language automatically.
- Preserve the original meaning and tone.
- If you cannot translate, return the original text unchanged.

Text to translate:
{request.text}

Translation:"""
    result = await call_llm(prompt, request.model, max_tokens=request.max_tokens, temperature=0.1)
    log_action(current_user["username"], "translate", {"source_lang": request.source_lang, "target_lang": request.target_lang})
    return {"translated_text": result}

@app.post("/classify")
async def classify(
    request: ClassifyRequest,
    current_user: dict = Depends(require_role(["admin", "analyst"]))
):
    prompt = f"""Classify the following text into exactly one category: Financial, Legal, Technical, Marketing, General. Respond with only the category name.

Text:
{request.text}

Category:"""
    result = await call_llm(prompt, request.model, max_tokens=50, temperature=0.1)
    log_action(current_user["username"], "classify", {"category": result.strip()})
    return {"category": result.strip(), "confidence": 0.85}

@app.post("/action-items")
async def action_items(
    request: ActionItemsRequest,
    current_user: dict = Depends(require_role(["admin", "analyst"]))
):
    prompt = f"""Extract all action items from the text below. List each action in this format:
- Action: <description> | Assignee: <person> | Due: <date or 'Not specified'>

If the text does not contain any action items, respond with "No action items found."

Text:
{request.text}

Action Items:"""
    result = await call_llm(prompt, request.model, max_tokens=request.max_tokens, temperature=0.3)
    items = [{"task": result, "assignee": "Unknown", "due": "Not specified"}]
    log_action(current_user["username"], "action_items", {"text_preview": request.text[:100]})
    return {"items": items}

@app.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: dict = Depends(require_role(["admin", "analyst", "user"]))
):
    query_emb = embedding_model.encode([request.query])[0]
    
    filter_condition = None
    if request.doc_ids:
        filter_condition = {
            "must": [{"key": "doc_id", "match": {"any": request.doc_ids}}]
        }
    
    async with httpx.AsyncClient() as client:
        search_payload = {
            "vector": query_emb.tolist(),
            "limit": 3,
            "with_payload": True,
            "with_vector": False
        }
        if filter_condition:
            search_payload["filter"] = filter_condition

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
    
    prompt = f"""You are a helpful assistant. Use the provided context to answer the user's question. If the context does not contain the answer, say "I don't have enough information." Always cite sources as [Source X].

Context:
{context}

Question: {request.query}

Answer:"""
    
    if len(prompt) > 3000:
        prompt = prompt[:3000] + "... (truncated)"
    
    result = await call_llm(prompt, request.model, max_tokens=request.max_tokens, temperature=0.2)
    log_action(current_user["username"], "chat", {"query": request.query, "sources": sources})
    return {"answer": result, "sources": sources, "tokens_used": len(result.split())}

@app.post("/reports")
async def reports(
    request: ReportsRequest,
    current_user: dict = Depends(require_role(["admin", "analyst"]))
):
    context = ""
    sources = []
    try:
        results = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            limit=1000,
            with_payload=True,
            with_vectors=False
        )
        points = results[0]
        for point in points:
            payload = point.payload
            doc_id = payload.get("doc_id")
            if doc_id in request.doc_ids:
                filename = payload.get("filename", "unknown")
                chunk_text = payload.get("text", "")
                context += f"({filename}): {chunk_text}\n"
                sources.append(filename)
        if not context:
            raise HTTPException(status_code=404, detail="No content found for the given document IDs.")
        
        context = context[:2000]
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to retrieve documents: {str(e)}")

    template_map = {
        "executive": "Executive Brief – Provide a high‑level overview, key findings, and actionable recommendations.",
        "comparative": "Comparative Market Analysis – Compare and contrast the main themes, identify trends, and highlight strengths/weaknesses.",
        "technical": "Technical Audit & Review – Focus on technical details, performance metrics, risks, and compliance.",
    }
    template_instruction = template_map.get(request.template, "Executive Brief – Provide a high‑level overview, key findings, and actionable recommendations.")

    prompt = f"""Generate a {template_instruction}

Use the following excerpts from the selected documents to inform your report. Organise the report with clear headings and bullet points where appropriate.

Document excerpts:
{context}

Report:"""
    try:
        result = await call_llm(prompt, request.model, max_tokens=request.max_tokens, temperature=0.3)
        unique_sources = list(set(sources))
        log_action(current_user["username"], "reports", {"template": request.template, "doc_ids": request.doc_ids})
        return {"report": result, "sources": unique_sources, "tokens_used": len(result.split())}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")

# --- FILE PROCESSING (Upload & Save) ---

@app.post("/process-file")
async def process_file(
    file: UploadFile = File(...),
    task: str = "summarize",
    model: Optional[str] = "qwen",
    max_tokens: Optional[int] = 200,
    source_lang: Optional[str] = "auto",
    target_lang: Optional[str] = "en",
    current_user: dict = Depends(require_role(["admin", "analyst", "user"]))
):
    contents = await file.read()
    text = extract_text_from_file(contents, file.filename)
    if not text or text.startswith("Error"):
        raise HTTPException(status_code=400, detail="Could not extract text from file.")
    
    if len(text) > 1000:
        text = text[:1000] + "... (truncated)"
    
    file_id = str(uuid.uuid4())
    original_filename = file.filename
    ext = original_filename.split('.')[-1] if '.' in original_filename else ''
    safe_name = f"{file_id}.{ext}" if ext else file_id
    file_path = UPLOAD_DIR / safe_name
    with open(file_path, "wb") as f:
        f.write(contents)
    
    uploaded_files_metadata[file_id] = {
        "original_filename": original_filename,
        "uploaded_at": datetime.utcnow().isoformat(),
        "size": len(contents),
        "task": task,
        "model": model
    }
    save_metadata(uploaded_files_metadata)

    if task == "summarize":
        prompt = f"""You are an expert summarizer. Provide a concise summary with 3–5 main points, using bullet points.

Text:
{text}

Summary:"""
    elif task == "translate":
        prompt = f"""You are a professional translator. Translate the following text from {source_lang} to {target_lang}.
Output ONLY the translated text. No explanations.

Text to translate:
{text}

Translation:"""
    elif task == "classify":
        prompt = f"""Classify the following text into exactly one category: Financial, Legal, Technical, Marketing, General. Respond with only the category name.

Text:
{text}

Category:"""
    elif task == "action-items":
        prompt = f"""Extract all action items from the text below. List each action in this format:
- Action: <description> | Assignee: <person> | Due: <date or 'Not specified'>

If the text does not contain any action items, respond with "No action items found."

Text:
{text}

Action Items:"""
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported task: {task}")

    result = await call_llm(prompt, model, max_tokens=max_tokens, temperature=0.3)
    log_action(current_user["username"], f"process_file_{task}", {"filename": original_filename})
    return {
        "task": task,
        "result": result,
        "tokens_used": len(result.split()),
        "filename": original_filename,
        "file_id": file_id
    }

# --- FILE MANAGEMENT ---

@app.get("/files")
async def list_uploaded_files(current_user: dict = Depends(require_role(["admin", "analyst", "user"]))):
    return {"files": uploaded_files_metadata}

@app.get("/files/{file_id}")
async def download_file(file_id: str, current_user: dict = Depends(require_role(["admin", "analyst", "user"]))):
    if file_id not in uploaded_files_metadata:
        raise HTTPException(status_code=404, detail="File not found")
    meta = uploaded_files_metadata[file_id]
    ext = meta["original_filename"].split('.')[-1] if '.' in meta["original_filename"] else ''
    safe_name = f"{file_id}.{ext}" if ext else file_id
    file_path = UPLOAD_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(path=file_path, filename=meta["original_filename"])

@app.delete("/files/{file_id}")
async def delete_file(file_id: str, current_user: dict = Depends(require_role(["admin"]))):
    if file_id not in uploaded_files_metadata:
        raise HTTPException(status_code=404, detail="File not found")
    meta = uploaded_files_metadata[file_id]
    ext = meta["original_filename"].split('.')[-1] if '.' in meta["original_filename"] else ''
    safe_name = f"{file_id}.{ext}" if ext else file_id
    file_path = UPLOAD_DIR / safe_name
    if file_path.exists():
        file_path.unlink()
    del uploaded_files_metadata[file_id]
    save_metadata(uploaded_files_metadata)
    log_action(current_user["username"], "delete_file", {"file_id": file_id})
    return {"message": f"File {file_id} deleted"}

# --- COMPARE DOCUMENTS ---

@app.post("/compare")
async def compare_documents(
    doc_id_1: str,
    doc_id_2: str,
    model: Optional[str] = "qwen",
    max_tokens: Optional[int] = 400,
    current_user: dict = Depends(require_role(["admin", "analyst", "user"]))
):
    try:
        results = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            limit=1000,
            with_payload=True,
            with_vectors=False
        )
        points = results[0]
        texts = []
        for point in points:
            if point.payload.get("doc_id") in [doc_id_1, doc_id_2]:
                texts.append({
                    "doc_id": point.payload.get("doc_id"),
                    "filename": point.payload.get("filename"),
                    "text": point.payload.get("text", "")
                })
        if len(texts) < 2:
            raise HTTPException(status_code=404, detail="One or both documents not found.")
        doc1_text = " ".join([t["text"] for t in texts if t["doc_id"] == doc_id_1])[:3000]
        doc2_text = " ".join([t["text"] for t in texts if t["doc_id"] == doc_id_2])[:3000]
        
        prompt = f"""You are an expert analyst. Compare the following two documents.
List:
- Key similarities
- Key differences
- Missing information in each document (what one has that the other lacks)

Document A ({texts[0]['filename']}):
{doc1_text}

Document B ({texts[1]['filename']}):
{doc2_text}

Comparison:"""
        result = await call_llm(prompt, model, max_tokens=max_tokens, temperature=0.3)
        log_action(current_user["username"], "compare_documents", {"doc_id_1": doc_id_1, "doc_id_2": doc_id_2})
        return {
            "comparison": result,
            "documents": [texts[0]["filename"], texts[1]["filename"]],
            "tokens_used": len(result.split())
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# --- COMPARE MODELS (with truncation) ---

@app.post("/compare-models")
async def compare_models(
    prompt: str,
    model1: str = "qwen",
    model2: str = "groq/openai/gpt-oss-20b",
    max_tokens: Optional[int] = 200,
    current_user: dict = Depends(require_role(["admin", "analyst", "user"]))
):
    # --- TRUNCATE PROMPT TO SAFE LENGTH ---
    if len(prompt) > 2000:
        prompt = prompt[:2000] + "... (truncated)"
    # ------------------------------------

    # Detect code/prompt type and add system instruction
    if "code" in prompt.lower() or "python" in prompt.lower():
        system = "You are a code generator. Output only Python code, no explanations, no markdown."
        prompt = f"{system}\n\n{prompt}"
    else:
        system = "You are an expert assistant. Provide a clear, concise, and structured response. If the question asks for differences, list them in bullet points or a table."
        prompt = f"{system}\n\nQuestion: {prompt}\n\nAnswer:"

    temperature = 0.0
    results = await asyncio.gather(
        call_llm(prompt, model1, max_tokens, temperature),
        call_llm(prompt, model2, max_tokens, temperature)
    )
    log_action(current_user["username"], "compare_models", {
        "model1": model1,
        "model2": model2,
        "prompt_preview": prompt[:50]
    })
    return {
        "model1": model1,
        "model2": model2,
        "response1": results[0],
        "response2": results[1],
        "tokens_used": len(results[0].split()) + len(results[1].split())
    }

# --- ROLE-BASED STATS ENDPOINT ---

@app.get("/stats")
async def get_stats(current_user: dict = Depends(get_current_user)):
    role = current_user["role"]
    username = current_user["username"]

    try:
        results = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            limit=10000,
            with_payload=True,
            with_vectors=False
        )
        all_points = results[0]
        all_docs = set()
        user_docs = set()
        for point in all_points:
            doc_id = point.payload.get("doc_id")
            owner = point.payload.get("owner")
            if doc_id:
                all_docs.add(doc_id)
                if owner == username:
                    user_docs.add(doc_id)
    except Exception as e:
        all_docs = set()
        user_docs = set()

    total_files = len(uploaded_files_metadata)

    if role == "admin":
        return {
            "role": "admin",
            "total_users": len(fake_users_db),
            "total_documents": len(all_docs),
            "total_processed_files": total_files,
            "message": "Welcome, Admin. You have full visibility."
        }
    elif role == "analyst":
        return {
            "role": "analyst",
            "your_documents": len(user_docs),
            "total_processed_files": total_files,
            "message": "Welcome, Analyst. You can access advanced analytics."
        }
    else:
        return {
            "role": "user",
            "your_documents": len(user_docs),
            "total_processed_files": total_files,
            "message": "Welcome, User. You have basic summarization and chat access."
        }

# --- HISTORY ENDPOINT (with logging) ---

@app.get("/history")
async def get_history(current_user: dict = Depends(require_role(["admin", "analyst", "user"]))):
    history = load_user_history(current_user["username"])
    return {"history": history}

# --- ADMIN ENDPOINTS ---

@app.get("/admin/users")
async def admin_users(current_user: dict = Depends(require_role(["admin"]))):
    return {"users": [
        {"username": "admin", "role": "admin", "active": True},
        {"username": "analyst", "role": "analyst", "active": True},
        {"username": "user", "role": "user", "active": True}
    ]}

@app.get("/admin/usage")
async def admin_usage(current_user: dict = Depends(require_role(["admin"]))):
    return {"usage": [{"date": datetime.utcnow().strftime("%Y-%m-%d"), "tokens": 100}]}

@app.post("/prompts/validate")
async def validate_prompt(request: ValidatePromptRequest, current_user: dict = Depends(require_role(["admin", "analyst", "user"]))):
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
