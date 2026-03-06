// static/js/stockDetail.js
document.addEventListener('alpine:init', () => {
    Alpine.data('stockDetailPage', (stockCode, initialData) => {
        // 반응형으로 관리할 상태(state)들을 data 객체 안에 명시적으로 모아줍니다.
        const data = Alpine.reactive({
            activeTab: 'dashboard',
            chartPeriod: '1y',
            metricsPeriod: 'quarterly',
            financialsPeriod: 'quarterly',
            activeFinStatement: 'IS',
        });

        // Chart.js 인스턴스처럼 반응성이 필요 없는 객체들
        let priceChart = null;
        let metricsCharts = {};



        return {
            // ------------------ 상태 (State) ------------------
            data: data,
            stockCode: stockCode,
            initialData: initialData,            
            activeTab: 'dashboard',
            kpiData: null,       // KPI 데이터를 저장할 곳 (초기값은 null)
            isKpiLoading: false, // 로딩 상태를 관리할 변수
            // ------------------ 초기화 (Initialization) ------------------
            init() {
                // DOM이 준비된 후, 이 컴포넌트의 모든 초기화 작업을 수행
                this.$nextTick(() => {
                    this.initPriceChart();
                    this.initMetricsCharts();
                    this.loadKpiData();
                });
            },

            // ------------------ 공통 옵션 및 헬퍼 ------------------
            commonMetricsChartOptions() {
                return {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: 'top', labels: { color: '#d1d5db', boxWidth: 10, padding: 20 }}},
                    scales: {
                        x: { ticks: { color: '#9ca3af' }, grid: { display: false } },
                        y: {
                            ticks: {
                                color: '#9ca3af',
                                callback: (value) => {
                                    if (Math.abs(value) >= 1e9) return (value / 1e9).toFixed(1) + 'B';
                                    if (Math.abs(value) >= 1e6) return (value / 1e6).toFixed(1) + 'M';
                                    if (Math.abs(value) >= 1e3) return (value / 1e3).toFixed(1) + 'K';
                                    return value;
                                }
                            },
                            grid: { color: 'rgba(255, 255, 255, 0.1)' }
                        }
                    }
                };
            },

            formatNumber(value) {
                if (value === null || value === undefined) return '-';
                if (isNaN(value)) return value;
                return new Intl.NumberFormat('en-US').format(value);
            },

            // ------------------ 주가 차트 관련 ------------------
            initPriceChart() {
                if (!this.$refs.priceCanvas) return;
                const isPositive = this.initialData.price.changePercent >= 0;
                const config = {
                    type: 'line',
                    data: {
                        labels: this.initialData.price.labels,
                        datasets: [this.createPriceDataset(this.initialData.price.values , isPositive)]
                    },
                    options: {
                        responsive: true, maintainAspectRatio: false,
                        interaction: { mode: 'index', intersect: false },
                        plugins: { legend: { display: false }, tooltip: { position: 'nearest' }},
                        scales: {
                            x: { type: 'time', time: { unit: 'month' }, ticks: { color: '#9ca3af', maxRotation: 0, autoSkip: true, autoSkipPadding: 30 }, grid: { display: false }},
                            y: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(255, 255, 255, 0.1)' }}
                        }
                    }
                };
                priceChart = new Chart(this.$refs.priceCanvas, config);
            },
            

            async updatePriceChart(period) {
                if (this.data.chartPeriod === period) return;
                this.data.chartPeriod = period;
                
                const response = await fetch(`${window.location.pathname}?format=json&period=${period}`);
                const newData = await response.json();
                
                // priceChart는 이제 순수한 Chart.js 객체이므로 안전합니다.
                if (priceChart) {
                    priceChart.data.labels = newData.labels;
                    priceChart.data.datasets[0].data = newData.data;
                    priceChart.update();
                }
            },

            // --- 메서드(Method) 추가 ---
            async selectTab(tabName) {
                this.activeTab = tabName;
                
                // KPI 탭을 처음 선택하고, 아직 데이터가 없을 때만 API 호출
                if (tabName === 'kpis' && !this.kpiData) {
                    await this.loadKpiData();
                }
                // Financials 탭 등 다른 탭에 대해서도 유사한 로직 추가 가능
            },

            async loadKpiData() {
                this.isKpiLoading = true;
                try {
                    const response = await fetch(`/api/kpis/${stockCode}/`);
                    this.kpiData = await response.json();
                } catch (error) {
                    console.error("Failed to load KPI data:", error);
                    // 에러 처리 로직 (예: 에러 메시지 표시)
                } finally {
                    this.isKpiLoading = false;
                }
            },

            createPriceDataset(data, isPositive) {
                const chartColor = isPositive ? 'rgb(52, 211, 153)' : 'rgb(239, 68, 68)';
                const gradientStart = isPositive ? 'rgba(52, 211, 153, 0.4)' : 'rgba(239, 68, 68, 0.4)';
                const gradientEnd = isPositive ? 'rgba(52, 211, 153, 0)' : 'rgba(239, 68, 68, 0)';

                return {
                    label: 'Price',
                    data: data,
                    borderColor: chartColor,
                    backgroundColor: (context) => {
                        const gradient = context.chart.ctx.createLinearGradient(0, 0, 0, context.chart.height);
                        gradient.addColorStop(0, gradientStart);
                        gradient.addColorStop(1, gradientEnd);
                        return gradient;
                    },
                    borderWidth: 2, pointRadius: 0, tension: 0.1, fill: true,
                };
            },

            // ------------------ 하단 재무 차트 관련 ------------------
            initMetricsCharts() {
                const chartData = this.initialData.metrics;
                const options = this.commonMetricsChartOptions();
                for (const key in chartData) {
                    const data = chartData[key];
                    const parsedData = data;
                    parsedData.options = options;
                    const canvas = this.$refs[key + 'Canvas'];
                    if (data && canvas) {
                        new Chart(canvas, parsedData);
                    }
                }
            },

            // // ------------------ 재무제표 테이블 관련 ------------------
            // get activeFinancials() {
            //     const parsedFinancial = JSON.parse(initialData.financials)  
            //     const stmtData = parsedFinancial[this.activeFinStatement] || {};
            //     return stmtData[this.financialsPeriod] || { dates: [], statements: {}, items: [] };
            // },


            // 1. 현재 선택된 재무제표(IS/BS/CF) 객체 전체를 반환하는 getter
            get currentStatementData() {
                const parsedFinancial = this.initialData.financials
                // console.log('currentStatementData', parsedFinancial[this.activeFinStatement])
                return parsedFinancial[this.data.activeFinStatement] || { items: [], annual: {}, quarterly: {} };
            },
            
            // 2. 현재 선택된 "기간"에 맞는 데이터(dates, statements)를 반환하는 getter
            get activePeriodData() {
                // console.log(this.currentStatementData[this.data.financialsPeriod].statements)
                return this.currentStatementData[this.data.financialsPeriod] || { dates: [], statements: {} };
            },

            get getKpiData(){
                // console.log(this.kpiData)
                return this.kpiData;
            },

            // [추가할 코드] HTML에서 'predictions'로 바로 접근할 수 있게 해주는 Getter
            get predictions() {
                // 데이터가 없을 경우를 대비해 기본값(빈 객체/배열)을 반환하여 에러 방지
                return this.initialData.predictions || { 
                    accuracy: 0, 
                    total_count: 0, 
                    logs: [] 
                };
            }


        };
    });
});