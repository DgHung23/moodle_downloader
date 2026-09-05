document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const sessionInput = document.getElementById('session-input');
  const btnDetectFirefox = document.getElementById('btn-detect-firefox');
  const btnDetectEdge = document.getElementById('btn-detect-edge');
  const btnDetectChrome = document.getElementById('btn-detect-chrome');
  const btnFetchCourses = document.getElementById('btn-fetch-courses');
  const sessionFeedback = document.getElementById('session-feedback');

  const statTotalCourses = document.getElementById('stat-total-courses');
  const statTotalFiles = document.getElementById('stat-total-files');
  const statTotalSize = document.getElementById('stat-total-size');
  const statAppStatus = document.getElementById('stat-app-status');

  const liveProgressCard = document.getElementById('live-progress-card');
  const liveCourseName = document.getElementById('live-course-name');
  const liveFileName = document.getElementById('live-file-name');
  const btnCancelDownload = document.getElementById('btn-cancel-download');

  const courseSearchInput = document.getElementById('course-search-input');
  const btnToggleDedup = document.getElementById('btn-toggle-dedup');
  const dedupStatusBadge = document.getElementById('dedup-status-badge');
  const dedupCountBadge = document.getElementById('dedup-count-badge');
  const btnDownloadAll = document.getElementById('btn-download-all');
  const btnDownloadAllText = document.getElementById('btn-download-all-text');
  const btnOpenOutputs = document.getElementById('btn-open-outputs');
  const coursesContainer = document.getElementById('courses-container');

  const logsToggle = document.getElementById('logs-toggle');
  const logsBody = document.getElementById('logs-body');

  let allCourses = [];
  let currentFilteredCourses = [];
  let isDedupActive = true; // Mặc định bật lọc trùng lặp cho giảng viên & sinh viên
  let pollInterval = null;

  // 1. Tự động phát hiện phiên đăng nhập từ các trình duyệt
  async function detectFromBrowser(browserName, btn) {
    const originalContent = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '⏳ Đang quét...';

    const browserTitles = {
      firefox: 'Mozilla Firefox',
      edge: 'Microsoft Edge',
      chrome: 'Google Chrome'
    };
    const title = browserTitles[browserName] || browserName;

    try {
      const res = await fetch(`/api/session/detect?browser=${browserName}`);
      const data = await res.json();

      if (data.status === 'ok') {
        if (data.moodle_session) {
          sessionInput.value = data.moodle_session;
          showFeedback('success', `Đã tự động lấy MoodleSession từ ${title}!`);
        } else {
          showFeedback('success', data.message || `Đã kết nối phiên đăng nhập từ ${title}.`);
        }
      } else {
        showFeedback('error', data.message || `Không thể trích xuất cookie từ ${title}.`);
      }
    } catch (err) {
      showFeedback('error', 'Lỗi kết nối tới server: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalContent;
    }
  }

  if (btnDetectFirefox) {
    btnDetectFirefox.addEventListener('click', () => detectFromBrowser('firefox', btnDetectFirefox));
  }
  if (btnDetectEdge) {
    btnDetectEdge.addEventListener('click', () => detectFromBrowser('edge', btnDetectEdge));
  }
  if (btnDetectChrome) {
    btnDetectChrome.addEventListener('click', () => detectFromBrowser('chrome', btnDetectChrome));
  }

  function showFeedback(type, message) {
    sessionFeedback.className = `session-feedback ${type}`;
    sessionFeedback.textContent = message;
    sessionFeedback.classList.remove('hidden');
  }

  // 2. Fetch danh sách môn học
  btnFetchCourses.addEventListener('click', async () => {
    const sessionId = sessionInput.value.trim();
    setFetchLoading(true);

    try {
      const res = await fetch('/api/courses/fetch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
      });
      const data = await res.json();

      if (data.status === 'ok') {
        allCourses = data.courses || [];
        updateDedupBadges();
        applyFiltersAndRender();
        btnDownloadAll.disabled = allCourses.length === 0;

        const uniqueCount = groupCourses(allCourses).length;
        if (allCourses.length > uniqueCount) {
          showFeedback('success', `Đã tìm thấy ${allCourses.length} lớp học (Gộp thành ${uniqueCount} môn học duy nhất)!`);
        } else {
          showFeedback('success', `Đã tìm thấy ${allCourses.length} môn học trong tài khoản của bạn!`);
        }
      } else {
        showFeedback('error', data.message || 'Không thể lấy danh sách khóa học.');
      }
    } catch (err) {
      showFeedback('error', 'Lỗi khi gọi API fetch môn học: ' + err.message);
    } finally {
      setFetchLoading(false);
    }
  });

  function setFetchLoading(isLoading) {
    btnFetchCourses.disabled = isLoading;
    if (isLoading) {
      btnFetchCourses.innerHTML = `
        <span class="pulsing-dot" style="display:inline-block; margin-right:8px;"></span>
        <span>Đang quét Moodle...</span>
      `;
    } else {
      btnFetchCourses.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"></circle>
          <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
        <span>Fetch Các Môn Học</span>
      `;
    }
  }

  // Helper: Gộp các môn học trùng lặp theo mã môn và tên môn (subject_key)
  function groupCourses(courses) {
    const map = new Map();
    courses.forEach(c => {
      const key = c.subject_key || c.name;
      if (!map.has(key)) {
        map.set(key, {
          id: c.id,
          code: c.code,
          title: c.title,
          name: c.name,
          subject_key: key,
          folder_name: c.folder_name,
          downloaded_files: c.downloaded_files || 0,
          classes: []
        });
      }
      const group = map.get(key);
      group.classes.push(c);
      if (c.downloaded_files > group.downloaded_files) {
        group.downloaded_files = c.downloaded_files;
      }
    });
    return Array.from(map.values());
  }

  // Cập nhật trạng thái badge của nút lọc trùng lặp
  function updateDedupBadges() {
    if (!allCourses || allCourses.length === 0) {
      if (dedupCountBadge) dedupCountBadge.textContent = '';
      return;
    }

    const uniqueCount = groupCourses(allCourses).length;
    if (btnToggleDedup) {
      if (isDedupActive) {
        btnToggleDedup.classList.add('active');
        dedupStatusBadge.className = 'filter-badge on';
        dedupStatusBadge.textContent = 'BẬT';
        dedupCountBadge.textContent = `${uniqueCount} môn duy nhất`;
      } else {
        btnToggleDedup.classList.remove('active');
        dedupStatusBadge.className = 'filter-badge off';
        dedupStatusBadge.textContent = 'TẮT';
        dedupCountBadge.textContent = `${allCourses.length} lớp học`;
      }
    }
  }

  // Nút bật/tắt lọc trùng lặp
  if (btnToggleDedup) {
    btnToggleDedup.addEventListener('click', () => {
      isDedupActive = !isDedupActive;
      updateDedupBadges();
      applyFiltersAndRender();
    });
  }

  // 3. Áp dụng bộ lọc (Tìm kiếm + Lọc trùng lặp) và Render
  function applyFiltersAndRender() {
    if (!allCourses || allCourses.length === 0) {
      currentFilteredCourses = [];
      renderCourses([], false);
      return;
    }

    const q = (courseSearchInput.value || '').toLowerCase().trim();
    let filtered = allCourses;

    if (q) {
      filtered = allCourses.filter(c =>
        (c.code && c.code.toLowerCase().includes(q)) ||
        (c.title && c.title.toLowerCase().includes(q)) ||
        (c.name && c.name.toLowerCase().includes(q)) ||
        (c.id && c.id.toString().includes(q)) ||
        (c.class_code && c.class_code.toLowerCase().includes(q))
      );
    }
    currentFilteredCourses = filtered;

    if (isDedupActive) {
      const grouped = groupCourses(filtered);
      renderGroupedCourses(grouped);
      const totalUnique = groupCourses(allCourses).length;
      statTotalCourses.textContent = `${totalUnique} môn (${allCourses.length} lớp)`;
      if (btnDownloadAllText) {
        btnDownloadAllText.textContent = `Tải Toàn Bộ (${grouped.length} Môn Duy Nhất)`;
      }
    } else {
      renderRawCourses(filtered);
      statTotalCourses.textContent = `${allCourses.length} lớp`;
      if (btnDownloadAllText) {
        btnDownloadAllText.textContent = `Tải Toàn Bộ (${filtered.length} Lớp Học)`;
      }
    }
  }

  // 3A. Render danh sách môn ở chế độ GỘP TRÙNG LẶP (Deduplicated)
  function renderGroupedCourses(groups) {
    if (!groups || groups.length === 0) {
      renderEmptyState();
      return;
    }

    coursesContainer.innerHTML = groups.map((group, idx) => {
      const classCount = group.classes.length;
      const classBadge = classCount > 1 
        ? `<span class="course-count-badge">✨ ${classCount} lớp học</span>`
        : '';

      const classPickerHtml = classCount > 1 ? `
        <div class="class-picker-box">
          <div class="class-picker-header">
            <span class="class-picker-label">📚 Chọn lớp học cần tải:</span>
            <span class="class-picker-hint">Gộp để tải đủ file</span>
          </div>
          <select class="class-picker-select" id="group-select-${idx}" data-group-index="${idx}">
            <option value="all" selected>🌟 Tất cả các lớp (Gộp toàn bộ tài liệu - Khuyên dùng)</option>
            ${group.classes.map(c => `
              <option value="${c.id}">
                Lớp ${escapeHtml(c.class_code || 'Chung')} ${c.academic_year ? `(${escapeHtml(c.academic_year)})` : ''} - [ID: ${c.id}]
              </option>
            `).join('')}
          </select>
        </div>
      ` : '';

      return `
        <div class="course-card" data-group-index="${idx}">
          <div class="course-card-top">
            <div class="course-badge-row">
              <span class="course-code-badge">${escapeHtml(group.code)}</span>
              ${classBadge}
              <span class="course-files-badge">
                📁 ${group.downloaded_files > 0 ? `${group.downloaded_files} files đã có` : 'Chưa tải'}
              </span>
            </div>
            <h3 class="course-card-title">${escapeHtml(group.title)}</h3>
            ${classPickerHtml}
          </div>

          <div class="course-card-actions">
            <button class="btn btn-primary btn-sm btn-download-group" data-group-index="${idx}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
              <span>Tải Môn Này</span>
            </button>
            <button class="btn btn-secondary btn-sm btn-open-course-folder" data-folder="${escapeHtml(group.folder_name)}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
              </svg>
              Mở Thư Mục
            </button>
          </div>
        </div>
      `;
    }).join('');

    // Gán event listeners
    document.querySelectorAll('.btn-download-group').forEach(btn => {
      btn.addEventListener('click', () => {
        const groupIndex = parseInt(btn.getAttribute('data-group-index'), 10);
        const group = groups[groupIndex];
        if (!group) return;

        const selectEl = document.getElementById(`group-select-${groupIndex}`);
        if (selectEl && selectEl.value !== 'all') {
          // Người dùng chọn 1 lớp cụ thể
          const selectedCourseId = selectEl.value;
          downloadCoursesByIds([selectedCourseId], btn);
        } else {
          // Tải toàn bộ các lớp của môn học này (gộp tài liệu)
          const allIds = group.classes.map(c => c.id);
          downloadCoursesByIds(allIds, btn);
        }
      });
    });

    document.querySelectorAll('.btn-open-course-folder').forEach(btn => {
      btn.addEventListener('click', () => {
        const folderName = btn.getAttribute('data-folder');
        openFolder(folderName);
      });
    });
  }

  // 3B. Render danh sách môn ở chế độ HIỆN TẤT CẢ (Raw Classes)
  function renderRawCourses(courses) {
    if (!courses || courses.length === 0) {
      renderEmptyState();
      return;
    }

    coursesContainer.innerHTML = courses.map(course => {
      const classTag = course.class_code 
        ? `<span class="course-count-badge">Lớp ${escapeHtml(course.class_code)}</span>` 
        : '';

      return `
        <div class="course-card" data-id="${course.id}">
          <div class="course-card-top">
            <div class="course-badge-row">
              <span class="course-code-badge">${escapeHtml(course.code)}</span>
              ${classTag}
              <span class="course-files-badge">
                📁 ${course.downloaded_files > 0 ? `${course.downloaded_files} files đã có` : 'Chưa tải'}
              </span>
            </div>
            <h3 class="course-card-title">${escapeHtml(course.title)}</h3>
            <p class="card-desc" style="margin-top:6px; font-size:0.78rem; opacity:0.8;">
              ${escapeHtml(course.raw_name)} (ID: ${course.id})
            </p>
          </div>

          <div class="course-card-actions">
            <button class="btn btn-primary btn-sm btn-download-course" data-id="${course.id}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
              <span>Tải Lớp Này</span>
            </button>
            <button class="btn btn-secondary btn-sm btn-open-course-folder" data-folder="${escapeHtml(course.folder_name)}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
              </svg>
              Mở Thư Mục
            </button>
          </div>
        </div>
      `;
    }).join('');

    document.querySelectorAll('.btn-download-course').forEach(btn => {
      btn.addEventListener('click', () => {
        const courseId = btn.getAttribute('data-id');
        downloadCoursesByIds([courseId], btn);
      });
    });

    document.querySelectorAll('.btn-open-course-folder').forEach(btn => {
      btn.addEventListener('click', () => {
        const folderName = btn.getAttribute('data-folder');
        openFolder(folderName);
      });
    });
  }

  function renderEmptyState() {
    coursesContainer.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🔍</div>
        <h3>Không tìm thấy môn học nào</h3>
        <p>Không có môn học nào khớp với từ khóa tìm kiếm của bạn.</p>
      </div>
    `;
  }

  // 4. Tìm kiếm lọc môn học theo thời gian thực
  courseSearchInput.addEventListener('input', () => {
    applyFiltersAndRender();
  });

  // 5. Tải một hoặc nhiều môn học theo danh sách ID
  async function downloadCoursesByIds(courseIds, btn) {
    try {
      if (btn) btn.disabled = true;
      const res = await fetch('/api/course/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ course_ids: courseIds })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        startPolling();
      } else {
        alert(data.message);
      }
    } catch (err) {
      alert('Lỗi khi gửi yêu cầu tải môn học: ' + err.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // 6. Tải toàn bộ môn học (Download All)
  btnDownloadAll.addEventListener('click', async () => {
    let confirmMsg = '';
    let targetIds = [];

    const coursesToProcess = (currentFilteredCourses && currentFilteredCourses.length > 0)
      ? currentFilteredCourses
      : allCourses;

    if (!coursesToProcess || coursesToProcess.length === 0) {
      alert('Không có môn học nào để tải!');
      return;
    }

    const isFiltered = coursesToProcess.length < allCourses.length;
    const filterHint = isFiltered ? ' (đang lọc theo từ khóa tìm kiếm)' : '';

    if (isDedupActive) {
      const groups = groupCourses(coursesToProcess);
      // Thu thập toàn bộ ID của các lớp thuộc các môn duy nhất theo đúng thứ tự từng môn
      targetIds = [];
      groups.forEach(g => {
        g.classes.forEach(c => targetIds.push(c.id));
      });
      confirmMsg = `Bạn có chắc muốn tải toàn bộ tài liệu của ${groups.length} môn học duy nhất${filterHint}?\n(Hệ thống sẽ tự động gộp và tổng hợp tài liệu từ ${targetIds.length} lớp học tương ứng)`;
    } else {
      targetIds = coursesToProcess.map(c => c.id);
      confirmMsg = `Bạn có chắc muốn tải tài liệu của toàn bộ ${targetIds.length} lớp học${filterHint}?`;
    }

    if (!confirm(confirmMsg)) {
      return;
    }

    try {
      btnDownloadAll.disabled = true;
      const res = await fetch('/api/courses/download-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ course_ids: targetIds })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        startPolling();
      } else {
        alert(data.message);
      }
    } catch (err) {
      alert('Lỗi khi bắt đầu tải toàn bộ: ' + err.message);
    } finally {
      btnDownloadAll.disabled = false;
    }
  });

  // 7. Hủy tải
  btnCancelDownload.addEventListener('click', async () => {
    try {
      await fetch('/api/download/cancel', { method: 'POST' });
    } catch (e) {
      console.error(e);
    }
  });

  // 8. Mở thư mục outputs trong Windows Explorer
  btnOpenOutputs.addEventListener('click', () => openFolder(''));

  async function openFolder(folderName) {
    try {
      await fetch('/api/open-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_name: folderName })
      });
    } catch (err) {
      console.error('Không thể mở folder:', err);
    }
  }

  // 9. Polling trạng thái realtime
  function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(updateStatus, 1500);
    updateStatus();
  }

  async function updateStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();

      statTotalFiles.textContent = data.total_files_on_disk || 0;
      statTotalSize.textContent = `${data.total_size_mb || 0} MB`;

      if (data.is_downloading) {
        statAppStatus.textContent = 'Đang tải...';
        statAppStatus.className = 'stat-value status-badge busy';
        liveProgressCard.classList.remove('hidden');

        liveCourseName.textContent = `Đang xử lý: ${data.current_course_name || 'Đang chuẩn bị...'}`;
        liveFileName.textContent = data.current_file || 'Đang quét tài liệu...';
      } else {
        statAppStatus.textContent = 'Sẵn sàng';
        statAppStatus.className = 'stat-value status-badge ready';
        liveProgressCard.classList.add('hidden');
      }

      // Cập nhật logs
      if (data.logs && data.logs.length > 0) {
        logsBody.innerHTML = data.logs.map(log => `
          <div class="log-entry ${log.type}">
            <span class="log-time">[${log.time}]</span>
            <span class="log-text">${escapeHtml(log.text)}</span>
          </div>
        `).join('');
        logsBody.scrollTop = logsBody.scrollHeight;
      }
    } catch (err) {
      console.error('Polling error:', err);
    }
  }

  // Logs toggle
  logsToggle.addEventListener('click', () => {
    if (logsBody.style.display === 'none') {
      logsBody.style.display = 'flex';
      document.querySelector('.logs-toggle-indicator').textContent = '▼';
    } else {
      logsBody.style.display = 'none';
      document.querySelector('.logs-toggle-indicator').textContent = '▲';
    }
  });

  function escapeHtml(text) {
    if (!text) return '';
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    };
    return text.toString().replace(/[&<>"']/g, m => map[m]);
  }

  // Khởi động polling ban đầu để lấy stats
  startPolling();

  // Tự động kiểm tra session hoặc fetch môn học ban đầu nếu có sẵn
  fetch('/api/session/detect')
    .then(r => r.json())
    .then(data => {
      if (data.detected && data.moodle_session) {
        sessionInput.value = data.moodle_session;
      }
    })
    .catch(() => {});
});
