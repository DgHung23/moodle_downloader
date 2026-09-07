/**
 * form_filter.js - Tải Bài Nộp Sinh Viên theo Bộ Lọc Form Excel (Form.xls)
 * Đại học Greenwich
 */

// Global State
const state = {
  sessionToken: "",
  parsedResult: null,
  activeSheetName: "",
  students: [],
  selectedStts: new Set(),
  currentFilter: "all",
  searchQuery: "",
  isMatching: false,
  isDownloading: false,
  pollTimer: null,
  lastLogCount: 0
};

// DOM Elements
const elements = {
  sessionInput: document.getElementById("form-session-input"),
  btnSyncSession: document.getElementById("btn-sync-session"),
  userDisplay: document.getElementById("session-user-display"),
  cookiePreview: document.getElementById("session-cookie-preview"),
  lecturerBadge: document.getElementById("form-lecturer-badge"),

  dropZone: document.getElementById("drop-zone"),
  fileInput: document.getElementById("excel-file-input"),
  loadedFileBar: document.getElementById("loaded-file-bar"),
  loadedFileName: document.getElementById("loaded-file-name"),
  loadedFileSize: document.getElementById("loaded-file-size"),
  btnChangeFile: document.getElementById("btn-change-file"),
  btnLoadSample: document.getElementById("btn-load-sample-form"),

  stepMetadataCard: document.getElementById("step-metadata-card"),
  sheetTabsContainer: document.getElementById("sheet-tabs-container"),
  metaCourseCode: document.getElementById("meta-course-code"),
  metaAssessTitle: document.getElementById("meta-assess-title"),
  metaTotalStudents: document.getElementById("meta-total-students"),
  metaHasPaperId: document.getElementById("meta-has-paper-id"),
  metaClasses: document.getElementById("meta-classes"),
  btnStartMatching: document.getElementById("btn-start-matching"),

  stepStudentsCard: document.getElementById("step-students-card"),
  matchSummaryDesc: document.getElementById("match-summary-desc"),
  kpiTotal: document.getElementById("kpi-total"),
  kpiMatched: document.getElementById("kpi-matched"),
  kpiUnmatched: document.getElementById("kpi-unmatched"),
  filterSearch: document.getElementById("filter-students-search"),
  countAll: document.getElementById("count-all"),
  countMatched: document.getElementById("count-matched"),
  countUnmatched: document.getElementById("count-unmatched"),
  btnSelectAllMatched: document.getElementById("btn-select-all-matched"),
  thSelectAll: document.getElementById("th-select-all"),
  studentsTableBody: document.getElementById("students-table-body"),
  selectedCountDisplay: document.getElementById("selected-count-display"),
  btnStartDownload: document.getElementById("btn-start-download-selected"),
  btnDownloadText: document.getElementById("btn-download-text"),

  stepProgressCard: document.getElementById("step-progress-card"),
  btnStopDownload: document.getElementById("btn-stop-download"),
  progressFill: document.getElementById("form-progress-fill"),
  currentStudentText: document.getElementById("progress-current-student"),
  progressFraction: document.getElementById("progress-fraction"),
  terminalLogs: document.getElementById("form-terminal-logs"),
  postDownloadBanner: document.getElementById("post-download-banner"),
  btnDownloadZipFile: document.getElementById("btn-download-zip-file"),
  btnOpenResultFolder: document.getElementById("btn-open-result-folder"),
  btnOpenFormFolder: document.getElementById("btn-open-form-folder"),

  loadingOverlay: document.getElementById("form-loading-overlay"),
  loadingTitle: document.getElementById("form-loading-title"),
  loadingSubtitle: document.getElementById("form-loading-subtitle"),
  btnHideLoadingModal: document.getElementById("btn-hide-loading-modal"),
  toastContainer: document.getElementById("toast-container")
};

// =====================================================================
// 1. Toast Notifications
// =====================================================================
function showToast(message, type = "info", duration = 4000) {
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;

  const icons = {
    info: "ℹ️",
    success: "✅",
    warning: "⚠️",
    error: "❌"
  };

  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || "ℹ️"}</span>
    <span class="toast-message">${escapeHtml(message)}</span>
  `;

  elements.toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(20px)";
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

function escapeHtml(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// =====================================================================
// 2. Session Initialization & Verification
// =====================================================================
async function initSession() {
  const savedSession = localStorage.getItem("lecturer_session") || localStorage.getItem("moodle_session") || "";
  if (savedSession) {
    state.sessionToken = savedSession;
    elements.sessionInput.value = savedSession;
    elements.cookiePreview.textContent = `Cookie: ${savedSession.substring(0, 10)}... (Đã nạp từ bộ nhớ)`;
    await verifyLecturerSession(savedSession);
  } else {
    elements.cookiePreview.textContent = "Chưa có session. Vui lòng dán MoodleSession hoặc dùng trang chính để phát hiện.";
  }

  elements.btnSyncSession.addEventListener("click", async () => {
    const val = elements.sessionInput.value.trim();
    if (!val) {
      showToast("Vui lòng nhập MoodleSession!", "warning");
      return;
    }
    state.sessionToken = val;
    localStorage.setItem("lecturer_session", val);
    localStorage.setItem("moodle_session", val);
    showToast("Đã lưu MoodleSession!", "success");
    await verifyLecturerSession(val);
  });
}

async function verifyLecturerSession(sessionToken) {
  try {
    const res = await fetch("/api/submissions/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: sessionToken })
    });
    const data = await res.json();
    if (data.status === "ok" && data.is_lecturer) {
      elements.lecturerBadge.innerHTML = `
        <span class="pulsing-dot dot-active"></span>
        Giảng Viên: <strong>${escapeHtml(data.user_name)}</strong>
      `;
      elements.userDisplay.textContent = `Giảng viên: ${data.user_name}`;
    } else {
      elements.lecturerBadge.innerHTML = `
        <span class="pulsing-dot" style="background: #ef4444;"></span>
        Phiên chưa xác thực
      `;
    }
  } catch (err) {
    console.error("Lỗi xác thực session:", err);
  }
}

// =====================================================================
// 3. Drag & Drop and File Upload
// =====================================================================
function initUpload() {
  const dropZone = elements.dropZone;
  const fileInput = elements.fileInput;

  dropZone.addEventListener("click", () => fileInput.click());

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleSelectedFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files.length > 0) {
      handleSelectedFile(fileInput.files[0]);
    }
  });

  elements.btnChangeFile.addEventListener("click", () => {
    elements.loadedFileBar.classList.add("hidden");
    elements.dropZone.classList.remove("hidden");
    fileInput.value = "";
  });

  elements.btnLoadSample.addEventListener("click", loadSampleForm);
}

async function handleSelectedFile(file) {
  const ext = file.name.split(".").pop().toLowerCase();
  if (ext !== "xls" && ext !== "xlsx") {
    showToast("Định dạng không được hỗ trợ! Vui lòng chọn file .xls hoặc .xlsx.", "error");
    return;
  }

  // Cập nhật UI
  elements.dropZone.classList.add("hidden");
  elements.loadedFileBar.classList.remove("hidden");
  elements.loadedFileName.textContent = file.name;
  elements.loadedFileSize.textContent = `${(file.size / 1024).toFixed(1)} KB &bull; Đang phân tích...`;

  showLoading("Đang Phân Tích File Excel...", "Hệ thống đang trích xuất các sheet và danh sách sinh viên theo biểu mẫu chuẩn.");

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/form-filter/parse", {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    hideLoading();

    if (data.status === "ok" && data.result) {
      state.parsedResult = data.result;
      elements.loadedFileSize.textContent = `${(file.size / 1024).toFixed(1)} KB &bull; Đã phân tích thành công (${data.result.sheets.length} sheets)`;
      showToast(`Phân tích file thành công! Tìm thấy ${data.result.sheets.length} sheet dữ liệu.`, "success");
      renderParsedMetadata(data.result);
    } else {
      showToast(data.message || "Lỗi khi phân tích file Excel!", "error");
      elements.loadedFileSize.textContent = "Lỗi phân tích file";
    }
  } catch (err) {
    hideLoading();
    showToast(`Lỗi kết nối: ${err.message}`, "error");
  }
}

async function loadSampleForm() {
  showLoading("Đang Nạp File Mẫu form/Form.xls...", "Đang đọc trực tiếp file mẫu của Đại học Greenwich trong dự án.");
  try {
    const res = await fetch("/api/form-filter/load-sample");
    const data = await res.json();
    hideLoading();

    if (data.status === "ok" && data.result) {
      state.parsedResult = data.result;
      elements.dropZone.classList.add("hidden");
      elements.loadedFileBar.classList.remove("hidden");
      elements.loadedFileName.textContent = "Form.xls (File Mẫu)";
      elements.loadedFileSize.textContent = `142.5 KB &bull; Đã phân tích thành công (${data.result.sheets.length} sheets)`;
      showToast("Đã nạp file mẫu Form.xls thành công!", "success");
      renderParsedMetadata(data.result);
    } else {
      showToast(data.message || "Lỗi khi nạp file mẫu!", "error");
    }
  } catch (err) {
    hideLoading();
    showToast(`Lỗi: ${err.message}`, "error");
  }
}

// =====================================================================
// 4. Render Metadata & Sheet Tabs
// =====================================================================
function renderParsedMetadata(result) {
  elements.stepMetadataCard.classList.remove("hidden");
  elements.sheetTabsContainer.innerHTML = "";

  const sheets = result.sheets || [];
  if (!sheets.length) {
    showToast("Không tìm thấy sheet nào chứa dữ liệu sinh viên hợp lệ!", "warning");
    return;
  }

  // Chọn sheet mặc định (ưu tiên primary_sheet_name)
  const defaultSheetName = result.primary_sheet_name || sheets[0].sheet_name;
  state.activeSheetName = defaultSheetName;

  sheets.forEach((sh) => {
    const btn = document.createElement("button");
    btn.className = `segmented-btn ${sh.sheet_name === defaultSheetName ? "active" : ""}`;
    btn.innerHTML = `
      <span>📄 ${escapeHtml(sh.sheet_name)}</span>
      <span class="badge-count" style="margin-left: 6px; font-size: 0.75rem; opacity: 0.85;">(${sh.total_students})</span>
    `;
    btn.addEventListener("click", () => switchActiveSheet(sh.sheet_name));
    elements.sheetTabsContainer.appendChild(btn);
  });

  updateSheetBadges(defaultSheetName);
  elements.stepMetadataCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function switchActiveSheet(sheetName) {
  state.activeSheetName = sheetName;
  // Cập nhật active class trên tabs
  Array.from(elements.sheetTabsContainer.children).forEach((btn, idx) => {
    const sh = state.parsedResult.sheets[idx];
    if (sh && sh.sheet_name === sheetName) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });

  updateSheetBadges(sheetName);
  // Reset bảng sinh viên nếu đổi sheet
  elements.stepStudentsCard.classList.add("hidden");
  elements.stepProgressCard.classList.add("hidden");
}

function updateSheetBadges(sheetName) {
  if (!state.parsedResult) return;
  const sheet = state.parsedResult.sheets.find((s) => s.sheet_name === sheetName);
  if (!sheet) return;

  elements.metaCourseCode.textContent = sheet.course_code || "Không rõ";
  elements.metaAssessTitle.textContent = sheet.assessment_title || "Coursework";
  elements.metaTotalStudents.textContent = sheet.total_students || "0";
  elements.metaHasPaperId.textContent = `${sheet.students_with_paper_id} / ${sheet.total_students}`;
  elements.metaClasses.textContent = sheet.classes && sheet.classes.length ? sheet.classes.join(", ") : "Chung";
}

// =====================================================================
// 5. Match with Moodle Turnitin Drops
// =====================================================================
async function startMatching() {
  if (!state.parsedResult || !state.activeSheetName) {
    showToast("Vui lòng tải file Excel trước!", "warning");
    return;
  }

  const session = elements.sessionInput.value.trim() || state.sessionToken;
  if (!session) {
    showToast("Vui lòng nhập MoodleSession để đối khớp với hệ thống!", "warning");
    elements.sessionInput.focus();
    return;
  }

  state.isMatching = true;
  elements.btnStartMatching.disabled = true;
  showLoading("Đang Đối Khớp Với Moodle Turnitin...", "Hệ thống đang quét các đợt nộp Turnitin của giảng viên để tìm bài nộp khớp với Paper ID và sinh viên trong Form.");

  try {
    const res = await fetch("/api/form-filter/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sheet_name: state.activeSheetName,
        session: session
      })
    });

    const data = await res.json();
    hideLoading();
    state.isMatching = false;
    elements.btnStartMatching.disabled = false;

    if (data.status === "ok") {
      state.students = data.students || [];
      showToast(`Đối khớp hoàn tất! Khớp ${data.summary.matched_count}/${data.summary.total_students} bài nộp.`, "success");
      renderMatchedResults(data);
    } else {
      showToast(data.message || "Lỗi khi đối khớp bài nộp!", "error");
    }
  } catch (err) {
    hideLoading();
    state.isMatching = false;
    elements.btnStartMatching.disabled = false;
    showToast(`Lỗi kết nối: ${err.message}`, "error");
  }
}

function renderMatchedResults(data) {
  const summary = data.summary || {};
  elements.stepStudentsCard.classList.remove("hidden");

  elements.kpiTotal.textContent = `Tổng: ${summary.total_students || state.students.length}`;
  elements.kpiMatched.textContent = `✓ Đã khớp: ${summary.matched_count || 0}`;
  elements.kpiUnmatched.textContent = `✗ Chưa khớp: ${summary.unmatched_count || 0}`;

  elements.countAll.textContent = state.students.length;
  elements.countMatched.textContent = summary.matched_count || 0;
  elements.countUnmatched.textContent = summary.unmatched_count || 0;

  elements.matchSummaryDesc.textContent = `Đã tìm thấy ${summary.matched_count} bài nộp sẵn sàng tải từ ${summary.drops_count || 0} đợt nộp Turnitin của môn ${summary.course_code || ""}.`;

  // Mặc định chọn tất cả các bài đã khớp
  state.selectedStts.clear();
  state.students.forEach((st) => {
    if (st.is_matched) {
      state.selectedStts.add(st.stt);
    }
  });

  renderStudentsTable();
  elements.stepStudentsCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// =====================================================================
// 6. Render Students Table & Filtering
// =====================================================================
function renderStudentsTable() {
  const tbody = elements.studentsTableBody;
  tbody.innerHTML = "";

  const query = state.searchQuery.toLowerCase().trim();
  const filter = state.currentFilter;

  const filtered = state.students.filter((st) => {
    // Filter by tab
    if (filter === "matched" && !st.is_matched) return false;
    if (filter === "unmatched" && st.is_matched) return false;

    // Filter by search query
    if (query) {
      const matchName = (st.full_name || "").toLowerCase().includes(query);
      const matchFpt = (st.fpt_id || "").toLowerCase().includes(query);
      const matchGw = (st.greenwich_id || "").toLowerCase().includes(query);
      const matchPaper = (st.paper_id || "").toLowerCase().includes(query);
      const matchClass = (st.moodle_shell || st.class_code || "").toLowerCase().includes(query);
      return matchName || matchFpt || matchGw || matchPaper || matchClass;
    }
    return true;
  });

  if (!filtered.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="9" style="text-align: center; padding: 36px; color: var(--text-muted);">
          Không tìm thấy sinh viên nào phù hợp với bộ lọc hiện tại.
        </td>
      </tr>
    `;
    updateSelectedCount();
    return;
  }

  filtered.forEach((st) => {
    const tr = document.createElement("tr");
    tr.className = st.is_matched ? "row-matched" : "row-unmatched";

    const isChecked = state.selectedStts.has(st.stt);

    // Similarity score badge
    let simHtml = `<span style="color: var(--text-muted);">--</span>`;
    if (st.is_matched && st.similarity_text) {
      let simClass = "sim-green";
      const score = parseInt(st.similarity_text, 10);
      if (!isNaN(score)) {
        if (score >= 75) simClass = "sim-red";
        else if (score >= 50) simClass = "sim-orange";
        else if (score >= 25) simClass = "sim-yellow";
      }
      simHtml = `<span class="sim-badge ${simClass}">${escapeHtml(st.similarity_text)}</span>`;
    }

    // Match status pill
    let statusPill = `<span class="status-pill status-missing">Chưa nộp bài</span>`;
    if (st.is_matched) {
      if (st.match_type === "paper_id") {
        statusPill = `<span class="status-pill status-paper" title="Khớp chính xác qua Turnitin Paper ID">✓ Khớp Paper ID</span>`;
      } else if (st.match_type === "greenwich_id") {
        statusPill = `<span class="status-pill status-gwid">✓ Khớp MSSV</span>`;
      } else {
        statusPill = `<span class="status-pill status-name">✓ Khớp Họ Tên</span>`;
      }
    }

    // Student MSSV display
    let idBadge = "";
    if (st.fpt_id && st.greenwich_id) {
      idBadge = `<span class="id-fpt">${escapeHtml(st.fpt_id)}</span> <span class="id-gw">(${escapeHtml(st.greenwich_id)})</span>`;
    } else if (st.fpt_id) {
      idBadge = `<span class="id-fpt">${escapeHtml(st.fpt_id)}</span>`;
    } else if (st.greenwich_id) {
      idBadge = `<span class="id-gw">${escapeHtml(st.greenwich_id)}</span>`;
    }

    const shellCode = st.moodle_shell || st.class_code || "--";

    tr.innerHTML = `
      <td style="text-align: center;">
        <input type="checkbox" class="cb-student" data-stt="${st.stt}" ${isChecked ? "checked" : ""} ${!st.is_matched ? "disabled" : ""} />
      </td>
      <td style="color: var(--text-muted); font-size: 0.85rem;">${st.stt}</td>
      <td>
        <div style="font-weight: 600; color: var(--text-primary);">${escapeHtml(st.full_name)}</div>
        <div style="font-size: 0.8rem; margin-top: 2px;">${idBadge}</div>
      </td>
      <td>
        <span class="shell-badge">${escapeHtml(shellCode)}</span>
      </td>
      <td>
        <span style="font-family: monospace; font-size: 0.85rem; color: #60a5fa;">${escapeHtml(st.paper_id || "--")}</span>
      </td>
      <td>
        <div style="font-size: 0.85rem; max-width: 200px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${escapeHtml(st.drop_title || "")}">
          ${escapeHtml(st.drop_title || "--")}
        </div>
        ${st.part_name ? `<div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(st.part_name)}</div>` : ""}
      </td>
      <td style="text-align: center;">${simHtml}</td>
      <td style="text-align: center; font-weight: 600; font-size: 0.9rem;">${escapeHtml(st.grade || "--")}</td>
      <td style="text-align: center;">${statusPill}</td>
    `;

    // Checkbox click listener
    const cb = tr.querySelector(".cb-student");
    if (cb && !cb.disabled) {
      cb.addEventListener("change", (e) => {
        if (e.target.checked) {
          state.selectedStts.add(st.stt);
        } else {
          state.selectedStts.delete(st.stt);
        }
        updateSelectedCount();
      });
    }

    tbody.appendChild(tr);
  });

  updateSelectedCount();
}

function updateSelectedCount() {
  const count = state.selectedStts.size;
  elements.selectedCountDisplay.textContent = count;
  elements.btnDownloadText.textContent = `⬇️ Bắt Đầu Tải ${count} Bài Đã Chọn`;
  elements.btnStartDownload.disabled = count === 0;

  // Header checkbox state
  const matchedStts = state.students.filter((s) => s.is_matched).map((s) => s.stt);
  if (matchedStts.length && matchedStts.every((stt) => state.selectedStts.has(stt))) {
    elements.thSelectAll.checked = true;
  } else {
    elements.thSelectAll.checked = false;
  }
}

function initTableControls() {
  // Search input
  elements.filterSearch.addEventListener("input", (e) => {
    state.searchQuery = e.target.value;
    renderStudentsTable();
  });

  // Filter tabs
  const filterBtns = document.querySelectorAll(".filter-tab-btn");
  filterBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      filterBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.currentFilter = btn.dataset.filter;
      renderStudentsTable();
    });
  });

  // Header Checkbox
  elements.thSelectAll.addEventListener("change", (e) => {
    const checkAll = e.target.checked;
    state.students.forEach((st) => {
      if (st.is_matched) {
        if (checkAll) {
          state.selectedStts.add(st.stt);
        } else {
          state.selectedStts.delete(st.stt);
        }
      }
    });
    renderStudentsTable();
  });

  // Select All Matched Button
  elements.btnSelectAllMatched.addEventListener("click", () => {
    state.students.forEach((st) => {
      if (st.is_matched) state.selectedStts.add(st.stt);
    });
    renderStudentsTable();
    showToast(`Đã chọn toàn bộ bài nộp đã khớp!`, "info");
  });
}

// =====================================================================
// 7. Start Download & Live Progress Polling
// =====================================================================
function initDownloadControls() {
  elements.btnStartDownload.addEventListener("click", startDownloadSelected);
  elements.btnStopDownload.addEventListener("click", stopDownload);

  elements.btnOpenFormFolder.addEventListener("click", () => openFolder(""));
  elements.btnOpenResultFolder.addEventListener("click", () => openFolder(""));
}

async function startDownloadSelected() {
  if (state.selectedStts.size === 0) {
    showToast("Vui lòng chọn ít nhất một bài nộp để tải!", "warning");
    return;
  }

  const session = elements.sessionInput.value.trim() || state.sessionToken;
  const selectedList = Array.from(state.selectedStts);

  state.isDownloading = true;
  elements.btnStartDownload.disabled = true;
  elements.stepProgressCard.classList.remove("hidden");
  elements.btnStopDownload.classList.remove("hidden");
  elements.postDownloadBanner.classList.add("hidden");
  elements.terminalLogs.innerHTML = "";

  elements.stepProgressCard.scrollIntoView({ behavior: "smooth", block: "nearest" });

  try {
    const res = await fetch("/api/form-filter/start-download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session: session,
        only_matched: false,
        selected_stts: selectedList
      })
    });

    const data = await res.json();
    if (data.status === "ok") {
      showToast(`Đã khởi động tiến trình tải ngầm ${data.target_count} bài nộp!`, "success");
      startProgressPolling();
    } else {
      state.isDownloading = false;
      elements.btnStartDownload.disabled = false;
      elements.btnStopDownload.classList.add("hidden");
      showToast(data.message || "Lỗi khi bắt đầu tải bài nộp!", "error");
    }
  } catch (err) {
    state.isDownloading = false;
    elements.btnStartDownload.disabled = false;
    elements.btnStopDownload.classList.add("hidden");
    showToast(`Lỗi: ${err.message}`, "error");
  }
}

function startProgressPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);

  state.pollTimer = setInterval(async () => {
    try {
      const res = await fetch("/api/form-filter/status");
      const data = await res.json();

      updateProgressUI(data);

      if (!data.is_downloading) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        state.isDownloading = false;
        elements.btnStartDownload.disabled = false;
        elements.btnStopDownload.classList.add("hidden");

        if (data.has_zip) {
          elements.postDownloadBanner.classList.remove("hidden");
          showToast("Hoàn tất tải bài nộp và đóng gói file ZIP thành công!", "success", 6000);
        }
      }
    } catch (err) {
      console.error("Lỗi polling status:", err);
    }
  }, 1000);
}

function updateProgressUI(data) {
  const percent = data.percentage || 0;
  elements.progressFill.style.width = `${percent}%`;
  elements.progressFraction.textContent = `${percent}% (${data.current || 0}/${data.total || 0})`;

  if (data.current_student) {
    elements.currentStudentText.innerHTML = `Đang tải: <strong>${escapeHtml(data.current_student)}</strong>`;
  } else if (!data.is_downloading && data.current >= data.total && data.total > 0) {
    elements.currentStudentText.innerHTML = `🎉 <strong>Đã hoàn tất tất cả bài nộp!</strong>`;
  }

  // Logs terminal
  if (data.logs && data.logs.length) {
    const newLogs = data.logs.slice(state.lastLogCount);
    newLogs.forEach((log) => {
      const logLine = document.createElement("div");
      logLine.className = `log-line ${log.type || "info"}`;
      logLine.innerHTML = `<span style="opacity: 0.6;">[${log.time}]</span> ${escapeHtml(log.text)}`;
      elements.terminalLogs.appendChild(logLine);
    });
    elements.terminalLogs.scrollTop = elements.terminalLogs.scrollHeight;
    state.lastLogCount = data.logs.length;
  }
}

async function stopDownload() {
  try {
    const res = await fetch("/api/form-filter/stop", { method: "POST" });
    const data = await res.json();
    showToast(data.message || "Đã gửi tín hiệu dừng.", "warning");
  } catch (err) {
    showToast(`Lỗi: ${err.message}`, "error");
  }
}

async function openFolder(subpath = "") {
  try {
    const res = await fetch("/api/form-filter/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subpath })
    });
    const data = await res.json();
    if (data.status === "ok") {
      showToast("Đã mở thư mục trong Windows Explorer!", "success");
    } else {
      showToast(data.message || "Không thể mở thư mục!", "error");
    }
  } catch (err) {
    showToast(`Lỗi: ${err.message}`, "error");
  }
}

// =====================================================================
// 8. Modal & UI Helpers
// =====================================================================
function showLoading(title, subtitle) {
  elements.loadingTitle.textContent = title;
  elements.loadingSubtitle.textContent = subtitle;
  elements.loadingOverlay.classList.remove("hidden");
}

function hideLoading() {
  elements.loadingOverlay.classList.add("hidden");
}

// =====================================================================
// 9. Document Ready
// =====================================================================
document.addEventListener("DOMContentLoaded", () => {
  initSession();
  initUpload();
  initTableControls();
  initDownloadControls();

  elements.btnStartMatching.addEventListener("click", startMatching);
  elements.btnHideLoadingModal.addEventListener("click", hideLoading);
});
