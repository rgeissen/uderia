/**
 * RAG Collection Management - Utility Functions
 * 
 * Pure utility functions for RAG collection management.
 * No direct DOM manipulation except for notifications.
 */

/**
 * Show notification message in header
 * @param {string} type - Notification type: success, error, warning, info
 * @param {string} message - Message to display
 */
export function showNotification(type, message) {
    const colors = {
        success: 'bg-green-600/90',
        error: 'bg-red-600/90',
        warning: 'bg-yellow-600/90',
        info: 'bg-blue-600/90'
    };

    const statusElement = document.getElementById('header-status-message');
    if (!statusElement) {
        return;
    }
    
    // Clear any existing timeout
    if (statusElement.hideTimeout) {
        clearTimeout(statusElement.hideTimeout);
    }
    
    // Set the message and style
    statusElement.textContent = message;
    statusElement.className = `text-sm px-3 py-1 rounded-md transition-all duration-300 ${colors[type] || colors.info} text-white`;
    statusElement.style.opacity = '1';
    
    // Auto-hide after 5 seconds
    statusElement.hideTimeout = setTimeout(() => {
        statusElement.style.opacity = '0';
        setTimeout(() => {
            statusElement.textContent = '';
        }, 300);
    }, 5000);
}

/**
 * Populate MCP server dropdown with available servers
 * @param {HTMLSelectElement} selectElement - The select element to populate
 */
export function populateMcpServerDropdown(selectElement, autoSelectFirst = true) {
    if (!selectElement) return;
    
    // Clear existing options except the placeholder
    selectElement.innerHTML = '<option value="">Select an MCP Server...</option>';
    
    // Get MCP servers from window.configState
    if (window.configState && window.configState.mcpServers && Array.isArray(window.configState.mcpServers)) {
        window.configState.mcpServers.forEach(server => {
            const option = document.createElement('option');
            option.value = server.id;  // Use server ID instead of name
            option.textContent = server.name;
            selectElement.appendChild(option);
        });
        
        // Auto-select first server if requested and available
        if (autoSelectFirst && window.configState.mcpServers.length > 0) {
            selectElement.value = window.configState.mcpServers[0].id;
        }
    }
    
    // If no servers available, show message
    if (selectElement.options.length === 1) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'No MCP servers configured';
        option.disabled = true;
        selectElement.appendChild(option);
    }
}

/**
 * Validate collection name
 * @param {string} name - Collection name to validate
 * @returns {object} {valid: boolean, error: string}
 */
export function validateCollectionName(name) {
    if (!name || name.trim().length === 0) {
        return { valid: false, error: 'Collection name is required' };
    }
    
    if (name.length < 3) {
        return { valid: false, error: 'Collection name must be at least 3 characters' };
    }
    
    if (name.length > 100) {
        return { valid: false, error: 'Collection name must be less than 100 characters' };
    }
    
    // Check for invalid characters
    const invalidChars = /[<>:"/\\|?*]/;
    if (invalidChars.test(name)) {
        return { valid: false, error: 'Collection name contains invalid characters' };
    }
    
    return { valid: true };
}

/**
 * Format datetime string for display
 * @param {string} datetime - ISO datetime string
 * @returns {string} Formatted datetime
 */
export function formatDateTime(datetime) {
    if (!datetime) return 'N/A';
    
    try {
        const date = new Date(datetime);
        return date.toLocaleString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch (error) {
        console.error('Error formatting datetime:', error);
        return datetime;
    }
}

/**
 * Sanitize HTML to prevent XSS
 * @param {string} html - HTML string to sanitize
 * @returns {string} Sanitized HTML
 */
export function sanitizeHTML(html) {
    const div = document.createElement('div');
    div.textContent = html;
    return div.innerHTML;
}

/**
 * Debounce function execution
 * @param {Function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @returns {Function} Debounced function
 */
export function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Deep clone an object
 * @param {object} obj - Object to clone
 * @returns {object} Cloned object
 */
export function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
}
