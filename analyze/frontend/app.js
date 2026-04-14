document.addEventListener('DOMContentLoaded', () => {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const loadingOverlay = document.getElementById('loading-overlay');
    const resultSection = document.getElementById('result-section');
    const tableBody = document.getElementById('table-body');
    const summaryBadge = document.getElementById('summary-badge');

    // Prevent default drag behaviors
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    // Highlight drop zone when item is dragged over it
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, highlight, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, unhighlight, false);
    });

    function highlight(e) {
        dropZone.classList.add('dragover');
    }

    function unhighlight(e) {
        dropZone.classList.remove('dragover');
    }

    // Handle dropped files
    dropZone.addEventListener('drop', handleDrop, false);
    dropZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', function(e) {
        handleFiles(this.files);
    });

    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles(files);
    }

    function handleFiles(files) {
        if (files.length === 0) return;
        const file = files[0];
        
        // Check if file is video
        if (!file.type.startsWith('video/')) {
            alert('비디오 파일(.mp4, .avi 등)만 업로드 가능합니다.');
            return;
        }

        uploadFile(file);
    }

    async function uploadFile(file) {
        // Prepare UI for loading
        dropZone.classList.add('hidden');
        resultSection.classList.add('hidden');
        loadingOverlay.classList.remove('hidden');

        // Extract and display just the table data
        tableBody.innerHTML = '';
        summaryBadge.textContent = '총 객체 수: 계산 중...';

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/analyze', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`에러 발생: ${response.statusText}`);
            }

            const data = await response.json();
            
            // Hide loading, show results
            loadingOverlay.classList.add('hidden');
            resultSection.classList.remove('hidden');
            
            // Update summary
            summaryBadge.textContent = `총 추출된 객체 수: ${data.object_count}개 (${data.total_frames} 프레임 분석)`;

            // Render table rows
            if (data.records && data.records.length > 0) {
                data.records.forEach(record => {
                    const row = document.createElement('tr');
                    
                    row.innerHTML = `
                        <td><span style="color: var(--text-muted); font-size: 0.8rem;">${record.id.split('-')[0]}...</span></td>
                        <td><strong>${record.video_id}</strong></td>
                        <td>${record.frame}</td>
                        <td><span style="background:var(--drop-hover); padding:2px 6px; border-radius:4px; font-weight:bold; color:var(--primary-color);">#${record.track_id}</span></td>
                        <td><span style="color: var(--primary-color); font-weight: 600;">${record.object_type}</span></td>
                        <td>(${record.bbox_x1}, ${record.bbox_y1}) - (${record.bbox_x2}, ${record.bbox_y2})</td>
                        <td>${(record.confidence * 100).toFixed(1)}%</td>
                    `;
                    tableBody.appendChild(row);
                });
            } else {
                tableBody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">탐지된 객체가 없습니다.</td></tr>`;
            }

        } catch (error) {
            console.error('업로드 중 오류:', error);
            alert('영상 분석 중 오류가 발생했습니다. 서버 상태를 확인해주세요.');
            
            // Reset UI
            loadingOverlay.classList.add('hidden');
            dropZone.classList.remove('hidden');
        }
    }
});
