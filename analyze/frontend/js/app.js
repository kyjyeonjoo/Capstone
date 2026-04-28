document.addEventListener('DOMContentLoaded', () => {
    // --- State ---
    let isLoggedIn = false;
    let currentView = 'upload-view'; // 'upload-view', 'result-view', 'chat-view'
    
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
            
            // 로그인 권한 제어 (채팅만)
            if (targetView === 'chat-view' && !isLoggedIn) {
                authModal.classList.add('active');
                return;
            }
            
            // UI Update
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
    if(loginBtnNode) {
        loginBtnNode.addEventListener('click', () => {
            authModal.classList.add('active');
        });
    }

    if(closeModalBtn) {
        closeModalBtn.addEventListener('click', () => {
            authModal.classList.remove('active');
        });
    }

    // Modal tabs toggle (Login/Signup)
    modalTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.getAttribute('data-target');
            modalTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            formViews.forEach(f => f.classList.remove('active'));
            document.getElementById(target).classList.add('active');
        });
    });

    const resultViewBtn = document.getElementById('resultViewBtn');
    if (resultViewBtn) {
        resultViewBtn.addEventListener('click', (e) => {
            switchView(resultViewBtn.getAttribute('data-target'));
        });
    }

    const backToObjectsBtn = document.getElementById('backToObjectsBtn');
    if (backToObjectsBtn) {
        backToObjectsBtn.addEventListener('click', (e) => {
            switchView(backToObjectsBtn.getAttribute('data-target'));
        });
    }

    // Mock Login Submit
    const loginForm = document.getElementById('loginFormView');
    const loginSubmitBtn = loginForm.querySelector('.btn-primary');
    
    loginSubmitBtn.addEventListener('click', (e) => {
        e.preventDefault(); // prevent actual submit
        isLoggedIn = true;
        authModal.classList.remove('active');
        updateUIState();
    });

    // Mock Logout
    const logoutBtn = document.getElementById('logoutBtn');
    if(logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            isLoggedIn = false;
            userPopover.classList.remove('show');
            updateUIState();
        });
    }

    function updateUIState() {
        if(isLoggedIn) {
            loginBtnNode.style.display = 'none';
            userProfileNode.style.display = 'flex';
            // Show history items in sidebar
            document.querySelectorAll('.history-item').forEach(el => {
                el.style.display = 'flex';
            });
        } else {
            loginBtnNode.style.display = 'block';
            userProfileNode.style.display = 'none';
            // Hide history items
            document.querySelectorAll('.history-item').forEach(el => {
                el.style.display = 'none';
            });
            switchView('upload-view');
        }
    }

    // User Popover Toggle
    if(userProfileNode) {
        userProfileNode.addEventListener('click', (e) => {
            e.stopPropagation();
            userPopover.classList.toggle('show');
        });
        
        document.addEventListener('click', () => {
            if(userPopover.classList.contains('show')) {
                userPopover.classList.remove('show');
            }
        });
    }

    // --- Actions ---
    // Drag and Drop Effects & File Input
    const dropzone = document.getElementById('dropzone');
    const videoUpload = document.getElementById('videoUpload');
    let selectedFile = null;

    if(dropzone && videoUpload) {
        dropzone.addEventListener('click', () => videoUpload.click());
        
        videoUpload.addEventListener('change', (e) => {
            if(e.target.files.length > 0) {
                selectedFile = e.target.files[0];
                dropzone.querySelector('h3').textContent = '영상 파일 선택됨';
                dropzone.querySelector('p').textContent = selectedFile.name;
            }
        });

        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });
        dropzone.addEventListener('dragleave', () => {
            dropzone.classList.remove('dragover');
        });
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            if(e.dataTransfer.files.length > 0) {
                selectedFile = e.dataTransfer.files[0];
                dropzone.querySelector('h3').textContent = '영상 파일 드롭됨';
                dropzone.querySelector('p').textContent = selectedFile.name;
            }
        });
    }

    // Analysis Execution (Mock moving to Result screen)
    // Analysis Execution API 연결
    if(executeAnalysisBtn) {
        executeAnalysisBtn.addEventListener('click', () => {
            // 파일을 선택하지 않았더라도 UI 시연을 위해 결과화면으로 넘어갈 수 있도록 처리 (원한다면 에러 표시 가능)
            if (!selectedFile) {
                switchView('result-view');
                return;
            }

            executeAnalysisBtn.innerHTML = '🔄 영상 분석 중...';
            executeAnalysisBtn.disabled = true;

            const formData = new FormData();
            formData.append('file', selectedFile);

            fetch('/api/analyze', {
                method: 'POST',
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                console.log('Analysis Result:', data);
                
                // Populate objects view
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

                switchView('objects-view');
            })
            .catch(err => {
                console.error('Error:', err);
                // 가상 데이터 제거 - 서버 통신 실패 시 안내 메시지만 출력
                document.getElementById('objTotalFrames').textContent = 0;
                document.getElementById('objTotalCount').textContent = 0;
                document.getElementById('objRecordsTable').innerHTML = `<tr><td colspan="3" style="padding: 1rem; text-align: center; color: var(--text-secondary);">데이터가 없습니다. (API 통신 실패)</td></tr>`;
                
                alert('서버와 통신 중 문제가 발생했습니다. API 서버가 작동 중인지 확인해주세요.');
                switchView('objects-view'); 
            })
            .finally(() => {
                executeAnalysisBtn.innerHTML = '✨ 영상 분석 실행 버튼';
                executeAnalysisBtn.disabled = false;
            });
        });
    }
    
    // Selecting History Item (Mock Result switch)
    const historyItems = document.querySelectorAll('.history-item');
    historyItems.forEach(item => {
        item.addEventListener('click', (e) => {
            // Prevent if action buttons clicked
            if(e.target.closest('.action-btn')) return;
            
            historyItems.forEach(h => h.classList.remove('active'));
            item.classList.add('active');
            switchView('result-view');
        });
    });

    // Initial state execution
    updateUIState();
});
