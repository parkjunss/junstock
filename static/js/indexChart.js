// static/js/main.js

document.addEventListener('DOMContentLoaded', function() {
    // ===== 미니 차트 생성 함수 =====
    const createMiniChart = (elementId, data) => {
        const ctx = document.getElementById(elementId).getContext('2d');
        const numberArray = data.map(parseFloat);
        let isPositive = true;
        if(numberArray[numberArray.length - 1] - numberArray[numberArray.length - 2] < 0){
            isPositive = false
        }
        const chartColor = isPositive ? '#4CAF50' : '#F44336';
        // 그라데이션 설정
        const gradient = ctx.createLinearGradient(0, 0, 0, 70);
        gradient.addColorStop(0, `${chartColor}40`); // 25% 투명도
        gradient.addColorStop(1, `${chartColor}00`); // 0% 투명도

        new Chart(ctx, {
            type: 'line',
            data: {
                labels: numberArray.map((_, i) => i), // x축 레이블은 숨김
                datasets: [{
                    data: numberArray,
                    borderColor: chartColor,
                    borderWidth: 2.5,
                    fill: true,
                    backgroundColor: gradient,
                    pointRadius: 0, // 점 숨기기
                    tension: 0.2 // 라인을 부드럽게
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false // 범례 숨기기
                    },
                    tooltip: {
                        enabled: false // 툴팁 숨기기
                    }
                },
                scales: {
                    x: {
                        display: false // x축 숨기기
                    },
                    y: {
                        display: false // y축 숨기기
                    }
                }
            }
        });
    };

    const chartElements = document.querySelectorAll('canvas');
    const indexList = {
        'sp-500': 'S&P 500',
        'nasdaq': 'Nasdaq',
        'dow-jones': 'Dow Jones',
        'kospi': 'KOSPI',
    }

    chartElements.forEach(canvas => {
        const canvasId = canvas.id;
        // 3. 캔버스 ID를 기반으로 데이터 스크립트의 ID를 만든다.
        const dataScriptId = indexList[canvasId];
        
        const dataElement = document.getElementById(dataScriptId);

        if (dataElement) {
            // 5. 데이터를 파싱하고 차트를 그린다.
            const historyData = dataElement.textContent.replace("[", "").replace("]", "").split(" ");
            // is_positive 같은 추가 정보는 canvas의 data-* 속성을 활용할 수 있음
            createMiniChart(canvasId, historyData);
        }
    });
});