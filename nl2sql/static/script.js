document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('query-input');
    const searchBtn = document.getElementById('search-btn');
    const tryBtn = document.getElementById('try-btn');
    const btnText = document.getElementById('btn-text');
    const btnLoader = document.getElementById('btn-loader');

    const resultsSection = document.getElementById('results-section');
    const sqlOutput = document.getElementById('sql-output');
    const assistantMessage = document.getElementById('assistant-message');
    const tableCard = document.getElementById('table-card');
    const tableHead = document.getElementById('table-head');
    const tableBody = document.getElementById('table-body');
    const errorContainer = document.getElementById('error-container');

    const ragResultsSection = document.getElementById('rag-results-section');
    const ragRouteBadge = document.getElementById('rag-route-badge');
    const ragConfidence = document.getElementById('rag-confidence');
    const ragAnswer = document.getElementById('rag-answer');
    const ragCitationsCard = document.getElementById('rag-citations-card');
    const ragCitationsList = document.getElementById('rag-citations-list');

    const modeSql = document.getElementById('mode-sql');
    const modeRag = document.getElementById('mode-rag');

    let currentMode = 'sql';

    const SQL_EXAMPLES = [
        "Show me the top 5 companies by total assets",
        "Show Microsoft's annual net income over the last 5 fiscal years",
        "Compare accounts receivable for Amazon and Alphabet in fiscal year 2025 quarter 1",
        "Which companies have the most balance sheet rows in the database?"
    ];

    const RAG_EXAMPLES = [
        "What was Apple's revenue in 2024?",
        "What are the risk factors for Tesla?",
        "Who are Apple's board members?",
        "Does Apple management contradict their filings?",
        "How many patents does NVIDIA have?",
        "What did the CEO say about growth in the earnings call?"
    ];

    // Mode toggle
    modeSql.addEventListener('click', () => {
        currentMode = 'sql';
        modeSql.classList.add('active');
        modeRag.classList.remove('active');
        btnText.textContent = 'Generate SQL';
        input.placeholder = 'e.g., Show me the top 5 companies by total assets in 2024...';
        resultsSection.classList.add('hidden');
        ragResultsSection.classList.add('hidden');
        errorContainer.classList.add('hidden');
    });

    modeRag.addEventListener('click', () => {
        currentMode = 'rag';
        modeRag.classList.add('active');
        modeSql.classList.remove('active');
        btnText.textContent = 'Ask RAG';
        input.placeholder = 'e.g., What are the risk factors for Tesla?';
        resultsSection.classList.add('hidden');
        ragResultsSection.classList.add('hidden');
        errorContainer.classList.add('hidden');
    });

    // Health check
    const checkHealth = async () => {
        try {
            const res = await fetch('/health');
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
        const examples = currentMode === 'sql' ? SQL_EXAMPLES : RAG_EXAMPLES;
        input.value = examples[Math.floor(Math.random() * examples.length)];
    });

    // Execute query
    const executeQuery = async () => {
        const query = input.value.trim();
        if (!query) return;

        btnText.classList.add('hidden');
        btnLoader.classList.remove('hidden');
        searchBtn.disabled = true;
        errorContainer.classList.add('hidden');
        resultsSection.classList.add('hidden');
        ragResultsSection.classList.add('hidden');

        try {
            if (currentMode === 'sql') {
                await executeSqlQuery(query);
            } else {
                await executeRagQuery(query);
            }
        } catch (e) {
            errorContainer.textContent = e.message || 'An unexpected error occurred.';
            errorContainer.classList.remove('hidden');
        } finally {
            btnText.classList.remove('hidden');
            btnLoader.classList.add('hidden');
            searchBtn.disabled = false;
        }
    };

    // SQL mode — hits POST /chat
    async function executeSqlQuery(query) {
        const res = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: query })
        });
        if (!res.ok) throw new Error('API Error - Failed to parse request.');
        const data = await res.json();

        sqlOutput.textContent = data.sql_query || '-- No SQL generated';
        assistantMessage.textContent = data.message;

        if (data.rows && data.rows.length > 0) {
            tableHead.innerHTML = `<tr>${data.columns.map(col => `<th>${col}</th>`).join('')}</tr>`;
            tableBody.innerHTML = data.rows.map(row =>
                `<tr>${row.map(cell => `<td>${cell !== null ? cell : '-'}</td>`).join('')}</tr>`
            ).join('');
            tableCard.classList.remove('hidden');
        } else {
            tableCard.classList.add('hidden');
        }
        resultsSection.classList.remove('hidden');
    }

    // RAG mode — hits POST /query
    async function executeRagQuery(query) {
        const res = await fetch('/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: query, filters: {} })
        });
        if (!res.ok) throw new Error('RAG API Error - Failed to process query.');
        const data = await res.json();

        ragRouteBadge.textContent = data.route || 'unknown';
        ragConfidence.textContent = `Confidence: ${Math.round((data.confidence || 0) * 100)}%`;
        ragAnswer.textContent = data.answer || 'No answer generated.';

        if (data.citations && data.citations.length > 0) {
            ragCitationsList.innerHTML = data.citations.map(c =>
                `<div class="citation-item">
                    <div>${c.source_text || 'No source text'}</div>
                    <div class="citation-meta">${c.company_name} · ${c.filing_type} · ${c.filing_date}</div>
                </div>`
            ).join('');
            ragCitationsCard.classList.remove('hidden');
        } else {
            ragCitationsCard.classList.add('hidden');
        }
        ragResultsSection.classList.remove('hidden');
    }

    searchBtn.addEventListener('click', executeQuery);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') executeQuery();
    });
});
