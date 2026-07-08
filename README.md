## Project Overview

The **Spotify Voice-Activated RAG & Discovery Engine** is a full-stack, enterprise-grade web application that transitions traditional music discovery away from rigid keyword/regex filtering into a contextual, AI-driven semantic experience.

Instead of searching strictly for an artist name or explicit title, users can supply conversational, emotional queries via text or vocal dictation (e.g., *"Find me something acoustic and melancholic to listen to while it rains"*). The system parses user intent, computes vector embeddings, matches the conceptual meaning against a massive cloud index of over **600,000 tracks**, and delivers personalized AI recommendations coupled with direct real-world playlist generation.

---

## Architectural Layout

The application utilizes a fully decoupled, multi-container architecture broken down into four foundational layers:

### 1. Client Interface Layer (Frontend)

* **Technologies:** React.js (Vite), Tailwind CSS.
* **Capabilities:** Features a modern, responsive web dashboard with a single-page reactive layout. It captures live vocal dictation directly inside the browser using the native HTML5 **MediaRecorder API**, handles audio staging, and dynamically updates search grids without page refreshes.

### 2. Application Gateway Engine (Backend API)

* **Technologies:** FastAPI (Python), Uvicorn, SQLAlchemy, PyODBC.
* **Capabilities:** Serves as the asynchronous central nervous system. It exposes highly optimized endpoints to manage incoming audio payloads, orchestrate internal text routing, handle multi-layered error catching, and preserve conversational pipeline states.

### 3. AI Engineering & Embedding Layer

* **Speech-to-Text:** Routes raw audio files from the client to the **Groq Whisper-large-v3 Cloud API** for instantaneous, near-zero-latency text transcriptions.
* **Semantic Vectorization:** Leverages a sandboxed local **Ollama Container** running the `nomic-embed-text` model to convert user text queries into dense 768-dimensional geometric vector embeddings.
* **Augmentation & Synthesis:** Utilizes **Groq's Llama-3.3-70b-versatile** model to execute real-time intent extraction (isolating volume limits and sorting directives) and synthesize personalized, natural language reasoning explanations for the tracks returned.

### 4. Enterprise Cloud Data Tier (Storage)

* **Technologies:** Microsoft Azure SQL Serverless Database.
* **Capabilities:** Hosts a resilient, scaled database containing 600k tracks ingested via a chunked, fault-tolerant Pandas pipeline. It executes native cloud-side similarity math via **Cosine Distance vector math** (`VECTOR_DISTANCE`) to find nearest-neighbor tracks in milliseconds.

---

## Key Active Features

* **Dual-Engine Input Pipeline:** Users can query the system by typing freely or clicking a native microphone shortcut that records, uploads, and transcribes voice input transparently.
* **Semantic RAG Matchmaking:** Bypasses keyword constraints completely by mapping abstract concepts (moods, vibes, activities) directly to corresponding numerical track audio profiles.
* **Automated Intent Extraction:** The LLM acts as an inline query planner, dynamically reading the user's natural language to alter T-SQL structures (such as adjusting variables like `TOP (5)` or ordering matches by best/worst fit).
* **OAuth 2.0 Spotify Integration:** Incorporates official third-party security handshakes. Users securely authenticate through Spotify's explicit authorization node, enabling the React application to instantly construct customized public or private playlists directly inside the user's genuine Spotify profile using modern web endpoint interfaces.
