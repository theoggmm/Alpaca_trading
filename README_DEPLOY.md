# Déploiement sur Render (gratuit avec HTTPS)

## Option 1 : Déploiement facile sur Render

1. **Connecte-toi à Render** : https://render.com (crée un compte gratuit avec GitHub)

2. **Crée un nouveau Web Service** :
   - Clique sur "New +" → "Web Service"
   - Relie ton repo GitHub `Alpaca_trading`
   - Remplis les infos :
     - **Name** : `alpaca-trading`
     - **Environment** : `Python 3`
     - **Build Command** : `pip install -r requirements.txt` (ou `uv sync` si uv est dispo)
     - **Start Command** : `gunicorn app:app`
     - **Plan** : Free

3. **Récupère l'URL HTTPS** : Une fois déployé, Render te donne une URL du type :
   ```
   https://alpaca-trading-abc123.onrender.com
   ```

## Option 2 : Déploiement sur Vercel

1. Connecte-toi à Vercel : https://vercel.com
2. Importe le projet GitHub
3. Ajoute une variable d'environnement si nécessaire
4. Deploy (HTTPS automatique)

## Option 3 : Déploiement local avec tunnel (ngrok)

```bash
cd /Users/theodoremeyer/Documents/Alpaca_trading
.venv/bin/python app.py
```

Puis dans un autre terminal :
```bash
brew install ngrok
ngrok http 5000
```

Ngrok te donne une URL publique HTTPS temporaire.

## Pour tester en local d'abord

```bash
cd /Users/theodoremeyer/Documents/Alpaca_trading
.venv/bin/python app.py
```

Accès : http://localhost:5000
