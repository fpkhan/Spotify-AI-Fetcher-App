from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from typing import List
import pandas as pd
import shutil
import os
import json
import urllib
import logging
import httpx
from sqlalchemy import create_engine
import ollama
from groq import Groq
from Credentials import DB_USER as user, DB_PASSWORD as password

app = FastAPI()

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Groq client (Reads GROQ_API_KEY from environment)
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Initialize Explicit Ollama Client to target the host machine loopback address inside Docker
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
ollama_client = ollama.Client(host=OLLAMA_HOST)

# Spotify OAuth Configuration Variables
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8000/api/callback"

# Establish connection engine to your Azure cloud server
server = 'jio-internship-server.database.windows.net'
database = 'SpotifyDB'
connection_string = f'Driver={{ODBC Driver 18 for SQL Server}};Server=tcp:{server},1433;Database={database};Uid={user};Pwd={password};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=50;'
params = urllib.parse.quote_plus(connection_string)
engine = create_engine(f'mssql+pyodbc:///?odbc_connect={params}')

current_status = "Ready"

# Pydantic Schemas
class SearchIntent(BaseModel):
    clean_vibe_query: str = Field(description="The core emotional vibe, mood, or topic to convert into a vector.")
    limit: int = Field(default=5, description="The exact number of songs requested. Default to 5 if unspecified.")
    sort_order: str = Field(default="ASC", description="Must be 'ASC' for best/closest matches, or 'DESC' for worst/furthest matches.")

class RAGQueryRequest(BaseModel):
    query: str

class PlaylistRequest(BaseModel):
    token: str
    playlist_name: str
    track_ids: List[str]

@app.post("/api/transcribe")
async def transcribe_audio_to_text(file: UploadFile = File(...)):
    """Accepts incoming browser audio files and transcribes them to raw text strings via Groq Whisper."""
    global current_status
    current_status = "Processing dictation audio format..."
    
    incoming_filename = file.filename if file.filename else "incoming_dictation.webm"
    temp_filepath = f"temp_{incoming_filename}"
    
    try:
        with open(temp_filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        print(f">>> Audio file staged as {temp_filepath}. Sending payload to Groq Whisper API...")
        current_status = "Transcribing voice on Groq hardware..."
        
        with open(temp_filepath, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
                file=(temp_filepath, audio_file.read()),
                model="whisper-large-v3",
                response_format="json"
            )
            
        detected_text = transcription.text
        print(f">>> Speech transcription complete: '{detected_text}'")
        
        current_status = "Ready"
        return {"status": "success", "text": detected_text}
        
    except Exception as e:
        current_status = f"Transcription Error: {str(e)}"
        print(f">>> [Whisper Error] {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)

@app.post("/api/query-rag")
async def trigger_text_rag_query(request: RAGQueryRequest):
    """Executes native vector similarity calculation in Azure SQL and synthesizes advice via Groq."""
    global current_status
    user_text = request.query
    
    if not user_text.strip():
        raise HTTPException(status_code=400, detail="Query text cannot be empty.")
    
    try:
        # 1. INTENT EXTRACTION LAYER
        current_status = "Analyzing search intent and volume constraints..."
        intent_limit = 5      
        order_clause = "ASC"  
        clean_query = user_text

        try:
            intent_completion = groq_client.chat.completions.create(
                messages=[
                    {
                        "role": "system", 
                        "content": (
                            "You are a precise search intent analyzer. Extract variables from the user prompt as a JSON object. "
                            "Required JSON keys:\n"
                            "1. 'limit': exact integer requested (default to 5 if not mentioned, cap at 50).\n"
                            "2. 'sort_order': Use 'DESC' only if they ask for 'worst/hated/furthest/least liked' tracks, else use 'ASC'.\n"
                            "3. 'clean_query': The core musical concept or mood isolated from structural words."
                            "4. return all answers in the latin alphabet"
                        )
                    },
                    {"role": "user", "content": user_text}
                ],
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                temperature=0.0
            )
            
            intent_text = intent_completion.choices[0].message.content
            intent_json = json.loads(intent_text)
            
            intent_limit = min(max(int(intent_json.get("limit", 5)), 1), 50)
            order_clause = "DESC" if intent_json.get("sort_order") == "DESC" else "ASC"
            clean_query = intent_json.get("clean_query", user_text)
            
        except Exception as e:
            logger.warning(f"Intent extraction fell back to defaults: {e}")
    
        # 2. RETRIEVAL (Explicit Ollama Container Client Hook)
        current_status = "Computing semantic query vector embeddings..."
        try:
            # FIXED: Routing execution sequence through the client mapping instead of package namespace root
            response = ollama_client.embeddings(model="nomic-embed-text", prompt=clean_query)

            query_vector = None
            if isinstance(response, dict):
                if "embedding" in response:
                    query_vector = response["embedding"]
                elif "data" in response and isinstance(response["data"], list) and response["data"]:
                    first = response["data"][0]
                    if isinstance(first, dict) and "embedding" in first:
                        query_vector = first["embedding"]
                elif "embeddings" in response:
                    query_vector = response["embeddings"]

            if query_vector is None:
                try:
                    query_vector = getattr(response, "embedding", None)
                except Exception:
                    query_vector = None

            if not query_vector:
                raise ValueError(f"No embedding found in Ollama response: {type(response)}")

            json_vector_str = json.dumps(query_vector)
        except Exception as e:
            logger.exception("Failed to compute embeddings")
            current_status = f"Error computing embeddings: {str(e)}"
            raise HTTPException(status_code=500, detail=f"Embedding error: {str(e)}")
        
        current_status = "Searching cloud records for concept matches..."
        
        similarity_query = f"""
        SELECT TOP ({intent_limit}) 
            id,
            name, 
            artists,
            VECTOR_DISTANCE('cosine', embedding, CAST(CAST(? AS VARCHAR(MAX)) AS VECTOR(768))) AS distance
        FROM track_data
        WHERE embedding IS NOT NULL
        ORDER BY distance {order_clause};
        """
        
        with engine.raw_connection() as raw_conn:
            cursor = raw_conn.cursor()
            cursor.execute(similarity_query, (json_vector_str,))
            
            db_results = []
            for row in cursor.fetchall():
                db_results.append({
                    "id": row[0],
                    "name": row[1],
                    "artists": row[2],
                    "distance": float(row[3]) if row[3] is not None else 0.0
                })

        if not db_results:
            current_status = "Done"
            return {
                "status": "success",
                "ai_response": "No matching vectors found in your Azure database tracks.",
                "tracks": []
            }

        # 3. AUGMENTATION & GENERATION (Groq Llama 3.3 Integration)
        current_status = "Formulating smart AI recommendations..."
        context_string = "\n".join([
            f"- '{t.get('name', 'Unknown Title')}' by {t.get('artists', 'Unknown Artist')} (Distance: {t.get('distance', 0.0):.4f})" 
            for t in db_results
        ])
        system_prompt = (
            "You are a brilliant Spotify AI recommendation assistant. "
            "Your job is to analyze the matching tracks pulled from the user's database and present them "
            "conversationally. Explain briefly why these recommendations suit their mood or requested concept."
        )
        
        user_prompt = f"User Request: '{user_text}'\n\nRetrieved {intent_limit} Matches From Azure Database:\n{context_string}"
        
        ai_paragraph = None
        try:
            chat_completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model="llama-3.3-70b-versatile",
                temperature=0.7
            )

            if hasattr(chat_completion, "choices") and chat_completion.choices:
                choice = chat_completion.choices[0]
                ai_paragraph = getattr(choice, "message", None)
                if ai_paragraph:
                    ai_paragraph = getattr(ai_paragraph, "content", None) or ai_paragraph
            if not ai_paragraph and isinstance(chat_completion, dict):
                try:
                    ai_paragraph = (chat_completion.get("choices", [])[0].get("message", {}).get("content"))
                except Exception:
                    ai_paragraph = None

            if not ai_paragraph:
                ai_paragraph = str(chat_completion)

        except Exception as e:
            logger.exception("Groq chat completion failed")
            ai_paragraph = f"AI generation failed: {str(e)}"
        current_status = "Done"
        
        return {
            "status": "success",
            "ai_response": ai_paragraph,
            "tracks": db_results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled error in /api/query-rag")
        current_status = f"Error: {str(e)}"
        raise HTTPException(status_code=500, detail=str(e))

# ----------------------------------------------------------------------
# SPOTIFY OAUTH & PLAYLIST CREATION LAYER
# ----------------------------------------------------------------------

@app.get("/api/login")
def spotify_login():
    """Redirects the client interface to Spotify's secure Authorization node with properly formatted explicit query params."""
    # Explicitly comma-separate or space-separate according to standard web parameters
    scope = "playlist-modify-public playlist-modify-private user-read-private user-read-email"
    
    # We will let standard urllib build this request dictionary to prevent format string dropping bugs
    query_params = {
        "response_type": "code",
        "client_id": SPOTIFY_CLIENT_ID,
        "scope": scope,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "show_dialog": "true" # <-- CRITICAL: This forces Spotify to show the prompt again instead of bypassing it!
    }
    
    encoded_params = urllib.parse.urlencode(query_params)
    spotify_url = f"https://accounts.spotify.com/authorize?{encoded_params}"
    
    logger.info(f"Redirecting user to Spotify Authorization node with explicit parameters: {spotify_url}")
    return RedirectResponse(url=spotify_url)

@app.get("/api/callback")
async def spotify_callback(code: str):
    """Exchanges code parameter for operational network tokens and redirects back to Vite frontend."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": SPOTIFY_REDIRECT_URI,
                "client_id": SPOTIFY_CLIENT_ID,
                "client_secret": SPOTIFY_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
    
    if response.status_code != 200:
        logger.error(f"Token Exchange Error: {response.text}")
        raise HTTPException(status_code=400, detail="Failed to retrieve functional authorization token.")
        
    token_data = response.json()
    logger.info(f"Token Exchange Success: {token_data['access_token']}")
    frontend_url = f"http://localhost:5173/#access_token={token_data['access_token']}"
    return RedirectResponse(url=frontend_url)

@app.post("/api/create-playlist")
async def create_playlist(data: PlaylistRequest):
    """Creates a new playlist container on the target Spotify user profile and attaches tracks."""
    headers = {"Authorization": f"Bearer {data.token}"}

    async with httpx.AsyncClient() as client:
        # Step 1: Identify current Spotify User profile ID
        user_res = await client.get("https://api.spotify.com/v1/me", headers=headers)
        if user_res.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid or expired Spotify token credential context.")

        user_data = user_res.json()
        user_id = user_data["id"]

        # Step 2: Establish new empty playlist
        # NOTE: Spotify removed POST /users/{user_id}/playlists in its Feb 2026 API
        # changes. Playlist creation now always targets the authenticated user via
        # POST /me/playlists (no user id in the path).
        playlist_res = await client.post(
            "https://api.spotify.com/v1/me/playlists",
            json={
                "name": data.playlist_name,
                "description": "Generated via Decoupled Semantic Discovery Engine Architecture.",
                "public": False
            },
            headers=headers
        )
        if playlist_res.status_code not in [200, 201]:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to initialize new playlist container: {playlist_res.status_code} {playlist_res.text}"
            )
        playlist_id = playlist_res.json()["id"]

        # Step 3: Parse IDs into standardized uniform resource indicators (URIs)
        track_uris = [f"spotify:track:{tid}" if not str(tid).startswith("spotify:") else tid for tid in data.track_ids]

        # Step 4: Inject tracks directly into the newly constructed target ID block
        # NOTE: Spotify renamed playlist track-management endpoints from /tracks to
        # /items in the same Feb 2026 update.
        add_res = await client.post(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/items",
            json={"uris": track_uris},
            headers=headers
        )
        if add_res.status_code not in [200, 201]:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to push track array to target playlist endpoint structure: {add_res.status_code} {add_res.text}"
            )

    return {"status": "success", "playlist_id": playlist_id}

@app.get("/api/query-status")
async def check_pipeline_status():
    global current_status
    return {"status": current_status}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)