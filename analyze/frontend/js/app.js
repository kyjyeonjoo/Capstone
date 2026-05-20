document.addEventListener('DOMContentLoaded', () => {
    // --- Toast Notification ---
    function showToast(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        if (!container) return;
        
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        let icon = '💬';
        if (type === 'error') icon = '⚠️';
        if (type === 'success') icon = '✅';
        
        toast.innerHTML = `
            <span class="toast-icon">${icon}</span>
            <span style="flex: 1;">${message}</span>
        `;
        
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.classList.add('hiding');
            toast.addEventListener('animationend', () => toast.remove());
        }, 3000);
    }
    // --- Token Auto-Refresh ---
    async function getValidToken() {
        const token = localStorage.getItem('access_token');
        const refreshToken = localStorage.getItem('refresh_token');
        if (!token) return null;

        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            const now = Math.floor(Date.now() / 1000);
            if (payload.exp && payload.exp > now + 60) return token; // 아직 유효
        } catch {
            return token;
        }

        // 만료 임박 — refresh 시도
        if (!refreshToken) return null;
        try {
            const res = await fetch('/api/refresh-token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: refreshToken })
            });
            if (!res.ok) throw new Error('refresh 실패');
            const data = await res.json();
            localStorage.setItem('access_token', data.token);
            localStorage.setItem('refresh_token', data.refresh_token);
            return data.token;
        } catch {
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            return null;
        }
    }

    // --- State ---
    let isLoggedIn = false;
    let currentView = 'upload-view';

    // --- Elements ---
    const navTabs = document.querySelectorAll('.nav-tab');
    const views = document.querySelectorAll('.view');
    const loginBtnNode = document.getElementById('loginBtn');
    const userProfileNode = document.getElementById('userProfile');
    const userPopover = document.getElementById('userPopover');
    const authModal = document.getElementById('authModal');
    const closeModalBtn = document.querySelector('.close-modal'); // Only selects the first one
    const profileModal = document.getElementById('profileModal');
    const profileMenuBtn = document.getElementById('profileMenuBtn');
    const modalTabs = document.querySelectorAll('.modal-tab');
    const formViews = document.querySelectorAll('.form-view');
    const executeAnalysisBtn = document.getElementById('executeAnalysisBtn');

    // --- Navigation ---
    navTabs.forEach(tab => {
        tab.addEventListener('click', (e) => {
            const targetView = tab.getAttribute('data-target');
            if (targetView === 'chat-view' && !isLoggedIn) {
                authModal.classList.add('active');
                return;
            }
            navTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            switchView(targetView);

            // Automatically select active accident in chat room when opening chat view
            if (targetView === 'chat-view') {
                const selectEl = document.getElementById('chatReportSelect');
                if (selectEl && window.currentAccidentData?.result_id) {
                    selectEl.value = window.currentAccidentData.result_id;
                    loadChatHistory(window.currentAccidentData.result_id);
                }
            }
        });
    });

    function switchView(viewId) {
        currentView = viewId;
        views.forEach(v => v.classList.remove('active'));
        document.getElementById(viewId).classList.add('active');
    }

    // --- Authentication ---
    if (loginBtnNode) loginBtnNode.addEventListener('click', () => authModal.classList.add('active'));
    if (closeModalBtn) closeModalBtn.addEventListener('click', () => authModal.classList.remove('active'));

    function showMessage(elementId, text, isError = true) {
        const el = document.getElementById(elementId);
        if (!el) return;
        el.textContent = text;
        el.className = 'msg-text ' + (isError ? 'error' : 'success');
    }

    function clearMessage(elementId) {
        const el = document.getElementById(elementId);
        if (el) { el.className = 'msg-text'; el.textContent = ''; }
    }

    const resetPasswordFormView = document.getElementById('resetPasswordFormView');
    if (modalTabs.length > 0) {
        modalTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                modalTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                const targetId = tab.getAttribute('data-target');
                formViews.forEach(view => view.classList.remove('active'));
                document.getElementById(targetId).classList.add('active');
                clearMessage('loginMsg');
                clearMessage('signupMsg');
                clearMessage('emailDupMsg');
                clearMessage('resetMsg');
            });
        });
    }

    document.querySelectorAll('.close-modal').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const overlay = e.target.closest('.modal-overlay');
            if (overlay) overlay.classList.remove('active');
        });
    });
    const showResetFormBtn = document.getElementById('showResetFormBtn');
    const backToLoginBtn = document.getElementById('backToLoginBtn');
    if (showResetFormBtn) {
        showResetFormBtn.addEventListener('click', () => {
            formViews.forEach(view => view.classList.remove('active'));
            if (resetPasswordFormView) resetPasswordFormView.classList.add('active');
            modalTabs.forEach(t => { t.style.opacity = '0.5'; t.style.pointerEvents = 'none'; });
        });
    }
    if (backToLoginBtn) {
        backToLoginBtn.addEventListener('click', () => {
            modalTabs.forEach(t => { t.style.opacity = '1'; t.style.pointerEvents = 'auto'; });
            document.querySelector('.modal-tab[data-target="loginFormView"]').click();
        });
    }

    const resultViewBtn = document.getElementById('resultViewBtn');
    if (resultViewBtn) resultViewBtn.addEventListener('click', () => switchView(resultViewBtn.getAttribute('data-target')));

    const backToObjectsBtn = document.getElementById('backToObjectsBtn');
    if (backToObjectsBtn) {
        backToObjectsBtn.addEventListener('click', () => {
            switchView(backToObjectsBtn.getAttribute('data-target'));
        });
    }

    // --- Forgot Password Logic ---
    const forgotPasswordLink = document.getElementById('forgotPasswordLink');
    if (forgotPasswordLink) {
        forgotPasswordLink.addEventListener('click', async (e) => {
            e.preventDefault();
            const email = document.getElementById('loginEmail').value;
            if (!email) {
                return showToast('비밀번호를 찾을 이메일을 위에 입력한 뒤 클릭해주세요.', 'error');
            }

            try {
                const res = await fetch('/api/reset-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || '메일 발송 실패');

                showToast('비밀번호 재설정 메일이 발송되었습니다. 이메일함을 확인해주세요!', 'success');
            } catch (err) {
                showToast(err.message, 'error');
            }
        });
    }

    // Handle password recovery token from URL hash
    if (window.location.hash && window.location.hash.includes('type=recovery')) {
        const hashParams = new URLSearchParams(window.location.hash.substring(1));
        const accessToken = hashParams.get('access_token');

        if (accessToken) {
            localStorage.setItem('access_token', accessToken);
            window.location.hash = '';
            setTimeout(() => {
                showToast('비밀번호 재설정 모드로 진입했습니다. 새 비밀번호를 설정해주세요.', 'success');
                if (profileModal) {
                    const titleEl = document.getElementById('profileModalTitle');
                    const sectionEl = document.getElementById('profileNonPasswordSection');
                    if (titleEl) titleEl.textContent = '새 비밀번호 설정';
                    if (sectionEl) sectionEl.style.display = 'none';
                    profileModal.classList.add('active');
                }
            }, 500);
            updateUIState();
        }
    }

    // --- Auth Forms ---

    const realLoginForm = document.getElementById('realLoginForm');
    if (realLoginForm) {
        realLoginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const email = document.getElementById('loginEmail').value;
            const password = document.getElementById('loginPassword').value;
            const submitBtn = realLoginForm.querySelector('button[type="submit"]');
            clearMessage('loginMsg');
            submitBtn.textContent = '로그인 중..';
            submitBtn.disabled = true;
            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || '로그인 실패');
                localStorage.setItem('access_token', data.token);
                localStorage.setItem('refresh_token', data.refresh_token);
                localStorage.setItem('user_email', data.user);
                if (data.nickname) {
                    localStorage.setItem('user_nickname', data.nickname);
                }
                isLoggedIn = true;
                authModal.classList.remove('active');
                updateUIState();
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                submitBtn.textContent = '로그인';
                submitBtn.disabled = false;
            }
        });
    }

    const checkEmailBtn = document.getElementById('checkEmailBtn');
    let isEmailChecked = false;

    if (checkEmailBtn) {
        checkEmailBtn.addEventListener('click', async () => {
            const email = document.getElementById('signupEmail').value;
            if (!email) {
                showToast('이메일을 먼저 입력해주세요.', 'error');
                return;
            }

            checkEmailBtn.textContent = '확인 중...';
            checkEmailBtn.disabled = true;

            try {
                const res = await fetch('/api/check-email', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                const data = await res.json();

                if (!res.ok) throw new Error(data.detail || '중복 확인 에러');

                if (data.exists) {
                    showToast('이미 가입된 이메일입니다.', 'error');
                    isEmailChecked = false;
                } else {
                    showToast('사용 가능한 이메일입니다!', 'success');
                    isEmailChecked = true;
                }
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                checkEmailBtn.textContent = '중복확인';
                checkEmailBtn.disabled = false;
            }
        });
    }

    const realSignupForm = document.getElementById('realSignupForm');
    if (realSignupForm) {
        realSignupForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const email = document.getElementById('signupEmail').value;
            const nickname = document.getElementById('signupNickname').value;
            const password = document.getElementById('signupPassword').value;
            const submitBtn = realSignupForm.querySelector('button[type="submit"]');
            clearMessage('signupMsg');
            submitBtn.textContent = '처리 중..';
            submitBtn.disabled = true;
            try {
                const res = await fetch('/api/signup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password, nickname })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || '회원가입 실패');
                showToast('회원가입이 완료되었습니다!', 'success');
                document.querySelector('.modal-tab[data-target="loginFormView"]').click();
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                submitBtn.textContent = '회원가입';
                submitBtn.disabled = false;
            }
        });
    }

    const resetPasswordForm = document.getElementById('resetPasswordForm');
    if (resetPasswordForm) {
        resetPasswordForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const email = document.getElementById('resetEmail').value;
            const submitBtn = resetPasswordForm.querySelector('button[type="submit"]');
            clearMessage('resetMsg');
            submitBtn.textContent = '전송 중..';
            submitBtn.disabled = true;
            try {
                const res = await fetch('/api/reset-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || '발송 실패');
                showMessage('resetMsg', '비밀번호 재설정 링크가 발송되었습니다.', false);
                document.getElementById('resetEmail').value = '';
            } catch (err) {
                showMessage('resetMsg', err.message, true);
            } finally {
                submitBtn.textContent = '재설정 링크 발송하기';
                submitBtn.disabled = false;
            }
        });
    }

    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            localStorage.removeItem('user_email');
            localStorage.removeItem('user_nickname');
            isLoggedIn = false;
            userPopover.classList.remove('show');
            updateUIState();
        });
    }

    function updateUIState() {
        if (isLoggedIn) {
            const currentUser = localStorage.getItem('user_nickname') || localStorage.getItem('user_email') || '사용자';
            if (loginBtnNode) loginBtnNode.style.display = 'none';
            if (userProfileNode) {
                userProfileNode.style.display = 'flex';
                userProfileNode.querySelector('span').textContent = currentUser;
            }
            loadAnalysisHistory();
        } else {
            if (loginBtnNode) loginBtnNode.style.display = 'block';
            if (userProfileNode) userProfileNode.style.display = 'none';
            const historyList = document.querySelector('.history-list');
            if (historyList) historyList.innerHTML = '';
            const selectEl = document.getElementById('chatReportSelect');
            if (selectEl) selectEl.innerHTML = '<option value="">대화할 사건 분석을 선택하세요</option>';
            switchView('upload-view');
        }
    }

    if (userProfileNode) {
        userProfileNode.addEventListener('click', (e) => {
            e.stopPropagation();
            userPopover.classList.toggle('show');
        });
        document.addEventListener('click', () => {
            if (userPopover.classList.contains('show')) userPopover.classList.remove('show');
        });
    }

    // Profile Modal Logic
    if (profileMenuBtn && profileModal) {
        profileMenuBtn.addEventListener('click', () => {
            document.getElementById('profileEmail').value = localStorage.getItem('user_email') || '';
            document.getElementById('profileNickname').value = localStorage.getItem('user_nickname') || '';
            document.getElementById('profilePassword').value = '';
            const titleEl = document.getElementById('profileModalTitle');
            const sectionEl = document.getElementById('profileNonPasswordSection');
            if (titleEl) titleEl.textContent = '회원정보 수정';
            if (sectionEl) sectionEl.style.display = 'block';
            profileModal.classList.add('active');
            userPopover.classList.remove('show');
        });
    }

    const updateNicknameBtn = document.getElementById('updateNicknameBtn');
    if (updateNicknameBtn) {
        updateNicknameBtn.addEventListener('click', async () => {
            const newNickname = document.getElementById('profileNickname').value;
            if (!newNickname) return showToast('닉네임을 입력해주세요.', 'error');

            updateNicknameBtn.textContent = '변경 중...';
            updateNicknameBtn.disabled = true;

            try {
                const res = await fetch('/api/update-profile', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                    },
                    body: JSON.stringify({ nickname: newNickname })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || '변경 실패');

                localStorage.setItem('user_nickname', newNickname);
                updateUIState();
                showToast('닉네임이 변경되었습니다!', 'success');
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                updateNicknameBtn.textContent = '변경';
                updateNicknameBtn.disabled = false;
            }
        });
    }

    const updatePasswordBtn = document.getElementById('updatePasswordBtn');
    if (updatePasswordBtn) {
        updatePasswordBtn.addEventListener('click', async () => {
            const newPassword = document.getElementById('profilePassword').value;
            if (!newPassword || newPassword.length < 6) return showToast('비밀번호는 6자 이상이어야 합니다.', 'error');

            updatePasswordBtn.textContent = '변경 중...';
            updatePasswordBtn.disabled = true;

            try {
                const res = await fetch('/api/update-profile', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                    },
                    body: JSON.stringify({ password: newPassword })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || '변경 실패');

                showToast('비밀번호가 성공적으로 변경되었습니다!', 'success');
                document.getElementById('profilePassword').value = '';
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                updatePasswordBtn.textContent = '비밀번호 변경';
                updatePasswordBtn.disabled = false;
            }
        });
    }

    // --- 파일 드롭존 ---
    const dropzone = document.getElementById('dropzone');
    const videoUpload = document.getElementById('videoUpload');
    let selectedFile = null;

    if (dropzone && videoUpload) {
        dropzone.addEventListener('click', () => videoUpload.click());
        videoUpload.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                selectedFile = e.target.files[0];
                dropzone.querySelector('h3').textContent = '영상 파일 드롭됨';
                dropzone.querySelector('p').textContent = selectedFile.name;
            }
        });
        dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
        dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) {
                selectedFile = e.dataTransfer.files[0];
                dropzone.querySelector('h3').textContent = '영상 파일 드롭됨';
                dropzone.querySelector('p').textContent = selectedFile.name;
            }
        });
    }

    // ──────────────────────────────────────────
    // 핵심: 분석 실행 + 결과 화면 반영
    // ──────────────────────────────────────────
    if (executeAnalysisBtn) {
        executeAnalysisBtn.addEventListener('click', async () => {
            if (!selectedFile) {
                switchView('result-view');
                return;
            }

            executeAnalysisBtn.innerHTML = '⏳ 영상 분석 중..';
            executeAnalysisBtn.disabled = true;

            const formData = new FormData();
            formData.append('file', selectedFile);

            const token = await getValidToken();
            const headers = token ? { 'Authorization': `Bearer ${token}` } : {};

            fetch('/api/analyze', { method: 'POST', headers, body: formData })
                .then(res => res.json())
                .then(data => {
                    console.log('분석 결과:', data);
                    window.currentAccidentData = data;

                    document.getElementById('objTotalFrames').textContent = data.total_frames || 0;
                    document.getElementById('objTotalCount').textContent = data.object_count || (data.records ? data.records.length : 0);

                    const tableBody = document.getElementById('objRecordsTable');
                    if (data.records && data.records.length > 0) {
                        tableBody.innerHTML = data.records.map(r => `
                            <tr style="border-bottom: 1px solid #e2e8f0;">
                                <td style="padding: 0.75rem; color: var(--text-primary);">${r.frame || r.frame_number || '-'}</td>
                                <td style="padding: 0.75rem; font-weight: 500;">
                                    <span style="background: var(--bg-alt); padding: 0.2rem 0.5rem; border-radius: 4px; border: 1px solid #cbd5e1; color: var(--text-primary);">
                                        ${r.object_type || r.class_name || '탐지됨'}
                                    </span>
                                </td>
                                <td style="padding: 0.75rem; color: var(--text-secondary);">${(r.confidence ? (r.confidence * 100).toFixed(1) : 0)}%</td>
                            </tr>
                        `).join('');
                    } else {
                        tableBody.innerHTML = `<tr><td colspan="3" style="padding:1rem;text-align:center;color:var(--text-secondary);">탐지된 객체가 없습니다.</td></tr>`;
                    }

                    // 과실비율 반영
                    const faultA = data.fault_ratio_a ?? 50;
                    const faultB = data.fault_ratio_b ?? 50;

                    const ratioCircles = document.querySelectorAll('.ratio-value');
                    if (ratioCircles.length >= 2) {
                        ratioCircles[0].textContent = faultA;
                        ratioCircles[1].textContent = faultB;
                    }

                    const circleAEl = document.querySelector('.ratio-circle.a');
                    const circleBEl = document.querySelector('.ratio-circle.b');
                    if (circleAEl && circleBEl) {
                        const colorA = faultA >= 70 ? '#ef4444' : faultA >= 40 ? '#f97316' : '#22c55e';
                        const colorB = faultB >= 70 ? '#ef4444' : faultB >= 40 ? '#f97316' : '#22c55e';
                        circleAEl.style.background = `conic-gradient(${colorA} ${faultA}%, #f1f5f9 0)`;
                        circleBEl.style.background = `conic-gradient(${colorB} ${faultB}%, #f1f5f9 0)`;
                    }

                    // 판단 근거 업데이트
                    const judgmentCard = document.querySelector('#result-view .law-content');
                    if (judgmentCard && data.situation_summary) {
                        judgmentCard.innerHTML = `
                            <p>${data.situation_summary}</p>
                            <p>${data.accident_cause || ''}</p>
                            <ul>
                                <li><strong>감지된 위반:</strong> ${(data.detected_events || []).join(', ') || '없음'}</li>
                                <li><strong>사고 유형:</strong> ${data.accident_type_name || '불명확'}</li>
                                <li><strong>신뢰도:</strong> ${data.confidence_level || '-'}</li>
                            </ul>
                        `;
                    }

                    // 법률 정보 업데이트
                    const lawCard = document.querySelector('#result-view .full-width .law-content');
                    if (lawCard) {
                        let html = `<p><strong>[적용 법조문]</strong></p><p>${data.legal_basis || ''}</p>`;
                        if (data.case_laws && data.case_laws.length > 0) {
                            data.case_laws.forEach(c => {
                                html += `
                                    <hr style="border:0; border-top:1px solid #e2e8f0; margin:1rem 0;">
                                    <p><strong>[관련 판례] ${c.case_title || ''}</strong></p>
                                    <p>법원: ${c.court_name || ''} | 선고일: ${c.decision_date || ''}</p>
                                    <p>${c.summary || '판례 요약 없음'}</p>
                                    ${c.fault_ratio ? `<p>과실비율: ${c.fault_ratio}</p>` : ''}
                                `;
                            });
                        } else {
                            html += `<p style="color:var(--text-secondary); margin-top:1rem;">관련 판례가 없습니다.</p>`;
                        }
                        lawCard.innerHTML = html;
                    }

                    switchView('objects-view');
                    loadAnalysisHistory();
                })
                .catch(err => {
                    console.error('오류:', err);
                    showToast('서버와 통신 중 문제가 발생했습니다. API 서버가 작동 중인지 확인해주세요.', 'error');
                    switchView('objects-view');
                })
                .finally(() => {
                    executeAnalysisBtn.innerHTML = '✨ 영상 분석 실행 버튼';
                    executeAnalysisBtn.disabled = false;
                });
        });
    }

    // --- Dynamic Analysis History Loader ---
    async function loadAnalysisHistory() {
        if (!isLoggedIn) return;

        try {
            const token = await getValidToken();
            if (!token) {
                localStorage.removeItem('access_token');
                localStorage.removeItem('refresh_token');
                localStorage.removeItem('user_email');
                localStorage.removeItem('user_nickname');
                isLoggedIn = false;
                updateUIState();
                return;
            }

            const res = await fetch('/api/results', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || '이력 조회 실패');

            const historyList = document.querySelector('.history-list');
            const selectEl = document.getElementById('chatReportSelect');

            if (historyList) {
                if (data.results && data.results.length > 0) {
                    historyList.innerHTML = data.results.map(item => {
                        const title = item.video_record?.original_name 
                            ? item.video_record.original_name.split('.')[0] 
                            : `분석 결과 #${item.result_id}`;
                        return `
                            <div class="history-item" data-result-id="${item.result_id}" style="display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;">
                                <span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">📁 ${title}</span>
                                <div class="history-actions">
                                    <button class="action-btn rename-hist-btn" title="이름바꾸기" data-result-id="${item.result_id}">✏️</button>
                                    <button class="action-btn delete-hist-btn" title="삭제" data-result-id="${item.result_id}">🗑️</button>
                                </div>
                            </div>
                        `;
                    }).join('');

                    // Add click event listeners to new history items
                    historyList.querySelectorAll('.history-item').forEach(el => {
                        const resultId = el.getAttribute('data-result-id');

                        el.addEventListener('click', async (e) => {
                            if (e.target.closest('.action-btn')) return; // ignore if rename/delete button is clicked
                            await loadAnalysisDetail(resultId);
                        });

                        // Rename button listener
                        const renameBtn = el.querySelector('.rename-hist-btn');
                        if (renameBtn) {
                            renameBtn.addEventListener('click', async (e) => {
                                e.stopPropagation();
                                const currentTitle = el.querySelector('span').textContent.replace('📁 ', '').trim();
                                const newTitle = prompt('변경할 사건 이름을 입력하세요:', currentTitle);
                                if (!newTitle || newTitle.trim() === '' || newTitle.trim() === currentTitle) return;

                                try {
                                    const token = await getValidToken();
                                    const res = await fetch(`/api/results/${resultId}/rename`, {
                                        method: 'PUT',
                                        headers: {
                                            'Content-Type': 'application/json',
                                            'Authorization': `Bearer ${token}`
                                        },
                                        body: JSON.stringify({ new_name: newTitle.trim() })
                                    });
                                    const resData = await res.json();
                                    if (!res.ok) throw new Error(resData.detail || '이름 변경 실패');

                                    showToast('이름이 성공적으로 변경되었습니다.', 'success');
                                    await loadAnalysisHistory(); // Refresh list

                                    const activeEl = document.querySelector('.history-item.active');
                                    if (activeEl && activeEl.getAttribute('data-result-id') === String(resultId)) {
                                        await loadAnalysisDetail(resultId);
                                    }
                                } catch (err) {
                                    showToast(err.message, 'error');
                                }
                            });
                        }

                        // Delete button listener
                        const deleteBtn = el.querySelector('.delete-hist-btn');
                        if (deleteBtn) {
                            deleteBtn.addEventListener('click', async (e) => {
                                e.stopPropagation();
                                if (!confirm('정말 이 사건 분석 기록을 삭제하시겠습니까?\n채팅 내역을 포함한 모든 기록이 삭제되며 복구할 수 없습니다.')) return;

                                try {
                                    const token = await getValidToken();
                                    const res = await fetch(`/api/results/${resultId}`, {
                                        method: 'DELETE',
                                        headers: { 'Authorization': `Bearer ${token}` }
                                    });
                                    const resData = await res.json();
                                    if (!res.ok) throw new Error(resData.detail || '기록 삭제 실패');

                                    showToast('기록이 정상적으로 삭제되었습니다.', 'success');

                                    const activeEl = document.querySelector('.history-item.active');
                                    const isActive = activeEl && activeEl.getAttribute('data-result-id') === String(resultId);

                                    await loadAnalysisHistory(); // Refresh list

                                    if (isActive) {
                                        switchView('upload-view');
                                    }
                                } catch (err) {
                                    showToast(err.message, 'error');
                                }
                            });
                        }
                    });
                } else {
                    historyList.innerHTML = `<div style="text-align:center; padding:1rem; font-size:0.85rem; color:var(--text-secondary);">분석 이력이 없습니다.</div>`;
                }
            }

            // Update chat dropdown options
            if (selectEl) {
                selectEl.innerHTML = '<option value="">대화할 사건 분석을 선택하세요</option>' + 
                    (data.results || []).map(item => {
                        const title = item.video_record?.original_name 
                            ? item.video_record.original_name.split('.')[0] 
                            : `분석 결과 #${item.result_id}`;
                        return `<option value="${item.result_id}">${title}</option>`;
                    }).join('');
            }

        } catch (err) {
            console.error('이력 로딩 실패:', err);
        }
    }

    async function loadAnalysisDetail(resultId) {
        try {
            const token = await getValidToken();
            if (!token) {
                localStorage.removeItem('access_token');
                localStorage.removeItem('refresh_token');
                localStorage.removeItem('user_email');
                localStorage.removeItem('user_nickname');
                isLoggedIn = false;
                updateUIState();
                throw new Error('인증 세션이 만료되었습니다. 다시 로그인해주세요.');
            }
            const headers = { 'Authorization': `Bearer ${token}` };

            const res = await fetch(`/api/results/${resultId}`, { headers });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || '상세 조회 실패');

            // Set as current accident data
            window.currentAccidentData = data;

            // Switch to result-view
            switchView('result-view');
            
            // Update active state in sidebar
            document.querySelectorAll('.history-item').forEach(el => {
                if (el.getAttribute('data-result-id') === String(resultId)) {
                    el.classList.add('active');
                } else {
                    el.classList.remove('active');
                }
            });

            // Update UI with the loaded details
            const faultA = data.fault_a ?? 50;
            const faultB = data.fault_b ?? 50;
            const ratioCircles = document.querySelectorAll('.ratio-value');
            if (ratioCircles.length >= 2) {
                ratioCircles[0].textContent = faultA;
                ratioCircles[1].textContent = faultB;
            }
            const circleAEl = document.querySelector('.ratio-circle.a');
            const circleBEl = document.querySelector('.ratio-circle.b');
            if (circleAEl && circleBEl) {
                const colorA = faultA >= 70 ? '#ef4444' : faultA >= 40 ? '#f97316' : '#22c55e';
                const colorB = faultB >= 70 ? '#ef4444' : faultB >= 40 ? '#f97316' : '#22c55e';
                circleAEl.style.background = `conic-gradient(${colorA} ${faultA}%, #f1f5f9 0)`;
                circleBEl.style.background = `conic-gradient(${colorB} ${faultB}%, #f1f5f9 0)`;
            }

            const title = data.video_record?.original_name 
                ? data.video_record.original_name.split('.')[0] 
                : `분석 결과 #${data.result_id}`;
            const headerEl = document.querySelector('#result-view .result-header h2');
            if (headerEl) {
                headerEl.innerHTML = `${title} <span style="font-size: 1rem; color: var(--text-secondary); font-weight: normal; margin-left: 0.5rem;">영상 분석 결과</span>`;
            }

            const judgmentCard = document.querySelector('#result-view .law-content');
            if (judgmentCard) {
                const detectedEventsText = (data.detected_events && data.detected_events.length > 0)
                    ? data.detected_events.join(', ')
                    : '없음';
                const confidenceText = data.confidence_level || '보통';

                judgmentCard.innerHTML = `
                    <p>${data.summary || '분석 요약 정보가 없습니다.'}</p>
                    <p>${data.accident_cause || ''}</p>
                    <ul>
                        <li><strong>감지된 위반:</strong> ${detectedEventsText}</li>
                        <li><strong>사고 유형:</strong> ${data.accident_type_name || '불명확'}</li>
                        <li><strong>신뢰도:</strong> ${confidenceText}</li>
                    </ul>
                `;
            }

            // Restore objects-view metadata and table too
            const totalFramesEl = document.getElementById('objTotalFrames');
            const totalCountEl = document.getElementById('objTotalCount');
            const recordsTable = document.getElementById('objRecordsTable');
            
            // Reconstruct total frames from video_record duration
            const duration = data.video_record?.duration ?? 0;
            const totalFrames = duration ? Math.round(duration * 5) : (data.records?.length ? Math.max(...data.records.map(r => r.frame)) : 0);
            
            if (totalFramesEl) totalFramesEl.textContent = totalFrames || '-';
            if (totalCountEl) totalCountEl.textContent = data.records?.length || '0';
            
            if (recordsTable) {
                if (data.records && data.records.length > 0) {
                    recordsTable.innerHTML = data.records.map(r => {
                        const sec = (r.frame / 5.0).toFixed(1);
                        return `
                            <tr style="border-bottom: 1px solid var(--card-border);">
                                <td style="padding: 0.75rem;">${sec}초 (${r.frame}f)</td>
                                <td style="padding: 0.75rem;"><span class="badge badge-warning">${r.object_type}</span></td>
                                <td style="padding: 0.75rem;">${(r.confidence * 100).toFixed(1)}%</td>
                            </tr>
                        `;
                    }).join('');
                } else {
                    recordsTable.innerHTML = `<tr><td colspan="3" style="padding: 1rem; text-align: center; color: var(--text-secondary);">탐지된 객체가 없습니다.</td></tr>`;
                }
            }

            const lawCard = document.querySelector('#result-view .full-width .law-content');
            if (lawCard) {
                let html = `<p><strong>[적용 법조문]</strong></p><p>${data.legal_basis || '적용 법조문 정보가 없습니다.'}</p>`;
                if (data.case_laws && data.case_laws.length > 0) {
                    data.case_laws.forEach(c => {
                        html += `
                            <hr style="border:0; border-top:1px solid #e2e8f0; margin:1rem 0;">
                            <p><strong>[관련 판례] ${c.case_title || ''}</strong></p>
                            <p>법원: ${c.court_name || ''} | 선고일: ${c.decision_date || ''}</p>
                            <p>${c.summary || '판례 요약 없음'}</p>
                            ${c.fault_ratio ? `<p>과실비율: ${c.fault_ratio}</p>` : ''}
                        `;
                    });
                } else {
                    html += `<p style="color:var(--text-secondary); margin-top:1rem;">관련 판례가 없습니다.</p>`;
                }
                lawCard.innerHTML = html;
            }

            const selectEl = document.getElementById('chatReportSelect');
            if (selectEl) {
                selectEl.value = resultId;
            }
            await loadChatHistory(resultId);

        } catch (err) {
            showToast(err.message, 'error');
        }
    }

    async function loadChatHistory(resultId) {
        const chatMessages = document.querySelector('.chat-messages');
        if (!chatMessages) return;

        const greeting = chatMessages.firstElementChild;
        chatMessages.innerHTML = '';
        if (greeting) {
            chatMessages.appendChild(greeting);
        }

        if (!resultId) return;

        try {
            const token = await getValidToken();
            if (!token) return;

            const res = await fetch(`/api/chat/history?result_id=${resultId}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || '채팅 내역 로드 실패');

            if (data.history && data.history.length > 0) {
                data.history.forEach(chat => {
                    const userMsgDiv = document.createElement('div');
                    userMsgDiv.className = 'message user';
                    userMsgDiv.textContent = chat.question;
                    chatMessages.appendChild(userMsgDiv);

                    const botMsgDiv = document.createElement('div');
                    botMsgDiv.className = 'message bot';
                    botMsgDiv.innerHTML = (chat.answer || '').replace(/\n/g, '<br>');
                    chatMessages.appendChild(botMsgDiv);
                });
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
        } catch (err) {
            showToast(err.message, 'error');
        }
    }

    async function initSession() {
        const token = await getValidToken();
        const savedUser = localStorage.getItem('user_email');
        if (token && savedUser) {
            isLoggedIn = true;
        } else {
            isLoggedIn = false;
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            localStorage.removeItem('user_email');
            localStorage.removeItem('user_nickname');
        }
        updateUIState();
    }
    initSession();

    // --- Chat Logic ---
    const chatInput = document.querySelector('.chat-input');
    const sendBtn = document.querySelector('.send-btn');
    const chatMessages = document.querySelector('.chat-messages');

    if (chatInput && sendBtn && chatMessages) {
        async function sendMessage() {
            const message = chatInput.value.trim();
            if (!message) return;

            // ── 비로그인 사용자 차단 ──
            if (!isLoggedIn) {
                showToast('채팅 기능은 로그인 후 이용 가능합니다.', 'error');
                authModal.classList.add('active');
                return;
            }

            // 토큰 유효성 사전 확인
            const token = await getValidToken();
            if (!token) {
                showToast('세션이 만료되었습니다. 다시 로그인해주세요.', 'error');
                localStorage.removeItem('access_token');
                localStorage.removeItem('refresh_token');
                localStorage.removeItem('user_email');
                localStorage.removeItem('user_nickname');
                isLoggedIn = false;
                updateUIState();
                authModal.classList.add('active');
                return;
            }

            // Add user message to UI
            const userMsgDiv = document.createElement('div');
            userMsgDiv.className = 'message user';
            userMsgDiv.textContent = message;
            chatMessages.appendChild(userMsgDiv);

            chatInput.value = '';
            chatMessages.scrollTop = chatMessages.scrollHeight;

            // Add loading indicator
            const botMsgDiv = document.createElement('div');
            botMsgDiv.className = 'message bot';
            botMsgDiv.innerHTML = '<span class="loading-dots">답변을 생성 중입니다...</span>';
            chatMessages.appendChild(botMsgDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;

            try {
                const accidentData = window.currentAccidentData || null;
                const chatHeaders = {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                };

                const selectEl = document.getElementById('chatReportSelect');
                const selectedResultId = selectEl ? selectEl.value : null;

                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: chatHeaders,
                    body: JSON.stringify({
                        user_question: message,
                        accident_data: accidentData,
                        result_id: selectedResultId ? parseInt(selectedResultId) : (accidentData?.result_id || null)
                    })
                });
                const data = await res.json();

                if (!res.ok) {
                    // 401이면 로그인 모달 띄우기
                    if (res.status === 401) {
                        showToast(data.detail || '인증이 만료되었습니다. 다시 로그인해주세요.', 'error');
                        localStorage.removeItem('access_token');
                        localStorage.removeItem('refresh_token');
                        localStorage.removeItem('user_email');
                        localStorage.removeItem('user_nickname');
                        isLoggedIn = false;
                        updateUIState();
                        authModal.classList.add('active');
                    }
                    throw new Error(data.detail || '채팅 응답 에러');
                }

                // Update bot message with actual response
                botMsgDiv.innerHTML = (data.answer || '응답을 받지 못했습니다.').replace(/\n/g, '<br>');
            } catch (err) {
                botMsgDiv.innerHTML = `<span style="color: var(--danger);">[오류] ${err.message}</span>`;
            } finally {
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
        }

        sendBtn.addEventListener('click', sendMessage);
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });

        // Dropdown selection change listener
        const chatReportSelect = document.getElementById('chatReportSelect');
        if (chatReportSelect) {
            chatReportSelect.addEventListener('change', async (e) => {
                const resultId = e.target.value;
                await loadChatHistory(resultId);
            });
        }
    }

    // Initial view reset to guarantee starting on video analysis tab
    switchView('upload-view');
    navTabs.forEach(t => t.classList.remove('active'));
    const defaultTab = document.querySelector('.nav-tab[data-target="upload-view"]');
    if (defaultTab) defaultTab.classList.add('active');
});
