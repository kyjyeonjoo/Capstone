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

    if (closeModalBtn) {
        // Find all close buttons inside modals
        document.querySelectorAll('.close-modal').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const overlay = e.target.closest('.modal-overlay');
                if (overlay) overlay.classList.remove('active');
            });
        });
    }

    const resultViewBtn = document.getElementById('resultViewBtn');
    if (resultViewBtn) resultViewBtn.addEventListener('click', () => switchView(resultViewBtn.getAttribute('data-target')));

    const backToObjectsBtn = document.getElementById('backToObjectsBtn');
    if (backToObjectsBtn) {
        backToObjectsBtn.addEventListener('click', (e) => {
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
            window.location.hash = ''; // Clear hash
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
                // 탭 전환 (회원가입 -> 로그인)
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

    // Profile updates
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

            fetch('/api/analyze', {
                method: 'POST',
                headers,
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                console.log('Analysis Result:', data);
                window.currentAccidentData = data;
                
                // ① objects-view 채우기
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
                    tableBody.innerHTML = `<tr><td colspan="3" style="padding: 1rem; text-align: center; color: var(--text-secondary);">탐지된 객체가 없습니다.</td></tr>`;
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
                console.error('Error:', err);
                document.getElementById('objTotalFrames').textContent = 0;
                document.getElementById('objTotalCount').textContent = 0;
                document.getElementById('objRecordsTable').innerHTML = `<tr><td colspan="3" style="padding: 1rem; text-align: center; color: var(--text-secondary);">데이터가 없습니다. (API 통신 실패)</td></tr>`;
                
                showToast('서버와 통신 중 문제가 발생했습니다. API 서버가 작동 중인지 확인해주세요.', 'error');
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

    // --- Chat Logic ---
    const chatInput = document.querySelector('.chat-input');
    const sendBtn = document.querySelector('.send-btn');
    const chatMessages = document.querySelector('.chat-messages');

    if (chatInput && sendBtn && chatMessages) {
        async function sendMessage() {
            const message = chatInput.value.trim();
            if (!message) return;

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
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_question: message,
                        accident_data: accidentData
                    })
                });
                const data = await res.json();

                if (!res.ok) throw new Error(data.detail || '채팅 응답 에러');

                // Update bot message with actual response
                // Replace line breaks with <br> for simple formatting
                botMsgDiv.innerHTML = data.answer.replace(/\n/g, '<br>');
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
    }
});
