const STORAGE_KEY = "engleesh_words";
const FOLDERS_KEY = "engleesh_folders";
const WORD_FOLDERS_KEY = "engleesh_word_folders";

let words = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
let folders = JSON.parse(localStorage.getItem(FOLDERS_KEY) || "[]");
let wordFolders = JSON.parse(localStorage.getItem(WORD_FOLDERS_KEY) || "{}");

let hideRu = false;
let hideEn = false;
let currentTab = "all";
let selectedRowId = null;
let selectMode = false;
let selectedWordIds = new Set();
let currentFolderId = null;

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
    document.querySelectorAll(".btn-play.playing").forEach(b => b.classList.remove("playing"));
    const btn = document.querySelector(`.btn-play[data-word="${CSS.escape(word)}"]`);
    if (btn) btn.classList.add("playing");
    u.onend = () => { if (btn) btn.classList.remove("playing"); };
    u.onerror = () => { if (btn) btn.classList.remove("playing"); };
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
    selectedWordIds.delete(id);
    for (const fid in wordFolders) {
        wordFolders[fid] = wordFolders[fid].filter(wid => wid !== id);
    }
    save();
    render();
    const s = document.getElementById("status");
    s.textContent = "Слово удалено.";
    s.style.color = "#888";
}

function selectRow(id) {
    if (selectMode) {
        if (selectedWordIds.has(id)) {
            selectedWordIds.delete(id);
        } else {
            selectedWordIds.add(id);
        }
        render();
        return;
    }
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
    currentFolderId = null;
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    const tabBtn = document.querySelector(`.tab[onclick="switchTab('${tab}')"]`);
    if (tabBtn) tabBtn.classList.add("active");
    const toolbar = document.getElementById("toolbar");
    const tableHeader = document.getElementById("tableHeader");
    if (tab === "folders") {
        toolbar.classList.add("hidden");
        tableHeader.classList.add("hidden");
    } else {
        toolbar.classList.remove("hidden");
        tableHeader.classList.remove("hidden");
    }
    if (selectMode) exitSelectMode();
    render();
}

// ─── Select mode ────────────────────────────────────────────────────────────

function toggleSelectMode() {
    if (selectMode) {
        exitSelectMode();
    } else {
        selectMode = true;
        selectedWordIds.clear();
        document.getElementById("selectBtn").textContent = "Отмена";
        document.getElementById("selectBtn").classList.add("active");
        render();
    }
}

function exitSelectMode() {
    selectMode = false;
    selectedWordIds.clear();
    document.getElementById("selectBtn").textContent = "Выбрать";
    document.getElementById("selectBtn").classList.remove("active");
    render();
}

// ─── Menu ───────────────────────────────────────────────────────────────────

function toggleMenu() {
    const dd = document.getElementById("menuDropdown");
    dd.classList.toggle("hidden");
}

document.addEventListener("click", (e) => {
    if (!e.target.closest("#menuBtn") && !e.target.closest("#menuDropdown")) {
        document.getElementById("menuDropdown").classList.add("hidden");
    }
});

// ─── Folders ────────────────────────────────────────────────────────────────

function saveFolders() {
    localStorage.setItem(FOLDERS_KEY, JSON.stringify(folders));
    localStorage.setItem(WORD_FOLDERS_KEY, JSON.stringify(wordFolders));
}

function createFolder() {
    document.getElementById("menuDropdown").classList.add("hidden");
    const name = prompt("Название папки:");
    if (!name || !name.trim()) return;

    const id = Date.now();
    folders.push({ id, name: name.trim() });
    wordFolders[id] = [...selectedWordIds];
    saveFolders();
    exitSelectMode();
    const s = document.getElementById("status");
    s.textContent = `Папка «${name.trim()}» создана (${wordFolders[id].length} слов).`;
    s.style.color = "#27ae60";
    switchTab("folders");
}

function openFolder(id) {
    currentFolderId = id;
    currentTab = "folder_view";
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.getElementById("toolbar").classList.add("hidden");
    document.getElementById("tableHeader").classList.remove("hidden");
    render();
}

function backToFolders() {
    currentFolderId = null;
    switchTab("folders");
}

function deleteFolder(id) {
    if (!confirm("Удалить папку? Слова не будут удалены.")) return;
    folders = folders.filter(f => f.id !== id);
    delete wordFolders[id];
    saveFolders();
    backToFolders();
}

function removeFromFolder(folderId, wordId) {
    wordFolders[folderId] = (wordFolders[folderId] || []).filter(wid => wid !== wordId);
    saveFolders();
    render();
}

// ─── Add to folder ──────────────────────────────────────────────────────────

function showAddToFolder() {
    document.getElementById("menuDropdown").classList.add("hidden");
    if (!selectedWordIds.size) {
        const s = document.getElementById("status");
        s.textContent = "Сначала выберите слова.";
        s.style.color = "#e67e22";
        return;
    }
    if (!folders.length) {
        const s = document.getElementById("status");
        s.textContent = "Сначала создайте папку.";
        s.style.color = "#e67e22";
        return;
    }
    let picker = document.getElementById("folderPicker");
    if (picker) picker.remove();
    picker = document.createElement("div");
    picker.id = "folderPicker";
    picker.className = "folder-picker-overlay";
    picker.innerHTML = `<div class="folder-picker">
        <div class="folder-picker-title">Выберите папку</div>
        <div class="folder-picker-list"></div>
        <button class="folder-picker-cancel" onclick="closeFolderPicker()">Отмена</button>
    </div>`;
    document.body.appendChild(picker);
    picker.addEventListener("click", (e) => { if (e.target === picker) closeFolderPicker(); });
    const listEl = picker.querySelector(".folder-picker-list");
    for (const f of folders) {
        const count = (wordFolders[f.id] || []).length;
        const item = document.createElement("div");
        item.className = "folder-picker-item";
        item.innerHTML = `
            <div class="folder-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            </div>
            <span class="folder-name">${esc(f.name)}</span>
            <span class="folder-count">${count} слов</span>
        `;
        item.addEventListener("click", () => addToFolder(f.id));
        listEl.appendChild(item);
    }
}

function addToFolder(folderId) {
    const ids = [...selectedWordIds];
    if (!wordFolders[folderId]) wordFolders[folderId] = [];
    for (const wid of ids) {
        if (!wordFolders[folderId].includes(wid)) {
            wordFolders[folderId].push(wid);
        }
    }
    saveFolders();
    closeFolderPicker();
    exitSelectMode();
    const s = document.getElementById("status");
    const f = folders.find(f => f.id === folderId);
    s.textContent = `${ids.length} слов(о) добавлено в «${f ? f.name : ''}».`;
    s.style.color = "#27ae60";
}

function closeFolderPicker() {
    const picker = document.getElementById("folderPicker");
    if (picker) picker.remove();
}

// ─── Render ─────────────────────────────────────────────────────────────────

function render() {
    const list = document.getElementById("wordList");
    const empty = document.getElementById("emptyMsg");
    list.innerHTML = "";

    if (currentTab === "folders" && !currentFolderId) {
        renderFolders(list, empty);
        return;
    }

    if (currentTab === "folder_view" && currentFolderId !== null) {
        renderFolderView(list, empty);
        return;
    }

    let filtered = words;
    if (currentTab === "mistakes") {
        filtered = words.filter(w => w.is_mistake);
    }

    if (!filtered.length) {
        empty.classList.remove("hidden");
        empty.textContent = currentTab === "mistakes"
            ? "Пока нет избранного. Отмечайте слова звёздочкой ☆, чтобы они появились здесь."
            : "Пока нет слов. Добавьте первое слово выше!";
        return;
    }

    empty.classList.add("hidden");

    for (const w of filtered) {
        buildWordRow(list, w, false);
    }
}

function renderFolders(list, empty) {
    if (!folders.length) {
        empty.classList.remove("hidden");
        empty.textContent = "Пока нет папок. Выберите слова и создайте папку.";
        return;
    }
    empty.classList.add("hidden");

    for (const f of folders) {
        const count = (wordFolders[f.id] || []).length;
        const item = document.createElement("div");
        item.className = "folder-item";
        item.innerHTML = `
            <div class="folder-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            </div>
            <span class="folder-name">${esc(f.name)}</span>
            <span class="folder-count">${count} слов</span>
        `;
        item.addEventListener("click", () => openFolder(f.id));
        list.appendChild(item);
    }
}

function renderFolderView(list, empty) {
    const folder = folders.find(f => f.id === currentFolderId);
    if (!folder) { backToFolders(); return; }

    const folderWordIds = wordFolders[currentFolderId] || [];
    const folderWords = words.filter(w => folderWordIds.includes(w.id));

    const backBtn = document.createElement("button");
    backBtn.className = "folder-back";
    backBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg> Назад`;
    backBtn.addEventListener("click", backToFolders);
    list.appendChild(backBtn);

    const header = document.createElement("div");
    header.className = "folder-header";
    header.innerHTML = `
        <span class="folder-title">${esc(folder.name)}</span>
        <button class="folder-delete-btn" onclick="deleteFolder(${folder.id})">Удалить папку</button>
    `;
    list.appendChild(header);

    if (!folderWords.length) {
        empty.classList.remove("hidden");
        empty.textContent = "Папка пуста.";
        return;
    }
    empty.classList.add("hidden");

    for (const w of folderWords) {
        buildWordRow(list, w, true, currentFolderId);
    }
}

function buildWordRow(list, w, inFolder, folderId) {
    const wrapper = document.createElement("div");
    wrapper.className = "word-row-wrapper";

    const row = document.createElement("div");
    row.className = "word-row" + (selectedRowId === w.id ? " selected" : "") + (selectMode ? " selectable" : "");
    row.dataset.id = w.id;

    let checkbox = "";
    if (selectMode) {
        const checked = selectedWordIds.has(w.id);
        checkbox = `<div class="select-check ${checked ? 'checked' : ''}" onclick="event.stopPropagation(); selectWordCheck(${w.id})"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></div>`;
    }

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
        ${checkbox}
        ${enText}
        ${trText}
        ${ruText}
        <span class="actions">
            <button class="btn-play" data-word="${esc(w.word_en)}" onclick="event.stopPropagation(); playWord('${esc(w.word_en)}')" title="Озвучка"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg></button>
            <button class="${starClass}" onclick="event.stopPropagation(); toggleMistake(${w.id})" title="Отметить ошибку">${starText}</button>
        </span>
    `;

    row.addEventListener("click", (e) => {
        if (selectMode) {
            selectWordCheck(w.id);
            return;
        }
        if (!row.classList.contains("swiped")) selectRow(w.id);
    });

    initSwipe(wrapper, row, w.id);

    const del = document.createElement("div");
    del.className = "swipe-delete";
    del.innerHTML = "<svg width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='3 6 5 6 21 6'/><path d='M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'/><line x1='10' y1='11' x2='10' y2='17'/><line x1='14' y1='11' x2='14' y2='17'/></svg>";
    del.addEventListener("click", (e) => {
        e.stopPropagation();
        if (inFolder && folderId !== null) {
            wrapper.style.transition = "opacity 0.3s ease, max-height 0.3s ease";
            wrapper.style.opacity = "0";
            wrapper.style.maxHeight = "0";
            wrapper.style.marginBottom = "0";
            wrapper.style.overflow = "hidden";
            setTimeout(() => removeFromFolder(folderId, w.id), 300);
        } else {
            wrapper.style.transition = "opacity 0.3s ease, max-height 0.3s ease";
            wrapper.style.opacity = "0";
            wrapper.style.maxHeight = "0";
            wrapper.style.marginBottom = "0";
            wrapper.style.overflow = "hidden";
            setTimeout(() => deleteWord(w.id), 300);
        }
    });

    wrapper.appendChild(row);
    wrapper.appendChild(del);
    list.appendChild(wrapper);
}

function selectWordCheck(id) {
    if (selectedWordIds.has(id)) {
        selectedWordIds.delete(id);
    } else {
        selectedWordIds.add(id);
    }
    render();
}

// ─── Swipe ───────────────────────────────────────────────────────────────────

const SWIPE_THRESHOLD = 70;

function initSwipe(wrapper, row, id) {
    let startX = 0, startY = 0, dx = 0, swiping = false, locked = false;

    const onStart = (x, y) => {
        if (selectedRowId === id && row.querySelector(".inline-input")) return;
        startX = x; startY = y; dx = 0; swiping = false; locked = false;
    };

    const onMove = (x, y) => {
        if (locked) return;
        const diffX = x - startX;
        const diffY = y - startY;
        if (!swiping && Math.abs(diffX) > Math.abs(diffY) && Math.abs(diffX) > 5) {
            swiping = true;
            row.style.transition = "none";
        }
        if (!swiping) return;
        dx = Math.min(0, diffX);
        if (dx < -SWIPE_THRESHOLD) dx = -SWIPE_THRESHOLD;
        row.style.transform = `translateX(${dx}px)`;
    };

    const onEnd = () => {
        if (!swiping) return;
        locked = true;
        row.style.transition = "transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94)";
        if (dx < -SWIPE_THRESHOLD / 2) {
            row.style.transform = `translateX(-80px)`;
            row.classList.add("swiped");
            wrapper.classList.add("swipe-open");
        } else {
            row.style.transform = "translateX(0)";
            row.classList.remove("swiped");
            wrapper.classList.remove("swipe-open");
        }
    };

    row.addEventListener("touchstart", e => {
        const t = e.touches[0];
        onStart(t.clientX, t.clientY);
    }, { passive: true });

    row.addEventListener("touchmove", e => {
        const t = e.touches[0];
        onMove(t.clientX, t.clientY);
        if (swiping) e.preventDefault();
    }, { passive: false });

    row.addEventListener("touchend", onEnd);

    row.addEventListener("mousedown", e => {
        if (e.button !== 0) return;
        onStart(e.clientX, e.clientY);
        const moveHandler = (ev) => onMove(ev.clientX, ev.clientY);
        const upHandler = () => {
            onEnd();
            document.removeEventListener("mousemove", moveHandler);
            document.removeEventListener("mouseup", upHandler);
        };
        document.addEventListener("mousemove", moveHandler);
        document.addEventListener("mouseup", upHandler);
    });
}

document.addEventListener("click", (e) => {
    if (selectedRowId !== null && !e.target.closest(".word-row")) {
        selectedRowId = null;
        render();
    }
    document.querySelectorAll(".word-row.swiped").forEach(r => {
        if (!e.target.closest(".word-row-wrapper") || !r.parentElement.contains(e.target)) {
            r.style.transition = "transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94)";
            r.style.transform = "translateX(0)";
            r.classList.remove("swiped");
            r.parentElement.classList.remove("swipe-open");
        }
    });
});

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
