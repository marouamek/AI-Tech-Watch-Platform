## AI Watch – Technology Monitoring Platform

Flask web application that automates technology watch around AI and data.
It collects articles from multiple sources (RSS, blogs, Google Scholar), cleans them,
stores them in a MySQL database, automatically classifies them with a language model, and
exposes dashboards and email alerts tailored to different roles (watcher, analyst,
decision maker, administrator).

---

## 1. Main Features

- Authentication with roles (watcher, analyst, decision maker, admin) and role‑based access control.
- User management (account creation, password reset / change).
- Watch configuration:
  - select predefined RSS sources (arXiv, NVIDIA, Hugging Face, Microsoft Research, etc.),
  - add custom feeds,
  - define watch keywords,
  - set execution frequency (one‑shot, daily, weekly, monthly).
- Automatic collection:
  - fetch articles via RSS,
  - academic search via Google Scholar (optional),
  - clean content (HTML, short summaries, dates, sources, links).
- Analysis and classification:
  - keyword extraction with TF‑IDF (scikit‑learn),
  - automatic article categorization with SentenceTransformer + trained classifier,
  - aggregation by categories and sources, trend detection.
- Dashboards:
  - watcher interface to run / schedule the watch,
  - analyst interface to explore and analyze collected articles,
  - decision‑maker interface to consult summaries and watch briefs,
  - admin interface for configuration and account management.
- Email alerts:
  - identify the most relevant articles,
  - send alerts to decision makers via email (Flask‑Mail).

---

## 2. Project Architecture

- app.py: main Flask app, routes, session & role logic, scheduling (APScheduler).
- db_mysql.py: MySQL connection, schema initialization, queries and CRUD operations.
- roles/
  - veilleur.py: article collection (RSS + Google Scholar), cleaning and persistence.
  - analyste.py: article analysis, keyword extraction, classification with ML model.
  - decideur.py: generation of watch briefs for decision makers.
- models/sentence_transformer_model/: SentenceTransformer model and related files.
- data/config.json: watch configuration (sources, keywords, frequency…).
- static/ & templates/: front files (CSS, JS) and HTML templates for the different roles.

---

## 3. Prerequisites

- Python 3.9+ (recommended)
- MySQL installed and reachable (local or remote)
- Internet access for RSS feeds / Google Scholar

---

## 4. Installation & Environment

1. **Clone the repository** (or copy the project) and move into the project root directory.

2. **Create the virtual environment**:

```bash
python -m venv venv
```

3. **Activate the virtual environment (Windows)**:

```bash
venv\Scripts\activate
```

4. **Install main dependencies**:

```bash
pip install flask flask-mail feedparser scholarly apscheduler mysql-connector-python pandas scikit-learn sentence-transformers joblib python-dateutil
```

_(You can also create a `requirements.txt` file and use `pip install -r requirements.txt` if you prefer.)_

---

## 5. MySQL Database

1. Create a MySQL database (for example `veille_ia`).
2. Run the provided SQL script to create the tables:

```sql
-- In your MySQL client
SOURCE script.sql;
```

3. Make sure the MySQL connection parameters in `db_mysql.py` match
   your local configuration (host, user, password, database, port).

The application will initialize / migrate the schema at startup via `init_db()`.

---

## 6. Watch Configuration

The configuration (sources, keywords, frequency, custom feeds, etc.) is stored in
`data/config.json` and managed through the web interface (configuration / watcher screen).

You can:

- choose predefined sources (arxiv, nvidia, huggingface, etc.),
- define keywords separated by commas,
- add your own RSS feeds,
- set the execution frequency (one‑shot, daily, weekly, monthly).

An APScheduler background job then automatically runs the watch based on this configuration
and, if needed, triggers the sending of email alerts to decision makers.

---

## 7. Run the Application

Once the environment is set up and the database is ready:

```bash
venv\Scripts\activate
python app.py
```

By default, the Flask application listens on `http://127.0.0.1:5000/`.

---

## 8. Roles & User Journeys

- **Admin**
  - logs in through the login interface,
  - creates user accounts and assigns roles,
  - monitors global statistics.

- **Watcher (Veilleur)**
  - configures sources and keywords,
  - manually launches a watch campaign or schedules it,
  - validates / rejects collected articles.

- **Analyst**
  - explores collected articles,
  - analyzes trends (categories, emerging keywords),
  - prepares summaries.

- **Decision Maker**
  - receives email alerts with the most relevant articles,
  - accesses summary pages and dashboards for decision making.

---

## 9. Customization & Deployment

- Update the SMTP configuration in `app.py` to use your own email account for sending alerts.
- Secure the Flask secret key (`app.secret_key`) before going to production.
- Deploy behind a WSGI server (gunicorn, uwsgi) and a web server (Nginx, Apache) if
  the application must be exposed publicly.

---

## 10. Contributing

For collaborative work:

- create a working branch,
- implement changes (code / templates / models),
- push your branch and open a pull request on GitHub.