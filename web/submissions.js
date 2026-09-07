// Greenwich Moodle - Submissions Manager Client Side Logic (UX Optimized & Fault Tolerant)
document.addEventListener("DOMContentLoaded", () => {
  // =========================================================================
  // STATE MANAGEMENT & IN-MEMORY CACHE
  // =========================================================================
  let subjects = [];
  let filteredSubjects = [];
  let currentYearFilter = "all";
  let currentSearchQuery = "";

  let selectedSubject = null;
  let selectedClass = null; // null = Quét tất cả các lớp của môn
  let currentDrops = [];
  let filteredDrops = [];
  let currentDeadlineFilter = "all";

  let selectedDrop = null;
  let selectedPart = null;
  let currentSubmissions = [];
  let filteredSubmissions = [];
  let selectedSubmissionIds = new Set();
  let statusPollTimer = null;
  let wasDownloading = false;

  // Local drops cache to avoid repeated network calls: { [courseId]: drops[] }
  const localDropsCache = new Map();

  // =========================================================================
  // DOM ELEMENTS
  // =========================================================================
  // Session & Auth
  const sessionInput = document.getElementById("sub-session-input");
  const sessionFeedback = document.getElementById("sub-session-feedback");
  const lecturerBadge = document.getElementById("lecturer-status-badge");
  const btnFetchCourses = document.getElementById("btn-sub-fetch-courses");
  const btnOpenSubmissionsFolder = document.getElementById("btn-open-submissions-folder");

  // Global Loading Modal & Step Progress
  const globalLoadingOverlay = document.getElementById("global-loading-overlay");
  const loadingModalTitle = document.getElementById("loading-modal-title");
  const loadingModalSubtitle = document.getElementById("loading-modal-subtitle");
  const stepVerify = document.getElementById("step-verify");
  const stepCourses = document.getElementById("step-courses");
  const stepGrouping = document.getElementById("step-grouping");
  const btnCancelModalLoading = document.getElementById("btn-cancel-modal-loading");

  // Toast Container
  const toastContainer = document.getElementById("toast-container");

  // Stats Counters
  const statSubjects = document.getElementById("stat-sub-subjects");
  const statDrops = document.getElementById("stat-sub-drops");
  const statFiles = document.getElementById("stat-sub-files");
  const statStatus = document.getElementById("stat-sub-status");

  // Subject Explorer & Skeletons
  const subjectsSection = document.getElementById("subjects-explorer-section");
  const subjectSearchInput = document.getElementById("subject-search-input");
  const yearFilterChips = document.querySelectorAll(".subjects-toolbar [data-year]");
  const btnRefreshSubjects = document.getElementById("btn-sub-refresh-subjects");
  const subjectsGrid = document.getElementById("subjects-grid");
  const subjectsSkeleton = document.getElementById("subjects-skeleton");
  const subjectsErrorContainer = document.getElementById("subjects-error-container");
  const subjectsErrorTitle = document.getElementById("subjects-error-title");
  const subjectsErrorDesc = document.getElementById("subjects-error-desc");
  const btnRetrySubjects = document.getElementById("btn-retry-subjects");

  // Active Subject Header & Class Switcher
  const activeSubjectHeader = document.getElementById("active-subject-header");
  const activeSubjectCode = document.getElementById("active-subject-code");
  const activeSubjectName = document.getElementById("active-subject-name");
  const activeSubjectStats = document.getElementById("active-subject-stats");
  const btnBackToSubjects = document.getElementById("btn-back-to-subjects");
  const classPillsContainer = document.getElementById("class-pills-container");

  // Drops Section, Skeletons & Errors
  const dropsSection = document.getElementById("drops-section");
  const dropsCountBadge = document.getElementById("drops-count-badge");
  const dropsContainer = document.getElementById("drops-list-container");
  const dropsSkeleton = document.getElementById("drops-skeleton");
  const dropsErrorContainer = document.getElementById("drops-error-container");
  const dropsErrorTitle = document.getElementById("drops-error-title");
  const dropsErrorDesc = document.getElementById("drops-error-desc");
  const btnRetryDrops = document.getElementById("btn-retry-drops");
  const deadlineFilterChips = document.querySelectorAll("[data-deadline]");

  // Submissions Viewer Section
  const submissionsSection = document.getElementById("submissions-viewer-section");
  const partTabsContainer = document.getElementById("part-tabs-container");
  const partMetaSummary = document.getElementById("part-meta-summary");
  const submissionsTableBody = document.getElementById("submissions-table-body");
  const subSearchInput = document.getElementById("sub-search-input");
  const subFilterStatus = document.getElementById("sub-filter-status");
  const checkAllSubmissions = document.getElementById("check-all-submissions");
  const btnDownloadSelected = document.getElementById("btn-download-selected");
  const btnDownloadSelectedText = document.getElementById("btn-download-selected-text");
  const btnDownloadAllPart = document.getElementById("btn-download-all-part");
  const btnDownloadTurnitinZip = document.getElementById("btn-download-turnitin-zip");
  const btnOpenPartFolder = document.getElementById("btn-open-part-folder");
  const emptyState = document.getElementById("sub-empty-state");

  // Live Progress & Batch Complete
  const liveProgressCard = document.getElementById("sub-live-progress-card");
  const liveTitle = document.getElementById("sub-live-title");
  const liveFile = document.getElementById("sub-live-file");
  const btnCancelDownload = document.getElementById("btn-sub-cancel-download");
  const batchDoneCard = document.getElementById("batch-download-done-card");
  const batchDoneTitle = document.getElementById("batch-done-title");
  const batchDoneDesc = document.getElementById("batch-done-desc");
  const btnDownloadLastZipFile = document.getElementById("btn-download-last-zip-file");
  const btnOpenDoneFolder = document.getElementById("btn-open-done-folder");

  // Logs Panel
  const logsToggle = document.getElementById("sub-logs-toggle");
  const logsBody = document.getElementById("sub-logs-body");

  // =========================================================================
  // TOAST NOTIFICATION UTILITIES
  // =========================================================================
  function showToast(title, message, type = "info", duration = 4500) {
    if (!toastContainer) return;

    const toast = document.createElement("div");
    toast.className = `toast-item ${type}`;

    let icon = "ℹ️";
    if (type === "success") icon = "✅";
    else if (type === "warning") icon = "⚠️";
    else if (type === "error") icon = "❌";

    toast.innerHTML = `
      <span class="toast-icon">${icon}</span>
      <div class="toast-content">
        <div class="toast-title">${escapeHtml(title)}</div>
        <div class="toast-message">${escapeHtml(message)}</div>
      </div>
      <button class="toast-close" title="Đóng">&times;</button>
    `;

    const closeBtn = toast.querySelector(".toast-close");
    closeBtn.addEventListener("click", () => removeToast(toast));

    toastContainer.appendChild(toast);

    if (duration > 0) {
      setTimeout(() => removeToast(toast), duration);
    }
  }

  function removeToast(toast) {
    if (!toast || !toast.parentNode) return;
    toast.classList.add("toast-fade-out");
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 300);
  }

  // =========================================================================
  // GLOBAL LOADING MODAL UTILITIES
  // =========================================================================
  function showGlobalLoading(title, subtitle) {
    if (!globalLoadingOverlay) return;
    if (title) loadingModalTitle.textContent = title;
    if (subtitle) loadingModalSubtitle.textContent = subtitle;
    setLoadingStep("step-verify", "waiting");
    setLoadingStep("step-courses", "waiting");
    setLoadingStep("step-grouping", "waiting");
    globalLoadingOverlay.classList.remove("hidden");
  }

  function hideGlobalLoading() {
    if (!globalLoadingOverlay) return;
    globalLoadingOverlay.classList.add("hidden");
  }

  function setLoadingStep(stepId, state) {
    const el = document.getElementById(stepId);
    if (!el) return;
    const icon = el.querySelector(".step-icon");
    el.classList.remove("active", "done");

    if (state === "active") {
      el.classList.add("active");
      if (icon) icon.textContent = "⏳";
    } else if (state === "done") {
      el.classList.add("done");
      if (icon) icon.textContent = "✅";
    } else if (state === "error") {
      if (icon) icon.textContent = "❌";
    } else {
      if (icon) icon.textContent = "⚪";
    }
  }

  if (btnCancelModalLoading) {
    btnCancelModalLoading.addEventListener("click", () => {
      hideGlobalLoading();
      showToast("Chế độ chạy nền", "Hệ thống vẫn đang tiếp tục xử lý dữ liệu từ Moodle.", "info");
    });
  }

  // =========================================================================
  // FAULT-TOLERANT FETCH (Retry with Exponential Backoff & Timeout)
  // =========================================================================
  async function fetchWithRetry(url, options = {}, maxRetries = 3, timeoutMs = 45000) {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);

      try {
        const res = await fetch(url, { ...options, signal: controller.signal });
        clearTimeout(timer);

        if (!res.ok) {
          if (res.status >= 500 && attempt < maxRetries) {
            throw new Error(`Máy chủ Moodle phản hồi mã lỗi ${res.status}`);
          }
        }

        const data = await res.json();
        return data;
      } catch (err) {
        clearTimeout(timer);
        const isLast = attempt === maxRetries;
        const errMsg = err.name === "AbortError" 
          ? "Thời gian kết nối quá lâu (Timeout)" 
          : (err.message || "Lỗi kết nối mạng");

        if (isLast) {
          throw new Error(errMsg);
        }

        const waitSec = attempt * 1.5;
        showToast("Mạng chập chờn", `${errMsg}. Đang tự động thử lại lần ${attempt + 1}/${maxRetries} sau ${waitSec}s...`, "warning", 3000);
        await new Promise(resolve => setTimeout(resolve, waitSec * 1000));
      }
    }
  }

  // =========================================================================
  // INITIALIZATION
  // =========================================================================
  const savedSession = localStorage.getItem("moodle_session");
  if (savedSession) {
    sessionInput.value = savedSession;
    // Khởi động mượt mà không chặn giao diện
    verifyLecturerSession(savedSession).then(isOk => {
      if (isOk) loadSubjects(savedSession, false);
    });
  }

  // Polling realtime
  pollStatus();
  statusPollTimer = setInterval(pollStatus, 2500);

  // Setup detectors
  setupBrowserDetectors();

  // =========================================================================
  // EVENT LISTENERS
  // =========================================================================
  // Logs Toggle
  if (logsToggle) {
    logsToggle.addEventListener("click", () => {
      logsBody.classList.toggle("collapsed");
      const indicator = logsToggle.querySelector(".logs-toggle-indicator");
      if (indicator) {
        indicator.textContent = logsBody.classList.contains("collapsed") ? "▶" : "▼";
      }
    });
  }

  // Mở folder gốc Submissions
  if (btnOpenSubmissionsFolder) {
    btnOpenSubmissionsFolder.addEventListener("click", () => openFolderOnServer(""));
  }

  // Nút Tải Danh Sách Môn Học
  btnFetchCourses.addEventListener("click", async () => {
    const sId = sessionInput.value.trim();
    if (sId) {
      localStorage.setItem("moodle_session", sId);
    }
    await verifyLecturerSession(sId);
    await loadSubjects(sId, true);
  });

  // Nút Làm Mới Dữ Liệu (Force Refresh Cache)
  if (btnRefreshSubjects) {
    btnRefreshSubjects.addEventListener("click", async () => {
      const sId = sessionInput.value.trim();
      localDropsCache.clear();
      showToast("Làm mới dữ liệu", "Đang xóa bộ nhớ đệm và quét lại trực tiếp từ Moodle...", "info");
      await loadSubjects(sId, true);
    });
  }

  // Nút Thử lại khi lỗi nạp môn học
  if (btnRetrySubjects) {
    btnRetrySubjects.addEventListener("click", () => {
      const sId = sessionInput.value.trim();
      loadSubjects(sId, true);
    });
  }

  // Nút Thử lại khi lỗi quét đợt nộp
  if (btnRetryDrops) {
    btnRetryDrops.addEventListener("click", () => {
      if (selectedClass) {
        selectClass(selectedClass, true);
      } else if (selectedSubject) {
        scanAllClassesInSubject(selectedSubject, true);
      }
    });
  }

  // Tìm kiếm môn học
  subjectSearchInput.addEventListener("input", () => {
    currentSearchQuery = subjectSearchInput.value.trim().toLowerCase();
    applySubjectFilters();
  });

  // Bộ lọc năm học
  yearFilterChips.forEach(chip => {
    chip.addEventListener("click", () => {
      yearFilterChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      currentYearFilter = chip.dataset.year;
      applySubjectFilters();
    });
  });

  // Quay lại danh sách môn học
  if (btnBackToSubjects) {
    btnBackToSubjects.addEventListener("click", () => {
      activeSubjectHeader.classList.add("hidden");
      dropsSection.classList.add("hidden");
      submissionsSection.classList.add("hidden");
      emptyState.classList.remove("hidden");
      selectedSubject = null;
      document.querySelectorAll(".subject-card").forEach(c => c.classList.remove("active"));
      subjectsSection.scrollIntoView({ behavior: "smooth" });
    });
  }

  // Bộ lọc hạn nộp
  deadlineFilterChips.forEach(chip => {
    chip.addEventListener("click", () => {
      deadlineFilterChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      currentDeadlineFilter = chip.dataset.deadline;
      applyDeadlineFilter();
    });
  });

  // Tìm kiếm và lọc trong bảng sinh viên
  subSearchInput.addEventListener("input", applyTableFilter);
  subFilterStatus.addEventListener("change", applyTableFilter);

  // Checkbox chọn tất cả
  checkAllSubmissions.addEventListener("change", () => {
    const isChecked = checkAllSubmissions.checked;
    selectedSubmissionIds.clear();

    const checkboxes = submissionsTableBody.querySelectorAll(".sub-row-check");
    checkboxes.forEach(cb => {
      if (!cb.disabled) {
        cb.checked = isChecked;
        if (isChecked) {
          selectedSubmissionIds.add(cb.value);
        }
      }
    });
    updateSelectedButtons();
  });

  // Nút Tải các bài đã chọn
  btnDownloadSelected.addEventListener("click", () => {
    if (selectedSubmissionIds.size === 0 || !selectedPart || !selectedDrop || !selectedSubject) return;
    const targets = currentSubmissions.filter(s => selectedSubmissionIds.has(String(s.paper_id)));
    if (targets.length === 0) return;
    triggerBatchDownload(targets);
  });

  // Nút Tải toàn bộ Part
  btnDownloadAllPart.addEventListener("click", () => {
    if (!selectedPart || !selectedDrop || !selectedSubject) return;
    const targets = currentSubmissions.filter(s => s.has_submission);
    if (targets.length === 0) {
      showToast("Không có bài nộp", "Không có sinh viên nào đã nộp bài trong Part này.", "warning");
      return;
    }
    if (confirm(`Bạn có chắc muốn tải toàn bộ ${targets.length} bài nộp của ${selectedPart.part_name}?`)) {
      triggerBatchDownload(targets);
    }
  });

  // Nút Tải ZIP chính thức từ Turnitin
  btnDownloadTurnitinZip.addEventListener("click", async () => {
    if (!selectedPart || !selectedDrop || !selectedSubject) return;

    try {
      btnDownloadTurnitinZip.disabled = true;
      const originalText = btnDownloadTurnitinZip.innerHTML;
      btnDownloadTurnitinZip.innerHTML = "⏳ Đang tạo file ZIP từ Turnitin...";
      showToast("Đang nén ZIP", "Turnitin đang tạo gói ZIP chính thức, vui lòng đợi...", "info", 6000);

      const data = await fetchWithRetry("/api/submissions/download-zip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_name: selectedSubject.name || selectedSubject.title,
          drop_title: selectedDrop.title,
          drop_url: selectedDrop.url,
          assignment_id: selectedDrop.assignment_id,
          part_id: selectedPart.part_id,
          part_name: selectedPart.part_name
        })
      }, 2, 90000);

      if (data.status === "ok" && data.download_url) {
        triggerBrowserDownload(data.download_url, data.file_name);
        showToast("Tải ZIP thành công", `File ZIP: ${data.file_name}`, "success");
      } else {
        showToast("Lỗi nén ZIP", data.message || "Turnitin không thể tạo file ZIP", "error");
      }
    } catch (e) {
      showToast("Lỗi kết nối", `Không thể tải file ZIP: ${e.message}`, "error");
    } finally {
      btnDownloadTurnitinZip.disabled = false;
      btnDownloadTurnitinZip.innerHTML = "📦 Tải ZIP Turnitin";
    }
  });

  // Nút Mở thư mục của Part hiện tại
  btnOpenPartFolder.addEventListener("click", () => {
    if (!selectedSubject || !selectedDrop || !selectedPart) return;
    const cleanSub = sanitizeName(selectedSubject.folder_name || selectedSubject.name);
    const cleanDrop = sanitizeName(selectedDrop.title);
    const cleanPart = sanitizeName(selectedPart.part_name);
    openFolderOnServer(`${cleanSub}/${cleanDrop}/${cleanPart}`);
  });

  // Nút Hủy tiến trình tải
  btnCancelDownload.addEventListener("click", async () => {
    try {
      await fetch("/api/submissions/download/cancel", { method: "POST" });
      showToast("Dừng tải", "Đã gửi yêu cầu dừng tiến trình tải bài nộp.", "warning");
    } catch (e) {
      console.error("Lỗi khi hủy tải:", e);
    }
  });

  // Nút tải file ZIP mới nhất về máy
  btnDownloadLastZipFile.addEventListener("click", () => {
    triggerBrowserDownload("/api/submissions/download-last-zip", "Coursework_Submissions.zip");
  });

  // Nút mở thư mục sau khi tải xong
  btnOpenDoneFolder.addEventListener("click", () => {
    openFolderOnServer("");
  });

  // =========================================================================
  // CORE LOGIC: SESSION & SUBJECTS EXPLORER
  // =========================================================================
  function showFeedback(msg, type = "info") {
    sessionFeedback.className = `session-feedback ${type}`;
    sessionFeedback.innerHTML = msg;
    sessionFeedback.classList.remove("hidden");
  }

  function setupBrowserDetectors() {
    const browsers = ["firefox", "edge", "chrome"];
    browsers.forEach(b => {
      const btn = document.getElementById(`btn-sub-detect-${b}`);
      if (!btn) return;
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        const originalText = btn.innerHTML;
        btn.innerHTML = "⏳ Đang tìm...";
        try {
          const data = await fetchWithRetry(`/api/session/detect?browser=${b}`, {}, 1, 10000);
          if (data.status === "ok" && data.moodle_session) {
            sessionInput.value = data.moodle_session;
            localStorage.setItem("moodle_session", data.moodle_session);
            showFeedback(`✅ ${data.message}`, "success");
            showToast("Tìm thấy Cookie", data.message, "success");
            await verifyLecturerSession(data.moodle_session);
            await loadSubjects(data.moodle_session, false);
          } else {
            showFeedback(`⚠️ ${data.message || "Không tìm thấy cookie phiên Moodle."}`, "error");
            showToast("Không tìm thấy Cookie", data.message || "Vui lòng mở Moodle trên trình duyệt trước", "warning");
          }
        } catch (e) {
          showFeedback(`❌ Lỗi trích xuất từ ${b}: ${e.message}`, "error");
        } finally {
          btn.disabled = false;
          btn.innerHTML = originalText;
        }
      });
    });
  }

  async function verifyLecturerSession(sessionId) {
    if (!sessionId) return false;
    try {
      const data = await fetchWithRetry("/api/submissions/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId })
      }, 2, 20000);

      if (data.status === "ok" && data.is_lecturer) {
        lecturerBadge.className = "lecturer-badge-pill verified";
        lecturerBadge.innerHTML = `<span>🧑‍🏫 Giảng Viên: ${escapeHtml(data.user_name || "Verified")}</span>`;
        return true;
      } else {
        lecturerBadge.className = "lecturer-badge-pill";
        lecturerBadge.innerHTML = `<span>⚠️ Chưa xác thực Giảng viên</span>`;
        return false;
      }
    } catch (e) {
      console.warn("Lỗi xác thực giảng viên:", e);
      return false;
    }
  }

  async function loadSubjects(sessionId, forceRefresh = false) {
    btnFetchCourses.disabled = true;
    btnFetchCourses.querySelector("span").textContent = "Đang nạp môn học...";
    subjectsErrorContainer.classList.add("hidden");

    // Hiển thị Global Loading Modal & Skeleton
    showGlobalLoading("Đang Tải Danh Sách Môn Học...", "Đang kết nối Greenwich Moodle và nạp 120+ lớp học của Giảng viên.");
    setLoadingStep("step-verify", "done");
    setLoadingStep("step-courses", "active");

    subjectsSkeleton.classList.remove("hidden");
    subjectsGrid.classList.add("hidden");

    try {
      const data = await fetchWithRetry("/api/submissions/subjects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, force_refresh: forceRefresh })
      }, 3, 55000);

      setLoadingStep("step-courses", "done");
      setLoadingStep("step-grouping", "active");

      if (data.status === "ok") {
        subjects = data.subjects || [];
        statSubjects.textContent = subjects.length;
        setLoadingStep("step-grouping", "done");

        setTimeout(() => {
          hideGlobalLoading();
          subjectsSkeleton.classList.add("hidden");
          subjectsGrid.classList.remove("hidden");
          applySubjectFilters();

          const cacheMsg = data.from_cache ? " (Từ bộ nhớ đệm tức thì)" : "";
          showFeedback(`✅ Đã nạp thành công ${subjects.length} môn học (tổng hợp từ ${data.total_classes || 0} lớp học)${cacheMsg}!`, "success");
          showToast("Nạp môn học thành công", `Đã tải ${subjects.length} môn học duy nhất${cacheMsg}.`, "success");
        }, 350);
      } else {
        throw new Error(data.message || "Lỗi không xác định từ Moodle");
      }
    } catch (e) {
      hideGlobalLoading();
      subjectsSkeleton.classList.add("hidden");
      subjectsGrid.classList.add("hidden");
      subjectsErrorContainer.classList.remove("hidden");

      subjectsErrorTitle.textContent = "Không thể nạp danh sách môn học";
      subjectsErrorDesc.textContent = `${e.message}. Máy chủ Moodle có thể đang quá tải hoặc kết nối mạng bị gián đoạn.`;

      showFeedback(`❌ Lỗi tải môn học: ${e.message}`, "error");
      showToast("Lỗi kết nối", `Không thể nạp danh sách môn học: ${e.message}`, "error", 6000);
    } finally {
      btnFetchCourses.disabled = false;
      btnFetchCourses.querySelector("span").textContent = "Tải Danh Sách Môn Học";
    }
  }

  function applySubjectFilters() {
    filteredSubjects = subjects.filter(sub => {
      // Filter year
      if (currentYearFilter !== "all") {
        const hasYear = (sub.classes || []).some(c => c.academic_year === currentYearFilter);
        if (!hasYear) return false;
      }

      // Filter search
      if (currentSearchQuery) {
        const codeMatch = (sub.code || "").toLowerCase().includes(currentSearchQuery);
        const nameMatch = (sub.name || "").toLowerCase().includes(currentSearchQuery);
        const titleMatch = (sub.title || "").toLowerCase().includes(currentSearchQuery);
        const classMatch = (sub.classes || []).some(c => (c.class_code || "").toLowerCase().includes(currentSearchQuery));
        if (!codeMatch && !nameMatch && !titleMatch && !classMatch) return false;
      }

      return true;
    });

    renderSubjectsGrid(filteredSubjects);
  }

  function renderSubjectsGrid(list) {
    subjectsGrid.innerHTML = "";

    if (list.length === 0) {
      subjectsGrid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1; padding: 32px;">
          <p style="color: var(--text-muted); font-size: 0.95rem;">Không tìm thấy môn học nào khớp với điều kiện tìm kiếm.</p>
        </div>
      `;
      return;
    }

    list.forEach(sub => {
      const card = document.createElement("div");
      card.className = "subject-card";
      if (selectedSubject && selectedSubject.subject_key === sub.subject_key) {
        card.classList.add("active");
      }

      const yearsSet = new Set();
      const classCodes = [];
      (sub.classes || []).forEach(c => {
        if (c.academic_year) yearsSet.add(c.academic_year);
        if (c.class_code && !classCodes.includes(c.class_code)) {
          classCodes.push(c.class_code);
        }
      });
      const yearsText = Array.from(yearsSet).sort().reverse().join(", ") || "2025-26";
      const totalClasses = (sub.classes || []).length;

      const pillsHtml = classCodes.slice(0, 5).map(code => 
        `<span class="class-mini-badge">${escapeHtml(code)}</span>`
      ).join("");
      const morePillHtml = classCodes.length > 5 ? `<span class="class-mini-badge" style="background: rgba(255,255,255,0.08); color: var(--text-dim);">+${classCodes.length - 5}</span>` : "";

      card.innerHTML = `
        <div class="subject-header-row">
          <span class="subject-code">${escapeHtml(sub.code || sub.name)}</span>
          <span class="subject-year-badge">${escapeHtml(yearsText)}</span>
        </div>
        <h3 class="subject-title">${escapeHtml(sub.title || sub.name)}</h3>
        <div class="subject-footer-row">
          <div class="subject-classes-preview">
            ${pillsHtml}
            ${morePillHtml}
          </div>
          <span class="subject-class-count">📚 ${totalClasses} lớp học</span>
        </div>
      `;

      card.addEventListener("click", () => {
        document.querySelectorAll(".subject-card").forEach(c => c.classList.remove("active"));
        card.classList.add("active");
        selectSubject(sub);
      });

      subjectsGrid.appendChild(card);
    });
  }

  // =========================================================================
  // ACTIVE SUBJECT & CLASS SWITCHER (PARALLEL FETCH & CACHE)
  // =========================================================================
  function selectSubject(sub) {
    selectedSubject = sub;
    activeSubjectHeader.classList.remove("hidden");
    activeSubjectCode.textContent = sub.code || sub.name;
    activeSubjectName.textContent = sub.title || sub.name;

    const totalClasses = (sub.classes || []).length;
    const years = Array.from(new Set((sub.classes || []).map(c => c.academic_year).filter(Boolean))).join(", ");
    activeSubjectStats.textContent = `${totalClasses} lớp học • Năm học: ${years || "2025-26"}`;

    renderClassPills(sub);

    // Mặc định quét tất cả các lớp của môn học này (chạy song song đa luồng rất nhanh)
    scanAllClassesInSubject(sub, false);
  }

  function renderClassPills(sub) {
    classPillsContainer.innerHTML = "";

    // Nút "Quét Tất Cả Các Lớp"
    const allBtn = document.createElement("button");
    allBtn.className = "class-pill-btn active";
    allBtn.dataset.classId = "all";
    allBtn.innerHTML = `<span>🌟 Quét Tất Cả Các Lớp (${(sub.classes || []).length})</span>`;
    allBtn.addEventListener("click", () => {
      classPillsContainer.querySelectorAll(".class-pill-btn").forEach(b => b.classList.remove("active"));
      allBtn.classList.add("active");
      scanAllClassesInSubject(sub, false);
    });
    classPillsContainer.appendChild(allBtn);

    // Nút cho từng lớp
    (sub.classes || []).forEach(c => {
      const btn = document.createElement("button");
      btn.className = "class-pill-btn";
      btn.dataset.classId = c.id;
      const yr = c.academic_year ? ` (${c.academic_year})` : "";
      btn.innerHTML = `<span>${escapeHtml(c.class_code ? `Lớp ${c.class_code}` : c.raw_name)}${yr}</span>`;
      btn.addEventListener("click", () => {
        classPillsContainer.querySelectorAll(".class-pill-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        selectClass(c, false);
      });
      classPillsContainer.appendChild(btn);
    });
  }

  // Quét song song tất cả các lớp của môn học
  async function scanAllClassesInSubject(sub, forceRefresh = false) {
    selectedClass = null;
    dropsErrorContainer.classList.add("hidden");
    dropsSkeleton.classList.remove("hidden");
    dropsContainer.classList.add("hidden");
    dropsSection.classList.remove("hidden");
    submissionsSection.classList.add("hidden");
    emptyState.classList.add("hidden");

    showToast("Đang quét đợt nộp", `Đang quét song song ${(sub.classes || []).length} lớp của môn ${sub.code || sub.name}...`, "info", 3000);

    try {
      const sessionId = sessionInput.value.trim();
      const courseIds = (sub.classes || []).map(c => c.id);

      const data = await fetchWithRetry("/api/submissions/subject-drops", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_ids: courseIds,
          session_id: sessionId,
          force_refresh: forceRefresh
        })
      }, 3, 45000);

      dropsSkeleton.classList.add("hidden");
      dropsContainer.classList.remove("hidden");

      if (data.status === "ok") {
        currentDrops = data.drops || [];
        statDrops.textContent = currentDrops.length;
        applyDeadlineFilter();
        showToast("Quét hoàn tất", `Tìm thấy ${currentDrops.length} đợt nộp bài Coursework.`, "success");
      } else {
        throw new Error(data.message || "Lỗi quét các lớp");
      }
    } catch (e) {
      dropsSkeleton.classList.add("hidden");
      dropsContainer.classList.add("hidden");
      dropsErrorContainer.classList.remove("hidden");
      dropsErrorTitle.textContent = "Không thể quét các đợt nộp của môn";
      dropsErrorDesc.textContent = `${e.message}. Vui lòng bấm Thử lại để quét lại.`;
      showToast("Lỗi quét đợt nộp", e.message, "error", 5000);
    }
  }

  // Quét 1 lớp cụ thể
  async function selectClass(classObj, forceRefresh = false) {
    selectedClass = classObj;
    dropsErrorContainer.classList.add("hidden");
    dropsSkeleton.classList.remove("hidden");
    dropsContainer.classList.add("hidden");
    dropsSection.classList.remove("hidden");
    submissionsSection.classList.add("hidden");
    emptyState.classList.add("hidden");

    const label = classObj.class_code ? `Lớp ${classObj.class_code}` : classObj.name;
    showToast("Đang quét đợt nộp", `Đang kiểm tra đợt nộp của ${label}...`, "info", 2500);

    try {
      const sessionId = sessionInput.value.trim();
      const data = await fetchWithRetry("/api/submissions/drops", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_id: classObj.id,
          session_id: sessionId,
          force_refresh: forceRefresh
        })
      }, 3, 40000);

      dropsSkeleton.classList.add("hidden");
      dropsContainer.classList.remove("hidden");

      if (data.status === "ok") {
        currentDrops = data.drops || [];
        statDrops.textContent = currentDrops.length;
        applyDeadlineFilter();
      } else {
        throw new Error(data.message || "Lỗi quét đợt nộp");
      }
    } catch (e) {
      dropsSkeleton.classList.add("hidden");
      dropsContainer.classList.add("hidden");
      dropsErrorContainer.classList.remove("hidden");
      dropsErrorTitle.textContent = "Không thể quét đợt nộp bài của lớp";
      dropsErrorDesc.textContent = `${e.message}. Vui lòng bấm Thử lại.`;
      showToast("Lỗi quét lớp", e.message, "error", 5000);
    }
  }

  // =========================================================================
  // DROPS & DEADLINE PRESENTATION
  // =========================================================================
  function applyDeadlineFilter() {
    filteredDrops = currentDrops.filter(drop => {
      if (currentDeadlineFilter === "all") return true;

      const st = drop.deadline_status || "closed";
      const days = drop.days_left;

      if (currentDeadlineFilter === "urgent") {
        if (days !== null && days !== undefined) {
          return days >= -14 && days <= 30;
        }
        return st === "urgent" || st === "upcoming";
      }

      if (currentDeadlineFilter === "open") {
        if (days !== null && days !== undefined) {
          return days >= 0;
        }
        return st === "open" || st === "urgent" || st === "upcoming";
      }

      if (currentDeadlineFilter === "closed") {
        if (days !== null && days !== undefined) {
          return days < 0;
        }
        return st === "closed";
      }

      return true;
    });

    renderDrops(filteredDrops);
  }

  function renderDrops(drops) {
    dropsContainer.innerHTML = "";

    if (drops.length === 0) {
      dropsSection.classList.remove("hidden");
      dropsCountBadge.textContent = "0 đợt";
      dropsContainer.innerHTML = `
        <div class="empty-state" style="padding: 32px;">
          <p style="color: var(--text-muted);">Không có đợt nộp bài nào phù hợp với bộ lọc hạn nộp này.</p>
        </div>
      `;
      submissionsSection.classList.add("hidden");
      return;
    }

    dropsSection.classList.remove("hidden");
    dropsCountBadge.textContent = `${drops.length} đợt nộp`;

    drops.forEach((drop) => {
      const card = document.createElement("div");
      card.className = "drop-card";
      if (selectedDrop && selectedDrop.cm_id === drop.cm_id) {
        card.classList.add("selected");
      }
      card.dataset.cmId = drop.cm_id;

      const partsCount = (drop.parts || []).length;
      const partsBadgeText = partsCount === 1 ? "1 Part" : `${partsCount} Parts`;
      const deadlineHtml = renderDeadlineBadge(drop);

      card.innerHTML = `
        <div class="drop-card-header">
          <div class="drop-title-area" style="flex: 1;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px;">
              ${deadlineHtml}
              <span class="drop-section-badge">${escapeHtml(drop.section_name || "Coursework")}</span>
              ${drop.course_id ? `<span class="class-mini-badge">ID: ${drop.course_id}</span>` : ""}
            </div>

            <h3 class="drop-title">
              <span>${escapeHtml(drop.title)}</span>
            </h3>

            <div class="drop-meta-row" style="margin-top: 8px;">
              <span class="drop-meta-item">📦 ${partsBadgeText}</span>
              ${drop.primary_due_date ? `<span class="drop-meta-item">⏰ Hạn nộp: <strong>${escapeHtml(drop.primary_due_date)}</strong></span>` : ""}
              <a href="${drop.url}" target="_blank" class="drop-meta-item" style="color: var(--accent-cyan); text-decoration: none;">
                🌐 Mở trên Moodle ↗
              </a>
            </div>
          </div>

          <button class="btn btn-primary btn-sm btn-view-drop" style="align-self: center; white-space: nowrap;">
            Xem Danh Sách Sinh Viên (${partsCount} Part) →
          </button>
        </div>
      `;

      card.addEventListener("click", () => {
        document.querySelectorAll(".drop-card").forEach(c => c.classList.remove("selected"));
        card.classList.add("selected");
        selectDrop(drop);
      });

      dropsContainer.appendChild(card);
    });

    // Tự động mở đợt nộp đầu tiên
    if (drops.length > 0 && !selectedDrop) {
      const firstCard = dropsContainer.querySelector(".drop-card");
      if (firstCard) {
        firstCard.classList.add("selected");
        selectDrop(drops[0]);
      }
    }
  }

  function renderDeadlineBadge(drop) {
    const days = drop.days_left;
    const st = drop.deadline_status;

    if (days !== null && days !== undefined) {
      if (days < 0) {
        const absDays = Math.abs(days);
        return `<span class="deadline-badge closed">⚪ Đã kết thúc (${absDays} ngày trước)</span>`;
      } else if (days <= 7) {
        return `<span class="deadline-badge urgent">🔥 Sắp tới hạn: Còn ${days} ngày</span>`;
      } else if (days <= 30) {
        return `<span class="deadline-badge upcoming">⏳ Sắp tới: Còn ${days} ngày</span>`;
      } else {
        return `<span class="deadline-badge open">🟢 Đang mở nộp (Còn ${days} ngày)</span>`;
      }
    }

    if (drop.deadline_badge) {
      return `<span class="deadline-badge ${st || 'open'}">${escapeHtml(drop.deadline_badge)}</span>`;
    }

    return `<span class="deadline-badge closed">⚪ Đã lên lịch</span>`;
  }

  // =========================================================================
  // SUBMISSIONS TABLE & STUDENT DOWNLOADS
  // =========================================================================
  function selectDrop(drop) {
    selectedDrop = drop;
    emptyState.classList.add("hidden");
    submissionsSection.classList.remove("hidden");

    renderPartTabs(drop.parts || []);

    if (drop.parts && drop.parts.length > 0) {
      selectPart(drop.parts[0]);
    } else {
      submissionsTableBody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-dim);">Đợt nộp này không có Part nào.</td></tr>';
    }
  }

  function renderPartTabs(parts) {
    partTabsContainer.innerHTML = "";
    parts.forEach((p, idx) => {
      const btn = document.createElement("button");
      btn.className = `part-tab-btn ${idx === 0 ? "active" : ""}`;
      btn.dataset.partId = p.part_id;
      btn.innerHTML = `<span>📌 ${escapeHtml(p.part_name)}</span>`;
      btn.addEventListener("click", () => {
        partTabsContainer.querySelectorAll(".part-tab-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        selectPart(p);
      });
      partTabsContainer.appendChild(btn);
    });
  }

  async function selectPart(part) {
    selectedPart = part;
    selectedSubmissionIds.clear();
    updateSelectedButtons();

    const daysBadge = part.days_left !== null && part.days_left !== undefined
      ? (part.days_left < 0 ? `(Đã kết thúc ${Math.abs(part.days_left)} ngày trước)` : `(Còn ${part.days_left} ngày)`)
      : "";

    partMetaSummary.innerHTML = `
      <span><strong>Hạn nộp (Due Date):</strong> ${escapeHtml(part.due_date || "Chưa thiết lập")} <em style="color: #93c5fd;">${daysBadge}</em></span>
      <span>&bull;</span>
      <span><strong>Bắt đầu:</strong> ${escapeHtml(part.start_date || "N/A")}</span>
      <span>&bull;</span>
      <span><strong>Điểm tối đa:</strong> ${escapeHtml(part.max_marks || "100")}</span>
    `;

    // Shimmering table rows
    submissionsTableBody.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; padding: 36px 20px; color: var(--text-muted);">
          <div style="display: flex; flex-direction: column; align-items: center; gap: 12px;">
            <div class="loading-spinner-wrapper" style="width: 42px; height: 42px; margin: 0;">
              <div class="spinner-ring"></div>
            </div>
            <span style="font-weight: 600; color: #93c5fd;">Đang nạp danh sách sinh viên & bài nộp từ Turnitin...</span>
            <span style="font-size: 0.8rem; color: var(--text-dim);">Hệ thống đang tự động lọc các bài đã nộp và tính điểm tương đồng.</span>
          </div>
        </td>
      </tr>
    `;

    try {
      const sessionId = sessionInput.value.trim();
      const data = await fetchWithRetry("/api/submissions/list", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          drop_url: selectedDrop.url,
          assignment_id: selectedDrop.assignment_id,
          part_id: part.part_id,
          sesskey: selectedDrop.sesskey,
          session_id: sessionId
        })
      }, 3, 40000);

      if (data.status === "ok") {
        currentSubmissions = data.submissions || [];
        partMetaSummary.innerHTML += `
          <span>&bull;</span>
          <span style="color: #6ee7b7; font-weight: 600;">Đã nộp: ${data.submitted_count || 0}/${data.total || 0}</span>
        `;
        applyTableFilter();
      } else {
        throw new Error(data.message || "Không thể tải danh sách sinh viên");
      }
    } catch (e) {
      submissionsTableBody.innerHTML = `
        <tr>
          <td colspan="8" style="text-align: center; padding: 24px; color: #fca5a5;">
            ❌ Lỗi nạp bài nộp: ${escapeHtml(e.message)}
            <br>
            <button class="btn btn-secondary btn-sm" style="margin-top: 10px;" onclick="window.location.reload()">
              🔄 Thử Lại
            </button>
          </td>
        </tr>
      `;
      showToast("Lỗi nạp bài nộp", e.message, "error");
    }
  }

  function applyTableFilter() {
    const query = subSearchInput.value.trim().toLowerCase();
    const filter = subFilterStatus.value;

    filteredSubmissions = currentSubmissions.filter(s => {
      // Filter status
      if (filter === "submitted" && !s.has_submission) return false;
      if (filter === "missing" && s.has_submission) return false;

      // Query search
      if (query) {
        const nameMatch = (s.student_name || "").toLowerCase().includes(query);
        const idMatch = (s.student_id || "").toLowerCase().includes(query);
        const titleMatch = (s.submission_title || "").toLowerCase().includes(query);
        const paperMatch = String(s.paper_id || "").toLowerCase().includes(query);
        if (!nameMatch && !idMatch && !titleMatch && !paperMatch) return false;
      }

      return true;
    });

    renderSubmissionsTable(filteredSubmissions);
  }

  function renderSubmissionsTable(list) {
    submissionsTableBody.innerHTML = "";

    if (list.length === 0) {
      submissionsTableBody.innerHTML = `
        <tr>
          <td colspan="8" style="text-align: center; padding: 24px; color: var(--text-dim);">
            Không có sinh viên nào khớp với bộ lọc hiện tại.
          </td>
        </tr>
      `;
      return;
    }

    list.forEach(item => {
      const tr = document.createElement("tr");

      // Checkbox
      const tdCheck = document.createElement("td");
      tdCheck.style.textAlign = "center";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.className = "custom-checkbox sub-row-check";
      cb.value = item.paper_id;
      cb.disabled = !item.has_submission;
      cb.checked = selectedSubmissionIds.has(String(item.paper_id));
      cb.addEventListener("change", () => {
        if (cb.checked) {
          selectedSubmissionIds.add(String(item.paper_id));
        } else {
          selectedSubmissionIds.delete(String(item.paper_id));
        }
        updateSelectedButtons();
      });
      tdCheck.appendChild(cb);
      tr.appendChild(tdCheck);

      // Student info
      const tdStudent = document.createElement("td");
      tdStudent.innerHTML = `
        <div class="student-cell">
          ${item.student_profile_url ? `<a href="${item.student_profile_url}" target="_blank" class="student-name-link">${escapeHtml(item.student_name)}</a>` : `<span class="student-name-link">${escapeHtml(item.student_name)}</span>`}
          <span class="student-id-text">MSSV/ID: ${escapeHtml(item.student_id || "N/A")}</span>
        </div>
      `;
      tr.appendChild(tdStudent);

      // Submission Title
      const tdTitle = document.createElement("td");
      tdTitle.innerHTML = `
        <span style="font-weight: 500; color: #f1f5f9;">${escapeHtml(item.submission_title || "Coursework")}</span>
        ${item.paper_id ? `<br><span style="font-size: 0.76rem; color: var(--text-dim);">Paper ID: ${item.paper_id}</span>` : ""}
      `;
      tr.appendChild(tdTitle);

      // Submitted At
      const tdTime = document.createElement("td");
      tdTime.innerHTML = item.submitted_at ? `<span style="font-size: 0.85rem; color: #cbd5e1;">${escapeHtml(item.submitted_at)}</span>` : `<span style="color: var(--text-dim);">--</span>`;
      tr.appendChild(tdTime);

      // Similarity Score
      const tdSim = document.createElement("td");
      tdSim.style.textAlign = "center";
      tdSim.innerHTML = renderSimilarityPill(item.similarity_score, item.similarity_text, item.has_submission);
      tr.appendChild(tdSim);

      // Grade
      const tdGrade = document.createElement("td");
      tdGrade.style.textAlign = "center";
      tdGrade.innerHTML = `
        <span class="grade-badge">
          ${item.grade ? escapeHtml(item.grade) : "--"}
          <span class="max-score">/${item.max_grade || "100"}</span>
        </span>
      `;
      tr.appendChild(tdGrade);

      // Status
      const tdStatus = document.createElement("td");
      tdStatus.style.textAlign = "center";
      tdStatus.innerHTML = item.has_submission 
        ? `<span class="status-pill submitted">✔ Đã nộp</span>` 
        : `<span class="status-pill missing">Chưa nộp</span>`;
      tr.appendChild(tdStatus);

      // Actions
      const tdAction = document.createElement("td");
      tdAction.style.textAlign = "center";
      if (item.has_submission) {
        const btnDl = document.createElement("button");
        btnDl.className = "btn-row-download";
        btnDl.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          <span>Tải file</span>
        `;
        btnDl.addEventListener("click", () => downloadSingleStudent(item, btnDl));
        tdAction.appendChild(btnDl);
      } else {
        tdAction.innerHTML = `<span style="color: var(--text-dim); font-size: 0.8rem;">--</span>`;
      }
      tr.appendChild(tdAction);

      submissionsTableBody.appendChild(tr);
    });
  }

  function renderSimilarityPill(score, text, hasSubmission) {
    if (!hasSubmission) {
      return `<span class="similarity-pill sim-none">--</span>`;
    }
    if (score === null || score === undefined || isNaN(score)) {
      return `<span class="similarity-pill sim-none">${escapeHtml(text || "Chờ xử lý")}</span>`;
    }

    let colorClass = "sim-green";
    if (score >= 75) colorClass = "sim-red";
    else if (score >= 50) colorClass = "sim-orange";
    else if (score >= 25) colorClass = "sim-yellow";

    return `<span class="similarity-pill ${colorClass}">${score}%</span>`;
  }

  function updateSelectedButtons() {
    const count = selectedSubmissionIds.size;
    btnDownloadSelectedText.textContent = `Tải bài đã chọn (${count})`;
    btnDownloadSelected.disabled = count === 0;
  }

  // Tải trực tiếp bài nộp của 1 sinh viên (lưu server + tải về browser)
  async function downloadSingleStudent(item, btnElement) {
    if (!selectedDrop || !selectedPart || !selectedSubject) return;

    btnElement.disabled = true;
    const oldText = btnElement.innerHTML;
    btnElement.innerHTML = `<span>⏳ Đang tải...</span>`;
    showToast("Đang tải bài nộp", `Đang kết nối Turnitin LTI để tải bài của ${item.student_name}...`, "info", 3000);

    try {
      const data = await fetchWithRetry("/api/submissions/download-single", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          drop_url: selectedDrop.url,
          assignment_id: selectedDrop.assignment_id,
          submission_id: item.paper_id,
          course_name: selectedSubject.name || selectedSubject.title,
          drop_title: selectedDrop.title,
          part_name: selectedPart.part_name,
          student_name: item.student_name,
          student_id: item.student_id,
          submission_title: item.submission_title
        })
      }, 2, 60000);

      if (data.status === "ok") {
        btnElement.innerHTML = `<span>✅ Đã tải</span>`;
        if (data.download_url) {
          triggerBrowserDownload(data.download_url, data.file_name);
        }
        showToast("Tải bài nộp thành công", `File: ${data.file_name}`, "success");
        setTimeout(() => {
          btnElement.disabled = false;
          btnElement.innerHTML = oldText;
        }, 3000);
      } else {
        throw new Error(data.message || "Lỗi tải bài nộp");
      }
    } catch (e) {
      showToast("Lỗi tải bài nộp", e.message, "error", 5000);
      btnElement.disabled = false;
      btnElement.innerHTML = oldText;
    }
  }

  // Tải loạt bài nộp
  async function triggerBatchDownload(targets) {
    try {
      batchDoneCard.classList.add("hidden");
      const data = await fetchWithRetry("/api/submissions/download-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_name: selectedSubject.name || selectedSubject.title,
          drop_title: selectedDrop.title,
          drop_url: selectedDrop.url,
          assignment_id: selectedDrop.assignment_id,
          part_name: selectedPart.part_name,
          submissions: targets
        })
      }, 2, 30000);

      if (data.status === "ok") {
        liveProgressCard.classList.remove("hidden");
        liveTitle.textContent = `Đang tải ${targets.length} bài nộp của ${selectedPart.part_name}...`;
        wasDownloading = true;
        showToast("Bắt đầu tải loạt", `Hệ thống đang tải ${targets.length} bài nộp và sẽ tự động nén file ZIP.`, "info", 4000);
      } else {
        showToast("Lỗi tải loạt", data.message, "error");
      }
    } catch (e) {
      showToast("Lỗi kết nối", e.message, "error");
    }
  }

  // Polling status
  async function pollStatus() {
    try {
      const res = await fetch("/api/submissions/status");
      const data = await res.json();

      statFiles.textContent = data.total_files_on_disk || 0;

      if (data.is_downloading) {
        liveProgressCard.classList.remove("hidden");
        batchDoneCard.classList.add("hidden");
        wasDownloading = true;

        liveTitle.textContent = `Đang tải bài nộp [${data.total_downloaded || 0}/${data.total_target || 0}]: ${data.current_course || ""}`;
        liveFile.textContent = data.current_file || data.current_student || "Đang kết nối Turnitin...";
        statStatus.textContent = "Đang tải...";
        statStatus.className = "stat-value status-badge downloading";
      } else {
        liveProgressCard.classList.add("hidden");
        statStatus.textContent = "Sẵn sàng";
        statStatus.className = "stat-value status-badge ready";

        if (wasDownloading && data.has_last_zip) {
          wasDownloading = false;
          batchDoneCard.classList.remove("hidden");
          batchDoneTitle.textContent = `Đã hoàn tất tải toàn bộ bài nộp! (${data.total_downloaded || 0} files)`;
          batchDoneDesc.textContent = `Đã tự động nén sẵn file ZIP: ${data.last_zip_name || "Submissions.zip"}`;
          showToast("Hoàn tất tải loạt", `Đã lưu ${data.total_downloaded || 0} bài nộp. Bấm "Tải File ZIP Về Máy" để nhận toàn bộ.`, "success", 7000);
        }
      }

      if (data.logs && data.logs.length > 0) {
        renderLogs(data.logs);
      }
    } catch (e) {
      // Ignored polling errors
    }
  }

  function renderLogs(logs) {
    logsBody.innerHTML = "";
    logs.forEach(log => {
      const entry = document.createElement("div");
      entry.className = `log-entry ${log.type || "info"}`;
      entry.innerHTML = `<span class="log-time">[${escapeHtml(log.time || "")}]</span> <span>${escapeHtml(log.text || "")}</span>`;
      logsBody.appendChild(entry);
    });
    logsBody.scrollTop = logsBody.scrollHeight;
  }

  // =========================================================================
  // UTILITIES
  // =========================================================================
  function triggerBrowserDownload(downloadUrl, defaultFilename) {
    const a = document.createElement("a");
    a.href = downloadUrl;
    if (defaultFilename) {
      a.setAttribute("download", defaultFilename);
    }
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
    }, 500);
  }

  async function openFolderOnServer(subpath = "") {
    try {
      await fetch("/api/submissions/open-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subpath })
      });
      showToast("Mở thư mục", "Đã mở thư mục lưu trữ bài nộp trong Windows Explorer.", "info", 3000);
    } catch (err) {
      showToast("Lỗi", "Không thể mở thư mục trên hệ thống", "error");
    }
  }

  function sanitizeName(name) {
    if (!name) return "Folder";
    return name.replace(/[<>:"/\\|?*]/g, "_").trim();
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
});
