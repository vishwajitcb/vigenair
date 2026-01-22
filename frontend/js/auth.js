// Simple auth helper module

export async function checkAuth() {
    const token = localStorage.getItem('auth_token');

    if (!token) {
        // Redirect to login if on protected page
        if (!window.location.pathname.includes('login.html')) {
            window.location.href = '/login.html';
        }
        return false;
    }

    try {
        const response = await fetch('/api/auth/verify', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            localStorage.removeItem('auth_token');
            window.location.href = '/login.html';
            return false;
        }

        return true;
    } catch (error) {
        console.error('Auth check failed:', error);
        // If auth check fails, assume no auth is configured
        return true;
    }
}

export function getAuthHeader() {
    const token = localStorage.getItem('auth_token');
    return token ? { 'Authorization': `Bearer ${token}` } : {};
}

export function logout() {
    console.log('Logout clicked');
    const token = localStorage.getItem('auth_token');
    if (token) {
        fetch('/api/auth/logout', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`
            }
        }).catch(console.error);
    }
    localStorage.removeItem('auth_token');
    window.location.href = '/login.html';
}
