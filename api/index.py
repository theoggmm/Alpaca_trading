"""
Alpaca Trading Dashboard - Vercel serverless function
"""

from flask import Flask, render_template_string

app = Flask(__name__)
app.secret_key = "alpaca_trading_secret_key_2026"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Alpaca Trading Dashboard</title>
    <style>
        :root {
            --bg-light: #f8f9fa;
            --bg-dark: #1a1a1a;
            --text-light: #2c3e50;
            --text-dark: #ecf0f1;
            --accent: #0066cc;
            --accent-dark: #3385ff;
            --border-light: #e0e0e0;
            --border-dark: #333;
            --blue-bg: #1e90ff;
            --blue-dark: #1562cc;
        }

        @media (prefers-color-scheme: dark) {
            :root:not([data-theme="light"]) {
                --bg-light: var(--bg-dark);
                --text-light: var(--text-dark);
                --accent: var(--accent-dark);
                --border-light: var(--border-dark);
                color-scheme: dark;
            }
        }

        :root[data-theme="dark"] {
            --bg-light: var(--bg-dark);
            --text-light: var(--text-dark);
            --accent: var(--accent-dark);
            --border-light: var(--border-dark);
            color-scheme: dark;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background: var(--bg-light);
            color: var(--text-light);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 16px;
            line-height: 1.6;
            padding: 16px;
        }

        html, body {
            height: 100%;
        }

        .container {
            max-width: 400px;
            margin: 0 auto;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .login-page {
            width: 100%;
            display: none;
        }

        .login-page.active {
            display: block;
        }

        .login-form {
            background: var(--bg-light);
            padding: 40px 30px;
            border-radius: 8px;
            border: 1px solid var(--border-light);
            text-align: center;
        }

        .login-form h1 {
            font-size: 28px;
            margin-bottom: 10px;
            color: var(--accent);
        }

        .login-form p {
            color: var(--text-light);
            margin-bottom: 30px;
            opacity: 0.8;
        }

        .form-group {
            margin-bottom: 20px;
            text-align: left;
        }

        .form-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            font-size: 14px;
        }

        .form-group input {
            width: 100%;
            padding: 12px;
            border: 1px solid var(--border-light);
            border-radius: 6px;
            font-size: 16px;
            background: var(--bg-light);
            color: var(--text-light);
            transition: border-color 0.3s;
        }

        .form-group input:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(0, 102, 204, 0.1);
        }

        .login-btn {
            width: 100%;
            padding: 12px;
            background: var(--accent);
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.3s;
            margin-top: 10px;
        }

        .login-btn:hover {
            background: var(--blue-dark);
        }

        .login-btn:active {
            transform: scale(0.98);
        }

        .error-message {
            color: #e74c3c;
            font-size: 14px;
            margin-top: 15px;
            display: none;
        }

        .error-message.show {
            display: block;
        }

        .dashboard-page {
            width: 100%;
            display: none;
            height: 100%;
        }

        .dashboard-page.active {
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .dashboard {
            width: 100%;
            height: 100%;
            background: linear-gradient(135deg, #1e90ff 0%, #4169e1 100%);
            border-radius: 8px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 40px 20px;
            text-align: center;
        }

        .dashboard h2 {
            color: white;
            font-size: 32px;
            margin-bottom: 20px;
            text-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        }

        .dashboard p {
            color: rgba(255, 255, 255, 0.9);
            font-size: 18px;
            margin-bottom: 40px;
            max-width: 300px;
        }

        .logout-btn {
            padding: 12px 30px;
            background: rgba(255, 255, 255, 0.2);
            color: white;
            border: 2px solid white;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }

        .logout-btn:hover {
            background: rgba(255, 255, 255, 0.3);
        }

        .logout-btn:active {
            transform: scale(0.98);
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="login-page active">
            <div class="login-form">
                <h1>Alpaca Trading</h1>
                <p>Connectez-vous à votre tableau de bord</p>

                <form id="loginForm">
                    <div class="form-group">
                        <label for="username">Identifiant</label>
                        <input
                            type="text"
                            id="username"
                            placeholder="meyer.theodore"
                            required
                        />
                    </div>

                    <div class="form-group">
                        <label for="password">Mot de passe</label>
                        <input
                            type="password"
                            id="password"
                            placeholder="••••••••"
                            required
                        />
                    </div>

                    <button type="submit" class="login-btn">Connexion</button>

                    <div class="error-message" id="errorMessage"></div>
                </form>
            </div>
        </div>

        <div class="dashboard-page">
            <div class="dashboard">
                <h2>Bienvenue! 🚀</h2>
                <p>Vous êtes connecté à votre tableau de bord Alpaca Trading</p>
                <button class="logout-btn" id="logoutBtn">Déconnexion</button>
            </div>
        </div>
    </div>

    <script>
        const CORRECT_USERNAME = "meyer.theodore";
        const CORRECT_PASSWORD = "10qpalzmOC";

        const loginForm = document.getElementById("loginForm");
        const usernameInput = document.getElementById("username");
        const passwordInput = document.getElementById("password");
        const errorMessage = document.getElementById("errorMessage");
        const logoutBtn = document.getElementById("logoutBtn");

        const loginPage = document.querySelector(".login-page");
        const dashboardPage = document.querySelector(".dashboard-page");

        function checkLoggedIn() {
            const isLoggedIn = localStorage.getItem("alpacaLoggedIn") === "true";
            if (isLoggedIn) {
                showDashboard();
            }
        }

        function showDashboard() {
            loginPage.classList.remove("active");
            dashboardPage.classList.add("active");
        }

        function showLogin() {
            loginPage.classList.add("active");
            dashboardPage.classList.remove("active");
            usernameInput.value = "";
            passwordInput.value = "";
            errorMessage.classList.remove("show");
        }

        loginForm.addEventListener("submit", (e) => {
            e.preventDefault();

            const username = usernameInput.value.trim();
            const password = passwordInput.value;

            if (username === CORRECT_USERNAME && password === CORRECT_PASSWORD) {
                localStorage.setItem("alpacaLoggedIn", "true");
                showDashboard();
            } else {
                errorMessage.textContent = "Identifiant ou mot de passe incorrect";
                errorMessage.classList.add("show");
                passwordInput.value = "";
            }
        });

        logoutBtn.addEventListener("click", () => {
            localStorage.removeItem("alpacaLoggedIn");
            showLogin();
        });

        checkLoggedIn();
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/health")
def health():
    return {"status": "ok"}
