let currentThreadId = localStorage.getItem("travel_thread_id") || null;
let latestAnswerMarkdown = "";

function appendLog(message, type = "info") {
    const terminalLog = document.getElementById("terminalLog");
    if (!terminalLog) return;

    const entry = document.createElement("div");
    entry.className = `log-entry ${type}`;

    const timestamp = new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
    });
    document.getElementById("consoleClock").textContent = timestamp;

    const time = document.createElement("span");
    time.className = "log-time";
    time.textContent = timestamp;

    const text = document.createElement("span");
    text.className = "log-text";
    text.textContent = message;

    entry.append(time, text);

    terminalLog.appendChild(entry);
    terminalLog.scrollTop = terminalLog.scrollHeight;
}

function resetTerminalLog() {
    const terminalLog = document.getElementById("terminalLog");
    if (!terminalLog) return;

    terminalLog.innerHTML = "";
    document.getElementById("progressCount").textContent = "0 / 5 PHASES";
    document.getElementById("progressStage").textContent = "Awaiting your request";
    document.getElementById("activeModel").textContent = "No runtime active";
    document.getElementById("progressPercent").textContent = "0%";
    document.getElementById("progressFill").style.width = "0%";
    document.getElementById("progressTrack").setAttribute("aria-valuenow", "0");
    document.querySelectorAll(".stage-list li").forEach(stage => {
        stage.classList.remove("active", "complete");
    });
    setRunState("idle", "IDLE");
    appendLog("Ready for a travel request");
}

function setRunState(state, label) {
    const runState = document.getElementById("runState");
    runState.classList.toggle("running", state === "running");
    runState.classList.toggle("error", state === "error");
    runState.innerHTML = `<span></span> ${label}`;
}

function updateProgress(event) {
    const percent = event.total ? Math.round((event.completed / event.total) * 100) : 0;
    const isComplete = event.status === "complete";

    document.getElementById("progressCount").textContent = `${event.completed} / ${event.total} PHASES`;
    document.getElementById("progressStage").textContent = event.label;
    document.getElementById("activeModel").textContent = event.runtime || "Runtime not reported";
    document.getElementById("progressPercent").textContent = `${percent}%`;
    document.getElementById("progressFill").style.width = `${percent}%`;
    document.getElementById("progressTrack").setAttribute("aria-valuemax", String(event.total));
    document.getElementById("progressTrack").setAttribute("aria-valuenow", String(event.completed));

    const stageItem = document.querySelector(`[data-stage="${event.stage}"]`);
    if (stageItem) {
        if (isComplete) {
            stageItem.classList.remove("active");
            stageItem.classList.add("complete");
        } else {
            stageItem.classList.add("active");
        }
    }

    setRunState("running", "RUNNING");
    if (isComplete) {
        appendLog(`Completed: ${event.label}`, "success");
    } else {
        appendLog(`Running: ${event.label}`);
    }
}

async function readProgressStream(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

        let frameEnd = buffer.indexOf("\n\n");
        while (frameEnd !== -1) {
            const frame = buffer.slice(0, frameEnd);
            buffer = buffer.slice(frameEnd + 2);
            const dataLine = frame.split("\n").find(line => line.startsWith("data:"));
            if (dataLine) {
                onEvent(JSON.parse(dataLine.slice(5).trim()));
            }
            frameEnd = buffer.indexOf("\n\n");
        }

        if (done) break;
    }
}

function setPrompt(text) {
    document.getElementById("userInput").value = text;
}

function setLoading(isLoading) {
    const sendBtn = document.getElementById("sendBtn");
    const btnText = document.getElementById("btnText");
    const btnLoader = document.getElementById("btnLoader");

    sendBtn.disabled = isLoading;

    if (isLoading) {
        btnText.classList.add("hidden");
        btnLoader.classList.remove("hidden");
    } else {
        btnText.classList.remove("hidden");
        btnLoader.classList.add("hidden");
    }
}

function showError(message) {
    const errorBox = document.getElementById("errorBox");

    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
}

function hideError() {
    const errorBox = document.getElementById("errorBox");

    errorBox.classList.add("hidden");
    errorBox.textContent = "";
}

function showResult(answer, threadId) {
    latestAnswerMarkdown = answer;

    const resultSection = document.getElementById("resultSection");
    const resultBox = document.getElementById("resultBox");
    const threadInfo = document.getElementById("threadInfo");

    if (typeof marked !== "undefined") {
        resultBox.innerHTML = marked.parse(answer);
    } else {
        resultBox.innerText = answer;
    }

    threadInfo.textContent = `Thread ID: ${threadId}`;

    resultSection.classList.remove("hidden");

    resultSection.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}

async function sendMessage() {
    hideError();

    const input = document.getElementById("userInput");
    const message = input.value.trim();

    if (!message) {
        showError("Please enter your travel request first.");
        return;
    }

    setLoading(true);
    resetTerminalLog();
    appendLog("Request sent to travel planner");

    try {
        const response = await fetch("/api/travel/stream", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Accept": "text/event-stream"
            },
            body: JSON.stringify({
                message: message,
                thread_id: currentThreadId
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || "Something went wrong.");
        }

        let result = null;
        await readProgressStream(response, event => {
            if (event.type === "progress") {
                updateProgress(event);
            } else if (event.type === "result") {
                result = event.data;
            } else if (event.type === "error") {
                throw new Error(event.error || "Something went wrong.");
            }
        });

        if (!result) {
            throw new Error("The connection closed before a travel plan was ready.");
        }

        const data = result;
        currentThreadId = data.thread_id;
        localStorage.setItem("travel_thread_id", currentThreadId);

        document.getElementById("progressStage").textContent = "Travel plan ready";
        document.getElementById("activeModel").textContent = "All phases complete";
        document.getElementById("progressCount").textContent = "5 / 5 PHASES";
        document.getElementById("progressPercent").textContent = "100%";
        document.getElementById("progressFill").style.width = "100%";
        setRunState("idle", "COMPLETE");
        appendLog("Travel plan ready", "success");
        showResult(data.answer, data.thread_id);

    } catch (error) {
        document.getElementById("progressStage").textContent = "Generation failed";
        setRunState("error", "ERROR");
        appendLog(`Failed: ${error.message}`, "error");
        showError(error.message);
    } finally {
        setLoading(false);
    }
}

function copyResult() {
    const resultBox = document.getElementById("resultBox");
    const text = resultBox.innerText;

    if (!text) {
        return;
    }

    navigator.clipboard.writeText(text)
        .then(() => {
            const copyBtn = document.querySelector(".copy-btn");
            const oldText = copyBtn.textContent;

            copyBtn.textContent = "Copied!";

            setTimeout(() => {
                copyBtn.textContent = oldText;
            }, 1400);
        })
        .catch(() => {
            showError("Could not copy result.");
        });
}

function downloadPDF() {
    const pdfContent = document.getElementById("pdfContent");

    if (!latestAnswerMarkdown || !pdfContent) {
        showError("No travel plan available to download.");
        return;
    }

    const downloadBtn = document.querySelector(".download-btn");
    const oldText = downloadBtn.textContent;

    downloadBtn.textContent = "Preparing PDF...";
    downloadBtn.disabled = true;

    const options = {
        margin: 0.5,
        filename: "ai-travel-plan.pdf",
        image: {
            type: "jpeg",
            quality: 0.98
        },
        html2canvas: {
            scale: 2,
            useCORS: true,
            backgroundColor: "#ffffff"
        },
        jsPDF: {
            unit: "in",
            format: "a4",
            orientation: "portrait"
        },
        pagebreak: {
            mode: ["avoid-all", "css", "legacy"]
        }
    };

    html2pdf()
        .set(options)
        .from(pdfContent)
        .save()
        .then(() => {
            downloadBtn.textContent = oldText;
            downloadBtn.disabled = false;
        })
        .catch(() => {
            downloadBtn.textContent = oldText;
            downloadBtn.disabled = false;
            showError("Could not download PDF.");
        });
}

document.addEventListener("DOMContentLoaded", function () {
    resetTerminalLog();
});

document.addEventListener("keydown", function(event) {
    if (event.ctrlKey && event.key === "Enter") {
        sendMessage();
    }
});