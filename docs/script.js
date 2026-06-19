const STORAGE_KEY = "engleesh_words";
let words = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
let hideRu = false;
let hideEn = false;
let currentTab = "all";
let selectedRowId = null;

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
    throw new Error("Ошибка перевода");
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
    status.textContent = "Поиск…";
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
            status.textContent = `«${wordEn}» уже существует.`;
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
            status.textContent = `Добавлено: ${wordEn} — ${wordRu}  ${transcription || ""}`;
            status.style.color = "#27ae60";
            input.value = "";
        }
    } catch (e) {
        status.textContent = `Ошибка: ${e.message}`;
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
    if (selectedRowId === id) selectedRowId = null;
    save();
    render();
    const s = document.getElementById("status");
    s.textContent = "Слово удалено.";
    s.style.color = "#888";
}

function selectRow(id) {
    selectedRowId = selectedRowId === id ? null : id;
    render();
}

function startEdit(el, id, field) {
    const w = words.find(w => w.id === id);
    if (!w) return;

    const val = field === "en" ? w.word_en : w.word_ru;
    const input = document.createElement("input");
    input.type = "text";
    input.className = "inline-input";
    input.value = val;
    input.style.width = field === "en" ? "160px" : "100%";

    const finish = async () => {
        const newVal = input.value.trim();
        if (newVal && newVal !== val) {
            if (field === "en") {
                w.word_en = newVal.toLowerCase();
                w.transcription = await getTranscription(w.word_en);
            } else {
                w.word_ru = newVal;
            }
            save();
            const s = document.getElementById("status");
            s.textContent = `Обновлено: ${w.word_en} — ${w.word_ru}`;
            s.style.color = "#27ae60";
        }
        render();
    };

    input.addEventListener("blur", finish);
    input.addEventListener("keydown", e => {
        if (e.key === "Enter") input.blur();
        if (e.key === "Escape") { input.value = val; input.blur(); }
    });

    el.replaceWith(input);
    input.focus();
    input.select();
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
            ? "Пока нет ошибок. Отмечайте слова звёздочкой ☆, чтобы они появились здесь."
            : "Пока нет слов. Добавьте первое слово выше!";
        return;
    }

    empty.classList.add("hidden");

    for (const w of filtered) {
        const row = document.createElement("div");
        row.className = "word-row" + (selectedRowId === w.id ? " selected" : "");
        row.dataset.id = w.id;

        const enEditable = !hideEn && selectedRowId === w.id;
        const ruEditable = !hideRu && selectedRowId === w.id;

        const enText = hideEn
            ? `<span class="hidden-cell" onclick="event.stopPropagation(); reveal(this,'${esc(w.word_en)}')">[ … ]</span>`
            : enEditable
                ? `<span class="en editable" onclick="event.stopPropagation(); startEdit(this, ${w.id}, 'en')">${esc(w.word_en)}</span>`
                : `<span class="en">${esc(w.word_en)}</span>`;

        const trText = hideEn
            ? `<span class="hidden-cell" onclick="event.stopPropagation(); reveal(this,'${esc(w.transcription || "—")}')">[ … ]</span>`
            : `<span class="tr">${esc(w.transcription || "—")}</span>`;

        const ruText = hideRu
            ? `<span class="hidden-cell" onclick="event.stopPropagation(); reveal(this,'${esc(w.word_ru)}')">[ … ]</span>`
            : ruEditable
                ? `<span class="ru editable" onclick="event.stopPropagation(); startEdit(this, ${w.id}, 'ru')">${esc(w.word_ru)}</span>`
                : `<span class="ru">${esc(w.word_ru)}</span>`;

        const starClass = w.is_mistake ? "btn-star active" : "btn-star";
        const starText = w.is_mistake ? "★" : "☆";

        row.innerHTML = `
            ${enText}
            ${trText}
            ${ruText}
            <span class="actions">
                <button onclick="event.stopPropagation(); playWord('${esc(w.word_en)}')" title="Озвучка">🔊</button>
                <button class="${starClass}" onclick="event.stopPropagation(); toggleMistake(${w.id})" title="Отметить ошибку">${starText}</button>
                <button class="btn-del" onclick="event.stopPropagation(); deleteWord(${w.id})" title="Удалить">✕</button>
            </span>
        `;

        row.addEventListener("click", () => selectRow(w.id));
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
