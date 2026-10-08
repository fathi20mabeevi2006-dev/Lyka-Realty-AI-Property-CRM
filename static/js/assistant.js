/* =========================================================
   assistant.js — Chat UI for the AI Property Assistant
   Sends the user's question to /api/assistant (Flask backend)
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {
    const chatForm = document.getElementById("chatForm");
    const chatInput = document.getElementById("chatInput");
    const chatMessages = document.getElementById("chatMessages");

    if (!chatForm || !chatInput || !chatMessages) return;

    /* ---------- helpers ---------- */

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    /* Minimal markdown: **bold** → <strong>bold</strong> */
    function renderMarkdown(text) {
        let html = escapeHtml(text);
        html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
        html = html.replace(/`(.+?)`/g, "<code>$1</code>");
        return html;
    }

    function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function speakText(text) {
    window.speechSynthesis.cancel();

    const speech = new SpeechSynthesisUtterance(text);
    speech.lang = "en-US";
    speech.rate = 1;
    speech.pitch = 1;

    window.speechSynthesis.speak(speech);
}

    function appendMessage(role, contentHtml) {
        const wrapper = document.createElement("div");
        wrapper.className =
            role === "user"
                ? "message user-message"
                : "message assistant-message";

        const avatar = document.createElement("div");
        avatar.className = "message-avatar";
        avatar.textContent = role === "user" ? "🧑" : "🤖";

        const body = document.createElement("div");
        body.className = "message-content";
        body.innerHTML = contentHtml;

        wrapper.appendChild(avatar);
        wrapper.appendChild(body);
        chatMessages.appendChild(wrapper);
        scrollToBottom();
        return wrapper;
    }

    function showTyping() {
        return appendMessage(
            "assistant",
            '<div class="typing-indicator"><span></span><span></span><span></span></div>'
        );
    }

    /* ---------- send a question ---------- */

    async function sendQuestion(question) {
        const text = (question || "").trim();
        if (!text) return;

        appendMessage("user", escapeHtml(text));
        const typingEl = showTyping();

        try {
            const response = await fetch("/api/assistant", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text }),
            });

            if (!response.ok) {
                throw new Error("Server error");
            }

           const data = await response.json();
typingEl.remove();

const reply =
    data.reply || "Sorry, I couldn't answer that.";

appendMessage(
    "assistant",
    renderMarkdown(reply)
);

speakText(reply);
        } catch (err) {
            typingEl.remove();
            appendMessage(
                "assistant",
                "⚠️ Something went wrong while contacting the assistant. Please try again."
            );
        }
    }

    /* ---------- events ---------- */

    chatForm.addEventListener("submit", function (e) {
        e.preventDefault();
        const value = chatInput.value;
        chatInput.value = "";
        sendQuestion(value);
    });

    /* Suggestion chips */
    document.querySelectorAll(".chip[data-question]").forEach(function (chip) {
        chip.addEventListener("click", function () {
            sendQuestion(chip.getAttribute("data-question"));
        });
    });
});
/* ---------- Voice Input ---------- */

const voiceBtn = document.getElementById("voiceBtn");

if (voiceBtn) {
    const SpeechRecognition =
        window.SpeechRecognition ||
        window.webkitSpeechRecognition;

    if (SpeechRecognition) {
        const recognition = new SpeechRecognition();

        recognition.lang = "en-US";
        recognition.continuous = false;
        recognition.interimResults = false;

        voiceBtn.addEventListener("click", () => {
            recognition.start();
            voiceBtn.textContent = "🎙 Listening...";
        });

        recognition.onresult = (event) => {
            const transcript =
                event.results[0][0].transcript;

            document.getElementById("chatInput").value =
                transcript;

            voiceBtn.textContent = "🎤 Speak";
        };

        recognition.onerror = () => {
            voiceBtn.textContent = "🎤 Speak";
            alert("Microphone error.");
        };

        recognition.onend = () => {
            voiceBtn.textContent = "🎤 Speak";
        };
    } else {
        voiceBtn.style.display = "none";
    }
}