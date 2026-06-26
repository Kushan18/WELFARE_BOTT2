# WelfareBot Backend

This is the backend service for WelfareBot built with FastAPI. It handles chat interactions and provides an API for the frontend client.

## Setup Instructions

1. Navigate to the backend directory:
   ```bash
   cd welfarebot-backend
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   ```

3. Activate the virtual environment:
   - **Windows (PowerShell):**
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```
   - **Windows (Command Prompt):**
     ```cmd
     .\venv\Scripts\activate.bat
     ```
   - **macOS / Linux:**
     ```bash
     source venv/bin/activate
     ```

4. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Set up the environment variables:
   ```bash
   copy .env.example .env
   # Then edit .env to add your actual keys:
   # GROQ_API_KEY=YOUR_GROQ_KEY
   # MONGODB_URI=YOUR_MONGODB_CONNECTION_STRING
   # (Optionally keep GEMINI_API_KEY if needed for future)
   ```
   ```bash
   echo "GEMINI_API_KEY=YOUR_KEY_HERE" > .env
   ```
   Replace `YOUR_KEY_HERE` with your actual key. This file is ignored by Git.

6. Run the development server:
   ```bash
   uvicorn main:app --reload
   ```

By default, the API will be available at http://127.0.0.1:8000.


### Prerequisites
- Python 3.8 or higher installed.

### Installation

1. Navigate to the backend directory:
   ```bash
   cd welfarebot-backend
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   ```

3. Activate the virtual environment:
   - **Windows (PowerShell):**
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```
   - **Windows (Command Prompt):**
     ```cmd
     .\venv\Scripts\activate.bat
     ```
   - **macOS / Linux:**
     ```bash
     source venv/bin/activate
     ```

4. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Set up the environment variables:
   ```bash
   copy .env.example .env
   # or 'cp .env.example .env' on macOS/Linux
   ```

## Running the Server

Run the development server using Uvicorn:

```bash
uvicorn main:app --reload
```

By default, the API will be available at [http://127.0.0.1:8000](http://127.0.0.1:8000).

## API Endpoints

### 1. Health Check
- **Endpoint:** `GET /`
- **Response:**
  ```json
  {
    "status": "running"
  }
  ```

### 2. Chat Endpoint
- **Endpoint:** `POST /chat`
- **Request Body:**
  ```json
  {
    "session_id": "optional-session-id",
    "message": "Hello"
  }
  ```
- **Response:**
  ```json
  {
    "reply": "Hello! I received: Hello"
  }
  ```

## API Documentation
Once the server is running, you can access the interactive API docs at:
- Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- ReDoc: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
