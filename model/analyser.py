"""
model/analyser.py — Smart Resume Analyzer
==========================================
Loads trained pkl files once at startup, then runs analysis on demand.

Usage (from App.py):
    from model.analyser import Analyser
    analyser = Analyser()          # load pkls once at startup
    result   = analyser.run(resume_text, selected_role_id, db)

Result dict:
    {
      "readiness_score"   : 74.3,           # 0-100 blended score
      "predicted_role_id" : 12,             # NB top prediction
      "predicted_role"    : "Data Analyst", # name
      "matched_skills"    : [               # skills found in resume
          {"id":1, "name":"Python",     "importance":"core"},
          ...
      ],
      "missing_skills"    : [               # skills NOT found (core first)
          {"id":16, "name":"TensorFlow", "importance":"core"},
          ...
      ],
      "core_total"        : 7,
      "core_matched"      : 5,
      "secondary_total"   : 5,
      "secondary_matched" : 3,
      "bonus_total"       : 3,
      "bonus_matched"     : 1,
      "recommendations"   : [               # top 3 other roles
          {"role_id":8,  "role_name":"ML Engineer", "score":82.1, "rank":1},
          {"role_id":31, "role_name":"Data Analyst", "score":74.3, "rank":2},
          {"role_id":19, "role_name":"AI Researcher","score":61.7, "rank":3},
      ]
    }
"""

import os
import re
import pickle
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE       = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE, "nb_model.pkl")
VECT_PATH  = os.path.join(BASE, "vectorizer.pkl")
LE_PATH    = os.path.join(BASE, "label_encoder.pkl")

# Score weights — skill gap
# Core carries the most weight: fully matching core = strong signal even with weak secondary
W_CORE      = 0.70
W_SECONDARY = 0.25
W_BONUS     = 0.05

# Final blend weights (default — IT/Data/Engineering heavy roles)
W_SKILL = 0.60   # skill-gap score
W_NB    = 0.20   # NB model confidence
W_RULE  = 0.20   # rule-based score

# Category-specific blend overrides
# NB model was trained on IT/Data resumes — it gives poor scores for Finance,
# HR, Marketing, Teaching etc. Raise skill-gap weight for those categories
# so a person who matches all core skills gets a realistic high score.
CATEGORY_WEIGHTS = {
    #                     W_SKILL  W_NB   W_RULE
    "Teaching":          (0.80,   0.00,   0.20),
    "Healthcare":        (0.75,   0.05,   0.20),
    "HR/Management":     (0.70,   0.10,   0.20),
    "Legal":             (0.75,   0.05,   0.20),
    "Agriculture":       (0.75,   0.05,   0.20),
    "Social Work":       (0.75,   0.05,   0.20),
    "Hospitality":       (0.75,   0.05,   0.20),
    "Sports":            (0.75,   0.05,   0.20),
    "Govt":              (0.75,   0.05,   0.20),
    "Finance":           (0.70,   0.10,   0.20),
    "Marketing":         (0.70,   0.10,   0.20),
    "Design":            (0.65,   0.15,   0.20),
    "Media":             (0.65,   0.15,   0.20),
    "Engineering":       (0.65,   0.15,   0.20),
    "IT/Software":       (0.60,   0.20,   0.20),
    "Data/AI/ML":        (0.60,   0.20,   0.20),
}


# ── Rule-based prediction engine ──────────────────────────────────────────────
#
# Each rule is a dict:
#   role_name   : exact name in job_roles table
#   must        : keywords — ALL must appear (AND logic)
#   any_of      : keyword groups — at least one per group must appear (OR logic)
#   boosts      : extra optional signals that increase confidence
#   min_score   : minimum fraction of signals needed to fire (0.0–1.0)
#
# Scoring:
#   signal_score = (matched_must + matched_any_of + 0.5*matched_boosts)
#                / (len(must) + len(any_of) + 0.5*len(boosts))
#   rule_score   = signal_score × 100   (capped 0–100)
#
# Rules fire independently — highest scoring rule wins for prediction.
# The rule_score for the SELECTED role is used in the blend.

RULES = [
    # ── IT / Software ──────────────────────────────────────────────────
    {
        "role_name": "Frontend Developer",
        "must":   ["HTML", "CSS", "JavaScript"],
        "any_of": [["React", "Angular", "Vue.js", "Next.js", "HTML5", "ReactJS"]],
        "boosts": ["TypeScript", "Webpack", "Tailwind", "SASS", "Figma", "REST API"],
    },
    {
        "role_name": "React Developer",
        "must":   ["React", "JavaScript"],
        "any_of": [["Redux", "React Router", "Next.js", "TypeScript", "JSX"]],
        "boosts": ["Node.js", "REST API", "GraphQL", "Tailwind", "Webpack"],
    },
    {
        "role_name": "Backend Developer",
        "must":   ["API", "database"],
        "any_of": [["Python", "Java", "Node.js", "Go", "Ruby", "PHP", "C#"],
                   ["REST API", "GraphQL", "Microservices", "SQL", "PostgreSQL", "MySQL"]],
        "boosts": ["Docker", "Redis", "RabbitMQ", "Kafka", "CI/CD"],
    },
    {
        "role_name": "Full Stack Developer",
        "must":   ["frontend", "backend"],
        "any_of": [["React", "Angular", "Vue.js", "HTML", "CSS"],
                   ["Node.js", "Python", "Java", "PHP", "Ruby"]],
        "boosts": ["REST API", "MongoDB", "PostgreSQL", "Docker", "TypeScript"],
    },
    {
        "role_name": "DevOps Engineer",
        "must":   ["CI/CD", "Docker"],
        "any_of": [["Kubernetes", "Jenkins", "GitLab CI", "GitHub Actions", "Terraform"],
                   ["AWS", "Azure", "GCP", "cloud"]],
        "boosts": ["Ansible", "Prometheus", "Grafana", "Helm", "Terraform", "monitoring"],
    },
    {
        "role_name": "Site Reliability Engineer",
        "must":   ["reliability", "monitoring"],
        "any_of": [["Prometheus", "Grafana", "Kubernetes", "Docker"],
                   ["SLA", "SLO", "uptime", "incident", "on-call"]],
        "boosts": ["Terraform", "CI/CD", "Python", "Bash", "alerting"],
    },
    {
        "role_name": "Cloud Architect",
        "must":   ["cloud", "architecture"],
        "any_of": [["AWS", "Azure", "GCP"],
                   ["scalability", "infrastructure", "multi-cloud", "serverless"]],
        "boosts": ["Terraform", "Kubernetes", "security", "cost optimisation", "migration"],
    },
    {
        "role_name": "AWS Solutions Architect",
        "must":   ["AWS"],
        "any_of": [["EC2", "S3", "Lambda", "CloudFormation", "VPC", "RDS", "SageMaker"],
                   ["architecture", "solutions", "cloud"]],
        "boosts": ["Terraform", "IAM", "CloudWatch", "DynamoDB", "EKS"],
    },
    {
        "role_name": "Software Engineer",
        "must":   ["software", "development"],
        "any_of": [["Python", "Java", "C++", "Go", "Rust", "C#"],
                   ["algorithms", "data structures", "design patterns", "OOP"]],
        "boosts": ["Git", "Agile", "testing", "CI/CD", "REST API"],
    },
    {
        "role_name": "Mobile App Developer",
        "must":   ["mobile"],
        "any_of": [["Android", "iOS", "Flutter", "React Native", "Swift", "Kotlin"],
                   ["app", "Play Store", "App Store", "mobile development"]],
        "boosts": ["Firebase", "REST API", "UI/UX", "push notifications"],
    },
    {
        "role_name": "Cybersecurity Analyst",
        "must":   ["security"],
        "any_of": [["penetration testing", "vulnerability", "SIEM", "firewall", "encryption"],
                   ["threat", "malware", "OWASP", "SOC", "incident response"]],
        "boosts": ["CISSP", "CEH", "network security", "forensics", "compliance"],
    },
    {
        "role_name": "QA Engineer",
        "must":   ["testing"],
        "any_of": [["Selenium", "Cypress", "Pytest", "JUnit", "test automation", "manual testing"],
                   ["bug", "defect", "test cases", "regression", "UAT"]],
        "boosts": ["CI/CD", "Jira", "Postman", "performance testing", "API testing"],
    },

    # ── Data / AI / ML ─────────────────────────────────────────────────
    {
        "role_name": "Data Scientist",
        "must":   ["Python", "Machine Learning"],
        "any_of": [["Scikit-learn", "TensorFlow", "PyTorch", "XGBoost", "model"],
                   ["statistics", "SQL", "Pandas", "NumPy", "Jupyter"]],
        "boosts": ["deep learning", "NLP", "feature engineering", "Tableau", "A/B Testing"],
    },
    {
        "role_name": "Machine Learning Engineer",
        "must":   ["Machine Learning", "Python"],
        "any_of": [["TensorFlow", "PyTorch", "Scikit-learn", "model deployment", "training"],
                   ["pipeline", "MLflow", "feature engineering", "model optimization"]],
        "boosts": ["Docker", "Kubernetes", "API", "CI/CD", "cloud", "ONNX"],
    },
    {
        "role_name": "MLOps Engineer",
        "must":   ["MLOps", "CI/CD"],
        "any_of": [["MLflow", "Kubeflow", "Docker", "Kubernetes"],
                   ["model deployment", "pipeline", "monitoring", "drift detection"]],
        "boosts": ["Airflow", "DVC", "ArgoCD", "Prometheus", "SageMaker", "Terraform"],
    },
    {
        "role_name": "MLOps Architect",
        "must":   ["MLOps", "architecture"],
        "any_of": [["Kubernetes", "Docker", "CI/CD", "Kubeflow", "MLflow"],
                   ["infrastructure", "scalable", "ML pipeline", "model registry"]],
        "boosts": ["Terraform", "multi-cloud", "Airflow", "DVC", "governance", "SageMaker"],
    },
    {
        "role_name": "Data Engineer",
        "must":   ["pipeline", "ETL"],
        "any_of": [["Apache Spark", "Airflow", "Kafka", "dbt", "SQL"],
                   ["Snowflake", "Redshift", "BigQuery", "data warehouse", "data lake"]],
        "boosts": ["Python", "Hadoop", "stream processing", "Databricks", "cloud"],
    },
    {
        "role_name": "Data Analyst",
        "must":   ["SQL", "analysis"],
        "any_of": [["Tableau", "Power BI", "Excel", "Looker", "visualization"],
                   ["reporting", "dashboard", "KPI", "business intelligence", "insights"]],
        "boosts": ["Python", "statistics", "A/B Testing", "cohort analysis", "Pandas"],
    },
    {
        "role_name": "Business Intelligence Analyst",
        "must":   ["business intelligence"],
        "any_of": [["Tableau", "Power BI", "Looker", "QlikView", "dashboard"],
                   ["KPI", "reporting", "data warehouse", "SQL", "OLAP"]],
        "boosts": ["ETL", "Excel", "stakeholder", "executive reporting", "Snowflake"],
    },
    {
        "role_name": "Deep Learning Engineer",
        "must":   ["deep learning", "neural network"],
        "any_of": [["TensorFlow", "PyTorch", "CNN", "RNN", "LSTM", "Transformer"],
                   ["GPU", "CUDA", "model training", "image classification", "NLP"]],
        "boosts": ["Hugging Face", "ONNX", "model optimization", "distributed training"],
    },
    {
        "role_name": "NLP Engineer",
        "must":   ["NLP"],
        "any_of": [["Hugging Face", "BERT", "GPT", "transformers", "text classification"],
                   ["tokenization", "named entity recognition", "sentiment analysis", "LLM"]],
        "boosts": ["PyTorch", "TensorFlow", "spaCy", "NLTK", "LangChain"],
    },
    {
        "role_name": "LLM Engineer",
        "must":   ["LLM"],
        "any_of": [["GPT", "Claude", "Gemini", "Llama", "fine-tuning", "RAG"],
                   ["LangChain", "prompt engineering", "vector database", "embeddings"]],
        "boosts": ["Hugging Face", "RLHF", "quantization", "inference optimization"],
    },
    {
        "role_name": "Generative AI Engineer",
        "must":   ["generative AI"],
        "any_of": [["LLM", "diffusion", "GPT", "Stable Diffusion", "image generation"],
                   ["LangChain", "RAG", "fine-tuning", "prompt engineering"]],
        "boosts": ["Hugging Face", "vector database", "embeddings", "multimodal"],
    },

    # ── Finance ────────────────────────────────────────────────────────
    {
        "role_name": "Financial Analyst",
        "must":   ["financial", "analysis"],
        "any_of": [["Excel", "financial modeling", "valuation", "forecasting"],
                   ["P&L", "balance sheet", "DCF", "budgeting", "variance analysis"]],
        "boosts": ["SQL", "Python", "Power BI", "Bloomberg", "CFA"],
    },
    {
        "role_name": "Quantitative Analyst",
        "must":   ["quantitative", "financial"],
        "any_of": [["statistics", "Python", "R", "MATLAB", "stochastic"],
                   ["risk", "derivatives", "pricing models", "Monte Carlo", "regression"]],
        "boosts": ["C++", "time series", "Pandas", "NumPy", "machine learning"],
    },

    # ── Design ─────────────────────────────────────────────────────────
    {
        "role_name": "UI/UX Designer",
        "must":   ["design", "user experience"],
        "any_of": [["Figma", "Sketch", "Adobe XD", "wireframe", "prototype"],
                   ["user research", "usability", "interaction design", "UI design"]],
        "boosts": ["HTML", "CSS", "design system", "A/B testing", "accessibility"],
    },
    {
        "role_name": "Product Designer",
        "must":   ["product design"],
        "any_of": [["Figma", "user research", "prototype", "design system"],
                   ["UX", "usability testing", "user journey", "wireframe"]],
        "boosts": ["HTML", "CSS", "Zeplin", "cross-functional", "stakeholder"],
    },

    # ── Management ─────────────────────────────────────────────────────
    {
        "role_name": "Product Manager",
        "must":   ["product", "roadmap"],
        "any_of": [["stakeholder", "requirements", "user stories", "backlog", "sprint"],
                   ["market research", "KPI", "OKR", "prioritization", "go-to-market"]],
        "boosts": ["Jira", "Agile", "Scrum", "A/B testing", "data-driven"],
    },
]


# ── Token helper (must match trainer.py exactly) ──────────────────────────────

def _tok(skill_name: str) -> str:
    """Convert skill name to token — MUST match trainer.skill_to_token."""
    return (skill_name.lower()
            .replace(" ", "_")
            .replace("/", "_")
            .replace("-", "_")
            .replace(".", ""))


# ── Analyser class ────────────────────────────────────────────────────────────

class Analyser:
    """
    Loads pkl files once and exposes a single .run() method.
    Instantiate once at app startup — keep in memory.
    """

    def __init__(self):
        self._vectorizer  = None
        self._nb          = None
        self._le          = None
        self._loaded      = False

    # ── Model loading ─────────────────────────────────────────────────────────

    def load(self):
        """
        Load pkl files from disk into memory.
        Called once at app startup.
        Raises FileNotFoundError if pkls are missing (trainer not run yet).
        """
        for path, label in [
            (VECT_PATH,  "vectorizer.pkl"),
            (MODEL_PATH, "nb_model.pkl"),
            (LE_PATH,    "label_encoder.pkl"),
        ]:
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"{label} not found at {path}\n"
                    f"Run:  python model/trainer.py"
                )

        with open(VECT_PATH,  "rb") as f: self._vectorizer = pickle.load(f)
        with open(MODEL_PATH, "rb") as f: self._nb         = pickle.load(f)
        with open(LE_PATH,    "rb") as f: self._le         = pickle.load(f)
        self._loaded = True
        print("  Analyser: model loaded into memory")

    @property
    def ready(self) -> bool:
        return self._loaded

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self, resume_text: str, selected_role_id: int, db) -> dict:
        """
        Full analysis pipeline.

        Args:
            resume_text      : cleaned text from pdf_parser.extract()
            selected_role_id : job_roles.id the user selected
            db               : active SQLite connection (sqlite3.Row factory)

        Returns:
            result dict (see module docstring)
        """
        if not self._loaded:
            raise RuntimeError("Analyser not loaded. Call analyser.load() at startup.")

        # ── 1. Fetch role skills + category from DB ───────────────────────────
        role_skills = self._fetch_role_skills(selected_role_id, db)
        if not role_skills:
            raise ValueError(f"No skills found for role_id={selected_role_id}")

        role_row = db.execute(
            "SELECT name, category FROM job_roles WHERE id=?", (selected_role_id,)
        ).fetchone()
        selected_role_name     = role_row["name"]     if role_row else ""
        selected_role_category = role_row["category"] if role_row else ""

        # ── 2. Match resume text against skill names ──────────────────────────
        matched_ids = self._match_skills(resume_text, role_skills)

        # ── 3. Skill gap scoring ──────────────────────────────────────────────
        gap         = self._score_gap(role_skills, matched_ids)
        skill_score = gap["skill_score"]

        # ── 4. NB model score for selected role ───────────────────────────────
        nb_score, nb_predicted_name = self._nb_score(resume_text, selected_role_id, db)

        # ── 5. Rule-based score for selected role ─────────────────────────────
        rule_score, rule_predicted_name, rule_best_score = self._rule_score(
            resume_text, selected_role_name
        )

        # ── 6. Category-aware blend ───────────────────────────────────────────
        ws, wn, wr = CATEGORY_WEIGHTS.get(
            selected_role_category, (W_SKILL, W_NB, W_RULE)
        )
        readiness = round(
            (skill_score * ws) + (nb_score * wn) + (rule_score * wr), 1
        )
        readiness = max(0.0, min(100.0, readiness))

        # ── NB perfect confidence override ────────────────────────────────────
        # If NB model is 100% confident about the selected role, force 100.
        if nb_score >= 100.0:
            readiness = 100.0

        # ── All-skills matched override ───────────────────────────────────────
        # If every single skill (core + secondary + bonus) is matched,
        # force the final score to 100% regardless of NB/rules.
        total_skills   = len(role_skills)
        matched_skills = len(matched_ids)
        if total_skills > 0 and matched_skills >= total_skills:
            readiness = 100.0

        # ── 7. Predicted role: rule engine if confident, else NB ──────────────
        if rule_best_score >= 60.0 and rule_predicted_name:
            predicted_role_name = rule_predicted_name
        else:
            predicted_role_name = nb_predicted_name

        # ── 8. Top recommendations (other roles) ──────────────────────────────
        recommendations = self._recommend(resume_text, selected_role_id, db)

        # ── 9. Resolve predicted role id ─────────────────────────────────────
        predicted_role_id = self._role_id_by_name(predicted_role_name, db)

        # ── 10. Detailed scoring breakdown ────────────────────────────────────
        core_pct    = round((gap["core_matched"]      / gap["core_total"]      * 100) if gap["core_total"]      else 0, 1)
        sec_pct     = round((gap["secondary_matched"] / gap["secondary_total"] * 100) if gap["secondary_total"] else 0, 1)
        bonus_pct   = round((gap["bonus_matched"]     / gap["bonus_total"]     * 100) if gap["bonus_total"]     else 0, 1)

        scoring_breakdown = {
            # Component scores (0-100 each)
            "skill_gap_score"  : round(skill_score, 1),
            "nb_score"         : round(nb_score,    1),
            "rule_score"       : round(rule_score,  1),
            # Weights used
            "weight_skill"     : round(ws * 100),
            "weight_nb"        : round(wn * 100),
            "weight_rule"      : round(wr * 100),
            # Sub-breakdown of skill gap
            "core_pct"         : core_pct,
            "secondary_pct"    : sec_pct,
            "bonus_pct"        : bonus_pct,
            # Weighted contributions to final score
            "skill_contribution" : round(skill_score * ws, 1),
            "nb_contribution"    : round(nb_score    * wn, 1),
            "rule_contribution"  : round(rule_score  * wr, 1),
            # Category
            "role_category"    : selected_role_category,
        }

        return {
            "readiness_score"   : readiness,
            "predicted_role_id" : predicted_role_id,
            "predicted_role"    : predicted_role_name,
            "matched_skills"    : gap["matched"],
            "missing_skills"    : gap["missing"],
            "core_total"        : gap["core_total"],
            "core_matched"      : gap["core_matched"],
            "secondary_total"   : gap["secondary_total"],
            "secondary_matched" : gap["secondary_matched"],
            "bonus_total"       : gap["bonus_total"],
            "bonus_matched"     : gap["bonus_matched"],
            "recommendations"    : recommendations,
            "scoring_breakdown"  : scoring_breakdown,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _fetch_role_skills(self, role_id: int, db) -> list:
        """
        Return list of dicts:
            [{"id": skill_id, "name": skill_name, "importance": "core"}, ...]
        ordered core → secondary → bonus.
        """
        rows = db.execute("""
            SELECT s.id, s.name, rs.importance
            FROM role_skills rs
            JOIN skills s ON s.id = rs.skill_id
            WHERE rs.role_id = ?
            ORDER BY
                CASE rs.importance
                    WHEN 'core'      THEN 1
                    WHEN 'secondary' THEN 2
                    WHEN 'bonus'     THEN 3
                END,
                s.name
        """, (role_id,)).fetchall()
        return [dict(r) for r in rows]

    # Aliases: resume variants → canonical skill name in DB
    SKILL_ALIASES = {
        # ── Frontend ─────────────────────────────────────────────────────────
        "HTML5":                    "HTML",
        "HTML 5":                   "HTML",
        "CSS3":                     "CSS",
        "CSS 3":                    "CSS",
        "ES6":                      "JavaScript",
        "ES2015":                   "JavaScript",
        "JS":                       "JavaScript",
        "ReactJS":                  "React",
        "React.js":                 "React",
        "React JS":                 "React",
        "React Native":             "React",
        "VueJS":                    "Vue.js",
        "Vue JS":                   "Vue.js",
        "AngularJS":                "Angular",
        "Angular.js":               "Angular",
        "Angular JS":               "Angular",
        "NodeJS":                   "Node.js",
        "Node JS":                  "Node.js",
        "ExpressJS":                "Express.js",
        "Express JS":               "Express.js",
        "NextJS":                   "Next.js",
        "Next JS":                  "Next.js",
        "Responsive Web Design":    "Responsive Design",
        "responsive":               "Responsive Design",
        # ── Backend / API ────────────────────────────────────────────────────
        "RESTful API":              "REST API",
        "RESTful APIs":             "REST API",
        "REST APIs":                "REST API",
        "RESTful":                  "REST API",
        "REST":                     "REST API",
        "API design":               "REST API",
        "API development":          "API Development",
        "GraphQL API":              "GraphQL",
        "PostgresQL":               "PostgreSQL",
        "Postgres":                 "PostgreSQL",
        "MS SQL":                   "SQL Server",
        "MSSQL":                    "SQL Server",
        "MySQL Database":           "MySQL",
        "object oriented":          "OOP",
        "object-oriented":          "OOP",
        "OOPs":                     "OOP",
        "OOPS":                     "OOP",
        "microservice":             "Microservices",
        "micro-services":           "Microservices",
        "unit testing":             "Testing",
        "automated testing":        "Testing",
        "test automation":          "Testing",
        "JWT authentication":       "JWT",
        "JSON Web Token":           "JWT",
        # ── DevOps / Cloud ───────────────────────────────────────────────────
        "Google Cloud":             "GCP",
        "Google Cloud Platform":    "GCP",
        "Azure Machine Learning":   "Azure ML",
        "AWS SageMaker":            "SageMaker",
        "Amazon SageMaker":         "SageMaker",
        "CI CD":                    "CI/CD",
        "CI/CD pipelines":          "CI/CD",
        "CI/CD pipeline":           "CI/CD",
        "GitLab CI/CD":             "GitLab CI",
        "Gitlab":                   "GitLab",
        "agile methodology":        "Agile",
        "agile development":        "Agile",
        "scrum methodology":        "Scrum",
        "system design":            "System Design",
        # ── Data / ML ────────────────────────────────────────────────────────
        "Spark":                    "Apache Spark",
        "PySpark":                  "Apache Spark",
        "Kafka":                    "Apache Kafka",
        "Scikit Learn":             "Scikit-learn",
        "sklearn":                  "Scikit-learn",
        "sci-kit learn":            "Scikit-learn",
        "Scikit learn":             "Scikit-learn",
        "ML Ops":                   "MLOps",
        "D3":                       "D3.js",
        "D3 js":                    "D3.js",
        "data analysis":            "Data Analysis",
        "data analytics":           "Data Analysis",
        "data analyst":             "Data Analysis",
        "business intelligence":    "Business Intelligence",
        "BI":                       "Business Intelligence",
        "PowerBI":                  "Power BI",
        "power bi":                 "Power BI",
        # ── Finance ──────────────────────────────────────────────────────────
        "financial modelling":      "Financial Modeling",
        "financial model":          "Financial Modeling",
        "financial models":         "Financial Modeling",
        "DCF":                      "Valuation",
        "DCF valuation":            "Valuation",
        "equity valuation":         "Valuation",
        "company valuation":        "Valuation",
        "budget":                   "Budgeting",
        "forecast":                 "Forecasting",
        "forecasting & budgeting":  "Budgeting",
        "investment banking":       "Investment Analysis",
        "MS Excel":                 "Excel",
        "Microsoft Excel":          "Excel",
        "MS PowerPoint":            "PowerPoint",
        "Microsoft PowerPoint":     "PowerPoint",
        "accountant":               "Accounting",
        "accounts":                 "Accounting",
        # ── HR ───────────────────────────────────────────────────────────────
        "talent management":        "Talent Acquisition",
        "hiring":                   "Recruitment",
        "sourcing candidates":      "Sourcing",
        "candidate sourcing":       "Sourcing",
        "HR software":              "HRMS",
        "HRIS":                     "HRMS",
        "HR information system":    "HRMS",
        "performance appraisal":    "Performance Management",
        "performance review":       "Performance Management",
        "employee engagement":      "Employee Relations",
        "LinkedIn":                 "LinkedIn Recruiting",
        "applicant tracking":       "ATS",
        # ── Marketing ────────────────────────────────────────────────────────
        "search engine optimization":"SEO",
        "search engine optimisation":"SEO",
        "pay per click":            "Google Ads",
        "PPC":                      "Google Ads",
        "Google Adwords":           "Google Ads",
        "AdWords":                  "Google Ads",
        "social media marketing":   "Social Media Management",
        "social media":             "Social Media Management",
        "email campaigns":          "Email Marketing",
        "content strategy":         "Content Marketing",
        "Google Analytics 4":       "Google Analytics",
        "GA4":                      "Google Analytics",
        "GA":                       "Google Analytics",
        "marketing analytics":      "Analytics",
        "digital marketing":        "Digital Marketing",
        "keyword research":         "Keyword Research",
        "on page SEO":              "On-Page SEO",
        "on-page optimization":     "On-Page SEO",
        "link building":            "Link Building",
        "backlinks":                "Link Building",
        # ── Teaching ─────────────────────────────────────────────────────────
        "CBSE":                     "CBSE Curriculum",
        "CBSE board":               "CBSE Curriculum",
        "NCERT books":              "NCERT",
        "NCERT textbooks":          "NCERT",
        "lesson plan":              "Lesson Planning",
        "lesson plans":             "Lesson Planning",
        "classroom":                "Classroom Management",
        "class management":         "Classroom Management",
        "bloom taxonomy":           "Bloom's Taxonomy",
        "blooms taxonomy":          "Bloom's Taxonomy",
        "child psychology":         "Educational Psychology",
        "student evaluation":       "Student Assessment",
        "exam coaching":            "Exam Preparation",
        "activity based":           "Activity Based Learning",
        "project based":            "Project Based Learning",
        # ── Subject Teaching ─────────────────────────────────────────────────
        "maths":                    "Mathematics",
        "math":                     "Mathematics",
        "mathematics teacher":      "Mathematics",
        "hindi":                    "Hindi Teaching",
        "hindi language":           "Hindi Teaching",
        "devanagari":               "Devanagari Script",
        "vyaakaran":                "Vyakaran",
        "hindi vyakaran":           "Hindi Grammar",
        "physics teacher":          "Physics",
        "chemistry teacher":        "Chemistry",
        "biology teacher":          "Biology",
        "science teacher":          "Science Experiments",
        "lab":                      "Lab Management",
        "laboratory":               "Lab Management",
        "laboratory management":    "Lab Management",
        "practicals":               "Science Experiments",
        "practical":                "Science Experiments",
        "lab work":                 "Lab Management",
        "experiments":              "Science Experiments",
        "history teacher":          "History",
        "geography teacher":        "Geography",
        "civics teacher":           "Civics",
        "english teacher":          "English Literature",
        "grammar teacher":          "Grammar",
        "literature teacher":       "Literature",
        "computer teacher":         "Computer Fundamentals",
        "computers":                "Computer Fundamentals",
        "information technology":   "Computer Fundamentals",
        "programming basics":       "Programming",
        "coding":                   "Programming",
        "algebra teacher":          "Algebra",
        "geometry teacher":         "Geometry",
        "calculus teacher":         "Calculus",
        "trigonometry teacher":     "Trigonometry",
        "environmental studies":    "Environmental Science",
        "EVS":                      "Environmental Science",
        "life science":             "Life Sciences",
        "earth science":            "Earth Sciences",
    }

    def _match_skills(self, resume_text: str, role_skills: list) -> set:
        """
        Return set of skill IDs found in resume_text.
        Uses word-boundary matching, case-insensitive.
        Also checks SKILL_ALIASES so resume variants like HTML5, React.js,
        ReactJS, Spark, GitLab CI/CD etc. map to their canonical DB names.
        """
        text_lower = resume_text.lower()
        matched    = set()

        # Build reverse lookup: canonical_lower → [alias, ...]
        alias_map = {}
        for alias, canonical in self.SKILL_ALIASES.items():
            alias_map.setdefault(canonical.lower(), []).append(alias)

        def _search(term):
            escaped = re.escape(term)
            pattern = (
                r"(?<![A-Za-z])" + escaped + r"(?![A-Za-z+#])"
                if len(term) <= 2
                else r"\b" + escaped + r"\b"
            )
            try:
                return bool(re.search(pattern, resume_text, flags=re.IGNORECASE))
            except re.error:
                return term.lower() in text_lower

        for skill in role_skills:
            name = skill["name"]
            # Check canonical name first
            if _search(name):
                matched.add(skill["id"])
                continue
            # Check aliases for this canonical name
            for alias in alias_map.get(name.lower(), []):
                if _search(alias):
                    matched.add(skill["id"])
                    break

        return matched

    def _score_gap(self, role_skills: list, matched_ids: set) -> dict:
        """
        Calculate weighted skill gap score and build matched/missing lists.

        Scoring:
            core_score      = matched_core / total_core × 100
            secondary_score = matched_secondary / total_secondary × 100
            bonus_score     = matched_bonus / total_bonus × 100
            skill_score     = core×0.6 + secondary×0.3 + bonus×0.1
        """
        core      = [s for s in role_skills if s["importance"] == "core"]
        secondary = [s for s in role_skills if s["importance"] == "secondary"]
        bonus     = [s for s in role_skills if s["importance"] == "bonus"]

        def score(group):
            if not group:
                return 0.0, [], []
            matched = [s for s in group if s["id"] in matched_ids]
            missing = [s for s in group if s["id"] not in matched_ids]
            pct     = (len(matched) / len(group)) * 100
            return pct, matched, missing

        core_pct,  core_matched,  core_missing  = score(core)
        sec_pct,   sec_matched,   sec_missing   = score(secondary)
        bonus_pct, bonus_matched, bonus_missing = score(bonus)

        skill_score = (
            (core_pct  * W_CORE)
          + (sec_pct   * W_SECONDARY)
          + (bonus_pct * W_BONUS)
        )

        # Build output lists — missing core first, then secondary, then bonus
        all_matched = core_matched + sec_matched + bonus_matched
        all_missing = core_missing + sec_missing + bonus_missing

        return {
            "skill_score"       : skill_score,
            "matched"           : all_matched,
            "missing"           : all_missing,
            "core_total"        : len(core),
            "core_matched"      : len(core_matched),
            "secondary_total"   : len(secondary),
            "secondary_matched" : len(sec_matched),
            "bonus_total"       : len(bonus),
            "bonus_matched"     : len(bonus_matched),
        }

    def _nb_score(self, resume_text: str, selected_role_id: int, db) -> tuple:
        """
        Run NB model on resume text.
        Returns (score_for_selected_role 0-100, predicted_role_name).

        score_for_selected_role = probability the model assigns to the
        selected role × 100. High when resume strongly matches that role.
        """
        # Convert resume text to token string (match training format)
        tokens = self._text_to_tokens(resume_text, db)
        if not tokens:
            return 0.0, ""

        xv     = self._vectorizer.transform([tokens])
        proba  = self._nb.predict_proba(xv)[0]
        pred_i = self._nb.predict(xv)[0]

        predicted_name = self._le.inverse_transform([pred_i])[0]

        # Find probability for the SELECTED role
        selected_role_name = db.execute(
            "SELECT name FROM job_roles WHERE id=?", (selected_role_id,)
        ).fetchone()

        if selected_role_name:
            classes = list(self._le.classes_)
            name    = selected_role_name["name"]
            if name in classes:
                idx        = classes.index(name)
                role_prob  = proba[idx] * 100
            else:
                role_prob  = 0.0
        else:
            role_prob = 0.0

        # Scale relative to the actual max probability in THIS distribution.
        # Hardcoding 0.3 was wrong — real max is ~0.07 for broad profiles.
        # Relative scaling: selected_role_prob / max_prob * 100
        max_prob = float(max(proba))
        if max_prob > 0 and role_prob > 0:
            nb_score = min(100.0, (role_prob / 100 / max_prob) * 100)
        else:
            nb_score = 0.0

        return round(nb_score, 1), predicted_name

    def _text_to_tokens(self, resume_text: str, db) -> str:
        """
        Convert raw resume text to token string for NB model.
        Looks up ALL skill names from DB and converts matches to tokens.
        """
        all_skills = db.execute("SELECT name FROM skills").fetchall()
        text_lower = resume_text.lower()
        tokens     = []

        for row in all_skills:
            name    = row["name"]
            escaped = re.escape(name)
            pattern = (r"(?<![A-Za-z])" + escaped + r"(?![A-Za-z+#])"
                       if len(name) <= 2
                       else r"\b" + escaped + r"\b")
            try:
                if re.search(pattern, resume_text, flags=re.IGNORECASE):
                    tokens.append(_tok(name))
            except re.error:
                if name.lower() in text_lower:
                    tokens.append(_tok(name))

        return " ".join(tokens)

    def _recommend(self, resume_text: str, selected_role_id: int, db,
                   top_n: int = 5) -> list:
        """
        Two-pass recommendation:
          Pass 1 — fast token overlap across all 686 roles → top 30 candidates
          Pass 2 — full category-aware skill-gap blend on those 30 only
        This keeps accuracy high while staying under ~1s.
        """
        all_roles = db.execute(
            "SELECT id, name, category FROM job_roles"
        ).fetchall()

        # ── Pass 1: fast token overlap — single bulk query ──────────────────
        resume_lower = resume_text.lower()

        # Fetch all role skills in one query
        all_role_skills = db.execute("""
            SELECT rs.role_id, s.name
            FROM role_skills rs
            JOIN skills s ON s.id = rs.skill_id
            WHERE rs.importance IN ('core','secondary')
        """).fetchall()

        # Group by role_id
        from collections import defaultdict
        skills_by_role = defaultdict(list)
        for row in all_role_skills:
            skills_by_role[row["role_id"]].append(row["name"].lower())

        # Build role lookup
        role_lookup = {r["id"]: r for r in all_roles}

        candidates = []
        for role in all_roles:
            if role["id"] == selected_role_id:
                continue
            role_skills_lower = skills_by_role.get(role["id"], [])
            if not role_skills_lower:
                continue
            hits = sum(1 for s in role_skills_lower if s in resume_lower)
            overlap = hits / len(role_skills_lower) * 100
            candidates.append((role["id"], role["name"], role["category"], overlap))

        # Keep top 30 by overlap
        candidates.sort(key=lambda x: -x[3])
        top_candidates = candidates[:30]

        # ── NB batch: single predict_proba for all candidates at once ───────
        tokens = self._text_to_tokens(resume_text, db)
        xv     = self._vectorizer.transform([tokens]) if tokens else None
        if xv is not None:
            proba        = self._nb.predict_proba(xv)[0]
            classes      = list(self._le.classes_)
            prob_by_name = {name: float(proba[i]) for i, name in enumerate(classes)}
            max_prob     = max(proba) if max(proba) > 0 else 1.0
        else:
            prob_by_name = {}
            max_prob     = 1.0

        # ── Pass 2: full identical blend to run() on top 30 candidates ───────
        scored = []
        for rid, rname, rcat, _ in top_candidates:
            role_skills = self._fetch_role_skills(rid, db)
            if not role_skills:
                continue

            matched_ids = self._match_skills(resume_text, role_skills)
            gap         = self._score_gap(role_skills, matched_ids)
            skill_score = gap["skill_score"]

            # NB from batch (no extra DB call)
            raw_prob = prob_by_name.get(rname, 0.0)
            nb_score = raw_prob / max_prob * 100

            rule_score, _, _ = self._rule_score(resume_text, rname)

            # Exact same category-aware blend as run()
            ws, wn, wr = CATEGORY_WEIGHTS.get(rcat or "", (W_SKILL, W_NB, W_RULE))
            blended = round(
                (skill_score * ws) + (nb_score * wn) + (rule_score * wr), 1
            )
            blended = max(0.0, min(100.0, blended))

            # NB perfect confidence override — same rule as run()
            if nb_score >= 100.0:
                blended = 100.0

            # All-skills matched override — same rule as run()
            if len(role_skills) > 0 and len(matched_ids) >= len(role_skills):
                blended = 100.0

            scored.append((rid, rname, blended))

        scored.sort(key=lambda x: -x[2])

        return [
            {"role_id": rid, "role_name": rname, "score": score, "rank": i + 1}
            for i, (rid, rname, score) in enumerate(scored[:top_n])
        ]

    def _rule_score(self, resume_text: str, selected_role_name: str) -> tuple:
        """
        Run rule-based prediction on resume_text.

        Returns:
            (score_for_selected_role 0-100, best_matching_role_name, best_score)

        Logic per rule:
            - All `must` keywords must appear (case-insensitive, word boundary)
            - At least one keyword from each `any_of` group must appear
            - `boosts` add 0.5 each to signal count
            - score = matched_signals / max_signals * 100
        """
        text_lower = resume_text.lower()

        def _hit(term):
            """Word-boundary search, case-insensitive."""
            escaped = re.escape(term)
            pattern = r"\b" + escaped + r"\b"
            try:
                return bool(re.search(pattern, resume_text, flags=re.IGNORECASE))
            except re.error:
                return term.lower() in text_lower

        selected_score = 0.0
        best_name      = ""
        best_score     = 0.0

        for rule in RULES:
            # ── must: ALL required ────────────────────────────────────
            if not all(_hit(k) for k in rule["must"]):
                continue

            # ── any_of: at least one per group ────────────────────────
            any_of = rule.get("any_of", [])
            matched_groups = sum(
                1 for group in any_of if any(_hit(k) for k in group)
            )
            if any_of and matched_groups < len(any_of):
                # Partial credit if ≥ 50% of groups matched
                if matched_groups < max(1, len(any_of) * 0.5):
                    continue

            # ── boosts: optional extra signals ────────────────────────
            boosts      = rule.get("boosts", [])
            boost_hits  = sum(0.5 for k in boosts if _hit(k))

            # ── score ─────────────────────────────────────────────────
            max_signals = len(rule["must"]) + len(any_of) + len(boosts) * 0.5
            got_signals = len(rule["must"]) + matched_groups + boost_hits
            score       = min(100.0, round((got_signals / max_signals) * 100, 1))

            if score > best_score:
                best_score = score
                best_name  = rule["role_name"]

            if rule["role_name"].lower() == selected_role_name.lower():
                selected_score = score

        return selected_score, best_name, best_score

    def _role_id_by_name(self, role_name: str, db) -> Optional[int]:
        """Look up role_id by name. Returns None if not found."""
        row = db.execute(
            "SELECT id FROM job_roles WHERE name=?", (role_name,)
        ).fetchone()
        return row["id"] if row else None
analyser = Analyser()