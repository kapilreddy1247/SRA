"""
model/trainer.py — Smart Resume Analyzer
==========================================
Reads skills.csv + roles.csv, generates synthetic training data,
trains a TF-IDF + MultinomialNB pipeline, and saves .pkl files.

Run once:
    python model/trainer.py

Output:
    model/nb_model.pkl
    model/vectorizer.pkl
    model/label_encoder.pkl

Re-run whenever you update roles.csv or skills.csv.
"""

import os
import csv
import random
import pickle
import time
from collections import defaultdict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.preprocessing import LabelEncoder
from sklearn.pipeline import Pipeline
from sklearn.calibration import CalibratedClassifierCV

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE       = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE, "data")
SKILLS_CSV = os.path.join(DATA_DIR, "skills.csv")
ROLES_CSV  = os.path.join(DATA_DIR, "roles.csv")
MODEL_PATH = os.path.join(BASE, "nb_model.pkl")
VECT_PATH  = os.path.join(BASE, "vectorizer.pkl")
LE_PATH    = os.path.join(BASE, "label_encoder.pkl")

# ── Tuning ────────────────────────────────────────────────────────────────────
SNIPPETS_PER_ROLE  = 80      # synthetic resume snippets per role
CORE_PROB          = 0.90    # probability core skill appears in snippet
SECONDARY_PROB     = 0.55    # probability secondary skill appears
BONUS_PROB         = 0.25    # probability bonus skill appears
MIN_SKILLS_SNIPPET = 8       # min skills per snippet
MAX_SKILLS_SNIPPET = 20      # max skills per snippet
RANDOM_SEED        = 42


# ── Step 1: Load CSVs ─────────────────────────────────────────────────────────

def load_skills():
    """Return {skill_id: skill_name}."""
    skills = {}
    with open(SKILLS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            skills[int(r["skill_id"])] = r["skill_name"].strip()
    return skills


def load_roles():
    """
    Return {role_id: {"name": str, "category": str,
                       "core": [name,...], "secondary": [...], "bonus": [...]}}
    """
    roles = defaultdict(lambda: {
        "name": "", "category": "",
        "core": [], "secondary": [], "bonus": []
    })
    with open(ROLES_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rid = int(r["role_id"])
            imp = r["importance"].strip()
            sname = r["skill_name"].strip()
            roles[rid]["name"]     = r["role_name"].strip()
            roles[rid]["category"] = r["category"].strip()
            roles[rid][imp].append(sname)
    return dict(roles)


# ── Step 2: Synthetic data generation ────────────────────────────────────────

def skill_to_token(skill_name):
    """Convert skill name to a clean token: 'Machine Learning' → 'machine_learning'."""
    return skill_name.lower().replace(" ", "_").replace("/", "_").replace("-", "_").replace(".", "")


def generate_snippets(roles, n=SNIPPETS_PER_ROLE, seed=RANDOM_SEED):
    """
    For each role generate n synthetic 'resume text' snippets.
    Each snippet is a space-separated string of skill tokens,
    weighted by importance (core appears most, bonus least).

    Returns:
        docs   : list of strings (training documents)
        labels : list of role names (parallel to docs)
    """
    rng   = random.Random(seed)
    docs   = []
    labels = []

    for rid, role in roles.items():
        core      = [skill_to_token(s) for s in role["core"]]
        secondary = [skill_to_token(s) for s in role["secondary"]]
        bonus     = [skill_to_token(s) for s in role["bonus"]]

        # Edge case — role with very few skills still gets trained
        all_skills = core + secondary + bonus
        if not all_skills:
            continue

        for _ in range(n):
            selected = []

            # Sample core skills with high probability
            for s in core:
                if rng.random() < CORE_PROB:
                    selected.append(s)

            # Sample secondary skills with medium probability
            for s in secondary:
                if rng.random() < SECONDARY_PROB:
                    selected.append(s)

            # Sample bonus skills with low probability
            for s in bonus:
                if rng.random() < BONUS_PROB:
                    selected.append(s)

            # Ensure minimum length — fill from all_skills if needed
            if len(selected) < MIN_SKILLS_SNIPPET:
                extras = [s for s in all_skills if s not in selected]
                rng.shuffle(extras)
                selected += extras[:MAX(0, MIN_SKILLS_SNIPPET - len(selected))]

            # Cap to max length
            rng.shuffle(selected)
            selected = selected[:MAX_SKILLS_SNIPPET]

            if selected:
                # Repeat core skills 2-3x to reinforce their importance
                boosted = selected[:]
                for s in core:
                    if s in selected:
                        boosted.extend([s] * rng.randint(1, 2))
                rng.shuffle(boosted)
                docs.append(" ".join(boosted))
                labels.append(role["name"])

    return docs, labels


# ── Step 3: Train ─────────────────────────────────────────────────────────────

def train(docs, labels):
    """
    Fit TF-IDF vectorizer + MultinomialNB.
    Returns (vectorizer, nb_model, label_encoder).
    """
    print(f"  Fitting TF-IDF vectorizer ...")
    vectorizer = TfidfVectorizer(
        analyzer   = "word",
        ngram_range = (1, 2),       # unigrams + bigrams
        max_features = 12000,        # top 12k features
        sublinear_tf = True,         # log(tf) scaling
        min_df       = 2,            # ignore terms in fewer than 2 docs
    )
    X = vectorizer.fit_transform(docs)
    print(f"  Vocabulary size : {len(vectorizer.vocabulary_):,}")
    print(f"  Feature matrix  : {X.shape[0]:,} docs × {X.shape[1]:,} features")

    # Encode labels
    le     = LabelEncoder()
    y      = le.fit_transform(labels)
    print(f"  Classes         : {len(le.classes_)}")

    print(f"  Training MultinomialNB ...")
    nb = MultinomialNB(alpha=0.15)   # Laplace smoothing
    nb.fit(X, y)

    return vectorizer, nb, le


# ── Step 4: Save ──────────────────────────────────────────────────────────────

def save(vectorizer, nb, le):
    with open(VECT_PATH,  "wb") as f: pickle.dump(vectorizer, f)
    with open(MODEL_PATH, "wb") as f: pickle.dump(nb,         f)
    with open(LE_PATH,    "wb") as f: pickle.dump(le,         f)

    vect_kb  = os.path.getsize(VECT_PATH)  // 1024
    model_kb = os.path.getsize(MODEL_PATH) // 1024
    le_kb    = os.path.getsize(LE_PATH)    // 1024

    print(f"\n  Saved:")
    print(f"    vectorizer.pkl     {vect_kb:>5} KB")
    print(f"    nb_model.pkl       {model_kb:>5} KB")
    print(f"    label_encoder.pkl  {le_kb:>5} KB")


# ── Step 5: Quick sanity check ────────────────────────────────────────────────

def sanity_check(vectorizer, nb, le):
    """
    Test with skill-name lists to confirm the model predicts sensible roles.
    Skills must be passed as lists (not raw text) to match training token format.
    """
    tests = [
        (["Python","Pandas","NumPy","Scikit-learn","Statistics","Feature Engineering","TensorFlow","SQL"],
         "Data Scientist"),
        (["Lesson Planning","Classroom Management","Student Assessment","CBSE Curriculum","Communication","Child Development"],
         "Primary School Teacher"),
        (["AutoCAD","Structural Analysis","Civil 3D","Construction Management","Surveying","Geotechnical Engineering"],
         "Civil Engineer"),
        (["Photoshop","Illustrator","Figma","UI Design","Brand Identity","Typography","Color Theory"],
         "Graphic Designer"),
        (["Cardiology","Patient Care","Emergency Medicine","Surgery","Anatomy","Pharmacology"],
         "Cardiologist"),
    ]

    print("\n  Sanity checks:")
    print(f"  {'Skills (first 3)':<45} {'Expected':<30} {'Predicted':<30} OK?")
    print("  " + "─" * 115)

    for skill_list, expected in tests:
        tokens = " ".join(skill_to_token(s) for s in skill_list)
        xv     = vectorizer.transform([tokens])
        proba  = nb.predict_proba(xv)[0]
        top5   = proba.argsort()[-5:][::-1]
        pred   = le.inverse_transform([nb.predict(xv)[0]])[0]
        # Check if expected appears in top 5
        top5_names = [le.inverse_transform([i])[0] for i in top5]
        in_top5    = any(expected.lower() in n.lower() or n.lower() in expected.lower()
                         for n in top5_names)
        ok    = "✓" if (expected.lower() in pred.lower()
                        or pred.lower() in expected.lower()) else ("~" if in_top5 else "✗")
        short = ", ".join(skill_list[:3]) + "..."
        print(f"  {short:<45} {expected:<30} {pred:<30} {ok}")
        if ok == "✗":
            print(f"    Top 5: {top5_names}")


# ── Main ──────────────────────────────────────────────────────────────────────

def MAX(a, b):  # noqa — avoid shadowing builtin in snippet generator
    return a if a > b else b


def main():
    print("\n── Phase 2: Training NB Model ──────────────────────────")
    t0 = time.time()

    # Load
    print("\n[1/4] Loading CSVs ...")
    skills = load_skills()
    roles  = load_roles()
    print(f"  Skills loaded   : {len(skills):,}")
    print(f"  Roles loaded    : {len(roles):,}")

    # Generate
    print(f"\n[2/4] Generating synthetic training data ...")
    print(f"  {len(roles):,} roles × {SNIPPETS_PER_ROLE} snippets = "
          f"{len(roles) * SNIPPETS_PER_ROLE:,} expected docs")
    docs, labels = generate_snippets(roles)
    print(f"  Generated       : {len(docs):,} training documents")

    # Label distribution check
    from collections import Counter
    cat_counts = Counter()
    role_map = {r["name"]: r["category"] for r in roles.values()}
    for lbl in labels:
        cat_counts[role_map.get(lbl, "Unknown")] += 1
    print("\n  Docs per category:")
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f"    {cat:<30} {cnt:>6}")

    # Train
    print(f"\n[3/4] Training ...")
    vectorizer, nb, le = train(docs, labels)

    # Save
    print(f"\n[4/4] Saving model files ...")
    save(vectorizer, nb, le)

    # Sanity check
    sanity_check(vectorizer, nb, le)

    elapsed = time.time() - t0
    print(f"\n── Training complete in {elapsed:.1f}s ──────────────────────\n")


if __name__ == "__main__":
    main()
