const commonChartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: {
            position: 'top',
            labels: { color: '#d1d5db' }
        }
    },
    scales: {
        x: {
            ticks: { color: '#9ca3af' },
            grid: { display: false }
        },
        y: {
            ticks: {
                color: '#9ca3af',
                // 여기에 JavaScript 함수를 직접 작성합니다!
                callback: function(value) {
                    if (Math.abs(value) >= 1e9) {
                        return (value / 1e9).toFixed(1) + 'B'; // Billion (십억)
                    }
                    if (Math.abs(value) >= 1e6) {
                        return (value / 1e6).toFixed(1) + 'M'; // Million (백만)
                    }
                    return value;
                }
            },
            grid: {
                color: 'rgba(255, 255, 255, 0.1)'
            }
        }
    }
    
};

function jsonParseWithFunctions(jsonString) {
    if (!jsonString) return null;
    return JSON.parse(jsonString, (key, value) => {
        if (typeof value === 'string' && value.startsWith('function')) {
            return new Function('return ' + value)();
        }
        return value;
    });
}


function drawPriceChart(priceCtx, labels, data, chartColor, backgroundColor, backgroundColorStop){

    new Chart(priceCtx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Price',
                data: data,
                borderColor: chartColor, // Tailwind green-400
                backgroundColor: (context) => { // 그라데이션 효과
                    const ctx = context.chart.ctx;
                    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
                    gradient.addColorStop(0, backgroundColor);
                    gradient.addColorStop(1, backgroundColorStop);
                    return gradient;
                },
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.1,
                fill: true,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: { 
                legend: { display: false },
                tooltip: {
                    position: 'nearest',
                    titleFont: { size: 14 },
                    bodyFont: { size: 12 },
                    padding: 10
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'month', // This sets the x-axis labels to display months
                        // You can also customize the display format if needed
                        displayFormats: {
                            month: 'MMM yyyy' // Example: "Jan 2023", "Feb 2023"
                        }
                    },
                    ticks: { color: '#9ca3af' }, // gray-400
                    grid: { display:false }
                },
                y: {
                    ticks: { color: '#9ca3af' }, // gray-400
                    grid: { color: 'rgba(255, 255, 255, 0.1)' }
                }
            }
        }
    });
}

async function updatePriceChart(period) {
    if (this.activePeriod === period) return;
    this.activePeriod = period;

    
    // --- 이 부분이 변경됩니다 ---
    // 기존: /stocks/api/price-history/...
    // 변경: 현재 페이지 URL에 ?format=json&period=... 추가
    const currentPath = window.location.pathname;
    const response = await fetch(`${currentPath}?format=json&period=${period}`);
    // -------------------------
    const newData = await response.json();

    let chartColor = 'rgb(219, 18, 18)';
    let backgroundColor = 'rgba(219, 18, 18, 0.4)';
    let backgroundColorStop = 'rgba(219, 18, 18, 0)';

    const changePercent = jsonParseWithFunctions(document.getElementById('change-percent').textContent || 'null');


    if(changePercent > 0){
        chartColor = 'rgb(52, 211, 153)';
        backgroundColor = 'rgba(52, 211, 153, 0.4)';
        backgroundColorStop = 'rgba(52, 211, 153, 0)';
    }
    // 1. 메인 가격 차트
    const priceCtx = document.getElementById('priceChart').getContext('2d');

    let chartStatus = Chart.getChart('priceChart');
    if (chartStatus !== undefined) {
        chartStatus.destroy();
    }

    drawPriceChart(priceCtx, newData.labels, newData.data, chartColor, backgroundColor, backgroundColorStop)

    
}


    
document.addEventListener('DOMContentLoaded', function () {
    // 1. Income Overview
    // 이전에 직접 문자열을 넣던 방식 대신, DOM에서 데이터를 가져옵니다.
    const incomeOverviewAnnualData = jsonParseWithFunctions(document.getElementById('income-overview-annual-data').textContent || 'null');
    const jsonIncomeOverviewAnnualData = JSON.parse(incomeOverviewAnnualData);
    
    if (jsonIncomeOverviewAnnualData) {
        jsonIncomeOverviewAnnualData.options = commonChartOptions
        new Chart(document.getElementById('incomeOverviewAnnualChart'), jsonIncomeOverviewAnnualData);
    }
    
    // --- 다른 차트들도 모두 이 방식으로 수정합니다 ---
    const incomeOverviewQuarterlyData = jsonParseWithFunctions(document.getElementById('income-overview-quarterly-data').textContent || 'null');
    const jsonIncomeOverviewQuarterlyData = JSON.parse(incomeOverviewQuarterlyData);

    if (jsonIncomeOverviewQuarterlyData) {
        jsonIncomeOverviewQuarterlyData.options = commonChartOptions
        new Chart(document.getElementById('incomeOverviewQuarterlyChart'), jsonIncomeOverviewQuarterlyData);
    }

    // 2. Net Income (동일한 방식으로 수정)
    const netIncomeAnnualData = jsonParseWithFunctions(document.getElementById('net-income-annual-data').textContent || 'null');
    const jsonNetIncomeAnnualData = JSON.parse(netIncomeAnnualData);

    if (jsonNetIncomeAnnualData) {
        jsonNetIncomeAnnualData.options = commonChartOptions
        new Chart(document.getElementById('netIncomeAnnualChart'), jsonNetIncomeAnnualData);
    }

    const netIncomeQuarterlyData = jsonParseWithFunctions(document.getElementById('net-income-quarterly-data').textContent || 'null');
    const jsonNetIncomeQuarterlyData = JSON.parse(netIncomeQuarterlyData);

    if (jsonNetIncomeQuarterlyData) {
        jsonNetIncomeQuarterlyData.options = commonChartOptions
        new Chart(document.getElementById('netIncomeQuarterlyChart'), jsonNetIncomeQuarterlyData);
    }
    

    const fcfAnnualData = jsonParseWithFunctions(document.getElementById('fcf-annual-data').textContent || 'null');
    const jsonFcfAnnualData = JSON.parse(fcfAnnualData);

    if (jsonFcfAnnualData) {
        jsonFcfAnnualData.options = commonChartOptions
        new Chart(document.getElementById('fcfAnnualChart'), jsonFcfAnnualData);
    }

    const fcfQuarterlyData = jsonParseWithFunctions(document.getElementById('fcf-quarterly-data').textContent || 'null');
    const jsonFcfQuarterlyData = JSON.parse(fcfQuarterlyData);

    if (jsonFcfQuarterlyData) {
        jsonFcfQuarterlyData.options = commonChartOptions
        new Chart(document.getElementById('fcfQuarterlyChart'), jsonFcfQuarterlyData);
    }

    const priceLabels = jsonParseWithFunctions(document.getElementById('price-labels-json').textContent || 'null');
    const priceValues = jsonParseWithFunctions(document.getElementById('price-values-json').textContent || 'null');
    const changePercent = jsonParseWithFunctions(document.getElementById('change-percent').textContent || 'null');

    let chartColor = 'rgb(219, 18, 18)';
    let backgroundColor = 'rgba(219, 18, 18, 0.4)';
    let backgroundColorStop = 'rgba(219, 18, 18, 0)';

    if(changePercent > 0){
        chartColor = 'rgb(52, 211, 153)';
        backgroundColor = 'rgba(52, 211, 153, 0.4)';
        backgroundColorStop = 'rgba(52, 211, 153, 0)';
    }
    // 1. 메인 가격 차트
    const priceCtx = document.getElementById('priceChart').getContext('2d');
    drawPriceChart(priceCtx, JSON.parse(priceLabels), JSON.parse(priceValues), chartColor, backgroundColor, backgroundColorStop)



});