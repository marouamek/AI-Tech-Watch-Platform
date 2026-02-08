document.addEventListener('DOMContentLoaded', () => {
    // Login
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = document.getElementById('submitBtn');
            const err = document.getElementById('error-message');
            btn.textContent = '...'; btn.disabled = true; err.textContent = '';
            try {
                const res = await fetch('/api/login', {
                    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(Object.fromEntries(new FormData(loginForm)))
                });
                const result = await res.json();
                if (result.success) window.location.href = result.redirect_url;
                else { err.textContent = result.message; btn.textContent = 'Se connecter'; btn.disabled = false; }
            } catch (e) { err.textContent = 'Error'; btn.disabled = false; }
        });
    }

    // Modal
    const modal = document.getElementById('contactModal');
    const openBtn = document.getElementById('openContactModal');
    const closeSpan = document.querySelector('.close-modal');
    const contactForm = document.getElementById('contactForm');

    if (openBtn) {
        openBtn.onclick = () => modal.style.display = "flex";
        closeSpan.onclick = () => modal.style.display = "none";
        window.onclick = (e) => { if (e.target == modal) modal.style.display = "none"; }

        contactForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = document.getElementById('sendContactBtn');
            const msg = document.getElementById('contact-msg');
            btn.textContent = "Sending..."; btn.disabled = true;
            try {
                const res = await fetch('/api/contact_admin', {
                    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(Object.fromEntries(new FormData(contactForm)))
                });
                const result = await res.json();
                msg.textContent = result.message; msg.style.color = result.success ? 'green' : 'red';
                btn.textContent = "Send"; btn.disabled = false;
                if(result.success) contactForm.reset();
            } catch(e) { msg.textContent = "Error"; btn.disabled = false; }
        });
    }
});