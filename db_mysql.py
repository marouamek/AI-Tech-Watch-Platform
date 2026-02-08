import mysql.connector
import hashlib
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

# ---------- CONFIG DB ----------
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "pass_root",
    "database": "veille_ia"
}

# ---------- CONNEXION ----------


def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

# ---------- INIT DB ----------


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # Table articles
    cur.execute("""
    CREATE TABLE IF NOT EXISTS articles (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(512) NOT NULL,
        source VARCHAR(100) NOT NULL,
        published VARCHAR(20),
        summary TEXT,
        summary_short VARCHAR(512),
        categorie VARCHAR(100),
        classe VARCHAR(100),
        mots_cles TEXT,
        link TEXT,
        collected_at DATETIME,
        hash CHAR(64) UNIQUE,
        verifie INT DEFAULT 0
    )
    """)

    # S'assure que toutes les colonnes attendues existent même si
    # la table a été créée avec un ancien schéma.
    try:
        cur.execute("""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'articles'
        """, (DB_CONFIG["database"],))

        existing_cols = {row[0] for row in cur.fetchall()}

        # Colonnes attendues avec leurs définitions SQL
        expected_columns = {
            "summary": "ALTER TABLE articles ADD COLUMN summary TEXT",
            "summary_short": "ALTER TABLE articles ADD COLUMN summary_short VARCHAR(512)",
            "link": "ALTER TABLE articles ADD COLUMN link TEXT",
            "collected_at": "ALTER TABLE articles ADD COLUMN collected_at DATETIME",
            "hash": "ALTER TABLE articles ADD COLUMN hash CHAR(64) UNIQUE",
            "verifie": "ALTER TABLE articles ADD COLUMN verifie INT DEFAULT 0",
            "categorie": "ALTER TABLE articles ADD COLUMN categorie VARCHAR(100)",
            "classe": "ALTER TABLE articles ADD COLUMN classe VARCHAR(100)",
            "mots_cles": "ALTER TABLE articles ADD COLUMN mots_cles TEXT",
        }

        for col_name, ddl in expected_columns.items():
            if col_name not in existing_cols:
                try:
                    cur.execute(ddl)
                except Exception as e:
                    # On log l'erreur mais on ne bloque pas l'init DB
                    print(
                        f"Erreur lors de l'ajout de la colonne {col_name} : {e}")
    except Exception as e:
        print(
            f"Erreur lors de la vérification du schéma de la table articles : {e}")

    # Table users pour le login
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(255) NOT NULL UNIQUE,
        email VARCHAR(255) NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(50) NOT NULL,
        is_first_login TINYINT(1) NOT NULL DEFAULT 1
    )
    """)

    conn.commit()
    conn.close()

# ---------- HASH ----------


def article_hash(title, source, published):
    raw = f"{title}|{source}|{published}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------- INSERT ARTICLES ----------
def save_articles(articles):
    conn = get_connection()
    cur = conn.cursor()

    for a in articles:
        h = article_hash(a["title"], a["source"], a["published"])

        cur.execute("""
            INSERT IGNORE INTO articles
            (title, source, published, link, collected_at, hash,
             verifie, categorie, classe, mots_cles, summary, summary_short)
            VALUES (%s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s)
        """, (
            a["title"],
            a["source"],
            a.get("published"),
            a.get("link"),
            datetime.utcnow(),
            h,
            a.get("verifie", 0),
            a.get("categorie"),
            a.get("classe"),
            a.get("mots_cles"),
            a.get("summary"),
            a.get("summary_short"),
        ))

    conn.commit()
    conn.close()

# ---------- SELECT ARTICLES ----------

def get_all_articles():
    """
    Récupère tous les articles non rejetés.
    """
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT id, title, source, published, summary, summary_short,
                   categorie, classe, mots_cles, link, collected_at, verifie
            FROM articles
            WHERE verifie = 0
            ORDER BY collected_at DESC
        """)
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"Erreur lors de la récupération des articles : {e}")
        return []

# ---------- ARTICLES : CATEGORIES MANQUANTES ----------

def get_articles_without_category():
    """
    Retourne les articles dont la colonne categorie est NULL ou vide.
    """
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT id, title, summary, source
            FROM articles
            WHERE categorie IS NULL OR categorie = ''
        """)

        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"Erreur lors de la récupération des articles sans catégorie : {e}")
        return []


def update_article_category_and_classe(article_id, categorie, classe):
    """
    Met à jour la catégorie et la classe d'un article.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            UPDATE articles
            SET categorie = %s, classe = %s
            WHERE id = %s
        """, (categorie, classe, article_id))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erreur lors de la mise à jour de la catégorie/classe : {e}")
        
# ---------- DELETE / REJET ARTICLES ----------


def reject_article(article_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE articles
        SET verifie = 1
        WHERE id = %s
    """, (article_id,))

    conn.commit()
    conn.close()

# ---------- LOGIN FUNCTIONS ----------


def verify_user(username, password):
    """
    Vérifie les identifiants de l'utilisateur
    Retourne (True, user_data) ou (False, None)
    """
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT id, username, email, password_hash, role, is_first_login
            FROM users
            WHERE username = %s
        """, (username,))

        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            return True, user

        return False, None

    except Exception as e:
        print(f"Erreur lors de la vérification : {e}")
        return False, None


def get_user_by_username(username):
    """
    Récupère les informations d'un utilisateur par son nom d'utilisateur
    """
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT id, username, email, role, is_first_login
            FROM users
            WHERE username = %s
        """, (username,))

        user = cur.fetchone()
        conn.close()
        return user
    except Exception as e:
        print(f"Erreur lors de la récupération de l'utilisateur : {e}")
        return None


def get_user_by_id(user_id):
    """
    Récupère les informations d'un utilisateur par son ID
    """
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT id, username, email, role, is_first_login
            FROM users
            WHERE id = %s
        """, (user_id,))

        user = cur.fetchone()
        conn.close()
        return user
    except Exception as e:
        print(f"Erreur lors de la récupération de l'utilisateur : {e}")
        return None


def update_password(user_id, new_password):
    """
    Met à jour le mot de passe d'un utilisateur et marque la première connexion comme complétée
    """
    try:
        conn = get_connection()
        cur = conn.cursor()

        hashed_pw = generate_password_hash(new_password)

        cur.execute("""
            UPDATE users
            SET password_hash = %s, is_first_login = 0
            WHERE id = %s
        """, (hashed_pw, user_id))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Erreur lors de la mise à jour du mot de passe : {e}")
        return False


def create_user(username, email, password, role):
    """
    Crée un nouvel utilisateur
    """
    try:
        conn = get_connection()
        cur = conn.cursor()

        hashed_pw = generate_password_hash(password)

        cur.execute("""
            INSERT INTO users (username, email, password_hash, role, is_first_login)
            VALUES (%s, %s, %s, %s, 1)
        """, (username, email, hashed_pw, role))

        conn.commit()
        conn.close()
        return True
    except mysql.connector.Error as e:
        print(f"Erreur lors de la création de l'utilisateur : {e}")
        return False


def get_user_statistics():
    """
    Récupère les statistiques des utilisateurs par rôle
    """
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Récupère le nombre total d'utilisateurs et par rôle
        cur.execute("""
            SELECT role, COUNT(*) as count
            FROM users
            GROUP BY role
        """)

        stats = {}
        total = 0
        for role, count in cur.fetchall():
            stats[role] = count
            total += count

        stats['total'] = total
        conn.close()
        return stats
    except Exception as e:
        print(f"Erreur lors de la récupération des statistiques : {e}")
        return {'total': 0, 'admin': 0, 'veilleur': 0, 'analyste': 0, 'decideur': 0}


def get_all_users():
    """
    Récupère la liste complète des utilisateurs
    """
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, username, email, role, is_first_login
            FROM users
            ORDER BY role, username
        """)

        users = cur.fetchall()
        conn.close()
        return users
    except Exception as e:
        print(f"Erreur lors de la récupération des utilisateurs : {e}")
        return []
