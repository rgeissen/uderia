/**
 * Authentication Client for Uderia Platform
 * 
 * Handles user authentication, token management, and session persistence.
 * Provides methods for login, logout, registration, and token refresh.
 */

class AuthClient {
    constructor() {
        this.baseUrl = '/api/v1/auth';
        this.tokenKey = 'tda_auth_token';
        this.userKey = 'tda_user';
        this.tokenExpiryKey = 'tda_token_expiry';
        
        // Start auto-refresh timer if authenticated
        if (this.isAuthenticated()) {
            this.startAutoRefresh();
        }
    }

    /**
     * Check if user is currently authenticated
     * @returns {boolean}
     */
    isAuthenticated() {
        const token = this.getToken();
        if (!token) {
            return false;
        }
        
        // Check if token is expired
        const expiry = localStorage.getItem(this.tokenExpiryKey);
        if (expiry && new Date(expiry) < new Date()) {
            console.log('Token expired, clearing session');
            this.clearSession();
            return false;
        }
        
        return true;
    }

    /**
     * Get stored authentication token
     * @returns {string|null}
     */
    getToken() {
        return localStorage.getItem(this.tokenKey);
    }

    /**
     * Get stored user information
     * @returns {object|null}
     */
    getUser() {
        const userJson = localStorage.getItem(this.userKey);
        return userJson ? JSON.parse(userJson) : null;
    }

    /**
     * Store authentication token and user info
     * @param {string} token - JWT token
     * @param {object} user - User object
     */
    setSession(token, user) {
        localStorage.setItem(this.tokenKey, token);
        localStorage.setItem(this.userKey, JSON.stringify(user));
        
        // Calculate expiry (24 hours from now by default)
        const expiry = new Date();
        expiry.setHours(expiry.getHours() + 24);
        localStorage.setItem(this.tokenExpiryKey, expiry.toISOString());
        
        console.log('Session stored:', { username: user.username, expiry: expiry.toISOString() });
        
        // Start auto-refresh
        this.startAutoRefresh();
    }

    /**
     * Store authentication token from OAuth callback
     * Decodes JWT to extract user info and sets session
     * @param {string} token - JWT token from OAuth callback
     */
    setToken(token) {
        if (!token) {
            console.error('Invalid token');
            return false;
        }

        try {
            // Decode JWT payload (without verification - backend verifies signature)
            const parts = token.split('.');
            if (parts.length !== 3) {
                throw new Error('Invalid token format');
            }

            // Decode payload
            const payload = JSON.parse(atob(parts[1]));
            
            // Extract user info from token
            const user = {
                id: payload.user_id,
                username: payload.username,
                email: payload.email || '',
            };

            // Store session
            this.setSession(token, user);
            
            console.log('Token set from OAuth callback:', { username: user.username });
            return true;
        } catch (error) {
            console.error('Error processing OAuth token:', error);
            return false;
        }
    }

    /**
     * Clear stored session data
     */
    clearSession() {
        localStorage.removeItem(this.tokenKey);
        localStorage.removeItem(this.userKey);
        localStorage.removeItem(this.tokenExpiryKey);
        
        // Stop auto-refresh
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = null;
        }
        
        console.log('Session cleared');
    }

    /**
     * Register a new user
     * @param {string} username 
     * @param {string} email 
     * @param {string} password 
     * @param {string} displayName - Optional display name
     * @returns {Promise<{success: boolean, message: string, user?: object, errors?: array}>}
     */
    async register(username, email, password, displayName = '') {
        try {
            const response = await fetch(`${this.baseUrl}/register`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    username,
                    email,
                    password,
                    display_name: displayName
                })
            });

            const data = await response.json();

            if (response.ok && data.status === 'success') {
                return {
                    success: true,
                    message: data.message,
                    user: data.user
                };
            } else {
                return {
                    success: false,
                    message: data.message || 'Registration failed',
                    errors: data.errors || []
                };
            }
        } catch (error) {
            console.error('Registration error:', error);
            return {
                success: false,
                message: 'Network error. Please check your connection.',
                errors: []
            };
        }
    }

    /**
     * Login user
     * @param {string} username 
     * @param {string} password 
     * @returns {Promise<{success: boolean, message: string, user?: object, token?: string}>}
     */
    async login(username, password) {
        try {
            const response = await fetch(`${this.baseUrl}/login`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    username,
                    password
                })
            });

            const data = await response.json();

            if (response.ok && data.status === 'success') {
                // Store session
                this.setSession(data.token, data.user);

                return {
                    success: true,
                    message: data.message,
                    user: data.user,
                    token: data.token
                };
            } else {
                return {
                    success: false,
                    message: data.message || 'Login failed',
                    requires_email_verification: data.requires_email_verification || false
                };
            }
        } catch (error) {
            console.error('Login error:', error);
            return {
                success: false,
                message: 'Network error. Please check your connection.'
            };
        }
    }

    /**
     * Logout user
     * @returns {Promise<{success: boolean, message: string}>}
     */
    async logout() {
        const token = this.getToken();
        
        if (!token) {
            this.clearSession();
            return {
                success: true,
                message: 'Already logged out'
            };
        }

        try {
            const response = await fetch(`${this.baseUrl}/logout`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json',
                }
            });

            const data = await response.json();

            // Clear session regardless of response
            this.clearSession();

            if (response.ok && data.status === 'success') {
                return {
                    success: true,
                    message: data.message
                };
            } else {
                return {
                    success: true, // Still success since we cleared local session
                    message: 'Logged out locally'
                };
            }
        } catch (error) {
            console.error('Logout error:', error);
            // Clear session even on error
            this.clearSession();
            return {
                success: true,
                message: 'Logged out locally'
            };
        }
    }

    /**
     * Get current user profile
     * @returns {Promise<{success: boolean, user?: object, message?: string}>}
     */
    async getCurrentUser() {
        const token = this.getToken();
        
        if (!token) {
            return {
                success: false,
                message: 'Not authenticated'
            };
        }

        try {
            const response = await fetch(`${this.baseUrl}/me`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json',
                }
            });

            const data = await response.json();

            if (response.ok && data.status === 'success') {
                // Update stored user info
                localStorage.setItem(this.userKey, JSON.stringify(data.user));
                
                return {
                    success: true,
                    user: data.user
                };
            } else {
                // Token might be invalid
                if (response.status === 401) {
                    this.clearSession();
                }
                
                return {
                    success: false,
                    message: data.message || 'Failed to get user info'
                };
            }
        } catch (error) {
            console.error('Get current user error:', error);
            return {
                success: false,
                message: 'Network error'
            };
        }
    }

    /**
     * Refresh authentication token
     * @returns {Promise<{success: boolean, token?: string, message?: string}>}
     */
    async refreshToken() {
        const token = this.getToken();
        
        if (!token) {
            return {
                success: false,
                message: 'Not authenticated'
            };
        }

        try {
            const response = await fetch(`${this.baseUrl}/refresh`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json',
                }
            });

            const data = await response.json();

            if (response.ok && data.status === 'success') {
                // Update token
                const user = this.getUser();
                this.setSession(data.token, user);
                
                console.log('Token refreshed successfully');
                
                return {
                    success: true,
                    token: data.token
                };
            } else {
                // Token refresh failed, clear session
                if (response.status === 401) {
                    this.clearSession();
                }
                
                return {
                    success: false,
                    message: data.message || 'Token refresh failed'
                };
            }
        } catch (error) {
            console.error('Token refresh error:', error);
            return {
                success: false,
                message: 'Network error'
            };
        }
    }

    /**
     * Change user password
     * @param {string} currentPassword 
     * @param {string} newPassword 
     * @returns {Promise<{success: boolean, message: string}>}
     */
    async changePassword(currentPassword, newPassword) {
        const token = this.getToken();
        
        if (!token) {
            return {
                success: false,
                message: 'Not authenticated'
            };
        }

        try {
            const response = await fetch(`${this.baseUrl}/change-password`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    current_password: currentPassword,
                    new_password: newPassword
                })
            });

            const data = await response.json();

            if (response.ok && data.status === 'success') {
                return {
                    success: true,
                    message: data.message
                };
            } else {
                return {
                    success: false,
                    message: data.message || 'Password change failed',
                    errors: data.errors || []
                };
            }
        } catch (error) {
            console.error('Password change error:', error);
            return {
                success: false,
                message: 'Network error'
            };
        }
    }

    /**
     * Make authenticated API request
     * @param {string} url - API endpoint URL
     * @param {object} options - Fetch options
     * @returns {Promise<Response>}
     */
    async authenticatedFetch(url, options = {}) {
        const token = this.getToken();
        
        if (!token) {
            throw new Error('Not authenticated');
        }

        // Add authorization header
        const headers = {
            ...options.headers,
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
        };

        const response = await fetch(url, {
            ...options,
            headers
        });

        // Handle 401 Unauthorized
        if (response.status === 401) {
            console.warn('Authentication failed, clearing session');
            this.clearSession();
            // Optionally redirect to login
            if (window.location.pathname !== '/login') {
                window.location.href = '/login';
            }
        }

        return response;
    }

    /**
     * Start automatic token refresh timer
     * Refreshes token 5 minutes before expiry
     */
    startAutoRefresh() {
        // Clear existing timer
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
        }

        // Check every 5 minutes
        this.refreshTimer = setInterval(async () => {
            const expiry = localStorage.getItem(this.tokenExpiryKey);
            if (!expiry) {
                return;
            }

            const expiryDate = new Date(expiry);
            const now = new Date();
            const minutesUntilExpiry = (expiryDate - now) / (1000 * 60);

            // Refresh if less than 10 minutes until expiry
            if (minutesUntilExpiry < 10 && minutesUntilExpiry > 0) {
                console.log('Auto-refreshing token...');
                const result = await this.refreshToken();
                
                if (!result.success) {
                    console.error('Auto-refresh failed:', result.message);
                }
            } else if (minutesUntilExpiry <= 0) {
                console.log('Token expired, clearing session');
                this.clearSession();
                
                // Redirect to login if not already there
                if (window.location.pathname !== '/login' && window.location.pathname !== '/register') {
                    window.location.href = '/login';
                }
            }
        }, 5 * 60 * 1000); // Check every 5 minutes
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AuthClient;
}
