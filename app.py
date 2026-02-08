# ------------------ Modules standard ------------------
import datetime
from datetime import datetime
import os
import json
from functools import wraps

# ------------------ Flask et extensions ------------------
from flask import Flask, render_template, request, jsonify, session, g, redirect, url_for
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash
from flask import flash


# ------------------ Scheduler ------------------
from apscheduler.schedulers.background import BackgroundScheduler

# ------------------ Modules du projet ------------------
from roles.analyste import Analyste
from roles.veilleur import Veilleur
from db_mysql import (
    get_connection,
    init_db,
    get_all_articles,
    reject_article,
    verify_user,
    get_user_by_id,
    update_password,
    create_user,
    get_user_statistics,
    get_all_users
)


app = Flask(__name__)
app.secret_key = 'super_secret_key_for_dev_only'

# Initialise / migre le schéma de la BDD au démarrage de l'app
init_db()

# ========== ROLE-BASED ACCESS CONTROL ==========


def require_role(*allowed_roles):
    """
    Décorateur pour vérifier le rôle de l'utilisateur.
    Usage: @require_role('admin', 'veilleur')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Vérifie que l'utilisateur est connecté
            if 'user_id' not in session:
                return redirect(url_for('login_page'))

            # Vérifie que le rôle est autorisé
            user_role = session.get('role')
            if user_role not in allowed_roles:
                return "Access Denied - Insufficient Permissions", 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ---------- EMAIL CONFIGURATION ----------
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'decideinc.verify@gmail.com'
app.config['MAIL_PASSWORD'] = 'ntdj tyii wgcg mtth'
app.config['MAIL_DEFAULT_SENDER'] = (
    'Decide System', 'decideinc.verify@gmail.com')

mail = Mail(app)

# ---------- CONFIG ----------
BASE_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(BASE_DIR, "data", "config.json")
CONFIG_FILE_SAVE = os.path.join(BASE_DIR, "data", "config_save.json")


def parse_keywords(raw: str):
    # Transforme une chaîne de mots-clés en liste propre
    # Exemple : "AI, RAG, LLM" → ["ai", "rag", "llm"]
    return [
        k.strip().lower()           # enlève les espaces et met en minuscule
        for k in (raw or "").split(",")  # découpe par virgule (évite None)
        if k.strip()                # ignore les éléments vides
    ]


def load_config():
    # Charge la configuration depuis un fichier JSON
    if os.path.exists(CONFIG_FILE):
        try:
            # Ouvre le fichier config en lecture
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                # retourne la config sous forme de dictionnaire
                return json.load(f)
        except Exception:
            # Si le fichier est corrompu ou illisible
            return {}
    # Si le fichier n'existe pas
    return {}


def save_config(cfg: dict):
    # Sauvegarde la configuration dans un fichier JSON
    # Crée le dossier si nécessaire
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)

    # Ouvre le fichier config en écriture
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        # Écrit la config en JSON lisible
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------- SCHEDULER ----------
# Démarre un planificateur en arrière-plan
scheduler = BackgroundScheduler()
scheduler.start()


def run_veille_from_config():
    """
    Lance la veille en utilisant la configuration sauvegardée
    """
    cfg = load_config()

    # Sources sélectionnées, flux personnalisés et mots-clés
    sources = cfg.get("sources", [])
    custom_sources = cfg.get("custom_sources", [])
    keywords = cfg.get("keywords", "")

    # Séparer les flux RSS de Google Scholar
    rss_sources = [s for s in sources if s != "google_scholar"]

    # Requête Scholar seulement si sélectionné
    scholar_query = keywords if "google_scholar" in sources and keywords else None

    # Création et exécution du veilleur (inclut les flux personnalisés persistés)
    veilleur = Veilleur(
        sources=rss_sources or None,
        custom_sources=custom_sources or None,
        scholar_query=scholar_query
    )
    veilleur.run()

    # Après la fin de la veille, génère et envoie les alertes par email aux décideurs
    try:
        send_veille_alerts()
    except Exception as e:
        print(f"Erreur lors de l'envoi des alertes post-veille : {e}")


def reschedule_job():
    scheduler.remove_all_jobs()
    cfg = load_config()
    freq = cfg.get("frequency", "once")

    if freq == "daily":
        scheduler.add_job(
            run_veille_from_config,
            "interval",
            days=1,
            id="veille_job"
        )
    elif freq == "weekly":
        scheduler.add_job(
            run_veille_from_config,
            "interval",
            weeks=1,
            id="veille_job"
        )
    elif freq == "monthly":
        scheduler.add_job(
            run_veille_from_config,
            "interval",
            weeks=4,
            id="veille_job"
        )


reschedule_job()


# ---------- ALERTS (génération & envoi) ----------

def compute_alerts_from_articles(articles, top_n=3):
    """Retourne la liste des alertes triées à partir d'une liste d'articles."""
    analyste_obj = Analyste(load_model=False)
    analysis = analyste_obj.analyze(data=articles)
    trending_keywords = analysis.get("trends", {}).get("top_keywords", [])
    trending_keywords = trending_keywords[:8]

    from datetime import datetime

    alerts = []
    for art in articles:
        title = art.get("title", "") or ""
        summary = art.get("summary", "") or art.get("summary_short", "") or ""
        mots_cles = art.get("mots_cles", "") or ""

        full_text = f"{title} {summary} {mots_cles}".lower()

        # Score de correspondance avec les mots-clés tendance
        match_score = 0
        for kw in trending_keywords:
            kw_lower = kw.lower()
            if kw_lower and kw_lower in full_text:
                match_score += 1

        if match_score == 0:
            continue

        # Score de récence sur 0-30 (plus récent = plus élevé)
        raw_date = art.get("collected_at") or art.get("published")
        recency_label = calculate_recency(raw_date)

        recency_score = 0
        if raw_date:
            try:
                if isinstance(raw_date, datetime):
                    d_obj = raw_date
                else:
                    s = str(raw_date)
                    try:
                        d_obj = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        d_obj = datetime.fromisoformat(s)
                days = (datetime.now() - d_obj).days
                recency_score = max(0, 30 - days)
            except Exception:
                recency_score = 0

        total_score = match_score * 10 + recency_score

        alerts.append({
            "title": title,
            "source": art.get("source", "Inconnu"),
            "published": art.get("published") or "Date inconnue",
            "summary": summary,
            "summary_short": art.get("summary_short") or (summary[:600] if summary else ""),
            "link": art.get("link"),
            "recency_label": recency_label,
            "score": total_score,
        })

    # Trier par score décroissant et garder les N meilleures alertes
    alerts.sort(key=lambda x: x["score"], reverse=True)
    return alerts[:top_n]


def send_alerts_via_email(alerts):
    """Envoie les alertes (list) par email à tous les décideurs."""
    try:
        if not alerts:
            return

        users = get_all_users()
        decideurs_emails = [u[2] for u in users if u[3] == 'decideur' and u[2]]
        if not decideurs_emails:
            return

        # --- Construction du corps texte & HTML (style carte dark + bouton) ---
        plain_lines = ["Bonjour,", "",
                       "Voici les alertes de veille identifiées :", ""]

        html_lines = [
            "<html><body style=\"background:#0b0f12;color:#fff;font-family:Arial,Helvetica,sans-serif;\">",
            "<div style=\"max-width:600px;margin:0 auto;padding:16px;\">",
            "<h2 style=\"color:#fff;font-size:20px;margin:0 0 12px 0;\">Vous avez " +
            str(len(alerts)) + " alerte(s) de veille</h2>",
        ]

        for a in alerts:
            # Plain text (sans score)
            plain_lines.append(
                f"- {a['title']} ({a['source']}) - {a['published']}")
            if a.get('summary_short'):
                s_short = a['summary_short']
                if len(s_short) > 600:
                    s_short = s_short[:600] + '...'
                plain_lines.append(f"  {s_short}")
            if a.get('link'):
                plain_lines.append(f"  Read more: {a['link']}")
            plain_lines.append("")

            # HTML styled card
            card_html = (
                "<div style=\"background:#111827;border-radius:12px;padding:16px;margin-bottom:14px;color:#fff;box-shadow:0 1px 3px rgba(0,0,0,0.3);\">"
                f"<div style=\"font-size:12px;color:#9ca3af;text-transform:uppercase;margin-bottom:8px;\">{a.get('source', 'Inconnu')}</div>"
                f"<div style=\"font-size:18px;font-weight:700;margin-bottom:8px;color:#fff;\">{a['title']}</div>"
            )

            if a.get('summary_short'):
                summary_html = a['summary_short']
                if len(summary_html) > 600:
                    summary_html = summary_html[:600] + '...'
                card_html += f"<div style=\"color:#d1d5db;font-size:14px;margin-bottom:12px;\">{summary_html}</div>"

            # Read more button (rounded)
            if a.get('link'):
                link_html = a['link']
                card_html += (
                    f"<div><a href=\"{link_html}\" style=\"display:inline-block;background:#374151;color:#fff;text-decoration:none;padding:10px 18px;border-radius:9999px;font-weight:600;\">Read More</a></div>"
                )

            card_html += "</div>"  # fin card

            html_lines.append(card_html)

        plain_lines.append("Cordialement,\nL'équipe de veille")
        html_lines.append(
            "<p style=\"color:#9ca3af;font-size:13px;\">Cordialement,<br/>L'équipe de veille</p>")
        html_lines.append("</div></body></html>")

        plain_body = "\n".join(plain_lines)
        html_body = "\n".join(html_lines)

        # Envoi individuel pour respecter la confidentialité
        subject = f"Alerte veille : {len(alerts)} alerte(s)"
        for email in decideurs_emails:
            try:
                msg = Message(subject=subject, recipients=[
                              email], body=plain_body, html=html_body)
                mail.send(msg)
            except Exception as mail_err:
                print(f"Erreur envoi email à {email} : {mail_err}")

    except Exception as e:
        print(f"Erreur lors de l'envoi des alertes par email : {e}")


def send_veille_alerts():
    """Collecte les articles récents, calcule les alertes et les envoie."""
    try:
        articles = get_all_articles()
        alerts = compute_alerts_from_articles(articles, top_n=3)
        if alerts:
            send_alerts_via_email(alerts)
    except Exception as e:
        print(
            f"Erreur lors de la génération/envoi des alertes post-veille : {e}")


# ---------- LOGIN & SESSION ----------

@app.route('/login')
def login_page():
    # Vérifie si l'utilisateur est déjà connecté
    if 'user_id' in session:
        # S'il est connecté, redirige vers son tableau de bord
        return redirect(url_for('dispatch_dashboard'))

    # Sinon, affiche la page de connexion
    return render_template('login.html')


@app.route('/api/login', methods=['POST'])
def api_login():
    # Récupère les données envoyées en JSON depuis le formulaire
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    # Vérifie les identifiants (fonction personnalisée)
    success, user = verify_user(username, password)

    if success:
        # Nettoie l'ancienne session (sécurité)
        session.clear()

        # Stocke les infos de l'utilisateur dans la session
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        session['is_first_login'] = user['is_first_login']

        # Si c'est la première connexion → forcer le changement de mot de passe
        if user['is_first_login']:
            return jsonify({
                'success': True,
                'redirect_url': '/change_password'
            })

        # Connexion normale → redirection selon le rôle
        return jsonify({
            'success': True,
            'redirect_url': '/dispatch'
        })

    else:
        # Identifiants incorrects
        return jsonify({
            'success': False,
            'message': 'Invalid credentials.'
        }), 401


@app.route('/api/contact_admin', methods=['POST'])
def contact_admin():
    # Récupère les données envoyées en JSON depuis le formulaire
    data = request.get_json()
    user_email = data.get('email')     # Email de l'utilisateur
    motive = data.get('motive')        # Motif de la demande
    message_text = data.get('message')  # Contenu du message

    # Vérifie que tous les champs sont remplis
    if not all([user_email, motive, message_text]):
        return jsonify({
            'success': False,
            'message': 'All fields are required.'
        }), 400

    try:
        # Email de l'administration (défini dans la config Flask)
        company_email = app.config['MAIL_USERNAME']

        # Création du message email
        msg = Message(
            subject=f'Assistance requested : "{motive}"',
            recipients=[company_email],  # Envoi à l’admin
            body=f"""New Assistance Request

From: {user_email}
Motive: {motive}

Message:
{message_text}
            """
        )

        # Envoi de l'email
        mail.send(msg)

        # Réponse OK au frontend
        return jsonify({
            'success': True,
            'message': 'Request sent to administration.'
        })

    except Exception as e:
        # En cas d’erreur lors de l’envoi de l’email
        print(f"Mail Error: {e}")
        return jsonify({
            'success': False,
            'message': 'Error sending email.'
        }), 500


@app.route('/dispatch')
def dispatch_dashboard():
    # Si l'utilisateur n'est pas connecté → retour à la page de login
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    # Si c'est la première connexion → forcer le changement de mot de passe
    if session.get('is_first_login'):
        return redirect(url_for('change_password_page'))

    # Récupère le rôle de l'utilisateur connecté
    role = session.get('role')

    # Redirection selon le rôle
    if role == 'admin':
        return redirect(url_for('dashboard_admin'))
    elif role == 'veilleur':
        return redirect(url_for('index'))
    elif role == 'analyste':
        return redirect(url_for('analyste'))
    elif role == 'decideur':
        return redirect(url_for('decideur'))

    # Cas d'erreur : rôle inconnu
    return "Unknown Role", 403


@app.route('/change_password')
def change_password_page():
    # Empêche l'accès si l'utilisateur n'est pas connecté
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    # Affiche la page de changement de mot de passe
    return render_template('change_password.html')


@app.route('/api/change_password', methods=['POST'])
def api_change_password():
    # Sécurité : vérifie que l'utilisateur est connecté
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    # Récupère le nouveau mot de passe depuis le frontend
    data = request.get_json()
    new_password = data.get('new_password')

    # Met à jour le mot de passe dans la base de données
    success = update_password(session['user_id'], new_password)

    if success:
        # Marque que ce n'est plus la première connexion
        session['is_first_login'] = 0

        # Redirection vers le dashboard
        return jsonify({
            'success': True,
            'redirect_url': '/dispatch'
        })
    else:
        # Erreur lors de la mise à jour du mot de passe
        return jsonify({
            'success': False,
            'message': 'Error updating password'
        }), 500


# ---------- DASHBOARDS ----------

@app.route('/dashboard_admin')
@require_role('admin')
def dashboard_admin():
    # Affiche le dashboard admin
    return render_template('dashboard_admin.html')


@app.route('/dashboard_admin/create_account')
@require_role('admin')
def dashboard_admin_create_account():
    # Page dédiée pour créer un compte
    return render_template('admin_create_account.html')


@app.route('/api/admin/stats', methods=['GET'])
@require_role('admin')
def api_admin_stats():
    """
    Récupère les statistiques des utilisateurs
    """
    stats = get_user_statistics()
    return jsonify(stats)


@app.route('/api/admin/users', methods=['GET'])
@require_role('admin')
def api_admin_users():
    """
    Récupère la liste complète des utilisateurs
    """
    users = get_all_users()
    # Convertir les tuples en dictionnaire pour JSON
    users_list = [
        {
            'id': u[0],
            'username': u[1],
            'email': u[2],
            'role': u[3],
            'is_first_login': bool(u[4])
        }
        for u in users
    ]
    return jsonify({'users': users_list})


@app.route('/api/admin/create_user', methods=['POST'])
@require_role('admin')
def api_create_user():
    # Récupère les données JSON envoyées par le frontend
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    role = data.get('role')

    try:
        # Crée l'utilisateur en base de données
        success = create_user(username, email, password, role)

        if success:
            # Si création réussie, tente d'envoyer un email à l'utilisateur
            try:
                msg = Message(
                    subject="Bienvenue sur Decide - Vos identifiants",
                    recipients=[email],
                    body=f"ID: {username}\nPass: {password}\n\nConnectez-vous et changez votre mot de passe."
                )
                mail.send(msg)
            except:
                # Ne bloque pas la création si l'email échoue
                pass

            return jsonify({'success': True, 'message': 'User created.'})
        else:
            # L'utilisateur existe déjà
            return jsonify({'success': False, 'message': 'User already exists.'}), 400
    except Exception as e:
        # Gestion des erreurs inattendues
        print(f"Error creating user: {e}")
        return jsonify({'success': False, 'message': 'Error creating user.'}), 500


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    # GET: afficher la page de confirmation
    if request.method == 'GET':
        return render_template('confirm_logout.html')

    # POST: effectuer la déconnexion
    session.clear()
    return redirect(url_for('login_page'))

# ---------- ROUTES PRINCIPALES (avec vérification session) ----------


@app.route('/')
@require_role('admin', 'veilleur')
def index():
    articles = get_all_articles()
    sources = sorted({a["source"] for a in articles})

    # Charger la configuration actuelle pour afficher
    # les flux RSS personnalisés et autres paramètres sur la page veilleur
    current_config = load_config()

    return render_template(
        "veilleur.html",
        articles=articles,
        sources=sources,
        current_config=current_config,
    )


@app.route('/configuration')
@require_role('admin', 'veilleur')
def configuration():
    """Page de configuration et affichage de la configuration actuelle"""
    current_config = load_config()

    return render_template(
        "configuration.html",
        current_config=current_config,
    )


@app.route("/configurer", methods=["POST"])
@require_role('admin', 'veilleur')
def configurer():
    cfg = load_config()

    selected_sources = request.form.getlist("sources")
    keywords = request.form.get("keywords", "").strip()
    frequency = request.form.get("frequency", "once")
    date_from = request.form.get("date_from") or None
    date_to = request.form.get("date_to") or None
    custom_rss = request.form.get("custom_rss", "").strip()
    custom_rss_name = request.form.get("custom_rss_name", "").strip()

    # ajout flux perso
    if custom_rss:
        cfg.setdefault("custom_sources", [])
        # Vérifier si ce flux n'existe pas déjà
        existing_urls = [s["url"] if isinstance(
            s, dict) else s for s in cfg["custom_sources"]]
        if custom_rss not in existing_urls:
            cfg["custom_sources"].append({
                "url": custom_rss,
                "name": custom_rss_name or "Sans nom"
            })

    # vérification source
    has_any_source = bool(selected_sources) or bool(
        custom_rss or cfg.get("custom_sources"))
    if not has_any_source:
        flash(
            "⚠️ Veuillez sélectionner au moins une source ou saisir un flux RSS.", "error")
        return redirect("/configuration")

    # mise à jour config
    cfg["frequency"] = frequency
    cfg["sources"] = selected_sources
    cfg["keywords"] = keywords
    cfg["date_from"] = date_from
    cfg["date_to"] = date_to
    save_config(cfg)
    reschedule_job()

    # action = save uniquement

    flash("✅ Configuration enregistrée", "success")
    return redirect("/")


@app.route("/lancer", methods=["POST"])
@require_role('admin', 'veilleur')
def lancer():
    cfg = load_config()

    # --- récupération des valeurs du formulaire ---
    selected_sources = request.form.getlist("sources")
    selected_custom_urls = request.form.getlist("custom_sources")
    keywords = request.form.get("keywords", "").strip()
    frequency = request.form.get("frequency", "once")
    date_from = request.form.get("date_from") or None
    date_to = request.form.get("date_to") or None
    custom_rss = request.form.get("custom_rss", "").strip()
    custom_rss_name = request.form.get("custom_rss_name", "").strip()

    # --- vérification qu'il y a au moins une source (prédef ou custom) ---
    has_any_source = bool(selected_sources) or bool(
        selected_custom_urls) or bool(custom_rss)
    if not has_any_source:
        flash(
            "⚠️ Veuillez sélectionner au moins une source ou saisir un flux RSS.", "error")
        return redirect("/")

    # --- gérer les flux personnalisés
    custom_sources_to_use = []

    # 1) flux personnalisés déjà connus en config
    existing_custom = cfg.get("custom_sources", [])

    # 1.a) n'utiliser que ceux qui sont cochés pour ce run
    if selected_custom_urls:
        for item in existing_custom:
            url = item["url"] if isinstance(item, dict) else item
            if url in selected_custom_urls:
                custom_sources_to_use.append(item)

    # 2) si un nouveau flux est saisi, l'ajouter à la config SANS effacer les anciens
    if custom_rss:
        # Vérifier si le flux n'existe pas déjà dans la config complète
        existing_urls = [
            (s["url"] if isinstance(s, dict) else s)
            for s in existing_custom
        ]
        if custom_rss not in existing_urls:
            new_entry = {
                "url": custom_rss,
                "name": custom_rss_name or "Sans nom"
            }
            # il est utilisé pour ce run
            custom_sources_to_use.append(new_entry)
            # et ajouté à la liste globale persistée
            existing_custom.append(new_entry)
            cfg["custom_sources"] = existing_custom
            save_config(cfg)
            reschedule_job()

    # --- préparer la query Google Scholar ---
    scholar_query = keywords if "google_scholar" in selected_sources else None

    # --- création du Veilleur avec paramètres directs ---
    veilleur = Veilleur(
        sources=[s for s in selected_sources if s !=
                 "google_scholar"],  # flux prédéfinis
        # flux personnalisés
        custom_sources=custom_sources_to_use if custom_sources_to_use else None,
        scholar_query=scholar_query,
        keywords=keywords,
        frequency=frequency,
        date_from=date_from,
        date_to=date_to,
    )

    # --- lancer la veille ---
    veilleur.run()

    # Après lancement manuel, envoyer les alertes par email
    try:
        send_veille_alerts()
        flash("✅ Veille lancée et alertes envoyées.", "success")
    except Exception as e:
        print(f"Erreur envoi alertes après lancement manuel: {e}")
        flash("✅ Veille lancée (mais erreur lors de l'envoi des alertes).", "warning")

    return redirect("/")


@app.route("/api/delete_rss", methods=["POST"])
@require_role('admin', 'veilleur')
def api_delete_rss():
    """Supprime un flux RSS personnalisé de la configuration"""
    data = request.get_json()
    rss_url = data.get('rss_url', '').strip()

    if not rss_url:
        return jsonify({'success': False, 'message': 'URL vide'}), 400

    cfg = load_config()
    custom_sources = cfg.get('custom_sources', [])

    # Chercher et supprimer le flux (peut être un dict ou une string)
    for i, item in enumerate(custom_sources):
        item_url = item["url"] if isinstance(item, dict) else item
        if item_url == rss_url:
            custom_sources.pop(i)
            cfg['custom_sources'] = custom_sources
            save_config(cfg)
            reschedule_job()
            return jsonify({'success': True, 'message': 'Flux supprimé avec succès'})

    return jsonify({'success': False, 'message': 'Flux non trouvé'}), 404


@app.route("/analyste")
@require_role('admin', 'analyste')
def analyste():
    # pas de modèle ML ici
    analyste_obj = Analyste(load_model=False)
    articles = get_all_articles()

    analysis = analyste_obj.analyze(data=articles)

    recent_articles = articles[:10]

    return render_template(
        "analyste.html",
        total_articles=analysis["total_documents"],
        by_source=analysis["by_source"],
        by_category=analysis["by_category"],
        emerging_keywords=analysis["emerging_keywords"],
        emerging_by_category=analysis.get("emerging_by_category", {}),
        trends=analysis["trends"],
        recent_articles=recent_articles
    )


@app.route("/decideur")
@require_role('admin', 'decideur')
def decideur():
    """Dashboard Décideur : KPIs + tendances + alertes stratégiques."""

    # ----------------- KPIs globaux -----------------
    conn = get_connection()
    cur = conn.cursor()

    # Nombre total d'articles non rejetés
    cur.execute("SELECT COUNT(*) FROM articles WHERE verifie = 0")
    total_articles = cur.fetchone()[0] or 0

    # Nombre de sources distinctes (articles non rejetés)
    cur.execute("SELECT COUNT(DISTINCT source) FROM articles WHERE verifie = 0")
    total_sources = cur.fetchone()[0] or 0

    # Classe la plus fréquente (sur les articles non rejetés)
    cur.execute(
        "SELECT categorie, COUNT(*) AS cnt FROM articles "
        "WHERE verifie = 0 "
        "GROUP BY categorie ORDER BY cnt DESC LIMIT 1"
    )
    top_category = cur.fetchone()

    # Dernière date de collecte (articles non rejetés)
    cur.execute("SELECT MAX(collected_at) FROM articles WHERE verifie = 0")
    last_fetch = cur.fetchone()[0]

    # ----------------- Données de tendance -----------------
    # Récupère les données de tendance par date et catégorie
    # recuperer les lables et leurs données a fin de les passer au graphique
    cur.execute(
        "SELECT classe, COUNT(*) AS cnt "
        "FROM articles "
        "WHERE verifie = 0 "
        "GROUP BY classe "
    )
    rows = cur.fetchall()
    trend_labels = []
    trend_series = []

    for categorie, cnt in rows:
        trend_labels.append(categorie)
        trend_series.append(cnt)

    # Donnees pour le graphique de suivi par classification au fil du temps
    cur.execute(
        "SELECT classe, DATE_FORMAT(collected_at, '%Y-%m') AS mois, COUNT(*) AS cnt "
        "FROM articles "
        "WHERE verifie = 0 "
        "GROUP BY classe, mois "
        "ORDER BY mois"
    )
    line_rows = cur.fetchall()
    # First, collect all unique months in order
    line_labels = []
    for row in line_rows:
        mois = row[1]
        if mois not in line_labels:
            line_labels.append(mois)

    # Then, build the data structure
    line_data = {}
    for row in line_rows:
        classe, mois, cnt = row
        if classe not in line_data:
            line_data[classe] = [0] * len(line_labels)
        idx = line_labels.index(mois)
        line_data[classe][idx] = cnt

    print(line_data)

    cur.close()
    conn.close()

    # ----------------- Articles & tendances Analyste -----------------
    articles = get_all_articles()
    recent_articles = articles[:10]

    # Analyse des tendances pour récupérer les mots-clés forts
    analyste_obj = Analyste(load_model=False)
    analysis = analyste_obj.analyze(data=articles)
    trending_keywords = analysis.get("trends", {}).get("top_keywords", [])

    # On limite l'affichage des tags de tendance
    trending_keywords = trending_keywords[:8]

    # ----------------- Sélection des alertes -----------------
    from datetime import datetime

    alerts = []
    for art in articles:
        title = art.get("title", "") or ""
        summary = art.get("summary", "") or art.get("summary_short", "") or ""
        mots_cles = art.get("mots_cles", "") or ""

        full_text = f"{title} {summary} {mots_cles}".lower()

        # Score de correspondance avec les mots-clés tendance
        match_score = 0
        for kw in trending_keywords:
            kw_lower = kw.lower()
            if kw_lower and kw_lower in full_text:
                match_score += 1

        if match_score == 0:
            # on ignore les articles qui ne matchent aucune tendance
            continue

        # Score de récence sur 0-30 (plus récent = plus élevé)
        raw_date = art.get("collected_at") or art.get("published")
        recency_label = calculate_recency(raw_date)

        recency_score = 0
        if raw_date:
            try:
                if isinstance(raw_date, datetime):
                    d_obj = raw_date
                else:
                    s = str(raw_date)
                    try:
                        d_obj = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        d_obj = datetime.fromisoformat(s)
                days = (datetime.now() - d_obj).days
                recency_score = max(0, 30 - days)
            except Exception:
                recency_score = 0

        total_score = match_score * 10 + recency_score

        alerts.append({
            "title": title,
            "source": art.get("source", "Inconnu"),
            "published": art.get("published") or "Date inconnue",
            "summary": summary,
            "recency_label": recency_label,
            "score": total_score,
        })

    # Trier par score décroissant et garder les 3 meilleures alertes
    alerts.sort(key=lambda x: x["score"], reverse=True)
    alerts = alerts[:3]

    return render_template(
        "decideur.html",
        total_articles=total_articles,
        total_sources=total_sources,
        top_category=top_category,
        last_fetch=last_fetch,
        trend_labels=trend_labels,
        trend_series=trend_series,
        line_labels=line_labels,
        line_data=line_data,
        recent_articles=recent_articles,
        alerts=alerts,
        trending_keywords=trending_keywords,
    )


@app.route("/rejeter/<int:article_id>", methods=["POST"])
@require_role('admin', 'veilleur')
def rejeter_article(article_id):
    reject_article(article_id)
    return jsonify({"status": "ok"})


@app.route("/add_synthese/<int:class_id>", methods=["GET", "POST"])
@require_role('admin', 'analyste')
def add_synthese(class_id):
    conn = get_connection()
    cur = conn.cursor()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()

        if content:
            cur.execute(
                "INSERT into syntheses (title, content, class) values (%s, %s, %s)",
                (title, content, class_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            return redirect(url_for('view_synthese', class_id=class_id))
    return render_template("new_synthese.html", class_id=class_id)


@app.route("/view_synthese/<int:class_id>", methods=["GET"])
@require_role('admin', 'analyste')
def view_synthese(class_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT title, content, date FROM syntheses WHERE class = %s ORDER BY id DESC", (class_id,))
    content = cur.fetchall()

    cur.close()
    conn.close()
    return render_template("view_synthese.html", class_id=class_id, contents=content if content else None)


@app.route("/view_last_synthese/<int:class_id>", methods=["GET"])
@require_role('admin', 'decideur')
def view_last_synthese(class_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT title, content, date FROM syntheses WHERE class = %s ORDER BY id DESC LIMIT 1", (class_id,))
    content = cur.fetchone()
    print(content)
    cur.close()
    conn.close()
    return render_template("view_last_synthese.html", class_id=class_id, content=content)


def calculate_recency(date_str):
    """Calcule le label de temps (Aujourd'hui, etc.)"""
    if not date_str:
        return "Récent"
    try:
        date_obj = date_str if isinstance(
            date_str, datetime) else datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        diff = datetime.now() - date_obj
        if diff.days < 1:
            return "Aujourd'hui"
        return f"Il y a {diff.days} jours"
    except:
        return "Récemment"


# ---------- MAIN ----------

if __name__ == "__main__":
    app.run(debug=True)
