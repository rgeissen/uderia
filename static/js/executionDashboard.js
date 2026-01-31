/**
 * Execution Dashboard Controller
 * Manages the three-tier execution insights dashboard
 */

class ExecutionDashboard {
    constructor() {
        this.currentSessionId = null;
        this.sessionsData = [];
        this.analyticsData = null;
        this.velocityChart = null;
        this.viewAllSessions = false;
        this.hasViewAllSessionsFeature = false;
        this.refreshInterval = null;
        this.autoRefreshEnabled = true;
        this.refreshIntervalMs = 60000; // 60 seconds (reduced from 30 to minimize server load)
        this.currentPerformanceView = 'my'; // 'my' or 'system'
        this.isAdmin = false;
        this.showUtilitySessions = true; // Default to showing utility sessions
    }

    /**
     * Get headers for API requests including User UUID and Auth token
     */
    _getHeaders() {
        const headers = {
            'Content-Type': 'application/json'
        };
        
        // Add authentication token if available
        const authToken = localStorage.getItem('tda_auth_token');
        if (authToken) {
            headers['Authorization'] = `Bearer ${authToken}`;
        }
        
        // Authentication is handled via JWT tokens only
        
        return headers;
    }

    /**
     * Initialize the dashboard
     */
    async initialize() {
        // Check if user has VIEW_ALL_SESSIONS feature
        await this.checkViewAllSessionsFeature();
        
        // Load saved utility sessions filter preference
        const savedUtilityPref = localStorage.getItem('showUtilitySessions');
        if (savedUtilityPref !== null) {
            this.showUtilitySessions = savedUtilityPref === 'true';
        }
        
        // Set up event listeners
        this.setupEventListeners();
        
        // Load initial data
        await this.refreshDashboard();
        
        // Start auto-refresh
        this.startAutoRefresh();
    }
    
    /**
     * Start auto-refresh interval
     */
    startAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
        
        if (this.autoRefreshEnabled) {
            this.refreshInterval = setInterval(() => {
                console.log('[ExecutionDashboard] Auto-refreshing...');
                this.refreshDashboard();
            }, this.refreshIntervalMs);
        }
    }
    
    /**
     * Stop auto-refresh interval
     */
    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }

    /**
     * Set up all event listeners
     */
    setupEventListeners() {
        // Refresh button
        document.getElementById('refresh-dashboard-btn')?.addEventListener('click', () => {
            this.refreshDashboard();
        });

        // Auto-refresh toggle
        const autoRefreshToggle = document.getElementById('execution-auto-refresh-toggle');
        if (autoRefreshToggle) {
            // Load saved preference
            const savedAutoRefresh = localStorage.getItem('executionAutoRefresh');
            if (savedAutoRefresh !== null) {
                this.autoRefreshEnabled = savedAutoRefresh === 'true';
                autoRefreshToggle.checked = this.autoRefreshEnabled;
            } else {
                // Default is true (as per constructor)
                autoRefreshToggle.checked = this.autoRefreshEnabled;
            }

            autoRefreshToggle.addEventListener('change', (e) => {
                this.autoRefreshEnabled = e.target.checked;
                localStorage.setItem('executionAutoRefresh', this.autoRefreshEnabled.toString());

                if (this.autoRefreshEnabled) {
                    console.log('[ExecutionDashboard] Auto-refresh enabled');
                    this.startAutoRefresh();
                    window.showNotification?.('Auto-refresh enabled', 'success');
                } else {
                    console.log('[ExecutionDashboard] Auto-refresh disabled');
                    this.stopAutoRefresh();
                    window.showNotification?.('Auto-refresh disabled', 'info');
                }
            });
        }

        // View all sessions toggle (only for users with feature)
        const viewAllToggle = document.getElementById('view-all-sessions-toggle');
        if (viewAllToggle) {
            viewAllToggle.addEventListener('change', (e) => {
                console.log('[ExecutionDashboard] Toggle changed to:', e.target.checked);
                this.viewAllSessions = e.target.checked;
                this.refreshDashboard();
            });
        }

        // Search input
        const searchInput = document.getElementById('session-search');
        const clearSearchBtn = document.getElementById('clear-search-btn');
        
        if (searchInput) {
            
            // Show/hide clear button based on input content
            const updateClearButton = () => {
                if (clearSearchBtn) {
                    clearSearchBtn.classList.toggle('hidden', !searchInput.value);
                }
            };
            
            searchInput.addEventListener('input', (e) => {
                updateClearButton();
                this.filterAndRenderSessions();
            });
            
            // Clear search when clicking the X button
            if (clearSearchBtn) {
                clearSearchBtn.addEventListener('click', () => {
                    searchInput.value = '';
                    updateClearButton();
                    this.filterAndRenderSessions();
                    searchInput.focus();
                });
            }
            
            // Track if the search was set programmatically (from clicking a question)
            searchInput.addEventListener('focus', () => {
                // If search box has content and user clicks to edit, select all text for easy replacement
                if (searchInput.value) {
                    searchInput.select();
                }
            });
            
            updateClearButton();
        } else {
            console.error('[DEBUG] Search input element not found during setup');
        }

        // Filter and sort controls
        document.getElementById('session-filter-status')?.addEventListener('change', () => {
            this.filterAndRenderSessions();
        });

        document.getElementById('session-sort')?.addEventListener('change', () => {
            this.filterAndRenderSessions();
        });
        
        // Show utility sessions toggle
        const showUtilityToggle = document.getElementById('show-utility-sessions-toggle');
        if (showUtilityToggle) {
            // Set initial state from preference
            showUtilityToggle.checked = this.showUtilitySessions;
            
            showUtilityToggle.addEventListener('change', (e) => {
                this.showUtilitySessions = e.target.checked;
                localStorage.setItem('showUtilitySessions', e.target.checked);
                this.filterAndRenderSessions();
            });
        }

        // Inspector close button
        document.getElementById('close-inspector-btn')?.addEventListener('click', () => {
            this.closeInspector();
        });

        // Export buttons
        document.getElementById('export-json-btn')?.addEventListener('click', () => {
            this.exportSessionAsJSON();
        });

        document.getElementById('export-report-btn')?.addEventListener('click', () => {
            this.exportSessionAsReport();
        });
    }

    /**
     * Refresh all dashboard data (used on initial load and when sessions toggle changes)
     * Always fetches analytics based on current tab view AND sessions based on viewAllSessions toggle
     */
    async refreshDashboard() {
        
        try {
            // Show loading state
            this.showLoadingState();
            
            // Load analytics and sessions in parallel
            const headers = this._getHeaders();
            
            // Determine which consumption endpoint to use based on current tab view
            const consumptionUrl = (this.currentPerformanceView === 'system' && this.isAdmin)
                ? '/api/v1/consumption/system-summary'
                : '/api/v1/consumption/summary';
            
            // Build sessions URL - only controlled by viewAllSessions toggle
            const sessionsUrl = this.viewAllSessions
                ? '/api/v1/sessions?limit=100&all_users=true'
                : '/api/v1/sessions?limit=100';
            
            console.log('[ExecutionDashboard] Refreshing full dashboard');
            console.log('[ExecutionDashboard] Current view:', this.currentPerformanceView);
            console.log('[ExecutionDashboard] Fetching consumption from:', consumptionUrl);
            console.log('[ExecutionDashboard] Fetching sessions from:', sessionsUrl);
            
            // Fetch consumption metrics (fast DB query with velocity and model distribution) and sessions list
            const [consumptionResponse, sessionsResponse] = await Promise.all([
                fetch(consumptionUrl, { method: 'GET', headers: headers }),
                fetch(sessionsUrl, { method: 'GET', headers: headers })
            ]);

            if (!consumptionResponse.ok || !sessionsResponse.ok) {
                console.error('[ExecutionDashboard] API error - consumption:', consumptionResponse.status, 'sessions:', sessionsResponse.status);
                throw new Error('Failed to fetch dashboard data');
            }

            // Use consumption data directly (includes velocity_data and model_distribution from DB)
            this.analyticsData = await consumptionResponse.json();
            const sessionsData = await sessionsResponse.json();
            console.log('[ExecutionDashboard] Raw sessions response:', sessionsData);
            
            this.sessionsData = Array.isArray(sessionsData) ? sessionsData : (sessionsData.sessions || []);
            console.log('[ExecutionDashboard] Processed sessions count:', this.sessionsData.length);

            // Render all sections
            this.renderAnalytics();
            this.filterAndRenderSessions();

        } catch (error) {
            console.error('Error refreshing dashboard:', error);
            this.showErrorState(error.message);
        }
    }

    /**
     * Render analytics section (Tier 1)
     */
    renderAnalytics() {
        if (!this.analyticsData) return;

        const data = this.analyticsData;

        // Update scope indicator with user count (consistent with Intelligence Performance)
        const scopeIndicator = document.getElementById('execution-scope-indicator');
        if (scopeIndicator) {
            if (this.currentPerformanceView === 'system') {
                const userCount = data.total_users || data.active_users || '';
                scopeIndicator.textContent = userCount
                    ? `System-Wide Performance (${userCount} Users)`
                    : 'System-Wide Performance (All Users)';
            } else {
                scopeIndicator.textContent = 'Your Learning Performance';
            }
        }

        // Update metric cards
        document.getElementById('metric-total-sessions').textContent = (data.total_sessions || 0).toLocaleString();
        document.getElementById('metric-total-tokens').textContent = (data.total_tokens || 0).toLocaleString();
        document.getElementById('metric-input-tokens').textContent = (data.total_input_tokens || 0).toLocaleString();
        document.getElementById('metric-output-tokens').textContent = (data.total_output_tokens || 0).toLocaleString();
        document.getElementById('metric-success-rate').textContent = `${data.success_rate_percent || 0}%`;
        document.getElementById('metric-estimated-cost').textContent = `$${(data.estimated_cost_usd || 0).toFixed(2)}`;

        // Render velocity sparkline
        this.renderVelocitySparkline(data.velocity_data);

        // Render model distribution
        this.renderModelDistribution(data.model_distribution);

        // Render top expensive queries and questions
        this.renderTopExpensiveQueries(data.top_expensive_queries);
        this.renderTopExpensiveQuestions(data.top_expensive_questions);
    }

    /**
     * Render velocity sparkline chart
     */
    renderVelocitySparkline(velocityData) {
        const canvas = document.getElementById('velocity-sparkline');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const width = canvas.offsetWidth;
        const height = 32;
        canvas.width = width;
        canvas.height = height;

        if (!velocityData || velocityData.length === 0) {
            // Draw empty state
            ctx.fillStyle = '#374151';
            ctx.fillText('No velocity data', width / 2 - 40, height / 2);
            return;
        }

        // Extract counts
        const counts = velocityData.map(d => d.count);
        const maxCount = Math.max(...counts, 1);

        // Draw sparkline
        ctx.clearRect(0, 0, width, height);
        ctx.beginPath();
        ctx.strokeStyle = '#f97316'; // Orange
        ctx.lineWidth = 2;

        const stepX = width / (counts.length - 1 || 1);
        counts.forEach((count, i) => {
            const x = i * stepX;
            const y = height - (count / maxCount) * height * 0.8;
            
            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });

        ctx.stroke();

        // Fill area under line
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        ctx.closePath();
        ctx.fillStyle = 'rgba(249, 115, 22, 0.2)';
        ctx.fill();
    }

    /**
     * Render model distribution bars
     */
    renderModelDistribution(modelDist) {
        const container = document.getElementById('model-distribution-list');
        if (!container) return;

        if (!modelDist || Object.keys(modelDist).length === 0) {
            container.innerHTML = '<p class="text-gray-400 text-sm">No model data available</p>';
            return;
        }

        const html = Object.entries(modelDist)
            .sort((a, b) => b[1] - a[1])
            .map(([model, percentage]) => `
                <div class="flex items-center gap-2">
                    <div class="flex-1 flex items-center gap-2 min-w-0">
                        <span class="text-sm text-white truncate max-w-[200px]" title="${model}">${model}</span>
                        <div class="flex-1 h-2 bg-white/10 rounded-full overflow-hidden min-w-[40px]">
                            <div class="h-full bg-teradata-orange rounded-full" style="width: ${percentage}%"></div>
                        </div>
                    </div>
                    <span class="text-sm text-gray-400 w-12 text-right flex-shrink-0">${percentage}%</span>
                </div>
            `).join('');

        container.innerHTML = html;
    }

    /**
     * Render top efficiency champions
     */
    renderTopExpensiveQueries(sessions) {
        const container = document.getElementById('top-expensive-queries-list');
        if (!container) return;

        if (!sessions || sessions.length === 0) {
            container.innerHTML = '<p class="text-gray-400 text-sm">No session data available</p>';
            return;
        }

        const html = sessions.map((session, index) => `
            <div class="expensive-session-item flex items-center gap-3 p-2 rounded-lg transition-colors cursor-pointer" 
                 style="background-color: var(--card-bg);" 
                 onmouseover="this.style.backgroundColor='var(--hover-bg)'" 
                 onmouseout="this.style.backgroundColor='var(--card-bg)'" 
                 data-session-id="${session.session_id}">
                <div class="flex-shrink-0 w-6 h-6 bg-red-500/20 rounded-full flex items-center justify-center">
                    <span class="text-xs font-bold text-red-400">${index + 1}</span>
                </div>
                <div class="flex-1 min-w-0">
                    <p class="text-sm text-white truncate" title="${session.name}">${session.name}</p>
                    <p class="text-xs text-gray-500">ID: ${session.session_id}</p>
                </div>
                <div class="flex-shrink-0 text-xs font-semibold text-red-400">${session.tokens.toLocaleString()}</div>
            </div>
        `).join('');

        container.innerHTML = html;
        
        // Add click event listeners
        container.querySelectorAll('.expensive-session-item').forEach(item => {
            item.addEventListener('click', () => {
                const sessionId = item.getAttribute('data-session-id');
                this.highlightSession(sessionId);
            });
        });
    }

    /**
     * Render top expensive questions
     */
    renderTopExpensiveQuestions(questions) {
        const container = document.getElementById('top-expensive-questions-list');
        if (!container) return;

        if (!questions || questions.length === 0) {
            container.innerHTML = '<p class="text-gray-400 text-sm">No question data available</p>';
            return;
        }

        const html = questions.map((question, index) => `
            <div class="expensive-question-item flex items-center gap-3 p-2 rounded-lg transition-colors cursor-pointer" 
                 style="background-color: var(--card-bg);" 
                 onmouseover="this.style.backgroundColor='var(--hover-bg)'" 
                 onmouseout="this.style.backgroundColor='var(--card-bg)'" 
                 data-question-text="${question.query.replace(/"/g, '&quot;')}"
                 data-session-id="${question.session_id}">
                <div class="flex-shrink-0 w-6 h-6 bg-orange-500/20 rounded-full flex items-center justify-center">
                    <span class="text-xs font-bold text-orange-400">${index + 1}</span>
                </div>
                <div class="flex-1 min-w-0">
                    <p class="text-sm text-white truncate" title="${question.query}">${question.query}</p>
                    <p class="text-xs text-gray-500">Session: ${question.session_id}</p>
                </div>
                <div class="flex-shrink-0 text-xs font-semibold text-orange-400">${question.tokens.toLocaleString()}</div>
            </div>
        `).join('');

        container.innerHTML = html;

        // Add click event listeners to navigate to session
        container.querySelectorAll('.expensive-question-item').forEach(item => {
            item.addEventListener('click', () => {
                const sessionId = item.getAttribute('data-session-id');
                this.highlightSession(sessionId);
            });
        });
    }

    /**
     * Filter and render session cards (Tier 2)
     */
    filterAndRenderSessions() {
        const searchQuery = document.getElementById('session-search')?.value.toLowerCase() || '';
        const filterStatus = document.getElementById('session-filter-status')?.value || 'all';
        const sortBy = document.getElementById('session-sort')?.value || 'recent';

        // Check if there are any utility sessions and show/hide toggle accordingly
        const hasUtilitySessions = this.sessionsData.some(s => s.is_temporary);
        const utilityToggleContainer = document.getElementById('show-utility-sessions-container');
        if (utilityToggleContainer) {
            if (hasUtilitySessions) {
                utilityToggleContainer.classList.remove('hidden');
            } else {
                utilityToggleContainer.classList.add('hidden');
            }
        }

        // Filter sessions - search in both session name and questions within the session
        let filteredSessions = this.sessionsData.filter(session => {
            const matchesSessionName = session.name.toLowerCase().includes(searchQuery);
            
            // Also search in questions within this session
            let matchesQuestion = false;
            if (session.last_turn_data?.workflow_history) {
                matchesQuestion = session.last_turn_data.workflow_history.some(turn => 
                    turn.user_query?.toLowerCase().includes(searchQuery)
                );
            }
            
            // Debug: Log first session structure to understand data
            if (session === this.sessionsData[0] && searchQuery) {
            }
            
            const matchesSearch = matchesSessionName || matchesQuestion;
            const matchesStatus = filterStatus === 'all' || session.status === filterStatus;
            const matchesUtilityFilter = this.showUtilitySessions || !session.is_temporary;
            
            return matchesSearch && matchesStatus && matchesUtilityFilter;
        });


        // Sort sessions
        filteredSessions.sort((a, b) => {
            switch (sortBy) {
                case 'recent':
                    return (b.last_updated || '').localeCompare(a.last_updated || '');
                case 'oldest':
                    return (a.created_at || '').localeCompare(b.created_at || '');
                case 'tokens':
                    return b.total_tokens - a.total_tokens;
                case 'turns':
                    return b.turn_count - a.turn_count;
                default:
                    return 0;
            }
        });

        // Render session cards
        this.renderSessionCards(filteredSessions);
    }

    /**
     * Highlight a specific session by ID (supports partial IDs)
     */
    highlightSession(sessionId) {
        // Clear search box to show all sessions
        const searchInput = document.getElementById('session-search');
        const clearSearchBtn = document.getElementById('clear-search-btn');
        if (searchInput && searchInput.value) {
            searchInput.value = '';
            if (clearSearchBtn) {
                clearSearchBtn.classList.add('hidden');
            }
            this.filterAndRenderSessions();
        }
        
        // Scroll to session gallery
        const gallery = document.getElementById('session-gallery');
        if (gallery) {
            gallery.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        // Clear any existing highlights
        document.querySelectorAll('.session-card-highlighted').forEach(el => {
            el.classList.remove('session-card-highlighted');
        });

        // Find and highlight the target session (handle partial IDs)
        setTimeout(() => {
            let sessionCard = document.getElementById(`session-card-${sessionId}`);
            
            // If not found, try finding by partial match (for truncated IDs)
            if (!sessionCard) {
                const allCards = document.querySelectorAll('[id^="session-card-"]');
                for (const card of allCards) {
                    if (card.id.includes(sessionId)) {
                        sessionCard = card;
                        break;
                    }
                }
            }
            
            if (sessionCard) {
                sessionCard.classList.add('session-card-highlighted');
                sessionCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
                
                // Remove highlight after 3 seconds
                setTimeout(() => {
                    sessionCard.classList.remove('session-card-highlighted');
                }, 3000);
            }
        }, 500);
    }

    /**
     * Activate a session in the conversation view
     */
    async activateSession(sessionId) {
        try {
            // Import the session handler dynamically
            const { handleLoadSession } = await import('./handlers/sessionManagement.js?v=3.2');
            
            // Switch to conversation view
            const conversationViewBtn = document.getElementById('view-switch-conversation');
            if (conversationViewBtn) {
                conversationViewBtn.click();
            }
            
            // Wait a moment for view to switch
            await new Promise(resolve => setTimeout(resolve, 200));
            
            // Load the session
            await handleLoadSession(sessionId);
            
        } catch (error) {
            console.error('Error activating session:', error);
            if (window.showAppBanner) {
                window.showAppBanner('Failed to activate session. Please try again.', 'error');
            }
        }
    }

    /**
     * Search for sessions containing a specific question
     */
    searchForQuestion(questionText) {
        
        // Set the search input
        const searchInput = document.getElementById('session-search');
        if (searchInput) {
            searchInput.value = questionText;
            
            // Trigger the filter
            this.filterAndRenderSessions();
            
            // Scroll to gallery
            const gallery = document.getElementById('session-gallery');
            if (gallery) {
                gallery.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        } else {
            console.error('[DEBUG] Search input element not found');
        }
    }

    /**
     * Render session cards in the gallery
     */
    renderSessionCards(sessions) {
        const container = document.getElementById('session-cards-grid');
        if (!container) return;

        if (sessions.length === 0) {
            container.innerHTML = `
                <div class="col-span-full text-center py-12">
                    <p class="text-gray-400">No sessions found</p>
                </div>
            `;
            return;
        }

        const html = sessions.map(session => this.createSessionCard(session)).join('');
        container.innerHTML = html;

        // Add click listeners to cards
        sessions.forEach(session => {
            const card = document.getElementById(`session-card-${session.id}`);
            if (card) {
                card.addEventListener('click', (e) => {
                    // Don't open inspector if clicking the activate button
                    if (!e.target.closest('.activate-session-btn')) {
                        this.openInspector(session.id);
                    }
                });
                
                // Add listener to activate button
                const activateBtn = card.querySelector('.activate-session-btn');
                if (activateBtn) {
                    activateBtn.addEventListener('click', (e) => {
                        e.stopPropagation(); // Prevent card click
                        this.activateSession(session.id);
                    });
                }
            }
        });
    }

    /**
     * Create HTML for a single session card
     */
    createSessionCard(session) {
        const statusColors = {
            success: 'bg-green-500/20 text-green-400 border-green-500/50',
            partial: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/50',
            failed: 'bg-red-500/20 text-red-400 border-red-500/50',
            empty: 'bg-gray-500/20 text-gray-400 border-gray-500/50'
        };

        const statusColor = statusColors[session.status] || statusColors.empty;
        const date = session.created_at ? new Date(session.created_at).toLocaleString() : 'Unknown';
        
        // Determine if this is a utility/temporary session
        const isUtility = session.is_temporary || false;
        const utilityPurpose = session.temporary_purpose || 'Utility session';

        return `
            <div id="session-card-${session.id}" class="rounded-xl p-4 border transition-all cursor-pointer group ${session.archived ? 'opacity-75' : ''} ${isUtility ? 'border-l-4' : ''}" 
                 style="background-color: var(--card-bg); border-color: ${session.archived ? 'rgba(75, 85, 99, 0.5)' : 'var(--border-primary)'}; ${isUtility ? 'border-left-color: rgba(139, 92, 246, 0.6);' : ''}" 
                 onmouseover="this.style.borderColor='rgba(241, 95, 34, 0.5)'" 
                 onmouseout="this.style.borderColor='${session.archived ? 'rgba(75, 85, 99, 0.5)' : 'var(--border-primary)'}'">
                <div class="flex items-start justify-between mb-3">
                    <div class="flex-1 min-w-0">
                        <h3 class="text-white font-semibold truncate group-hover:text-teradata-orange transition-colors" title="${session.name}">
                            ${session.name}
                            ${session.archived ? '<span class="ml-2 text-xs text-gray-500">[Archived]</span>' : ''}
                        </h3>
                        ${isUtility ? `
                            <div class="flex items-center gap-1.5 mt-1 text-xs text-purple-400">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                    <path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                                    <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                </svg>
                                <span class="truncate" title="${utilityPurpose}">${utilityPurpose}</span>
                            </div>
                        ` : ''}
                    </div>
                    <div class="flex items-center gap-2 flex-shrink-0 ml-2">
                        <button class="activate-session-btn p-1.5 rounded hover:bg-teradata-orange/20 text-gray-400 hover:text-teradata-orange transition-colors" 
                                data-session-id="${session.id}" 
                                title="Activate in Conversation View">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3" />
                            </svg>
                        </button>
                        ${isUtility ? '<span class="px-2 py-1 text-xs font-semibold rounded border bg-purple-500/20 text-purple-400 border-purple-500/50" title="Utility/temporary session">utility</span>' : ''}
                        ${session.archived ? '<span class="px-2 py-1 text-xs font-semibold rounded border bg-gray-500/20 text-gray-400 border-gray-500/50">archived</span>' : ''}
                        <span class="px-2 py-1 text-xs font-semibold rounded border ${statusColor}">
                            ${session.status}
                        </span>
                    </div>
                </div>
                
                <div class="space-y-2 text-sm">
                    <div class="flex items-center justify-between text-gray-400">
                        <span>Model:</span>
                        <span class="text-white font-medium">${session.provider}/${session.model}</span>
                    </div>
                    <div class="flex items-center justify-between text-gray-400">
                        <span>Turns:</span>
                        <span class="text-white font-medium">${session.turn_count}</span>
                    </div>
                    <div class="flex items-center justify-between text-gray-400">
                        <span>Tokens:</span>
                        <span class="text-white font-medium">${session.total_tokens.toLocaleString()}</span>
                    </div>
                    <div class="flex items-center justify-between text-gray-400">
                        <span>Created:</span>
                        <span class="text-white text-xs">${date}</span>
                    </div>
                </div>
                
                ${session.has_rag ? `
                    <div class="mt-3 pt-3 border-t border-white/10 flex items-center gap-2 text-xs text-green-400">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
                        </svg>
                        RAG Enhanced
                    </div>
                ` : ''}
            </div>
        `;
    }

    /**
     * Open the deep dive inspector (Tier 3)
     */
    async openInspector(sessionId) {
        this.currentSessionId = sessionId;

        // Show inspector modal
        const inspector = document.getElementById('deep-dive-inspector');
        if (inspector) {
            inspector.classList.remove('hidden');
        }

        // Load session details
        try {
            const headers = this._getHeaders();
            const response = await fetch(`/api/v1/sessions/${sessionId}/details`, { 
                method: 'GET',
                headers: headers 
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
            }

            const sessionData = await response.json();
            this.renderInspector(sessionData);
        } catch (error) {
            console.error('Error loading session details:', error);
            if (window.showAppBanner) {
                window.showAppBanner('Failed to load session details: ' + error.message, 'error');
            }
            this.closeInspector();
        }
    }

    /**
     * Render inspector content
     */
    renderInspector(sessionData) {
        // Update header
        document.getElementById('inspector-session-name').textContent = sessionData.name || 'Unnamed Session';
        document.getElementById('inspector-session-meta').textContent = 
            `Created: ${new Date(sessionData.created_at).toLocaleString()} • ID: ${sessionData.id}`;

        // Update stats
        const workflow = sessionData.last_turn_data?.workflow_history || [];
        const turnCount = workflow.filter(t => t.isValid !== false).length;
        
        document.getElementById('inspector-turn-count').textContent = turnCount;
        document.getElementById('inspector-total-tokens').textContent = 
            (sessionData.input_tokens + sessionData.output_tokens).toLocaleString();
        document.getElementById('inspector-model').textContent = `${sessionData.provider}/${sessionData.model}`;
        
        const ragCases = sessionData.rag_cases || [];
        document.getElementById('inspector-rag-count').textContent = ragCases.length;

        // Render timeline
        this.renderTimeline(workflow);

        // Render RAG cases if any
        if (ragCases.length > 0) {
            document.getElementById('inspector-rag-section').classList.remove('hidden');
            this.renderRAGCases(ragCases);
        } else {
            document.getElementById('inspector-rag-section').classList.add('hidden');
        }
    }

    /**
     * Render execution timeline
     */
    renderTimeline(workflow) {
        const container = document.getElementById('inspector-timeline');
        if (!container) return;

        if (!workflow || workflow.length === 0) {
            container.innerHTML = '<p class="text-gray-400">No timeline data available</p>';
            return;
        }

        const html = workflow.map((turn, index) => {
            if (turn.isValid === false) return '';

            const hasError = turn.execution_trace?.some(entry =>
                entry.result?.status === 'error'
            );

            // Build profile tag badge if available - PURE INDUSTRIAL SOLID COLORS
            let profileBadgeHTML = '';
            if (turn.profile_tag) {
                // Find profile by tag to get color
                const profile = window.configState?.profiles?.find(p => p.tag === turn.profile_tag);
                let cssVars = '';

                if (profile && profile.color) {
                    // Helper to adjust color brightness
                    const adjustBrightness = (hex, percent) => {
                        hex = hex.replace('#', '');
                        const r = parseInt(hex.slice(0, 2), 16);
                        const g = parseInt(hex.slice(2, 4), 16);
                        const b = parseInt(hex.slice(4, 6), 16);
                        const factor = 1 + (percent / 100);
                        const newR = Math.min(255, Math.max(0, Math.round(r * factor)));
                        const newG = Math.min(255, Math.max(0, Math.round(g * factor)));
                        const newB = Math.min(255, Math.max(0, Math.round(b * factor)));
                        const toHex = (n) => n.toString(16).padStart(2, '0');
                        return `#${toHex(newR)}${toHex(newG)}${toHex(newB)}`;
                    };

                    // PURE INDUSTRIAL: Flat monolithic design
                    const solidBg = profile.color;
                    const hoverColor = adjustBrightness(profile.color, 10);
                    // Flat monolithic: border matches background, white text
                    cssVars = `--profile-tag-bg: ${solidBg}; --profile-tag-border: ${solidBg}; --profile-tag-bg-hover: ${hoverColor}; --profile-tag-text: #FFFFFF;`;
                }

                profileBadgeHTML = `<span class="profile-tag profile-tag--sm mr-2" style="${cssVars}">@${turn.profile_tag}</span>`;
            }

            return `
                <div class="flex gap-4">
                    <div class="flex flex-col items-center">
                        <div class="w-8 h-8 rounded-full ${hasError ? 'bg-red-500/20' : 'bg-teradata-orange/20'} flex items-center justify-center">
                            <span class="text-sm font-bold ${hasError ? 'text-red-400' : 'text-teradata-orange'}">${turn.turn_number || index + 1}</span>
                        </div>
                        ${index < workflow.length - 1 ? '<div class="w-0.5 h-12 bg-white/10"></div>' : ''}
                    </div>
                    <div class="flex-1 pb-8">
                        <div class="rounded-lg p-4 border" style="background-color: var(--card-bg); border-color: var(--border-primary);">
                            <div class="flex items-center mb-2">
                                ${profileBadgeHTML}
                                <p class="text-white font-semibold flex-1">${turn.user_query || 'Query ' + (index + 1)}</p>
                            </div>
                            <p class="text-gray-400 text-sm mb-2">${turn.final_summary || 'No summary available'}</p>
                            <div class="flex items-center gap-4 text-xs text-gray-500">
                                <span>Tokens: ${(turn.turn_input_tokens || 0) + (turn.turn_output_tokens || 0)}</span>
                                <span>Time: ${turn.timestamp ? new Date(turn.timestamp).toLocaleTimeString() : 'Unknown'}</span>
                                ${turn.task_id ? `<span>Task: ${turn.task_id.substring(0, 8)}...</span>` : ''}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = html;
    }

    /**
     * Render RAG efficiency cases
     */
    renderRAGCases(ragCases) {
        const container = document.getElementById('inspector-rag-cases');
        if (!container) return;

        const html = ragCases.map(ragCase => `
            <div class="rounded-lg p-4 border" style="background-color: var(--card-bg); border-color: var(--border-primary);">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-white font-semibold">Case ${ragCase.case_id.substring(0, 8)}</span>
                    ${ragCase.is_most_efficient ? `
                        <span class="px-2 py-1 bg-yellow-500/20 text-yellow-400 text-xs font-semibold rounded border border-yellow-500/50">
                            Most Efficient
                        </span>
                    ` : ''}
                </div>
                <div class="text-sm space-y-1">
                    <p class="text-gray-400">Turn: ${ragCase.turn_id || 'Unknown'}</p>
                    <p class="text-gray-400">Tokens: ${ragCase.output_tokens || 0}</p>
                    <p class="text-gray-400">Collection: ${ragCase.collection_id || 0}</p>
                </div>
            </div>
        `).join('');

        container.innerHTML = html;
    }

    /**
     * Close the inspector
     */
    closeInspector() {
        const inspector = document.getElementById('deep-dive-inspector');
        if (inspector) {
            inspector.classList.add('hidden');
        }
        this.currentSessionId = null;
    }

    /**
     * Export current session as JSON
     */
    async exportSessionAsJSON() {
        if (!this.currentSessionId) return;

        try {
            const headers = this._getHeaders();
            const response = await fetch(`/api/v1/sessions/${this.currentSessionId}/details`, { method: 'GET', headers: headers });
            const sessionData = await response.json();

            const dataStr = JSON.stringify(sessionData, null, 2);
            const dataBlob = new Blob([dataStr], { type: 'application/json' });
            const url = URL.createObjectURL(dataBlob);
            
            const link = document.createElement('a');
            link.href = url;
            link.download = `session_${this.currentSessionId}.json`;
            link.click();
            
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error('Export failed:', error);
            if (window.showAppBanner) {
                window.showAppBanner('Failed to export session: ' + error.message, 'error');
            }
        }
    }

    /**
     * Export current session as formatted report
     */
    async exportSessionAsReport() {
        if (!this.currentSessionId) return;

        try {
            const headers = this._getHeaders();
            const response = await fetch(`/api/v1/sessions/${this.currentSessionId}/details`, { method: 'GET', headers: headers });
            const sessionData = await response.json();

            const workflow = sessionData.last_turn_data?.workflow_history || [];
            const ragCases = sessionData.rag_cases || [];

            const report = `
EXECUTION REPORT
================

Session: ${sessionData.name}
ID: ${sessionData.id}
Created: ${new Date(sessionData.created_at).toLocaleString()}
Model: ${sessionData.provider}/${sessionData.model}

STATISTICS
----------
Total Turns: ${workflow.filter(t => t.isValid !== false).length}
Total Tokens: ${sessionData.input_tokens + sessionData.output_tokens}
  - Input: ${sessionData.input_tokens}
  - Output: ${sessionData.output_tokens}
RAG Cases: ${ragCases.length}

EXECUTION TIMELINE
------------------
${workflow.map((turn, i) => {
    if (turn.isValid === false) return '';
    return `
Turn ${turn.turn_number || i + 1}:
Query: ${turn.user_query || 'N/A'}
Summary: ${turn.final_summary || 'N/A'}
Tokens: ${(turn.turn_input_tokens || 0) + (turn.turn_output_tokens || 0)}
Time: ${turn.timestamp ? new Date(turn.timestamp).toLocaleString() : 'Unknown'}
`;
}).join('\n')}

${ragCases.length > 0 ? `
RAG EFFICIENCY CASES
--------------------
${ragCases.map(c => `
Case ID: ${c.case_id}
Turn: ${c.turn_id}
Most Efficient: ${c.is_most_efficient ? 'Yes' : 'No'}
Tokens: ${c.output_tokens || 0}
`).join('\n')}
` : ''}
            `.trim();

            const blob = new Blob([report], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            
            const link = document.createElement('a');
            link.href = url;
            link.download = `session_report_${this.currentSessionId}.txt`;
            link.click();
            
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error('Export failed:', error);
            if (window.showAppBanner) {
                window.showAppBanner('Failed to export report: ' + error.message, 'error');
            }
        }
    }

    /**
     * Check if user has VIEW_ALL_SESSIONS feature
     */
    async checkViewAllSessionsFeature() {
        try {
            const headers = this._getHeaders();
            const response = await fetch('/api/v1/auth/me/features', { headers });
            
            if (response.ok) {
                const data = await response.json();
                if (data.status === 'success' && data.features) {
                    this.hasViewAllSessionsFeature = data.features.includes('view_all_sessions');
                    this.isAdmin = this.hasViewAllSessionsFeature;
                    
                    // Show/hide the toggle based on feature availability
                    const toggleContainer = document.getElementById('view-all-sessions-container');
                    if (toggleContainer) {
                        if (this.hasViewAllSessionsFeature) {
                            toggleContainer.classList.remove('hidden');
                        } else {
                            toggleContainer.classList.add('hidden');
                        }
                    }
                    
                    // Show System Performance tab for admins
                    if (this.isAdmin) {
                        const systemTab = document.getElementById('tab-system-performance');
                        if (systemTab) {
                            systemTab.classList.remove('hidden');
                        }
                    }
                }
            }
        } catch (error) {
            console.error('Error checking VIEW_ALL_SESSIONS feature:', error);
            this.hasViewAllSessionsFeature = false;
            this.isAdmin = false;
        }
    }
    
    /**
     * Switch between My Performance and System Performance tabs
     * Only refreshes the analytics/metrics section, not the session gallery
     */
    async switchPerformanceTab(view) {
        if (view === 'system' && !this.isAdmin) {
            console.warn('System performance view is admin-only');
            return;
        }

        this.currentPerformanceView = view;

        // Update tab styling (match Intelligence Pane repository tabs)
        const myTab = document.getElementById('tab-my-performance');
        const systemTab = document.getElementById('tab-system-performance');

        if (view === 'my') {
            myTab.classList.remove('text-gray-400', 'border-transparent');
            myTab.classList.add('text-[#F15F22]', 'border-[#F15F22]');
            systemTab.classList.remove('text-[#F15F22]', 'border-[#F15F22]');
            systemTab.classList.add('text-gray-400', 'border-transparent');
        } else {
            systemTab.classList.remove('text-gray-400', 'border-transparent');
            systemTab.classList.add('text-[#F15F22]', 'border-[#F15F22]');
            myTab.classList.remove('text-[#F15F22]', 'border-[#F15F22]');
            myTab.classList.add('text-gray-400', 'border-transparent');
        }

        // Update scope indicator (consistent with Intelligence Performance)
        const scopeIndicator = document.getElementById('execution-scope-indicator');
        if (scopeIndicator) {
            scopeIndicator.textContent = view === 'system'
                ? 'System-Wide Performance (All Users)'
                : 'Your Learning Performance';
        }

        // Refresh only the analytics section (not session gallery)
        await this.refreshAnalytics();
    }
    
    /**
     * Refresh only the analytics/metrics section (used by tab switching)
     * Does NOT touch the session gallery at all
     */
    async refreshAnalytics() {
        try {
            const headers = this._getHeaders();
            
            // Determine which endpoint to use based on current view
            const consumptionUrl = (this.currentPerformanceView === 'system' && this.isAdmin)
                ? '/api/v1/consumption/system-summary'
                : '/api/v1/consumption/summary';
            
            console.log('[ExecutionDashboard] Refreshing analytics only from:', consumptionUrl);
            
            const consumptionResponse = await fetch(consumptionUrl, { method: 'GET', headers: headers });

            if (!consumptionResponse.ok) {
                console.error('[ExecutionDashboard] API error - consumption:', consumptionResponse.status);
                throw new Error('Failed to fetch analytics data');
            }

            this.analyticsData = await consumptionResponse.json();
            
            // Render only the analytics section - do NOT touch session gallery
            this.renderAnalytics();

        } catch (error) {
            console.error('Error refreshing analytics:', error);
            // Do NOT call showErrorState as it affects the session gallery
            // Just log the error - the metrics will show stale data
        }
    }

    /**
     * Show loading state
     */
    showLoadingState() {
        const grid = document.getElementById('session-cards-grid');
        if (grid) {
            grid.innerHTML = `
                <div class="col-span-full text-center py-12">
                    <p class="text-gray-400">Loading sessions...</p>
                </div>
            `;
        }
    }

    /**
     * Show error state
     */
    showErrorState(message) {
        const grid = document.getElementById('session-cards-grid');
        if (grid) {
            grid.innerHTML = `
                <div class="col-span-full text-center py-12">
                    <p class="text-red-400">Error loading dashboard: ${message}</p>
                </div>
            `;
        }
    }
}

// Export for use in main.js
window.ExecutionDashboard = ExecutionDashboard;
