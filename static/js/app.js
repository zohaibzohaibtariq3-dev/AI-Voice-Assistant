// AI Voice Assistant — Frontend logic
// Mic recording -> /api/converse -> render chat -> Browser SpeechSynthesis

const micBtn = document.getElementById("micBtn");
const chatPanel = document.getElementById("chatPanel");
const statusRow = document.getElementById("statusRow");
const hint = document.getElementById("hint");
const resetBtn = document.getElementById("resetBtn");

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let isProcessing = false;


// ---------------------------------------------------------
// Status
// ---------------------------------------------------------

function setStatus(message, type = "") {
    statusRow.textContent = message;
    statusRow.className = "status-row" + (type ? ` ${type}` : "");
}


// ---------------------------------------------------------
// Chat bubble
// ---------------------------------------------------------

function addBubble(role, text) {
    const emptyState = document.getElementById("emptyState");

    if (emptyState) {
        emptyState.remove();
    }

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


// ---------------------------------------------------------
// Browser Text-to-Speech
// ---------------------------------------------------------

function speakText(text) {
    return new Promise((resolve) => {

        if (!("speechSynthesis" in window)) {
            console.warn("Browser speech synthesis is not supported.");
            resolve();
            return;
        }

        // Stop previous speech
        window.speechSynthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(text);

        utterance.lang = "en-US";
        utterance.rate = 1;
        utterance.pitch = 1;

        utterance.onstart = () => {
            setStatus("Speaking…", "success");
        };

        utterance.onend = () => {
            setStatus("");
            resolve();
        };

        utterance.onerror = (error) => {
            console.error("Speech synthesis error:", error);
            setStatus("");
            resolve();
        };

        window.speechSynthesis.speak(utterance);
    });
}


// ---------------------------------------------------------
// Start Recording
// ---------------------------------------------------------

async function startRecording() {
    try {

        const stream = await navigator.mediaDevices.getUserMedia({
            audio: true
        });

        audioChunks = [];

        mediaRecorder = new MediaRecorder(stream);

        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }
        };

        mediaRecorder.onstop = () => {

            stream.getTracks().forEach((track) => {
                track.stop();
            });

            const audioBlob = new Blob(audioChunks, {
                type: "audio/webm"
            });

            sendAudio(audioBlob);
        };

        mediaRecorder.start();

        isRecording = true;

        micBtn.classList.add("recording");

        hint.textContent = "Listening… click to stop";

        setStatus("Recording…");

    } catch (error) {

        console.error(error);

        setStatus(
            "Microphone access denied or unavailable.",
            "error"
        );
    }
}


// ---------------------------------------------------------
// Stop Recording
// ---------------------------------------------------------

function stopRecording() {

    if (mediaRecorder && isRecording) {

        mediaRecorder.stop();

        isRecording = false;

        micBtn.classList.remove("recording");

        hint.textContent = "Processing…";
    }
}


// ---------------------------------------------------------
// Send Audio to Flask
// ---------------------------------------------------------

async function sendAudio(audioBlob) {

    isProcessing = true;

    micBtn.classList.add("processing");

    setStatus("Transcribing your voice…");

    const formData = new FormData();

    formData.append(
        "audio",
        audioBlob,
        "recording.webm"
    );

    try {

        const response = await fetch("/api/converse", {
            method: "POST",
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {

            setStatus(
                data.error || "Something went wrong.",
                "error"
            );

            return;
        }


        // Show user's text
        addBubble(
            "user",
            data.user_text
        );


        // Show thinking status
        setStatus("Thinking…");


        // Show AI response
        addBubble(
            "ai",
            data.ai_text
        );


        // Browser speaks AI response
        await speakText(data.ai_text);


    } catch (error) {

        console.error(error);

        setStatus(
            "Network error — is the server running?",
            "error"
        );

    } finally {

        isProcessing = false;

        micBtn.classList.remove("processing");

        hint.textContent = "Click to speak";
    }
}


// ---------------------------------------------------------
// Microphone Button
// ---------------------------------------------------------

micBtn.addEventListener("click", () => {

    if (isProcessing) {
        return;
    }

    if (isRecording) {
        stopRecording();
    } else {
        startRecording();
    }
});


// ---------------------------------------------------------
// Reset Conversation
// ---------------------------------------------------------

resetBtn.addEventListener("click", async () => {

    try {

        // Stop browser speech
        if ("speechSynthesis" in window) {
            window.speechSynthesis.cancel();
        }

        await fetch("/api/reset", {
            method: "POST"
        });

        chatPanel.innerHTML = `
            <div class="empty-state" id="emptyState">
                <div class="mic-illustration">🎙️</div>
                <p>Tap the microphone and start talking.</p>
            </div>
        `;

        setStatus(
            "Conversation reset.",
            "success"
        );

        setTimeout(() => {
            setStatus("");
        }, 1500);

    } catch (error) {

        console.error(error);

        setStatus(
            "Failed to reset conversation.",
            "error"
        );
    }
});