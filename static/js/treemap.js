document.addEventListener('DOMContentLoaded', function() {
    // 1. Django 템플릿에서 JSON 데이터 가져오기
    const heatmapDataElement = document.getElementById('heatmap-data');
    const jsonString = JSON.parse(heatmapDataElement.textContent);
    const heatmapSeriesData = JSON.parse(jsonString);

    if (!heatmapDataElement) {
        console.error("필수 요소(히트맵 데이터 또는 섹터 선택자)를 찾을 수 없습니다.");
        return;
    }
    // --- 1. 데이터 변환 시 필요한 정보 추가 ---
    function transformData(data) {
        const root = {
            name: "S&P 500",
            children: []
        };
        const t = new Map;
        data.forEach(company => {
            let s = t.get(company.Sector);
            if (!s) {
                s = {
                    name: company.Sector,
                    children: [],
                    industryMap: new Map()
                };
                t.set(company.Sector, s);
                root.children.push(s);
            }
            let i = s.industryMap.get(company.Industry);
            if (!i) {
                i = {
                    name: company.Industry,
                    children: []
                };
                s.industryMap.set(company.Industry, i);
                s.children.push(i);
            }
            i.children.push({
                name: company.Symbol,
                value: company["Market Cap"],
                change: company.percent_change,
                fullName: company.Name,
                price: company.Price // 주가 정보 추가
            });
        });
        root.children.forEach(s => delete s.industryMap);
        return root;
    }

    const treemapData = transformData(heatmapSeriesData);
    addNavigationPaths(treemapData);
    processData(treemapData);

    const container = document.getElementById('treemap-container');
    const backBtn = document.getElementById('back-btn');
    const breadcrumb = document.getElementById('breadcrumb');
    const tooltip = document.getElementById('tooltip'); // 툴팁 요소 가져오기
    let navigationPath = [];

    // --- 2. renderNode 함수에 이벤트 리스너 추가 ---
    function renderNode(node, pos, parentElement, depth) {
        const div = document.createElement('div');
        div.className = 'node';
        div.style.left = `${pos.x}px`;
        div.style.top = `${pos.y}px`;
        div.style.width = `${pos.width}px`;
        div.style.height = `${pos.height}px`;
        parentElement.appendChild(div);

        if (node.children) { // 부모 노드 (그룹)
            div.classList.add('parent-node', 'clickable', `level-${depth}`);
            if (pos.width > 50 && pos.height > 20) {
                div.dataset.label = node.name.toUpperCase();
            }
            div.addEventListener('click', e => {
                e.stopPropagation();
                navigationPath = [...node.path]; 
                drawCurrentTreemap();
            });
            treemap(node.children, {
                x: 0,
                y: 0,
                width: pos.width,
                height: pos.height
            }, div, depth + 1);
        } else { // 최종 자식 노드 (기업)
            div.classList.add('leaf-node'); // 호버 효과를 위한 클래스
            div.style.backgroundColor = getColor(node.change);
            if (pos.width > 35 && pos.height > 25) {
                const fontSize = Math.max(0.6, Math.min(1.5, Math.sqrt(pos.width * pos.height) / 50));
                div.innerHTML = `<span class="node-label" style="font-size: ${fontSize}em">${node.name}</span><span class="node-value" style="font-size: ${fontSize * 0.7}em">${node.change > 0 ? '+' : ''}${node.change.toFixed(2)}%</span>`;
            }

            // 마우스 이벤트 리스너 추가
            div.addEventListener('mouseover', () => showTooltip(node));
            div.addEventListener('mousemove', moveTooltip);
            div.addEventListener('mouseout', hideTooltip);
        }
    }

    // --- 3. 툴팁 관련 함수들 ---
    function showTooltip(node) {
        const marketCap = (node.value / 1_000_000_000).toFixed(2) + 'B'; // 십억 단위로 변환
        const changeColor = node.change >= 0 ? '#4CAF50' : '#F44336';

        tooltip.innerHTML = `
            <div id="tooltip-name">${node.fullName} (${node.name})</div>
            <div class="tooltip-row"><span>Market Cap</span>: <b>${marketCap}</b></div>
            <div class="tooltip-row"><span>Price</span>: <b>$${node.price.toFixed(2)}</b></div>
            <div class="tooltip-row"><span>Change</span>: <b style="color:${changeColor}">${node.change.toFixed(2)}%</b></div>
        `;
        tooltip.style.display = 'block';
    }

    function moveTooltip(event) {
        // 툴팁이 화면 밖으로 나가지 않도록 위치 조정
        const tooltipRect = tooltip.getBoundingClientRect();
        let x = event.clientX + 15;
        let y = event.clientY + 15;

        if (x + tooltipRect.width > window.innerWidth) {
            x = event.clientX - tooltipRect.width - 15;
        }
        if (y + tooltipRect.height > window.innerHeight) {
            y = event.clientY - tooltipRect.height - 15;
        }

        tooltip.style.left = `${x}px`;
        tooltip.style.top = `${y}px`;
    }

    function hideTooltip() {
        tooltip.style.display = 'none';
    }

    // (나머지 코드는 모두 동일)
    function drawCurrentTreemap() {
        const t = navigationPath[navigationPath.length - 1];
        if (container.innerHTML = "", updateBreadcrumb(), !t.children) return;
        const e = container.getBoundingClientRect(),
            n = navigationPath.length - 1;
        treemap(t.children, {
            x: 0,
            y: 0,
            width: e.width,
            height: e.height
        }, container, n)
    }
    const resizeObserver = new ResizeObserver(() => {
        if (window.resizeTimeout) clearTimeout(window.resizeTimeout);
        window.resizeTimeout = setTimeout(drawCurrentTreemap, 100)
    });
    resizeObserver.observe(container);

    function addNavigationPaths(t, e = []) {
        if (t.path = [...e, t], t.children) t.children.forEach(n => addNavigationPaths(n, t.path))
    }

    function processData(node) {
        if (node.children) {
            node.value = node.children.reduce((sum, child) => sum + processData(child), 0);
        }
        return node.value;
    }

    function updateBreadcrumb() {
        breadcrumb.textContent = navigationPath.map(node => node.name).join(' > ');
        backBtn.style.display = navigationPath.length > 1 ? 'block' : 'none';
    }
    backBtn.addEventListener('click', () => {
        if (navigationPath.length > 1) {
            navigationPath.pop();
            drawCurrentTreemap();
        }
    });

    function getColor(change) {
        const t = 10,
            e = Math.max(-1, Math.min(1, change / t)),
            o = [211, 47, 47],
            a = [95, 95, 95],
            n = [56, 142, 60];
        let r, d, c;
        if (e < 0) {
            const t = Math.abs(e);
            r = Math.round(a[0] + (o[0] - a[0]) * t), d = Math.round(a[1] + (o[1] - a[1]) * t), c = Math.round(a[2] + (o[2] - a[2]) * t)
        } else r = Math.round(a[0] + (n[0] - a[0]) * e), d = Math.round(a[1] + (n[1] - a[1]) * e), c = Math.round(a[2] + (n[2] - a[2]) * e);
        return `rgb(${r}, ${d}, ${c})`
    }

    function treemap(data, box, parentElement, depth) {
        if (!data || data.length === 0) return;
        const totalValue = data.reduce((sum, node) => sum + node.value, 0);
        const nodes = data.slice().sort((a, b) => b.value - a.value);
        squarify(nodes, box, totalValue, parentElement, depth);
    }

    function squarify(nodes, box, totalValue, parentElement, depth) {
        if (nodes.length === 0) return;
        if (nodes.length === 1) {
            renderNode(nodes[0], box, parentElement, depth);
            return;
        }
        let i = 1;
        while (i < nodes.length) {
            const row = nodes.slice(0, i);
            const nextRow = nodes.slice(0, i + 1);
            if (getWorstAspectRatio(nextRow, box, totalValue) > getWorstAspectRatio(row, box, totalValue)) break;
            i++;
        }
        const currentRow = nodes.slice(0, i);
        const remainingNodes = nodes.slice(i);
        const currentRowValue = currentRow.reduce((sum, n) => sum + n.value, 0);
        const {
            newBox,
            remainingBox
        } = layoutRow(currentRow, currentRowValue, box, totalValue);
        layoutNodesInBox(currentRow, newBox, parentElement, depth);
        squarify(remainingNodes, remainingBox, totalValue - currentRowValue, parentElement, depth);
    }

    function layoutNodesInBox(nodes, box, parentElement, depth) {
        const totalValue = nodes.reduce((s, n) => s + n.value, 0);
        const isHorizontal = box.width >= box.height;
        let offset = 0;
        nodes.forEach(node => {
            const proportion = node.value / totalValue;
            if (isHorizontal) {
                const nodeWidth = proportion * box.width;
                renderNode(node, {
                    x: box.x + offset,
                    y: box.y,
                    width: nodeWidth,
                    height: box.height
                }, parentElement, depth);
                offset += nodeWidth;
            } else {
                const nodeHeight = proportion * box.height;
                renderNode(node, {
                    x: box.x,
                    y: box.y + offset,
                    width: box.width,
                    height: nodeHeight
                }, parentElement, depth);
                offset += nodeHeight;
            }
        });
    }

    function layoutRow(r, v, b, t) {
        const i = b.width >= b.height,
            a = (v / t) * (b.width * b.height);
        if (i) {
            const h = a / b.width;
            return {
                newBox: {
                    x: b.x,
                    y: b.y,
                    width: b.width,
                    height: h
                },
                remainingBox: {
                    x: b.x,
                    y: b.y + h,
                    width: b.width,
                    height: b.height - h
                }
            }
        } else {
            const w = a / b.height;
            return {
                newBox: {
                    x: b.x,
                    y: b.y,
                    width: w,
                    height: b.height
                },
                remainingBox: {
                    x: b.x + w,
                    y: b.y,
                    width: b.width - w,
                    height: b.height
                }
            }
        }
    }

    function getWorstAspectRatio(r, b, t) {
        if (r.length === 0) return Infinity;
        const v = r.reduce((s, c) => s + c.value, 0),
            a = (v / t) * (b.width * b.height),
            i = b.width >= b.height,
            s = i ? b.width : b.height,
            l = a / s;
        let m = 0;
        r.forEach(c => {
            const n = (c.value / v) * a,
                o = Math.max(l / (n / l), (n / l) / l);
            if (o > m) m = o
        });
        return m
    }

    navigationPath = [treemapData];
    drawCurrentTreemap();
});