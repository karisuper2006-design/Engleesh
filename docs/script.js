const STORAGE_KEY = "engleesh_words";
let words = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
let hideRu = false;
let hideEn = false;
let currentTab = "all";

// ─── Language detection ─────────────────────────────────────────────────────

function isEnglish(text) {
    const letters = text.replace(/[^a-zA-Z]/g, "");
    if (!letters.length) return false;
    const ascii = letters.replace(/[^a-zA-Z]/g, "").length;
    return ascii / letters.length > 0.8;
}

// ─── Translation (MyMemory free API) ────────────────────────────────────────

async function translate(text, from, to) {
    const url = `https://api.mymemory.translated.net/get?q=${encodeURIComponent(text)}&langpair=${from}|${to}`;
    const res = await fetch(url);
    const data = await res.json();
    if (data.responseStatus === 200 && data.responseData.translatedText) {
        const t = data.responseData.translatedText;
        if (t.toUpperCase() === text.toUpperCase()) return text;
        return t;
    }
    throw new Error("Translation failed");
}

// ─── Transcription (Free Dictionary API) ────────────────────────────────────

async function getTranscription(word) {
    try {
        const res = await fetch(`https://api.dictionaryapi.dev/api/v2/entries/en/${encodeURIComponent(word)}`);
        if (!res.ok) return "";
        const data = await res.json();
        for (const entry of data) {
            if (entry.phonetic) return entry.phonetic;
            for (const p of (entry.phonetics || [])) {
                if (p.text) return p.text;
            }
        }
    } catch {}
    return "";
}

// ─── TTS (Web Speech API) ──────────────────────────────────────────────────

function playWord(word) {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(word);
    u.lang = "en-US";
    u.rate = 0.9;
    window.speechSynthesis.speak(u);
}

// ─── Add word ───────────────────────────────────────────────────────────────

async function addWord() {
    const input = document.getElementById("wordInput");
    const raw = input.value.trim();
    if (!raw) return;

    const btn = document.getElementById("addBtn");
    const status = document.getElementById("status");
    btn.disabled = true;
    status.textContent = "Looking up…";
    status.style.color = "#888";

    try {
        let wordEn, wordRu, transcription;

        if (isEnglish(raw)) {
            wordEn = raw.toLowerCase();
            wordRu = await translate(wordEn, "en", "ru");
            transcription = await getTranscription(wordEn);
        } else {
            wordRu = raw;
            wordEn = (await translate(wordRu, "ru", "en")).toLowerCase();
            transcription = await getTranscription(wordEn);
        }

        const exists = words.some(w => w.word_en === wordEn);
        if (exists) {
            status.textContent = `«${wordEn}» already exists.`;
            status.style.color = "#e67e22";
        } else {
            words.unshift({
                id: Date.now(),
                word_en: wordEn,
                word_ru: wordRu,
                transcription: transcription || "",
                is_mistake: false,
            });
            save();
            render();
            status.textContent = `Added: ${wordEn} — ${wordRu}  ${transcription || ""}`;
            status.style.color = "#27ae60";
            input.value = "";
        }
    } catch (e) {
        status.textContent = `Error: ${e.message}`;
        status.style.color = "#e74c3c";
    }

    btn.disabled = false;
}

// ─── Actions ────────────────────────────────────────────────────────────────

function toggleMistake(id) {
    const w = words.find(w => w.id === id);
    if (w) { w.is_mistake = !w.is_mistake; save(); render(); }
}

function deleteWord(id) {
    words = words.filter(w => w.id !== id);
    save();
    render();
    const s = document.getElementById("status");
    s.textContent = "Word removed.";
    s.style.color = "#888";
}

async function editWord(id) {
    const w = words.find(w => w.id === id);
    if (!w) return;

    const newEn = prompt("English:", w.word_en);
    if (newEn === null) return;
    const newRu = prompt("Russian:", w.word_ru);
    if (newRu === null) return;

    const oldEn = w.word_en;
    w.word_en = newEn.trim().toLowerCase();
    w.word_ru = newRu.trim();

    if (w.word_en !== oldEn) {
        w.transcription = await getTranscription(w.word_en);
    }

    save();
    render();
    const s = document.getElementById("status");
    s.textContent = `Updated: ${w.word_en} — ${w.word_ru}`;
    s.style.color = "#27ae60";
}

function setMode(which, checked) {
    if (which === 'ru') hideRu = checked;
    if (which === 'en') hideEn = checked;
    render();
}

function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelector(`.tab[onclick="switchTab('${tab}')"]`).classList.add("active");
    render();
}

// ─── Render ─────────────────────────────────────────────────────────────────

function render() {
    const list = document.getElementById("wordList");
    const empty = document.getElementById("emptyMsg");
    list.innerHTML = "";

    let filtered = words;
    if (currentTab === "mistakes") {
        filtered = words.filter(w => w.is_mistake);
    }

    if (!filtered.length) {
        empty.classList.remove("hidden");
        empty.textContent = currentTab === "mistakes"
            ? "No mistakes yet. Mark words with ☆ to track them here."
            : "No words yet. Add your first word above!";
        return;
    }

    empty.classList.add("hidden");

    for (const w of filtered) {
        const row = document.createElement("div");
        row.className = "word-row";

        const enText = hideEn
            ? `<span class="hidden-cell" onclick="reveal(this,'${esc(w.word_en)}')">[ … ]</span>`
            : esc(w.word_en);

        const trText = hideEn
            ? `<span class="hidden-cell" onclick="reveal(this,'${esc(w.transcription || "—")}')">[ … ]</span>`
            : esc(w.transcription || "—");

        const ruText = hideRu
            ? `<span class="hidden-cell" onclick="reveal(this,'${esc(w.word_ru)}')">[ … ]</span>`
            : esc(w.word_ru);

        const starClass = w.is_mistake ? "btn-star active" : "btn-star";
        const starText = w.is_mistake ? "★" : "☆";

        row.innerHTML = `
            <span class="en">${enText}</span>
            <span class="tr">${trText}</span>
            <span class="ru">${ruText}</span>
            <span class="actions">
                <button onclick="playWord('${esc(w.word_en)}')" title="Play">🔊</button>
                <button onclick="editWord(${w.id})" title="Edit">✏️</button>
                <button class="${starClass}" onclick="toggleMistake(${w.id})" title="Toggle mistake">${starText}</button>
                <button class="btn-del" onclick="deleteWord(${w.id})" title="Delete">✕</button>
            </span>
        `;
        list.appendChild(row);
    }
}

function reveal(el, text) {
    if (el.classList.contains("revealed")) {
        el.classList.remove("revealed");
        el.textContent = "[ … ]";
    } else {
        el.classList.add("revealed");
        el.textContent = text;
    }
}

function esc(s) {
    return String(s).replace(/'/g, "\\'").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function save() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(words));
}

// ─── Init ───────────────────────────────────────────────────────────────────

document.getElementById("wordInput").addEventListener("keydown", e => {
    if (e.key === "Enter") addWord();
});

render();
