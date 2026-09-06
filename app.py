

import os
import uuid
import logging
from pathlib import Path

from flask import Flask, request, jsonify, render_template, send_from_directory
from dotenv import load_dotenv
from gtts import gTTS
from groq import Groq
from faster_whisper import WhisperModel

# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("voice-assistant")

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
AUDIO_OUT_DIR = BASE_DIR / "static" / "audio"
UPLOAD_DIR.mkdir(exist_ok=True)
AUDIO_OUT_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")  # tiny/base/small/medium
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are a helpful, concise voice assistant. Keep replies short (2-4 sentences) "
    "and conversational, since they will be read aloud.",
)

if not GROQ_API_KEY:
    logger.warning("GROQ_API_KEY is not set. /api/chat and /api/converse will fail until it is configured.")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Lazy-load the Whisper model once, on first use, so app startup stays fast.
_whisper_model = None      


def get_whisper_model() -> WhisperModel:
    global _whisper_model
    if _whisper_model is None:
        logger.info(f"Loading faster-whisper model '{WHISPER_MODEL_SIZE}' ...")
        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        logger.info("Whisper model loaded.")
    return _whisper_model


# In-memory conversation history (single-session demo).
# For multi-user/production use, key this by session id instead.
conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

MAX_HISTORY_TURNS = 10  # keep last N user/assistant pairs to bound context size


# --------------------------------------------------------------------------
# Core pipeline functions
# --------------------------------------------------------------------------
def transcribe_audio(filepath: str) -> str:
    """Convert an audio file to text using faster-whisper."""
    model = get_whisper_model()
    segments, _info = model.transcribe(filepath, beam_size=5)
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return text


def get_llm_response(user_text: str) -> str:
    """Send user text to Groq LLM and return the assistant's reply."""
    if groq_client is None:
        raise RuntimeError("GROQ_API_KEY is not configured on the server.")

    conversation_history.append({"role": "user", "content": user_text})

    # Trim history: system prompt + last N turns (2 messages per turn)
    trimmed = [conversation_history[0]] + conversation_history[1:][-(MAX_HISTORY_TURNS * 2):]

    completion = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=trimmed,
        temperature=0.7,
        max_tokens=300,
    )
    reply = completion.choices[0].message.content.strip()
    conversation_history.append({"role": "assistant", "content": reply})
    return reply


def synthesize_speech(text: str) -> str:
    """Convert text to an mp3 file, return the filename (relative to static/audio)."""
    filename = f"{uuid.uuid4().hex}.mp3"
    filepath = AUDIO_OUT_DIR / filename
    tts = gTTS(text=text, lang="en")
    tts.save(str(filepath))
    return filename


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files["audio"]
    temp_path = UPLOAD_DIR / f"{uuid.uuid4().hex}.webm"
    audio_file.save(temp_path)

    try:
        text = transcribe_audio(str(temp_path))
        if not text:
            return jsonify({"error": "Could not detect any speech in the audio"}), 422
        return jsonify({"text": text})
    except Exception as exc:
        logger.exception("Transcription failed")
        return jsonify({"error": f"Transcription failed: {exc}"}), 500
    finally:
        temp_path.unlink(missing_ok=True)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(silent=True) or {}
    user_text = (data.get("text") or "").strip()
    if not user_text:
        return jsonify({"error": "No text provided"}), 400

    try:
        reply = get_llm_response(user_text)
        return jsonify({"reply": reply})
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        logger.exception("LLM call failed")
        return jsonify({"error": f"LLM call failed: {exc}"}), 500


@app.route("/api/speak", methods=["POST"])
def api_speak():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        filename = synthesize_speech(text)
        return jsonify({"audio_url": f"/static/audio/{filename}"})
    except Exception as exc:
        logger.exception("TTS failed")
        return jsonify({"error": f"Speech synthesis failed: {exc}"}), 500


@app.route("/api/converse", methods=["POST"])
def api_converse():
    """Full pipeline in a single request: audio in -> (text, reply, audio) out."""
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files["audio"]
    temp_path = UPLOAD_DIR / f"{uuid.uuid4().hex}.webm"
    audio_file.save(temp_path)

    try:
        user_text = transcribe_audio(str(temp_path))
        if not user_text:
            return jsonify({"error": "Could not detect any speech. Please try again."}), 422

        reply = get_llm_response(user_text)
        filename = synthesize_speech(reply)

        return jsonify({
            "user_text": user_text,
            "ai_text": reply,
            "audio_url": f"/static/audio/{filename}",
        })
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        logger.exception("Conversation pipeline failed")
        return jsonify({"error": f"Something went wrong: {exc}"}), 500
    finally:
        temp_path.unlink(missing_ok=True)


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Clear conversation memory/context."""
    global conversation_history
    conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]
    return jsonify({"status": "reset"})


@app.route("/static/audio/<path:filename>")
def serve_audio(filename):
    return send_from_directory(AUDIO_OUT_DIR, filename)


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "groq_configured": groq_client is not None,
        "whisper_model": WHISPER_MODEL_SIZE,
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
