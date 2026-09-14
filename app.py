
"""
AI Voice Assistant — Flask Backend

Pipeline:
Browser mic audio -> Whisper (STT) -> Groq LLM -> Browser SpeechSynthesis (TTS)

Endpoints:
GET  /                 -> renders the UI
POST /api/transcribe   -> audio blob -> transcribed text
POST /api/chat         -> text -> LLM response text
POST /api/converse     -> audio blob -> {user_text, ai_text}
POST /api/reset        -> reset conversation
GET  /health           -> health check
"""

import os

# --------------------------------------------------------------------------
# Vercel Writable Cache Directories
# --------------------------------------------------------------------------

os.environ["HF_HOME"] = "/tmp/huggingface"
os.environ["XDG_CACHE_HOME"] = "/tmp/cache"
os.environ["TRANSFORMERS_CACHE"] = "/tmp/huggingface"

import uuid
import logging
from pathlib import Path

from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from groq import Groq
from faster_whisper import WhisperModel


# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger("voice-assistant")

BASE_DIR = Path(__file__).resolve().parent

# Vercel project directory is read-only.
# /tmp is writable temporary storage.
UPLOAD_DIR = Path("/tmp/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


# --------------------------------------------------------------------------
# Environment Variables
# --------------------------------------------------------------------------

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b"
)

WHISPER_MODEL_SIZE = os.getenv(
    "WHISPER_MODEL_SIZE",
    "base"
)

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are a helpful, concise voice assistant. "
    "Keep replies short (2-4 sentences) and conversational, "
    "since they will be read aloud."
)


# --------------------------------------------------------------------------
# Groq Client
# --------------------------------------------------------------------------

if not GROQ_API_KEY:
    logger.warning(
        "GROQ_API_KEY is not set. "
        "/api/chat and /api/converse will fail until configured."
    )

groq_client = (
    Groq(api_key=GROQ_API_KEY)
    if GROQ_API_KEY
    else None
)


# --------------------------------------------------------------------------
# Whisper
# --------------------------------------------------------------------------

_whisper_model = None


def get_whisper_model() -> WhisperModel:
    global _whisper_model

    if _whisper_model is None:
        logger.info(
            f"Loading faster-whisper model "
            f"'{WHISPER_MODEL_SIZE}' ..."
        )

        _whisper_model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device="cpu",
            compute_type="int8",
            download_root="/tmp/whisper"
        )

        logger.info("Whisper model loaded.")

    return _whisper_model


# --------------------------------------------------------------------------
# Conversation History
# --------------------------------------------------------------------------

conversation_history = [
    {
        "role": "system",
        "content": SYSTEM_PROMPT
    }
]

MAX_HISTORY_TURNS = 10


# --------------------------------------------------------------------------
# Speech-to-Text
# --------------------------------------------------------------------------

def transcribe_audio(filepath: str) -> str:
    """Convert audio file to text using faster-whisper."""

    model = get_whisper_model()

    segments, _info = model.transcribe(
        filepath,
        beam_size=5
    )

    text = " ".join(
        segment.text.strip()
        for segment in segments
    ).strip()

    return text


# --------------------------------------------------------------------------
# Groq LLM
# --------------------------------------------------------------------------

def get_llm_response(user_text: str) -> str:
    """Send user text to Groq and return assistant reply."""

    if groq_client is None:
        raise RuntimeError(
            "GROQ_API_KEY is not configured on the server."
        )

    conversation_history.append(
        {
            "role": "user",
            "content": user_text
        }
    )

    trimmed = (
        [conversation_history[0]]
        + conversation_history[1:]
        [-(MAX_HISTORY_TURNS * 2):]
    )

    completion = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=trimmed,
        temperature=0.7,
        max_tokens=300,
    )

    reply = completion.choices[0].message.content.strip()

    conversation_history.append(
        {
            "role": "assistant",
            "content": reply
        }
    )

    return reply


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# --------------------------------------------------------------------------
# Transcribe
# --------------------------------------------------------------------------

@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():

    if "audio" not in request.files:
        return jsonify(
            {
                "error": "No audio file provided"
            }
        ), 400

    audio_file = request.files["audio"]

    temp_path = (
        UPLOAD_DIR /
        f"{uuid.uuid4().hex}.webm"
    )

    try:

        audio_file.save(temp_path)

        text = transcribe_audio(
            str(temp_path)
        )

        if not text:
            return jsonify(
                {
                    "error":
                    "Could not detect any speech in the audio"
                }
            ), 422

        return jsonify(
            {
                "text": text
            }
        )

    except Exception as exc:

        logger.exception(
            "Transcription failed"
        )

        return jsonify(
            {
                "error":
                f"Transcription failed: {exc}"
            }
        ), 500

    finally:

        temp_path.unlink(
            missing_ok=True
        )


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------

@app.route("/api/chat", methods=["POST"])
def api_chat():

    data = request.get_json(
        silent=True
    ) or {}

    user_text = (
        data.get("text") or ""
    ).strip()

    if not user_text:

        return jsonify(
            {
                "error":
                "No text provided"
            }
        ), 400

    try:

        reply = get_llm_response(
            user_text
        )

        return jsonify(
            {
                "reply": reply
            }
        )

    except RuntimeError as exc:

        return jsonify(
            {
                "error": str(exc)
            }
        ), 503

    except Exception as exc:

        logger.exception(
            "LLM call failed"
        )

        return jsonify(
            {
                "error":
                f"LLM call failed: {exc}"
            }
        ), 500


# --------------------------------------------------------------------------
# Converse
# --------------------------------------------------------------------------

@app.route("/api/converse", methods=["POST"])
def api_converse():

    if "audio" not in request.files:

        return jsonify(
            {
                "error":
                "No audio file provided"
            }
        ), 400

    audio_file = request.files["audio"]

    temp_path = (
        UPLOAD_DIR /
        f"{uuid.uuid4().hex}.webm"
    )

    try:

        audio_file.save(temp_path)

        user_text = transcribe_audio(
            str(temp_path)
        )

        if not user_text:

            return jsonify(
                {
                    "error":
                    "Could not detect any speech. "
                    "Please try again."
                }
            ), 422

        reply = get_llm_response(
            user_text
        )

        return jsonify(
            {
                "user_text": user_text,
                "ai_text": reply
            }
        )

    except RuntimeError as exc:

        return jsonify(
            {
                "error": str(exc)
            }
        ), 503

    except Exception as exc:

        logger.exception(
            "Conversation pipeline failed"
        )

        return jsonify(
            {
                "error":
                f"Something went wrong: {exc}"
            }
        ), 500

    finally:

        temp_path.unlink(
            missing_ok=True
        )


# --------------------------------------------------------------------------
# Reset Conversation
# --------------------------------------------------------------------------

@app.route("/api/reset", methods=["POST"])
def api_reset():

    global conversation_history

    conversation_history = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    return jsonify(
        {
            "status": "reset"
        }
    )


# --------------------------------------------------------------------------
# Health Check
# --------------------------------------------------------------------------

@app.route("/health")
def health():

    return jsonify(
        {
            "status": "ok",
            "groq_configured":
                groq_client is not None,
            "whisper_model":
                WHISPER_MODEL_SIZE,
            "groq_model":
                GROQ_MODEL
        }
    )


# --------------------------------------------------------------------------
# Run Server
# --------------------------------------------------------------------------

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )

