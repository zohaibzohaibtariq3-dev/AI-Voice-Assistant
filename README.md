# AI Voice Assistant
Speech-to-Text → LLM → Text-to-Speech, built as a Flask web app.

## Pipeline
1. Browser records your voice (MediaRecorder API)
2. Audio is sent to Flask → **faster-whisper** transcribes it to text (runs locally, no API key needed)
3. Text is sent to **Groq** (Llama 3.3 70B) for a response
4. Response is converted to speech with **gTTS** and played back in the browser
5. Conversation history is kept in memory, so follow-up questions have context

## Setup

```bash
# 1. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your API key
cp .env.example .env
# then open .env and paste your free Groq key from https://console.groq.com/keys

# 4. Run the app
python app.py
```

Open **http://localhost:5000** and click the mic button.

> First run will download the Whisper model (~150MB for `base`) — this happens once and is cached.

## Project structure
```
ai-voice-assistant/
├── app.py                 # Flask backend — STT, LLM, TTS routes
├── requirements.txt
├── .env.example            # copy to .env and add your GROQ_API_KEY
├── templates/
│   └── index.html          # chat UI
├── static/
│   ├── css/style.css
│   ├── js/app.js            # mic recording + fetch calls to backend
│   └── audio/                # generated TTS mp3s (created at runtime)
└── uploads/                  # temp recorded audio (deleted after transcription)
```

## API endpoints
| Route              | Method | Purpose                                              |
|---------------------|--------|-------------------------------------------------------|
| `/`                 | GET    | Serves the UI                                         |
| `/api/converse`     | POST   | Full pipeline: audio in → transcript + reply + speech |
| `/api/transcribe`   | POST   | Audio → text only                                     |
| `/api/chat`         | POST   | Text → LLM reply only                                 |
| `/api/speak`        | POST   | Text → mp3 URL only                                   |
| `/api/reset`        | POST   | Clears conversation memory                            |
| `/health`           | GET    | Server + config status check                          |

Each pipeline stage also works standalone via its own endpoint — handy for testing or swapping one piece out.

## Mapping to the assignment spec
- **Phase 1–2 (Setup/Audio):** browser `MediaRecorder` captures WAV/webm audio, no extra hardware libs needed
- **Phase 3 (STT):** `faster-whisper` — offline, no API key, good accuracy on short sentences
- **Phase 4 (LLM API):** Groq's OpenAI-compatible SDK, API key from `.env`, conversation history trimmed to last 10 turns
- **Phase 5 (TTS):** `gTTS`, served back as an mp3 the browser plays automatically
- **Phase 6 (Integration loop):** `/api/converse` chains all three steps in one request; mic button toggles record/stop
- **Phase 7 (UI):** single-page dark-mode chat interface, shows both transcript and reply text alongside audio playback
- **Phase 8 (Error handling):** every stage returns a clear JSON error (no mic input, empty transcription, missing API key, API failure) instead of crashing

## Notes / things worth knowing
- Conversation memory is a single in-process list — fine for a demo, but restarting the server clears it, and it's shared across browser tabs. For multi-user use you'd key it by session ID.
- `WHISPER_MODEL_SIZE=base` is the default trade-off of speed vs accuracy. Bump to `small` or `medium` in `.env` if accuracy matters more than latency on your machine.
- gTTS needs internet access (it calls Google's translate endpoint) — that's expected and normal for local dev.

## Optional enhancements (from the spec's bonus section)
- Wake word detection — could plug in `pvporcupine` or a simple keyword-spotting pass on short audio clips
- Streaming — Groq supports `stream=True`; would need to swap `/api/converse` to stream tokens and pipe partial text to TTS in chunks
- External API integration — e.g. add a `weather` intent that calls a weather API before falling back to the LLM
