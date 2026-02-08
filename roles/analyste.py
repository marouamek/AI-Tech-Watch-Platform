import os
import json
import joblib
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS


class Analyste:
    def __init__(self, load_model: bool = True):
        # base du projet : .../Veille_ai
        base_dir = os.path.dirname(os.path.dirname(__file__))

        # chemins des données (optionnels, pour compatibilité)
        self.input_path = os.path.join(base_dir, "data", "raw_data.json")
        # on ne forcera plus l'écriture dans analyzed_data.json
        self.output_path = None

        # chemins des modèles
        model_dir = os.path.join(base_dir, "models", "sentence_transformer_model")
        classifieur_path = os.path.join(base_dir, "models", "classifieur_model.pkl")
        le_path = os.path.join(base_dir, "models", "label_encoder.pkl")

        # flag pour savoir si le ML est dispo
        self.use_ml = False
        self.model = None
        self.classifieur = None
        self.le = None

        if load_model:
            try:
                self.model = SentenceTransformer(model_dir)
                self.classifieur = joblib.load(classifieur_path)
                self.le = joblib.load(le_path)
                self.use_ml = True
            except Exception as e:
                print(f"⚠️ Impossible de charger le modèle ML Analyste : {e}")
                self.use_ml = False
        else:
            print("ℹ️ Analyste : ML désactivé (utilisation des catégories BDD uniquement).")

    # --------- ML : classification ---------
    def classify_article_ml(self, text: str) -> str:
        if not text:
            text = ""
        emb = self.model.encode([text])
        pred_idx = self.classifieur.predict(emb)[0]
        pred_cat = self.le.inverse_transform([pred_idx])[0]
        return pred_cat

    def categorize_article(self, item) -> str:
        """Classe un article complet via le modèle ML."""
        text = (item.get("title", "") + " " + item.get("summary", "")).strip()
        if self.use_ml:
            try:
                return self.classify_article_ml(text)
            except Exception as e:
                print(f"⚠️ Erreur classification ML : {e}")
        return "Autres sujets IA"

    def categorize_keyword(self, kw: str) -> str:
        """Catégorise un mot-clé via le modèle ML."""
        if self.use_ml:
            try:
                return self.classify_article_ml(kw)
            except Exception as e:
                print(f"⚠️ Erreur classification ML pour keyword : {e}")
        return "Autres sujets IA"

    # --------- utils ---------

    def extract_keywords(self, corpus, top_n=15, extra_stopwords=None):
        """
        Extraction de mots-clés lisibles via TF‑IDF, avec filtrage.
        """
        custom_sw = {
            "ai", "llm", "large", "language", "model", "models", "based",
            "using", "use", "dataset", "data", "paper", "study", "result",
            "results", "method", "methods", "approach", "task", "tasks",
            "abstract", "announced", "announce", "arxiv", "cross"
        }
        if extra_stopwords:
            custom_sw.update(extra_stopwords)

        # sklearn veut 'english', une liste ou None -> on convertit en liste
        stop_words = list(ENGLISH_STOP_WORDS.union(custom_sw))

        vectorizer = TfidfVectorizer(
            stop_words=stop_words,
            max_features=top_n,
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-]{2,}\b",
        )
        vectorizer.fit(corpus)
        return vectorizer.get_feature_names_out().tolist()

    def load_data(self):
        """
        Méthode de compatibilité : si le fichier n'existe pas, on renvoie une liste vide.
        """
        try:
            with open(self.input_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return []

    def prepare_corpus(self, data):
        return [
            (item.get("title", "") + " " + item.get("summary", "")).strip()
            for item in data
        ]

    # --------- analyse globale ---------

    def analyze(self, data=None):
            # Si aucun data n'est fourni, on tente de charger depuis un fichier (optionnel).
        if data is None:
            data = self.load_data()
            
        if not data:
            return {
                "total_documents": 0,
                "by_source": {},
                "by_category": {},
                "emerging_keywords": [],
                "emerging_by_category": {},
                "trends": {
                    "top_categories": [],
                    "top_keywords": [],
                },
               
            }

        # On utilise la catégorie déjà en BDD
        by_category = {}
        by_source = {}
        for item in data:
            cat = (
                item.get("categorie")
                or item.get("category")
                or "Autres sujets IA"
            )
            src = item.get("source", "inconnu")
            by_category[cat] = by_category.get(cat, 0) + 1
            by_source[src] = by_source.get(src, 0) + 1

        corpus = self.prepare_corpus(data)

        # Mots-clés globaux
        emerging_keywords = self.extract_keywords(corpus, top_n=30)

        # Mots-clés classés par catégorie (si modèle dispo)
        emerging_by_category = {}
        for kw in emerging_keywords:
            cat = self.categorize_keyword(kw) or "Autres sujets IA"
            emerging_by_category.setdefault(cat, []).append(kw)

        # Top catégories (par nb d’articles)
        top_cat_items = sorted(
            by_category.items(), key=lambda x: x[1], reverse=True
        )[:17]
        top_categories = [c for c, _ in top_cat_items]
        top_keywords = emerging_keywords

        trends = {
            "top_categories": top_categories,
            "top_keywords": top_keywords,
        }

        return {
            "total_documents": len(data),
            "by_source": by_source,
            "by_category": by_category,
            "emerging_keywords": emerging_keywords,
            "emerging_by_category": emerging_by_category,
            "trends": trends,
          
        }
    

