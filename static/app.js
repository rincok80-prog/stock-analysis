// Frontend JavaScript Logic for A-Share Stock Analysis System

let currentStockCode = '600519';
let currentStockMarket = '1';
let currentStockName = '贵州茅台';
let activeIndicator = 'macd';

let klineChart = null;
let historicalKlines = [];
let indicatorsData = null;
let globalPredData = null; // Global reference for position diagnostics

// VIP & Monetization State
let isVip = localStorage.getItem('vip_active') === 'true'; // Loaded persistent state
let positionDiagnosticCount = 0;
let stockQueryCount = 0;

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    setupEventListeners();
    setupVipListeners();
    // Load initial stock (Kweichow Moutai)
    loadStockData(currentStockCode, currentStockMarket, currentStockName);
    // Fetch initial active stock scanner list
    triggerScanner();
});

// Initialize ECharts instance
function initChart() {
    const chartDom = document.getElementById('kline-chart-dom');
    klineChart = echarts.init(chartDom);
    
    window.addEventListener('resize', () => {
        if (klineChart) {
            klineChart.resize();
        }
    });
}

// Setup all DOM event listeners
function setupEventListeners() {
    const searchInput = document.getElementById('stock-search-input');
    const suggestionsBox = document.getElementById('search-suggestions');
    const scanBtn = document.getElementById('btn-scan-stocks');
    const favToggleBtn = document.getElementById('btn-toggle-favorite');
    const diagBtn = document.getElementById('btn-diag-position');
    
    // 1. Search Bar Input
    let debounceTimer;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(debounceTimer);
        const query = e.target.value.trim();
        
        if (!query) {
            suggestionsBox.style.display = 'none';
            return;
        }
        
        debounceTimer = setTimeout(() => {
            fetch(`/api/search?q=${encodeURIComponent(query)}`)
                .then(r => r.json())
                .then(data => {
                    renderSuggestions(data);
                })
                .catch(err => console.error("Search fetch error:", err));
        }, 200);
    });

    // Hide suggestions list when clicking outside
    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !suggestionsBox.contains(e.target)) {
            suggestionsBox.style.display = 'none';
        }
    });

    // 2. Indicator Tab Buttons
    const tabButtons = document.querySelectorAll('.chart-tab');
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            tabButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeIndicator = btn.dataset.ind;
            
            if (historicalKlines.length > 0) {
                renderChart();
            }
        });
    });

    // 3. Scan Button
    scanBtn.addEventListener('click', () => {
        const activeTab = document.querySelector('.sidebar-tab.active');
        if (activeTab.id === 'tab-scan-profit') {
            if (!isVip) {
                showVipModal("查看【游资狙击·短线黑马排行榜】属于 VIP 专属增值服务。");
                return;
            }
            loadLeaderboard();
        } else if (activeTab.id === 'tab-scan-favorites') {
            loadFavoritesList();
        } else {
            triggerScanner();
        }
    });

    // 4. Sidebar Tab Buttons
    const tabActive = document.getElementById('tab-scan-active');
    const tabProfit = document.getElementById('tab-scan-profit');
    const tabFavs = document.getElementById('tab-scan-favorites');
    
    const secActive = document.getElementById('scanner-active-section');
    const secProfit = document.getElementById('scanner-profit-section');
    const secFavs = document.getElementById('scanner-favorites-section');

    tabActive.addEventListener('click', () => {
        setActiveTab(tabActive, secActive);
    });

    tabProfit.addEventListener('click', () => {
        if (!isVip) {
            showVipModal("查看【游资狙击·短线黑马排行榜】属于 VIP 专属增值服务。");
            return;
        }
        setActiveTab(tabProfit, secProfit);
        loadLeaderboard();
    });

    tabFavs.addEventListener('click', () => {
        setActiveTab(tabFavs, secFavs);
        loadFavoritesList();
    });

    function setActiveTab(tabBtn, sectionEl) {
        document.querySelectorAll('.sidebar-tab').forEach(b => b.classList.remove('active'));
        tabBtn.classList.add('active');
        
        secActive.style.display = 'none';
        secProfit.style.display = 'none';
        secFavs.style.display = 'none';
        
        sectionEl.style.display = 'flex';
    }

    // 5. Add / Remove Favorite Button
    favToggleBtn.addEventListener('click', () => {
        toggleCurrentFavorite();
    });

    // 6. Position Diagnostics Button
    diagBtn.addEventListener('click', () => {
        if (!isVip) {
            if (positionDiagnosticCount >= 1) {
                showVipModal("您已试用过 1 次持仓诊断。开通 VIP 尊享无限次诊股及变盘分析。");
                return;
            }
            positionDiagnosticCount++;
        }
        runPositionDiagnosis();
    });
}

// Setup VIP Modal event listeners
function setupVipListeners() {
    const closeBtn = document.getElementById('btn-close-vip-modal');
    const activateBtn = document.getElementById('btn-activate-vip');
    const modal = document.getElementById('vip-modal');

    // Close Modal
    closeBtn.addEventListener('click', () => {
        modal.style.display = 'none';
    });

    // Code Activation
    activateBtn.addEventListener('click', () => {
        const codeInput = document.getElementById('input-vip-code');
        const errLbl = document.getElementById('lbl-activation-err');
        const code = codeInput.value.trim();

        // Hardcoded secret activation codes for testing/bypass
        if (code === '888888' || code === 'stockvip' || code === 'A股黑马') {
            isVip = true;
            localStorage.setItem('vip_active', 'true');
            modal.style.display = 'none';
            errLbl.style.display = 'none';
            codeInput.value = '';
            alert('👑 恭喜！VIP 会员通道已成功激活！您已解锁 23 维机器学习预测、短线黑马榜及无限次持仓诊断服务。');
            
            // Auto reload current stock / features if active
            if (currentStockCode) {
                loadStockData(currentStockCode, currentStockMarket, currentStockName);
            }
        } else {
            errLbl.innerText = '❌ 激活码错误，请重新输入或扫描二维码联系客服！';
            errLbl.style.display = 'block';
        }
    });
}

// Show VIP Modal with custom description
function showVipModal(reason) {
    const modal = document.getElementById('vip-modal');
    const headerP = modal.querySelector('.vip-modal-header p');
    headerP.innerHTML = `<span style="color: var(--color-warning); font-weight:700;">提示: ${reason}</span><br>开启高胜率23维机器学习模型与智能持仓诊断`;
    modal.style.display = 'flex';
}

// Render Suggestions Dropdown
function renderSuggestions(data) {
    const suggestionsBox = document.getElementById('search-suggestions');
    suggestionsBox.innerHTML = '';
    
    if (data.length === 0) {
        suggestionsBox.style.display = 'none';
        return;
    }
    
    data.forEach(item => {
        const div = document.createElement('div');
        div.className = 'suggestion-item';
        
        let marketStr = 'A股';
        if (item.quote_id.startsWith('1')) marketStr = '沪市';
        else if (item.quote_id.startsWith('0')) marketStr = '深市';
        
        div.innerHTML = `
            <div class="stock-info">
                <span class="stock-name">${item.name}</span>
                <span class="stock-code">${item.code}</span>
            </div>
            <span class="stock-market">${marketStr}</span>
        `;
        
        div.addEventListener('click', () => {
            currentStockCode = item.code;
            currentStockMarket = item.market;
            currentStockName = item.name;
            
            document.getElementById('stock-search-input').value = '';
            suggestionsBox.style.display = 'none';
            
            loadStockData(currentStockCode, currentStockMarket, currentStockName);
        });
        
        suggestionsBox.appendChild(div);
    });
    
    suggestionsBox.style.display = 'block';
}

// Load Stock Data from Backend
function loadStockData(code, market, name) {
    // Monetization Hook: Restrict to 3 stock searches for free users
    if (!isVip) {
        stockQueryCount++;
        if (stockQueryCount > 4) {
            showVipModal("您的免费股票查询额度（4次）已用尽。激活 VIP 开启无限次高速深度量化查股。");
            return;
        }
    }

    document.getElementById('lbl-stock-name').innerText = name;
    document.getElementById('lbl-stock-code').innerText = code;
    
    let marketName = '沪深A股';
    if (code.startsWith('688')) marketName = '科创板';
    else if (code.startsWith('30')) marketName = '创业板';
    else if (code.startsWith('8') || code.startsWith('43')) marketName = '北交所';
    document.getElementById('lbl-stock-market').innerText = marketName;

    // Check favorite status and update button style
    const favs = JSON.parse(localStorage.getItem('stock_favorites') || '[]');
    const isFav = favs.some(f => f.code === code);
    const favBtn = document.getElementById('btn-toggle-favorite');
    const favText = document.getElementById('lbl-fav-text');
    
    if (isFav) {
        favBtn.classList.add('favorited');
        favText.innerText = '已自选';
    } else {
        favBtn.classList.remove('favorited');
        favText.innerText = '加自选';
    }

    // Reset hold diagnostics display
    document.getElementById('panel-hold-diag-result').style.display = 'none';
    document.getElementById('panel-hold-diag-result').innerHTML = '';
    
    fetch(`/api/kline?code=${code}&market=${market}`)
        .then(res => {
            if (!res.ok) throw new Error("Stock load failed");
            return res.json();
        })
        .then(data => {
            historicalKlines = data.klines;
            indicatorsData = data.indicators;
            globalPredData = data.prediction; // Set global pred data reference
            
            // Render widgets
            renderHeaderStats(data.klines[data.klines.length - 1]);
            renderPredictionWidget(data.prediction);
            renderAnalysisReport(data.matched_setups, data.prediction);
            renderFactors(data.prediction.factors);
            renderFeatureImportances(data.prediction.feature_importances);
            
            // Render chart
            renderChart();

            // Populate hold diagnostics if saved in localStorage
            const savedPrice = localStorage.getItem(`hold_price_${code}`);
            const savedShares = localStorage.getItem(`hold_shares_${code}`);
            const priceInput = document.getElementById('input-hold-price');
            const sharesInput = document.getElementById('input-hold-shares');

            if (savedPrice !== null && savedShares !== null) {
                priceInput.value = savedPrice;
                sharesInput.value = savedShares;
                // Auto diagnose after a short delay
                setTimeout(() => {
                    runPositionDiagnosis();
                }, 100);
            } else {
                priceInput.value = '';
                sharesInput.value = '';
            }
        })
        .catch(err => {
            console.error("Load stock error:", err);
            alert(`加载股票 [${name} (${code})] 失败。可能历史交易记录不足或数据源解析异常。`);
        });
}

// Render Header Info Stats
function renderHeaderStats(latestBar) {
    const priceLbl = document.getElementById('lbl-stock-price');
    const chgLbl = document.getElementById('lbl-stock-change');
    
    priceLbl.innerText = latestBar.close.toFixed(2);
    
    const pct = latestBar.pct_change;
    const sign = pct > 0 ? '+' : '';
    chgLbl.innerText = `${sign}${pct.toFixed(2)}%`;
    
    priceLbl.className = 'stock-price';
    chgLbl.className = 'stock-change';
    if (pct > 0) {
        priceLbl.classList.add('up-text');
        chgLbl.classList.add('up-text');
    } else if (pct < 0) {
        priceLbl.classList.add('down-text');
        chgLbl.classList.add('down-text');
    }

    const volLots = latestBar.volume;
    const volStr = volLots >= 100000 ? `${(volLots / 10000).toFixed(1)}万手` : `${volLots}手`;
    document.getElementById('lbl-vol').innerText = volStr;
    
    const toRmb = latestBar.turnover;
    const toStr = toRmb >= 100000000 ? `${(toRmb / 100000000).toFixed(2)}亿元` : `${(toRmb / 10000).toFixed(1)}万元`;
    document.getElementById('lbl-turnover').innerText = toStr;
    
    document.getElementById('lbl-turnover-rate').innerText = `${latestBar.turnover_rate.toFixed(2)}%`;
    document.getElementById('lbl-amplitude').innerText = `${latestBar.amplitude.toFixed(2)}%`;
}

// Render circular gauge prediction value and Short-term Explosive diagnosis
function renderPredictionWidget(pred) {
    const prob = pred.probability;
    const probPct = Math.round(prob * 100);
    
    const circle = document.getElementById('gauge-progress');
    const circumference = 2 * Math.PI * 65; 
    const offset = circumference - (prob * circumference);
    
    circle.style.strokeDashoffset = offset;
    document.getElementById('lbl-pred-pct').innerText = `${probPct}%`;
    
    const ratingLbl = document.getElementById('lbl-pred-rating');
    const tipLbl = document.getElementById('lbl-pred-tip');
    
    ratingLbl.className = 'prediction-rating';
    if (prob >= 0.70) {
        ratingLbl.innerText = '极高爆发力';
        ratingLbl.classList.add('rating-high');
        tipLbl.innerText = '机器学习决策显示，多维量价特征呈现典型主力逼空拉升突破状态，后三日封板（涨停）概率大。';
    } else if (prob >= 0.40) {
        ratingLbl.innerText = '中等向上动能';
        ratingLbl.classList.add('rating-med');
        tipLbl.innerText = '量价形态维持上升趋势，但上方存在抛压，需注意洗盘动作。后三日可能冲击涨停，建议关注突破时机。';
    } else {
        ratingLbl.innerText = '常态波动 / 洗盘中';
        ratingLbl.classList.add('rating-low');
        tipLbl.innerText = '筹码尚未沉淀或属于低位筑底状态，动能偏弱。后三日出现涨停可能性较低，建议稳健观望。';
    }

    const diagPanel = document.getElementById('panel-explosive-diag');
    if (pred.explosive_score !== undefined) {
        document.getElementById('lbl-explosive-score').innerText = `${pred.explosive_score}%`;
        document.getElementById('lbl-explosive-diag').innerText = pred.explosive_diagnosis;
        diagPanel.style.display = 'block';
    } else {
        diagPanel.style.display = 'none';
    }
}

// Render Structured Quantitative Analysis Report
function renderAnalysisReport(setups, pred) {
    const dateLbl = document.getElementById('lbl-report-date');
    const setupsBox = document.getElementById('report-setups-matched');
    const buyAdviceBox = document.getElementById('lbl-report-buy-advice');
    const timingBox = document.getElementById('lbl-report-timing');

    // Update datetime in report header
    const now = new Date();
    const dateStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    dateLbl.innerText = `报告时间: ${dateStr}`;

    // 1. Classic Setups Match
    if (setups.length === 0) {
        setupsBox.innerHTML = `<span style="color: var(--text-muted);">暂未匹配到经典高胜率战法，目前该股处于常规盘整或跟风上涨阶段，量价波幅温和。</span>`;
    } else {
        setupsBox.innerHTML = '';
        setups.forEach(s => {
            const div = document.createElement('div');
            div.style.marginBottom = '6px';
            div.style.borderBottom = '1px solid rgba(255,255,255,0.03)';
            div.style.paddingBottom = '5px';
            div.innerHTML = `
                <div style="font-weight: 700; color: var(--color-warning); margin-bottom: 2px;">★ ${s.name} (战法契合度: ${s.score}分)</div>
                <div style="color: var(--text-secondary); margin-bottom: 2px; font-size: 11px;">${s.desc}</div>
                <div style="color: #fca5a5; font-size: 10px;">⚠️ 风控要点: ${s.risk}</div>
            `;
            setupsBox.appendChild(div);
        });
    }

    // 2. Buy Advice Recommendation
    buyAdviceBox.innerText = pred.buy_advice || "多维指标平衡，暂无强力推荐，持币观望为主。";

    // 3. Timing / When it might rise
    timingBox.innerText = pred.timing_analysis || "暂未发现明确变盘时间窗信号。";
}

// Render positive & negative factors
function renderFactors(factors) {
    const list = document.getElementById('pos-factors-list');
    list.innerHTML = '';
    
    factors.positive.forEach(f => {
        const div = document.createElement('div');
        div.className = 'factor-item positive';
        div.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M18 15l-6-6-6 6"/></svg>
            <span>${f}</span>
        `;
        list.appendChild(div);
    });

    factors.negative.forEach(f => {
        const div = document.createElement('div');
        div.className = 'factor-item negative';
        div.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
            <span>${f}</span>
        `;
        list.appendChild(div);
    });
    
    if (factors.positive.length === 0 && factors.negative.length === 0) {
        list.innerHTML = '<div style="color: var(--text-muted); font-size: 13px;">无明显强买/强卖边际特征数据。</div>';
    }
}

// Render feature importance bar chart
function renderFeatureImportances(importances) {
    const container = document.getElementById('feature-importance-list');
    container.innerHTML = '';
    
    let maxVal = 0.001;
    importances.forEach(item => {
        if (Math.abs(item.contrib) > maxVal) {
            maxVal = Math.abs(item.contrib);
        }
    });

    importances.forEach(item => {
        const row = document.createElement('div');
        row.className = 'importance-row';
        
        const pct = Math.min((Math.abs(item.contrib) / maxVal) * 100, 100);
        const styleClass = item.contrib >= 0 ? 'positive' : 'negative';
        
        row.innerHTML = `
            <span class="importance-lbl">${item.name}</span>
            <div class="importance-bar-bg">
                <div class="importance-bar-fill ${styleClass}" style="width: ${pct}%"></div>
            </div>
            <span class="importance-val ${styleClass === 'positive' ? 'up-text' : 'down-text'}">
                ${item.contrib >= 0 ? '+' : ''}${item.contrib.toFixed(2)}
            </span>
        `;
        container.appendChild(row);
    });
}

// Renders K-Line, Volume, and Indicators using ECharts
function renderChart() {
    const dates = historicalKlines.map(k => k.date);
    const dataValues = historicalKlines.map(k => [k.open, k.close, k.low, k.high]);
    const volumes = historicalKlines.map((k, idx) => [
        idx,
        k.volume,
        k.close > k.open ? 1 : -1
    ]);

    const ma5 = indicatorsData.ma5;
    const ma10 = indicatorsData.ma10;
    const ma20 = indicatorsData.ma20;
    const ma30 = indicatorsData.ma30;

    let subSeries = [];
    let subYAxisName = '';
    
    if (activeIndicator === 'macd') {
        subYAxisName = 'MACD';
        subSeries = [
            {
                name: 'DIF',
                type: 'line',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: indicatorsData.macd.dif,
                showSymbol: false,
                lineStyle: { width: 1.2, color: '#3b82f6' }
            },
            {
                name: 'DEA',
                type: 'line',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: indicatorsData.macd.dea,
                showSymbol: false,
                lineStyle: { width: 1.2, color: '#f59e0b' }
            },
            {
                name: 'MACD柱',
                type: 'bar',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: indicatorsData.macd.hist,
                itemStyle: {
                    color: function (params) {
                        return params.data >= 0 ? '#ef4444' : '#10b981';
                    }
                }
            }
        ];
    } else if (activeIndicator === 'kdj') {
        subYAxisName = 'KDJ';
        subSeries = [
            {
                name: 'K',
                type: 'line',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: indicatorsData.kdj.k,
                showSymbol: false,
                lineStyle: { width: 1.2, color: '#3b82f6' }
            },
            {
                name: 'D',
                type: 'line',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: indicatorsData.kdj.d,
                showSymbol: false,
                lineStyle: { width: 1.2, color: '#f59e0b' }
            },
            {
                name: 'J',
                type: 'line',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: indicatorsData.kdj.j,
                showSymbol: false,
                lineStyle: { width: 1.2, color: '#a855f7' }
            }
        ];
    } else if (activeIndicator === 'rsi') {
        subYAxisName = 'RSI';
        subSeries = [
            {
                name: 'RSI6',
                type: 'line',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: indicatorsData.rsi.rsi6,
                showSymbol: false,
                lineStyle: { width: 1.2, color: '#ef4444' }
            },
            {
                name: 'RSI12',
                type: 'line',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: indicatorsData.rsi.rsi12,
                showSymbol: false,
                lineStyle: { width: 1.2, color: '#10b981' }
            }
        ];
    } else if (activeIndicator === 'boll') {
        subYAxisName = 'Volume';
        subSeries = [
            {
                name: '成交量',
                type: 'bar',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: volumes.map(v => v[1]),
                itemStyle: {
                    color: function (params) {
                        return historicalKlines[params.dataIndex].close > historicalKlines[params.dataIndex].open ? '#ef4444' : '#10b981';
                    }
                }
            }
        ];
    }

    const mainSeries = [
        {
            name: '日K线',
            type: 'candlestick',
            data: dataValues,
            itemStyle: {
                color: '#ef4444',
                color0: '#10b981',
                borderColor: '#ef4444',
                borderColor0: '#10b981'
            }
        },
        {
            name: 'MA5',
            type: 'line',
            data: ma5,
            showSymbol: false,
            lineStyle: { width: 1, color: '#3b82f6', opacity: 0.8 }
        },
        {
            name: 'MA10',
            type: 'line',
            data: ma10,
            showSymbol: false,
            lineStyle: { width: 1, color: '#f59e0b', opacity: 0.8 }
        },
        {
            name: 'MA20',
            type: 'line',
            data: ma20,
            showSymbol: false,
            lineStyle: { width: 1, color: '#10b981', opacity: 0.8 }
        },
        {
            name: 'MA30',
            type: 'line',
            data: ma30,
            showSymbol: false,
            lineStyle: { width: 1, color: '#a855f7', opacity: 0.8 }
        }
    ];

    if (activeIndicator === 'boll') {
        mainSeries.push(
            {
                name: 'BOLL上轨',
                type: 'line',
                data: indicatorsData.boll.upper,
                showSymbol: false,
                lineStyle: { width: 1, color: '#f87171', type: 'dashed' }
            },
            {
                name: 'BOLL中轨',
                type: 'line',
                data: indicatorsData.boll.mid,
                showSymbol: false,
                lineStyle: { width: 1, color: '#60a5fa', type: 'dashed' }
            },
            {
                name: 'BOLL下轨',
                type: 'line',
                data: indicatorsData.boll.lower,
                showSymbol: false,
                lineStyle: { width: 1, color: '#34d399', type: 'dashed' }
            }
        );
    }

    const option = {
        backgroundColor: 'transparent',
        animation: false,
        legend: {
            bottom: 10,
            left: 'center',
            data: activeIndicator === 'boll' 
                ? ['日K线', 'MA5', 'MA10', 'MA20', 'MA30', 'BOLL上轨', 'BOLL中轨', 'BOLL下轨'] 
                : ['日K线', 'MA5', 'MA10', 'MA20', 'MA30'],
            textStyle: { color: '#9ca3af', fontSize: 11 }
        },
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            backgroundColor: 'rgba(15, 23, 42, 0.9)',
            borderColor: 'rgba(255,255,255,0.1)',
            textStyle: { color: '#f3f4f6', fontSize: 12 },
            position: function (pos, params, el, elRect, size) {
                const obj = { top: 10 };
                obj[['left', 'right'][+(pos[0] < size.viewSize[0] / 2)]] = 30;
                return obj;
            }
        },
        axisPointer: {
            link: [{ xAxisIndex: 'all' }],
            label: { backgroundColor: '#1e293b' }
        },
        grid: [
            { left: '4%', right: '4%', height: '58%', top: '5%' },
            { left: '4%', right: '4%', top: '72%', height: '18%' }
        ],
        xAxis: [
            {
                type: 'category',
                data: dates,
                boundaryGap: false,
                axisLine: { onZero: false, lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
                splitLine: { show: true, lineStyle: { color: 'rgba(255,255,255,0.03)' } },
                axisLabel: { show: false },
                axisPointer: { show: true }
            },
            {
                type: 'category',
                gridIndex: 1,
                data: dates,
                boundaryGap: false,
                axisLine: { onZero: false, lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
                splitLine: { show: true, lineStyle: { color: 'rgba(255, 255, 255, 0.03)' } },
                axisLabel: { color: '#9ca3af', fontSize: 10 },
                axisPointer: { show: true }
            }
        ],
        yAxis: [
            {
                scale: true,
                splitArea: { show: false },
                axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
                splitLine: { show: true, lineStyle: { color: 'rgba(255, 255, 255, 0.03)' } },
                axisLabel: { color: '#9ca3af', fontSize: 10 }
            },
            {
                scale: true,
                gridIndex: 1,
                splitNumber: 2,
                axisLabel: { show: true, color: '#9ca3af', fontSize: 10 },
                axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
                splitLine: { show: true, lineStyle: { color: 'rgba(255, 255, 255, 0.03)' } }
            }
        ],
        dataZoom: [
            {
                type: 'inside',
                xAxisIndex: [0, 1],
                start: 75,
                end: 100
            },
            {
                show: true,
                xAxisIndex: [0, 1],
                type: 'slider',
                bottom: '40',
                start: 75,
                end: 100,
                borderColor: 'rgba(255, 255, 255, 0.05)',
                fillerColor: 'rgba(59, 130, 246, 0.1)',
                textStyle: { color: '#9ca3af' }
            }
        ],
        series: [
            ...mainSeries,
            ...subSeries
        ]
    };

    klineChart.setOption(option, true);
}

// Trigger stock scanner API call
function triggerScanner() {
    const scanBtn = document.getElementById('btn-scan-stocks');
    const spinner = document.getElementById('scanner-spinner');
    const scanIcon = document.getElementById('scanner-icon');
    const listContainer = document.getElementById('scanner-list-container');
    
    scanBtn.classList.add('loading');
    scanBtn.disabled = true;
    spinner.style.display = 'inline-block';
    scanIcon.style.display = 'none';
    
    fetch('/api/scanner')
        .then(res => {
            if (!res.ok) throw new Error("Scanner failed");
            return res.json();
        })
        .then(data => {
            renderScannerList(data);
        })
        .catch(err => {
            console.error("Scanner error:", err);
            listContainer.innerHTML = '<div style="color: var(--color-up); font-size: 12px; padding: 20px 0; text-align: center;">扫描失败，请检查网络。</div>';
        })
        .finally(() => {
            scanBtn.classList.remove('loading');
            scanBtn.disabled = false;
            spinner.style.display = 'none';
            scanIcon.style.display = 'inline-block';
        });
}

// Render Scanner results list in sidebar
function renderScannerList(list) {
    const container = document.getElementById('scanner-list-container');
    container.innerHTML = '';
    
    document.getElementById('lbl-scan-count').innerText = `已扫描 ${list.length} 只`;
    
    if (list.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; text-align: center; padding: 40px 0;">扫描完成，但未发现符合特征的高胜率爆发个股。</div>';
        return;
    }
    
    list.forEach((item, index) => {
        const div = document.createElement('div');
        div.className = 'scanner-item';
        if (item.code === currentStockCode) {
            div.classList.add('active');
        }
        
        const probPct = Math.round(item.probability * 100);
        const chgSign = item.pct_change > 0 ? '+' : '';
        const chgClass = item.pct_change > 0 ? 'up-text' : (item.pct_change < 0 ? 'down-text' : '');
        
        let probClass = '';
        if (item.probability >= 0.70) probClass = 'up-text';
        else if (item.probability >= 0.40) probClass = 'down-text';
        
        const rankBadge = `<span class="rank-badge rank-normal">${index + 1}</span>`;
        
        div.innerHTML = `
            <div class="scanner-item-row1">
                <span class="scanner-item-name">${rankBadge}${item.name}</span>
                <span class="scanner-item-prob ${probClass}">${probPct}% 概率</span>
            </div>
            <div class="scanner-item-row2">
                <span class="scanner-item-code">${item.code}</span>
                <span class="scanner-item-price">${item.price.toFixed(2)}</span>
                <span class="scanner-item-chg ${chgClass}">${chgSign}${item.pct_change.toFixed(2)}%</span>
            </div>
            <span class="scanner-item-strategy">${item.strategy}</span>
        `;
        
        div.addEventListener('click', () => {
            currentStockCode = item.code;
            currentStockMarket = item.market;
            currentStockName = item.name;
            
            document.querySelectorAll('.scanner-item').forEach(el => el.classList.remove('active'));
            div.classList.add('active');
            
            loadStockData(currentStockCode, currentStockMarket, currentStockName);
        });
        
        container.appendChild(div);
    });
}

// Load short-term high-profit leaderboard
function loadLeaderboard() {
    const container = document.getElementById('leaderboard-list-container');
    container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; text-align: center; padding: 40px 0;">正在扫描 A股 游资短线暴利黑马...</div>';
    
    fetch('/api/leaderboard')
        .then(res => {
            if (!res.ok) throw new Error("Leaderboard load failed");
            return res.json();
        })
        .then(data => {
            renderLeaderboardList(data);
        })
        .catch(err => {
            console.error("Leaderboard error:", err);
            container.innerHTML = '<div style="color: var(--color-up); font-size: 12px; padding: 20px 0; text-align: center;">加载短线暴利榜失败，请重试。</div>';
        });
}

// Render Leaderboard items in sidebar
function renderLeaderboardList(list) {
    const container = document.getElementById('leaderboard-list-container');
    container.innerHTML = '';
    
    if (list.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; text-align: center; padding: 40px 0;">未发现符合高爆发特征的短线股。</div>';
        return;
    }
    
    list.forEach((item, index) => {
        const div = document.createElement('div');
        div.className = 'scanner-item';
        if (item.code === currentStockCode) {
            div.classList.add('active');
        }
        
        const chgSign = item.pct_change > 0 ? '+' : '';
        const chgClass = item.pct_change > 0 ? 'up-text' : (item.pct_change < 0 ? 'down-text' : '');
        
        // Custom Rank Badge
        let rankBadge = '';
        if (index === 0) rankBadge = '<span class="rank-badge rank-1">1</span>';
        else if (index === 1) rankBadge = '<span class="rank-badge rank-2">2</span>';
        else if (index === 2) rankBadge = '<span class="rank-badge rank-3">3</span>';
        else rankBadge = `<span class="rank-badge rank-normal">${index + 1}</span>`;
        
        div.innerHTML = `
            <div class="scanner-item-row1">
                <span class="scanner-item-name">${rankBadge}${item.name}</span>
                <span class="explosive-score-badge">${item.explosive_score}% 爆发力</span>
            </div>
            <div class="scanner-item-row2" style="margin-bottom: 4px;">
                <span class="scanner-item-code">${item.code}</span>
                <span class="scanner-item-price">${item.price.toFixed(2)}</span>
                <span class="scanner-item-chg ${chgClass}">${chgSign}${item.pct_change.toFixed(2)}%</span>
            </div>
            <div style="font-size: 10px; color: var(--text-secondary); display: flex; justify-content: space-between; border-top: 1px solid rgba(255,255,255,0.03); padding-top: 3px;">
                <span>流通盘: ${item.float_market_cap_billion.toFixed(1)}亿</span>
                <span>量比: ${item.volume_ratio.toFixed(2)}</span>
                <span>换手: ${item.turnover_rate.toFixed(1)}%</span>
            </div>
        `;
        
        div.addEventListener('click', () => {
            currentStockCode = item.code;
            currentStockMarket = item.market;
            currentStockName = item.name;
            
            document.querySelectorAll('.scanner-item').forEach(el => el.classList.remove('active'));
            div.classList.add('active');
            
            loadStockData(currentStockCode, currentStockMarket, currentStockName);
        });
        
        container.appendChild(div);
    });
}

// ----------------- Favorites (自选股) Logic -----------------

// Toggle current loaded stock favorite state
function toggleCurrentFavorite() {
    let favs = JSON.parse(localStorage.getItem('stock_favorites') || '[]');
    const isFav = favs.some(f => f.code === currentStockCode);
    const favBtn = document.getElementById('btn-toggle-favorite');
    const favText = document.getElementById('lbl-fav-text');
    
    if (isFav) {
        // Remove
        favs = favs.filter(f => f.code !== currentStockCode);
        favBtn.classList.remove('favorited');
        favText.innerText = '加自选';
    } else {
        // Add
        favs.push({
            code: currentStockCode,
            market: currentStockMarket,
            name: currentStockName
        });
        favBtn.classList.add('favorited');
        favText.innerText = '已自选';
    }
    
    localStorage.setItem('stock_favorites', JSON.stringify(favs));
    
    // Refresh list if current tab is Favorites tab
    const favsTab = document.getElementById('tab-scan-favorites');
    if (favsTab.classList.contains('active')) {
        loadFavoritesList();
    }
}

// Fetch and render favorites pool
function loadFavoritesList() {
    const container = document.getElementById('favorites-list-container');
    const countLbl = document.getElementById('lbl-fav-count');
    
    const favs = JSON.parse(localStorage.getItem('stock_favorites') || '[]');
    countLbl.innerText = `已添加 ${favs.length} 只`;
    
    if (favs.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; text-align: center; padding: 40px 0;">自选股池为空。您可以在上方搜索个股并点击“加自选”进行添加。</div>';
        return;
    }
    
    container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; text-align: center; padding: 40px 0;">正在更新自选股实时行情...</div>';
    
    // Construct secids parameter (e.g. 1.600519,0.000858)
    const secids = favs.map(f => `${f.market}.${f.code}`).join(',');
    
    fetch(`/api/favorites_quotes?secids=${encodeURIComponent(secids)}`)
        .then(res => {
            if (!res.ok) throw new Error("Favorites quotes fetch failed");
            return res.json();
        })
        .then(data => {
            renderFavoritesListItems(data);
        })
        .catch(err => {
            console.error("Favorites quotes error:", err);
            container.innerHTML = '<div style="color: var(--color-up); font-size: 12px; padding: 20px 0; text-align: center;">更新实时行情失败，请重试。</div>';
        });
}

// Render items in favorites pool list
function renderFavoritesListItems(list) {
    const container = document.getElementById('favorites-list-container');
    container.innerHTML = '';
    
    list.forEach((item, index) => {
        const div = document.createElement('div');
        div.className = 'scanner-item';
        if (item.code === currentStockCode) {
            div.classList.add('active');
        }
        
        const chgSign = item.pct_change > 0 ? '+' : '';
        const chgClass = item.pct_change > 0 ? 'up-text' : (item.pct_change < 0 ? 'down-text' : '');
        
        const rankBadge = `<span class="rank-badge rank-normal">${index + 1}</span>`;
        
        div.innerHTML = `
            <div class="scanner-item-row1">
                <span class="scanner-item-name">${rankBadge}${item.name}</span>
                <!-- Delete Favorite Button -->
                <button class="delete-fav-btn" data-code="${item.code}" style="background: transparent; border: none; color: var(--text-muted); cursor: pointer; font-size: 18px; padding: 0 4px; line-height: 1; outline: none;">&times;</button>
            </div>
            <div class="scanner-item-row2">
                <span class="scanner-item-code">${item.code}</span>
                <span class="scanner-item-price">${item.price.toFixed(2)}</span>
                <span class="scanner-item-chg ${chgClass}">${chgSign}${item.pct_change.toFixed(2)}%</span>
            </div>
        `;
        
        // Click to load stock
        div.addEventListener('click', () => {
            currentStockCode = item.code;
            currentStockMarket = item.market;
            currentStockName = item.name;
            
            document.querySelectorAll('.scanner-item').forEach(el => el.classList.remove('active'));
            div.classList.add('active');
            
            loadStockData(currentStockCode, currentStockMarket, currentStockName);
        });
        
        // Delete button listener (stops propagation)
        const delBtn = div.querySelector('.delete-fav-btn');
        delBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const codeToDelete = delBtn.dataset.code;
            let favs = JSON.parse(localStorage.getItem('stock_favorites') || '[]');
            favs = favs.filter(f => f.code !== codeToDelete);
            localStorage.setItem('stock_favorites', JSON.stringify(favs));
            
            // If the stock we just deleted is the loaded one, update header button state
            if (codeToDelete === currentStockCode) {
                document.getElementById('btn-toggle-favorite').classList.remove('favorited');
                document.getElementById('lbl-fav-text').innerText = '加自选';
            }
            
            // Reload list
            loadFavoritesList();
        });
        
        container.appendChild(div);
    });
}

// ----------------- Position Diagnostics (持仓分析) Logic -----------------

// Calculate P&L, Support/Resistance ranges, and predict next 3-day trend based on user inputs
function runPositionDiagnosis() {
    const priceVal = parseFloat(document.getElementById('input-hold-price').value);
    const sharesVal = parseInt(document.getElementById('input-hold-shares').value);
    const container = document.getElementById('panel-hold-diag-result');

    if (isNaN(priceVal) || isNaN(sharesVal) || priceVal <= 0 || sharesVal <= 0) {
        container.innerHTML = '<div style="color: var(--color-up);">请输入有效的持仓买入价格与持股数量！</div>';
        container.style.display = 'block';
        return;
    }

    // Save user holding stats to localStorage for persistent UX
    localStorage.setItem(`hold_price_${currentStockCode}`, priceVal);
    localStorage.setItem(`hold_shares_${currentStockCode}`, sharesVal);

    // Fetch current price from DOM
    const curPrice = parseFloat(document.getElementById('lbl-stock-price').innerText);
    if (isNaN(curPrice) || curPrice <= 0) {
        container.innerHTML = '<div style="color: var(--text-muted);">正在等待最新行情数据载入...</div>';
        container.style.display = 'block';
        return;
    }

    // Calculations
    const pnl = (curPrice - priceVal) * sharesVal;
    const pnlPct = ((curPrice - priceVal) / priceVal) * 100;

    const pnlSign = pnl >= 0 ? '+' : '';
    const pnlClass = pnl >= 0 ? 'up-text' : 'down-text';

    // Support and Resistance calculation based on MA5, MA20 and current prices
    let lastClose = curPrice;
    if (historicalKlines.length > 0) {
        lastClose = historicalKlines[historicalKlines.length - 1].close;
    }
    const ma5Val = (indicatorsData && indicatorsData.ma5) ? (indicatorsData.ma5[indicatorsData.ma5.length - 1] || lastClose) : lastClose;
    const ma20Val = (indicatorsData && indicatorsData.ma20) ? (indicatorsData.ma20[indicatorsData.ma20.length - 1] || lastClose) : lastClose;

    const support = Math.min(ma5Val, ma20Val, lastClose) * 0.97;
    const resistance = Math.max(ma5Val, ma20Val, lastClose) * 1.05;

    // Trend Forecast from ML model
    let mlProb = 50;
    if (globalPredData && globalPredData.probability !== undefined) {
        mlProb = Math.round(globalPredData.probability * 100);
    }

    let trendVerdict = '';
    let strategyText = '';

    if (mlProb >= 70) {
        trendVerdict = '【强势上攻，加速冲板】';
        strategyText = `当前持仓处于 ${pnl >= 0 ? '浮盈' : '套牢'} 状态。大盘行情向好，该股ML看涨信心极高。建议【坚定持股】，上看阻力位 ${resistance.toFixed(2)} 元。若日内封死涨停可继续锁仓；若跌破5日线建议分批减仓落袋为安。`;
    } else if (mlProb >= 40) {
        trendVerdict = '【主力洗盘，蓄势震荡】';
        strategyText = `当前持仓处于 ${pnl >= 0 ? '浮盈' : '套牢'} 状态。未来三日以主力缩量洗盘、消化浮筹为主。操作策略：建议【持股观望】，强支撑参考 ${support.toFixed(2)} 元，只要支撑不破即可底仓不动，静待缩量整理完毕发起二次拉升。`;
    } else {
        trendVerdict = '【趋势走弱，阴跌考验支撑】';
        strategyText = `当前持仓处于 ${pnl >= 0 ? '浮盈' : '套牢'} 状态。该股面临短线抛压，主力资金派发明显。操作建议：短线【逢高减仓】。若未来三日股价反弹至均线阻力位 ${resistance.toFixed(2)} 元附近无法放量站稳，建议逐步出局以防亏损扩大，下方防守位设在 ${support.toFixed(2)} 元。`;
    }

    container.innerHTML = `
        <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-weight: 700; border-bottom: 1px solid rgba(255,255,255,0.03); padding-bottom: 4px;">
            <span>持仓盈亏诊断</span>
            <span class="${pnlClass}">${pnlSign}${pnl.toFixed(2)}元 (${pnlSign}${pnlPct.toFixed(2)}%)</span>
        </div>
        <div style="margin-bottom: 6px;">
            <span style="font-weight: 700; color: var(--color-warning);">后三日走势预测: </span>
            <span style="font-weight: 800; color: var(--text-primary);">${trendVerdict}</span>
            <span> (上涨概率 ${mlProb}%)</span>
        </div>
        <div style="margin-bottom: 6px;">
            <strong>预计运行区间: </strong>
            <span style="font-family: monospace; font-weight: 600; color: var(--color-accent);">${support.toFixed(2)} 元 - ${resistance.toFixed(2)} 元</span>
        </div>
        <div style="font-size: 10px; color: var(--text-secondary); line-height: 1.4; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 5px; text-align: justify;">
            <strong>持仓应对策略: </strong>${strategyText}
        </div>
    `;
    container.style.display = 'block';
}
