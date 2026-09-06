// AI Voice Assistant — Frontend logic
// Handles: mic recording (MediaRecorder) -> /api/converse -> render chat + play TTS audio

const micBtn = document.getElementById("micBtn");
const chatPanel = document.getElementById("chatPanel");
const emptyState = document.getElementById("emptyState");
const statusRow = document.getElementById("statusRow");
const hint = document.getElementById("hint");
const resetBtn = document.getElementById("resetBtn");
const ttsAudio = document.getElementById("ttsAudio");

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let isProcessing = false;

function setStatus(message, type = "") {
    statusRow.textContent = message;
    statusRow.className = "status-row" + (type ? ` ${type}` : "");
}

function addBubble(role, text) {
    if (emptyState) emptyState.remove();
    const bubble = document.createElement("div");
    bubble.className = `bubble ${role}`;
    const label = document.createElement("span");
    label.className = "label";
    label.textContent = role === "user" ? "You" : "Assistant";
    const body = document.createElement("span");
    body.textContent = text;
    bubble.appendChild(label);
    bubble.appendChild(body);
    chatPanel.appendChild(bubble);
    chatPanel.scrollTop = chatPanel.scrollHeight;
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunks = [];
        mediaRecorder = new MediaRecorder(stream);

        mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) audioChunks.push(e.data);
        };

        mediaRecorder.onstop = () => {
            stream.getTracks().forEach((track) => track.stop());
            const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
            sendAudio(audioBlob);
        };

        mediaRecorder.start();
        isRecording = true;
        micBtn.classList.add("recording");
        hint.textContent = "Listening… click to stop";
        setStatus("Recording…");
    } catch (err) {
        console.error(err);
        setStatus("Microphone access denied or unavailable.", "error");
    }
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        micBtn.classList.remove("recording");
        hint.textContent = "Processing…";
    }
}

async function sendAudio(audioBlob) {
    isProcessing = true;
    micBtn.classList.add("processing");
    setStatus("Transcribing your voice…");

    const formData = new FormData();
    formData.append("audio", audioBlob, "recording.webm");

    try {
        const res = await fetch("/api/converse", {
            method: "POST",
            body: formData,
        });
        const data = await res.json();

        if (!res.ok) {
            setStatus(data.error || "Something went wrong.", "error");
            return;
        }

        addBubble("user", data.user_text);
        setStatus("Thinking…");
        addBubble("ai", data.ai_text);

        setStatus("Speaking…", "success");
        ttsAudio.src = data.audio_url;
        await ttsAudio.play();
        ttsAudio.onended = () => setStatus("");
    } catch (err) {
        console.error(err);
        setStatus("Network error — is the server running?", "error");
    } finally {
        isProcessing = false;
        micBtn.classList.remove("processing");
        hint.textContent = "Click to speak";
    }
}

micBtn.addEventListener("click", () => {
    if (isProcessing) return;
    if (isRecording) {
        stopRecording();
    } else {
        startRecording();
    }
});

resetBtn.addEventListener("click", async () => {
    await fetch("/api/reset", { method: "POST" });
    chatPanel.innerHTML = `
        <div class="empty-state" id="emptyState">
            <div class="mic-illustration">🎙️</div>
            <p>Tap the microphone and start talking.</p>
        </div>`;
    setStatus("Conversation reset.", "success");
    setTimeout(() => setStatus(""), 1500);
});
