import os
import re
import time
import feedparser
from html import unescape
from datetime import datetime
from scholarly import scholarly

from db_mysql import init_db, save_articles, get_articles_without_category, update_article_category_and_classe
from roles.analyste import Analyste

# ---------- MAPPING CATEGORIE (22) → CLASSE (7) ----------
BIG_CLASSES = [
    "LLM & GenAI pour le traitement des données",
    "Qualité & Préparation des données avec IA",
    "Retrieval & Connaissances augmentées pour données",
    "Adaptation & Entraînement sur données massives",
    "Architecture & Infrastructures data-centric AI",
    "Observabilité, Gouvernance & Ops",
    "Veille, tendances & synthèse",
]

CATEGORY_TO_CLASS = {
    # --- LLM & GenAI pour le traitement des données ---
    "LLM for ETL & Data Pipelines": "LLM & GenAI pour le traitement des données",
    "AI Agents for Data Processing": "LLM & GenAI pour le traitement des données",
    "Prompt Engineering & LLM Automation for Data": "LLM & GenAI pour le traitement des données",

    # --- Qualité & Préparation des données avec IA ---
    "Data Quality AI & Validation": "Qualité & Préparation des données avec IA",
    "Data Cleaning & Enrichment with LLMs": "Qualité & Préparation des données avec IA",
    "Synthetic Data & Privacy-Preserving Generation": "Qualité & Préparation des données avec IA",

    # --- Retrieval & Connaissances augmentées pour données ---
    "RAG & Retrieval for Enterprise Data": "Retrieval & Connaissances augmentées pour données",
    "Embeddings & Vector Models for Data": "Retrieval & Connaissances augmentées pour données",
    "Graph RAG & Knowledge Graphs in Data Lakes": "Retrieval & Connaissances augmentées pour données",

    # --- Adaptation & Entraînement sur données massives ---
    "Fine-tuning & PEFT on Data Lakes": "Adaptation & Entraînement sur données massives",
    "Foundation & Multimodal Models for Data Tasks": "Adaptation & Entraînement sur données massives",
    "Emerging Algorithms & Novel Approaches for Data": "Adaptation & Entraînement sur données massives",

    # --- Architecture & Infrastructures data-centric AI ---
    "AI-Ready Data & Data Lakes Modernization": "Architecture & Infrastructures data-centric AI",
    "Lakehouse for GenAI & LLM Workloads": "Architecture & Infrastructures data-centric AI",
    "Real-Time Data Processing with AI": "Architecture & Infrastructures data-centric AI",

    # --- Observabilité, Gouvernance & Ops ---
    "Data Observability & LLM Monitoring": "Observabilité, Gouvernance & Ops",
    "Data Governance, Lineage & Compliance for AI": "Observabilité, Gouvernance & Ops",
    "MLOps / LLMOps for Data Pipelines": "Observabilité, Gouvernance & Ops",

    # --- Veille, tendances & synthèse ---
    "Trends & Emerging Models in LLM for Data": "Veille, tendances & synthèse",
    "Best Practices & Reference Architectures": "Veille, tendances & synthèse",
    "Tools, Frameworks & Platforms for LLM-Data": "Veille, tendances & synthèse",
    "Autre / Hors-thème": "Veille, tendances & synthèse",
}


class Veilleur:

    RSS_SOURCES = {
            "arxiv": "https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=500",
            "nvidia": "https://developer.nvidia.com/blog/feed/",

            # --- Nouveaux ajouts ---
            "huggingface": "https://huggingface.co/blog/feed.xml",
            "microsoft_research": "https://www.microsoft.com/en-us/research/feed/",
            "langchain": "https://blog.langchain.dev/rss/",
            "towards_data_science": "https://towardsdatascience.com/feed",
            "mlops_community": "https://mlops.community/feed/"
        }

    def __init__(self, sources=None, scholar_query=None,
                custom_sources=None, date_from=None, date_to=None,
                data_path=None, keywords=None, frequency=None):

        self.rss_sources = dict(self.RSS_SOURCES)
        self.active_sources = []

        # --- Ajouter flux personnalisés ---
        if custom_sources:
            for item in custom_sources:
                # item peut être un dict {url, name} ou juste une string (URL)
                if isinstance(item, dict):
                    url = item.get("url")
                    name = item.get("name", "Custom Source")
                else:
                    url = item
                    name = "Custom Source"
                
                self.rss_sources[name] = url
                self.active_sources.append(name)  # ⚡️ rendre actif directement

        # --- Ajouter flux prédéfinis sélectionnés ---
        if sources:
            for s in sources:
                if s in self.RSS_SOURCES:
                    self.active_sources.append(s)

        # --- autres paramètres ---
        self.scholar_query = scholar_query
        self.date_from = date_from
        self.date_to = date_to
        self.data_path = data_path
        self.frequency = frequency

        # --- normaliser dates ---
        def _to_datetime(v):
            if not v:
                return None
            if isinstance(v, datetime):
                return v
            try:
                return datetime.fromisoformat(str(v))
            except Exception:
                try:
                    return datetime.strptime(str(v), "%Y-%m-%d")
                except Exception:
                    return None

        self.date_from = _to_datetime(self.date_from)
        self.date_to = _to_datetime(self.date_to)

        # --- support keywords ---
        self.keywords = self._parse_keywords(keywords)


    def _parse_keywords(self, keywords):
        if not keywords:
            return []
        return [k.lower().strip() for k in keywords.split(",") if k.strip()]
    
    def _match_keywords(self, text):
        if not self.keywords:
            return True
        text = text.lower()
        return any(k in text for k in self.keywords)

    def _compute_classe(self, categorie: str) -> str:
        """
        Détermine la 'classe' (7 grandes catégories) à partir de la catégorie fine (22).
        """
        if not categorie:
            return "Veille, tendances & synthèse"  # valeur par défaut
        return CATEGORY_TO_CLASS.get(categorie, "Veille, tendances & synthèse")
    

    def _format_rss_date(self, entry):
        for attr in ("published_parsed", "updated_parsed"):
            parsed = getattr(entry, attr, None)
            if parsed:
                return datetime.fromtimestamp(time.mktime(parsed))  # retourne un datetime
        for attr in ("published", "updated"):
            val = getattr(entry, attr, None)
            if val:
                from dateutil.parser import parse
                try:
                    return parse(val)
                except Exception:
                    return None
        return None

    def _clean_text(self, text: str) -> str:
        """Nettoie HTML + bouts WordPress (Read more, The post...)."""
        t = str(text or "").strip()
        if not t:
            return ""

        # enlever <img> puis tout HTML
        t = re.sub(r"<img[^>]*>", " ", t, flags=re.IGNORECASE)
        t = re.sub(r"<[^>]+>", " ", t)
        t = unescape(t)

        # supprimer les suffixes WordPress
        t = re.sub(r"Read more\s*»?", " ", t, flags=re.IGNORECASE)
        t = re.sub(r"The post .*? appeared first on .*", " ", t, flags=re.IGNORECASE)

        # normaliser espaces
        t = " ".join(t.split())
        return t

    def _short_summary(self, text, max_chars=260):
        """Résumé court basé sur le texte nettoyé."""
        clean = self._clean_text(text)
        if len(clean) <= max_chars:
            return clean
        cut = clean[:max_chars].rsplit(" ", 1)[0]
        return cut + "…"


    def _date_in_range(self, published: str = None, parsed=None) -> bool:
        """
        Vérifie si la date d'un article est dans l'intervalle.
        Si parsed est fourni (struct_time), on l'utilise.
        """
        if not self.date_from and not self.date_to:
            return True

        pub_date = None
        if parsed:  # si feedparser a déjà parsé la date
            pub_date = datetime.fromtimestamp(time.mktime(parsed))
        else:
            try:
                # fallback si c'est une string
                from dateutil.parser import parse
                pub_date = parse(published)
            except Exception:
                return False

        if self.date_from and pub_date < self.date_from:
            return False
        if self.date_to and pub_date > self.date_to:
            return False
        return True


    def clean_data(self, items):
        """Nettoie les entrées + garde résumé court et complet."""
        cleaned = []
        for item in items:
            title = str(item.get("title", "")).strip()
            raw_summary = item.get("summary", "")
            full_summary = self._clean_text(raw_summary)
            summary_short = self._short_summary(raw_summary)
            published = str(item.get("published", "")).strip()
            source = str(item.get("source", "")).strip() or "N/A"

            if not self._date_in_range(published):
                continue

            if title and published:
                item["title"] = title
                item["summary"] = full_summary
                item["summary_short"] = summary_short
                item["published"] = published
                item["source"] = source
                cleaned.append(item)
        return cleaned
    
    # ------------------ RSS ------------------

    def collect_rss(self):
        all_articles = []
        for source in self.active_sources:
            if source not in self.rss_sources:
                continue
            feed = feedparser.parse(self.rss_sources[source])
            for entry in feed.entries:
                title = entry.title
                summary = getattr(entry, "summary", "")
                full_text = f"{title} {summary}"
                
                # KHELI

                if not self._match_keywords(full_text):
                    continue

                published = self._format_rss_date(entry)
                if not self._date_in_range(published):
                    continue

                all_articles.append({
                    "title": title,
                    "summary": self._clean_text(summary),
                    "summary_short": self._short_summary(summary),
                    "published": published,
                    "source": source,
                    "link": getattr(entry, "link", ""),
                    "validated": False,
                    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                })
        return all_articles

    # ------------------ Google Scholar ------------------
    def collect_scholar(self):
        if not self.scholar_query:
            return []
        articles = []
        try:
            search = scholarly.search_pubs(self.scholar_query)
            while True:
                pub = next(search)
                bib = pub.get("bib", {})
                title = bib.get("title", "").strip()
                summary = bib.get("abstract", "").strip() if bib.get("abstract") else ""
                full_text = f"{title} {summary}"

                if not self._match_keywords(full_text):
                    continue

                articles.append({
                    "title": title,
                    "summary": self._clean_text(summary),
                    "summary_short": self._short_summary(summary),
                    "published": str(bib.get("pub_year", "N/A")),
                    "source": "Google Scholar",
                    "link": pub.get("pub_url", ""),
                    "validated": False,
                    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                })
        except StopIteration:
            pass
        except Exception as e:
            print("⚠️ Erreur Google Scholar :", e)
        return articles

    # ------------------ RUN ------------------
    def run(self):
        print("🔍 Démarrage de la veille technologique...")
        items = []

        items.extend(self.collect_rss() or [])
        items.extend(self.collect_scholar() or [])

        items = self.clean_data(items)

        # ⚠️ ici on a besoin du modèle -> load_model=True (par défaut)
        analyste = Analyste(load_model=True)

        # 1) Compléter les catégories/classe manquantes pour les articles déjà en BDD
        try:
            uncategorized = get_articles_without_category()
            print(f"➡️ {len(uncategorized)} articles sans categorie trouvés en BDD")
            for art in uncategorized:
                cat = analyste.categorize_article(art)
                classe = self._compute_classe(cat)
                update_article_category_and_classe(art["id"], cat, classe)
        except Exception as e:
            print(f"⚠️ Erreur lors du remplissage des catégories existantes : {e}")

        # 2) Classer les nouveaux articles collectés + leur classe
        for it in items:
            cat = analyste.categorize_article(it)
            it["categorie"] = cat
            it["classe"] = self._compute_classe(cat)

        if not items:
            print("⚠️ Aucun article collecté")
            return

        save_articles(items)
        print(f"✅ {len(items)} articles collectés, classés et enregistrés")



