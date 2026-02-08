import json
from datetime import datetime

class Decideur:
    def __init__(self):
        self.input_path = "data/analyzed_data.json"

    def load_analysis(self):
        with open(self.input_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def generate_brief(self):
        analysis = self.load_analysis()

        date = datetime.now().strftime("%d/%m/%Y")

        keywords = ", ".join(analysis["emerging_keywords"])

        brief = f"""
==============================
📌 FICHE DE VEILLE STRATÉGIQUE
==============================

Date : {date}
Domaine : {analysis["focus_domain"]}

📊 Synthèse globale
- Nombre de documents analysés : {analysis["total_documents"]}

🔥 Tendances émergentes détectées
- {keywords}

🧠 Interprétation
Les publications récentes montrent un intérêt croissant pour
l’utilisation des modèles de langage dans le traitement et
l’exploitation des données à grande échelle.

🎯 Recommandations
- Surveiller les approches LLM appliquées aux pipelines data
- Explorer les architectures RAG sur data lakes
- Anticiper l’impact sur les métiers Data Engineering

⚠️ Niveau de priorité : ÉLEVÉ
"""

        return brief

