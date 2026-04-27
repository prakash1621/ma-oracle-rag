document.addEventListener('DOMContentLoaded', () => {
    // API base URL — empty for same-origin (local dev), set for cross-origin (Vercel→Railway)
    const API_URL = window.__API_URL__ || '';

    // Auth check — redirect to login if no token
    const token = localStorage.getItem('access_token');
    if (!token) {
        window.location.href = '/';
        return;
    }

    // Auth headers for all API calls
    const authHeaders = () => ({
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
    });

    // Handle 401 — try refresh, else redirect to login
    async function handleUnauthorized() {
        const refreshToken = localStorage.getItem('refresh_token');
        if (!refreshToken) { logout(); return false; }
        try {
            const res = await fetch(`${API_URL}/api/auth/refresh`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: refreshToken }),
            });
            if (!res.ok) { logout(); return false; }
            const data = await res.json();
            localStorage.setItem('access_token', data.access_token);
            return true;
        } catch { logout(); return false; }
    }

    function logout() {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user_role');
        window.location.href = '/';
    }

    const input = document.getElementById('query-input');
    const searchBtn = document.getElementById('search-btn');
    const tryBtn = document.getElementById('try-btn');
    const btnText = document.getElementById('btn-text');
    const btnLoader = document.getElementById('btn-loader');

    const resultsSection = document.getElementById('results-section');
    const routeBadge = document.getElementById('route-badge');
    const confidenceText = document.getElementById('confidence-text');
    const answerText = document.getElementById('answer-text');
    const sqlCard = document.getElementById('sql-card');
    const sqlOutput = document.getElementById('sql-output');
    const tableCard = document.getElementById('table-card');
    const tableHead = document.getElementById('table-head');
    const tableBody = document.getElementById('table-body');
    const citationsCard = document.getElementById('citations-card');
    const citationsList = document.getElementById('citations-list');
    const errorContainer = document.getElementById('error-container');

    const EXAMPLES = [
        "What was Apple's revenue in 2024?",
        "Show me the top 5 companies by total assets",
        "What are the risk factors for Tesla?",
        "Who are Apple's board members?",
        "Does Apple management contradict their filings?",
        "Compare net income for Microsoft and Alphabet in 2024",
        "How many patents does NVIDIA have?",
        "What did the CEO say about growth in the earnings call?",
        "Show me TSLA competitors",
    ];

    // Health check
    const checkHealth = async () => {
        try {
            const res = await fetch(`${API_URL}/health`, { headers: authHeaders() });
            const data = await res.json();
            const indicator = document.querySelector('.pulse');
            const statusText = document.getElementById('health-text');
            if (data.status === 'ok') {
                indicator.classList.add('online');
                statusText.innerText = `Connected (${data.agent_memory_items} Memory Intents)`;
            } else {
                statusText.innerText = 'System degraded';
                indicator.style.backgroundColor = 'var(--error)';
            }
        } catch (e) {
            document.getElementById('health-text').innerText = 'System Offline';
            document.querySelector('.pulse').style.backgroundColor = 'var(--error)';
        }
    };
    checkHealth();

    // Example button
    tryBtn.addEventListener('click', () => {
        input.value = EXAMPLES[Math.floor(Math.random() * EXAMPLES.length)];
    });

    // Simple markdown to HTML
    function renderMarkdown(text) {
        return text
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/^\d+\.\s+/gm, match => `<br>${match}`)
            .replace(/^- /gm, '<br>• ')
            .replace(/\n/g, '<br>')
            .replace(/^<br>/, '');
    }

    // Unified query — hits POST /ask
    const executeQuery = async () => {
        const query = input.value.trim();
        if (!query) return;

        btnText.classList.add('hidden');
        btnLoader.classList.remove('hidden');
        searchBtn.disabled = true;
        errorContainer.classList.add('hidden');
        resultsSection.classList.add('hidden');

        try {
            const res = await fetch(`${API_URL}/ask`, {
                method: 'POST',
                headers: authHeaders(),
                body: JSON.stringify({ question: query, filters: {} })
            });
            if (res.status === 401) {
                const refreshed = await handleUnauthorized();
                if (!refreshed) return;
                // Retry with new token
                const retry = await fetch(`${API_URL}/ask`, {
                    method: 'POST',
                    headers: authHeaders(),
                    body: JSON.stringify({ question: query, filters: {} })
                });
                if (!retry.ok) throw new Error('API Error');
                var data = await retry.json();
            } else {
                if (!res.ok) throw new Error('API Error - Failed to process query.');
                var data = await res.json();
            }

            // Route and confidence
            routeBadge.textContent = data.route || 'unknown';
            confidenceText.textContent = `Confidence: ${Math.round((data.confidence || 0) * 100)}%`;

            // Answer
            answerText.innerHTML = renderMarkdown(data.answer || 'No answer generated.');

            // SQL card (only for xbrl_financial route)
            if (data.sql_query) {
                sqlOutput.textContent = data.sql_query;
                sqlCard.classList.remove('hidden');
            } else {
                sqlCard.classList.add('hidden');
            }

            // Table (only when rows exist)
            if (data.rows && data.rows.length > 0 && data.columns) {
                tableHead.innerHTML = `<tr>${data.columns.map(col => `<th>${col}</th>`).join('')}</tr>`;
                tableBody.innerHTML = data.rows.map(row =>
                    `<tr>${row.map(cell => `<td>${cell !== null ? cell : '-'}</td>`).join('')}</tr>`
                ).join('');
                tableCard.classList.remove('hidden');
            } else {
                tableCard.classList.add('hidden');
            }

            // Citations
            if (data.citations && data.citations.length > 0) {
                citationsList.innerHTML = data.citations.map(c =>
                    `<div class="citation-item">
                        <div>${c.source_text || 'No source text'}</div>
                        <div class="citation-meta">${c.company_name} · ${c.filing_type} · ${c.filing_date}</div>
                    </div>`
                ).join('');
                citationsCard.classList.remove('hidden');
            } else {
                citationsCard.classList.add('hidden');
            }

            resultsSection.classList.remove('hidden');
        } catch (e) {
            errorContainer.textContent = e.message || 'An unexpected error occurred.';
            errorContainer.classList.remove('hidden');
        } finally {
            btnText.classList.remove('hidden');
            btnLoader.classList.add('hidden');
            searchBtn.disabled = false;
        }
    };

    searchBtn.addEventListener('click', executeQuery);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') executeQuery();
    });
});
