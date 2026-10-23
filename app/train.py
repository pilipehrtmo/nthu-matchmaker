"""Run: python -m app.train
Leave-one-student-out evaluation with bootstrap 95% intervals over students, so a small sample is reported honestly.
Compares tag overlap vs embeddings vs embeddings+ranker, then trains the final ranker on all rows and saves it."""
import csv, os, random
import numpy as np
from .matching import similarity, features, load_now, RANKER_PATH
CSV = os.path.join(os.path.dirname(__file__), "..", "data", "labels.csv")

def load():
    X, y, g = [], [], []
    for r in csv.DictReader(open(CSV, encoding="utf-8-sig")):
        sim = similarity(r["student_text"], r["seat_text"]) or 0.0
        X.append(features(sim, r["student_tags"], r["seat_tags"], float(r["hours_ok"]), float(r["cross_faculty"])))
        y.append(int(r["label"])); g.append(r["group"])
    return np.array(X), np.array(y), np.array(g)

def per_student(scores, y, g):
    """One row per student: Hit@1, Recall@3, MRR. Ties broken randomly."""
    rnd = random.Random(0); out = []
    for grp in sorted(set(g)):
        idx = [i for i in range(len(g)) if g[i] == grp]
        if not any(y[i] for i in idx): continue
        order = sorted(idx, key=lambda i: (-scores[i], rnd.random()))
        out.append((float(y[order[0]]), sum(y[i] for i in order[:3]) / sum(y[i] for i in idx), 1 / next(j + 1 for j, i in enumerate(order) if y[i])))
    return np.array(out)

def boot(arr, n=1000):
    rng = np.random.default_rng(0); m = len(arr)
    b = np.array([arr[rng.integers(0, m, m)].mean(axis=0) for _ in range(n)])
    return arr.mean(axis=0), np.percentile(b, 2.5, axis=0), np.percentile(b, 97.5, axis=0)

def main():
    from sklearn.linear_model import LogisticRegression
    import joblib
    if not load_now(): raise SystemExit("Embedding model not available. Run: pip install -r requirements.txt")
    X, y, g = load(); groups = sorted(set(g)); names = ["tag overlap (baseline)", "embeddings only", "embeddings + ranker"]
    S = {k: np.zeros(len(y)) for k in names}
    for grp in groups:
        te = g == grp; tr = ~te
        clf = LogisticRegression(max_iter=1000).fit(X[tr], y[tr])
        S[names[0]][te] = X[te][:, 1]; S[names[1]][te] = X[te][:, 0]; S[names[2]][te] = clf.predict_proba(X[te])[:, 1]
    P = {k: per_student(S[k], y, g) for k in names}
    print(f"{len(groups)} students, {len(y)} rows, leave-one-student-out, mean [95% bootstrap interval over students]\n")
    for k in names:
        m, lo, hi = boot(P[k]); print(f"{k:24s} Hit@1 {m[0]:.2f} [{lo[0]:.2f}-{hi[0]:.2f}]  Recall@3 {m[1]:.2f} [{lo[1]:.2f}-{hi[1]:.2f}]  MRR {m[2]:.2f} [{lo[2]:.2f}-{hi[2]:.2f}]")
    print()
    rng = np.random.default_rng(1)
    for k in names[1:]:
        d = P[k][:, 2] - P[names[0]][:, 2]; b = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(1000)]; lo, hi = np.percentile(b, [2.5, 97.5])
        verdict = "no clear difference" if lo <= 0 <= hi else ("better" if lo > 0 else "worse")
        print(f"MRR vs baseline, {k}: {d.mean():+.2f} [{lo:+.2f}, {hi:+.2f}] -> {verdict}")
    clf = LogisticRegression(max_iter=1000).fit(X, y); joblib.dump(clf, RANKER_PATH); print("\nsaved", RANKER_PATH)
if __name__ == "__main__": main()
