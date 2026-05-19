document.addEventListener('DOMContentLoaded', () => {
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
    const closeModalBtn = document.querySelector('.close-modal');
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
    if (backToObjectsBtn) backToObjectsBtn.addEventListener('click', () => switchView(backToObjectsBtn.getAttribute('data-target')));

    // --- Auth Forms ---
    const savedToken = localStorage.getItem('access_token');
    const savedUser = localStorage.getItem('user_email');
    if (savedToken && savedUser) isLoggedIn = true;

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
                localStorage.setItem('user_email', data.user);
                isLoggedIn = true;
                authModal.classList.remove('active');
                updateUIState();
            } catch (err) {
                showMessage('loginMsg', err.message, true);
            } finally {
                submitBtn.textContent = '로그인';
                submitBtn.disabled = false;
            }
        });
    }

    const realSignupForm = document.getElementById('realSignupForm');
    if (realSignupForm) {
        realSignupForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const email = document.getElementById('signupEmail').value;
            const password = document.getElementById('signupPassword').value;
            const submitBtn = realSignupForm.querySelector('button[type="submit"]');
            clearMessage('signupMsg');
            submitBtn.textContent = '처리 중..';
            submitBtn.disabled = true;
            try {
                const res = await fetch('/api/signup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || '회원가입 실패');
                showMessage('signupMsg', '회원가입이 완료되었습니다. 로그인해 주세요.', false);
                setTimeout(() => document.querySelector('.modal-tab[data-target="loginFormView"]').click(), 1500);
            } catch (err) {
                showMessage('signupMsg', err.message, true);
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
            localStorage.removeItem('user_email');
            isLoggedIn = false;
            userPopover.classList.remove('show');
            updateUIState();
        });
    }

    function updateUIState() {
        if (isLoggedIn) {
            const currentUser = localStorage.getItem('user_email') || '사용자';
            loginBtnNode.style.display = 'none';
            userProfileNode.style.display = 'flex';
            userProfileNode.querySelector('span').textContent = currentUser;
            document.querySelectorAll('.history-item').forEach(el => el.style.display = 'flex');
        } else {
            loginBtnNode.style.display = 'block';
            userProfileNode.style.display = 'none';
            document.querySelectorAll('.history-item').forEach(el => el.style.display = 'none');
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
        executeAnalysisBtn.addEventListener('click', () => {
            if (!selectedFile) {
                switchView('result-view');
                return;
            }

            executeAnalysisBtn.innerHTML = '⏳ 영상 분석 중..';
            executeAnalysisBtn.disabled = true;

            const formData = new FormData();
            formData.append('file', selectedFile);

            const token = localStorage.getItem('access_token');
            const headers = token ? { 'Authorization': `Bearer ${token}` } : {};

            fetch('/api/analyze', { method: 'POST', headers, body: formData })
                .then(res => res.json())
                .then(data => {
                    console.log('분석 결과:', data);

                    // ① objects-view 채우기
                    document.getElementById('objTotalFrames').textContent = data.total_frames || 0;
                    document.getElementById('objTotalCount').textContent = data.object_count || 0;

                    const tableBody = document.getElementById('objRecordsTable');
                    if (data.records && data.records.length > 0) {
                        tableBody.innerHTML = data.records.map(r => `
                            <tr style="border-bottom: 1px solid #e2e8f0;">
                                <td style="padding: 0.75rem;">${r.frame || '-'}</td>
                                <td style="padding: 0.75rem; font-weight: 500;">
                                    <span style="background: var(--bg-alt); padding: 0.2rem 0.5rem; border-radius: 4px; border: 1px solid #cbd5e1;">
                                        ${r.object_type || '-'}
                                    </span>
                                </td>
                                <td style="padding: 0.75rem; color: var(--text-secondary);">
                                    ${(r.confidence ? (r.confidence * 100).toFixed(1) : 0)}%
                                </td>
                            </tr>
                        `).join('');
                    } else {
                        tableBody.innerHTML = `<tr><td colspan="3" style="padding:1rem;text-align:center;color:var(--text-secondary);">탐지된 객체가 없습니다.</td></tr>`;
                    }

                    // ② result-view 과실비율 반영
                    const faultA = data.fault_ratio_a ?? 50;
                    const faultB = data.fault_ratio_b ?? 50;

                    // 숫자 업데이트
                    const ratioCircles = document.querySelectorAll('.ratio-value');
if (ratioCircles.length >= 2) {
    ratioCircles[0].textContent = faultA;
    ratioCircles[1].textContent = faultB;
}

// 원형 게이지 비율 + 색상 동시 업데이트
const circleAEl = document.querySelector('.ratio-circle.a');
const circleBEl = document.querySelector('.ratio-circle.b');

if (circleAEl && circleBEl) {
    let colorA = faultA >= 70 ? '#ef4444' : faultA >= 40 ? '#f97316' : '#22c55e';
    let colorB = faultB >= 70 ? '#ef4444' : faultB >= 40 ? '#f97316' : '#22c55e';

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
                })
                .catch(err => {
                    console.error('오류:', err);
                    alert('서버와 통신 중 문제가 발생했습니다. API 서버가 작동 중인지 확인해 주세요.');
                    switchView('objects-view');
                })
                .finally(() => {
                    executeAnalysisBtn.innerHTML = '🎬 영상 분석 실행 버튼';
                    executeAnalysisBtn.disabled = false;
                });
        });
    }

    // 히스토리 아이템 클릭
    const historyItems = document.querySelectorAll('.history-item');
    historyItems.forEach(item => {
        item.addEventListener('click', (e) => {
            if (e.target.closest('.action-btn')) return;
            historyItems.forEach(h => h.classList.remove('active'));
            item.classList.add('active');
            switchView('result-view');
        });
    });

    updateUIState();
});
