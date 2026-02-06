"""
WMIBO solution validator (v1.0)

Validates:
- variable domains (b in {0,1}, i integral and within bounds, r within bounds)
- hard CNF/WCNF clauses satisfied
- active linear constraints satisfied (considering indicators)
- objective value matches reported "o" (within tolerance), accounting for min/max conventions

Usage:
  python validate_wmibo_solution.py instance.wmibo --sol solution.txt
  wmibo.exe instance.wmibo > out.txt && python validate_wmibo_solution.py instance.wmibo --sol out.txt
  cat out.txt | python validate_wmibo_solution.py instance.wmibo

Exit codes:
  0 = OK
  1 = validation failed
  2 = parse error
  
© Oscar Riveros. Todos los derechos reservados. 
"""
import argparse
import math
import re
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

INF = 1e300

# ---------- Data structures ----------

@dataclass
class VarDecl:
    kind: str  # 'b','i','r'
    idx: int
    lo: float
    hi: float
    free: bool = False
    binary: bool = False

@dataclass
class Clause:
    hard: bool
    weight: int
    lits: List[Tuple[int, bool]]  # (b_index, neg)

@dataclass
class LinConstr:
    cid: str
    sense: str  # <=, >=, =
    rhs: float
    terms: List[Tuple[float, str, int]]  # (coef, kind, idx)

IndicatorVal = Union[Tuple[int, bool], Tuple[str]]  # (bi,neg) or ("CONFLICT",)

@dataclass
class WMIBO:
    B: int
    I: int
    R: int
    vars: Dict[Tuple[str, int], VarDecl]
    cnf_hard: List[Clause]
    cnf_soft: List[Clause]
    wcnf_hard: List[Clause]
    wcnf_soft: List[Clause]
    lin: Dict[str, LinConstr]
    ind: Dict[str, IndicatorVal]  # cid -> indicator literal or ("CONFLICT",)
    obj_sense: Optional[str]      # min|max|None
    obj_terms: List[Tuple[float, str, int]]
    opts: Dict[str, float]        # feas_tol, int_tol, ...


# ---------- Parsing helpers ----------

def is_comment(line: str) -> bool:
    if not line:
        return True
    if line[0] == '#':
        return True
    # DIMACS-style: comment is "c" followed by whitespace/end; NOT "cl"
    if line[0] == 'c' and (len(line) == 1 or line[1].isspace()):
        return True
    return False

def parse_lit(tok: str) -> Tuple[int, bool]:
    neg = False
    if tok.startswith("~"):
        neg = True
        tok = tok[1:]
    if not tok.startswith("b") or not tok[1:].isdigit():
        raise ValueError(f"bad literal token: {tok!r}")
    bi = int(tok[1:])
    return bi, neg

def parse_var(tok: str) -> Tuple[str, int]:
    if len(tok) < 2 or tok[0] not in "bir" or not tok[1:].isdigit():
        raise ValueError(f"bad var token: {tok!r}")
    return tok[0], int(tok[1:])

def parse_bounds(tok: str) -> Tuple[float, float]:
    m = re.match(r"^\[(.*?),(.*?)\]$", tok)
    if not m:
        raise ValueError(f"bad bounds: {tok!r}")
    return float(m.group(1)), float(m.group(2))

def parse_wmibo(path: str) -> WMIBO:
    txt = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()

    B = I = R = 0
    vars_: Dict[Tuple[str, int], VarDecl] = {}
    cnf_hard: List[Clause] = []
    cnf_soft: List[Clause] = []
    wcnf_hard: List[Clause] = []
    wcnf_soft: List[Clause] = []
    lin: Dict[str, LinConstr] = {}
    ind: Dict[str, IndicatorVal] = {}
    obj_sense: Optional[str] = None
    obj_terms: List[Tuple[float, str, int]] = []
    opts: Dict[str, float] = {"feas_tol": 1e-8, "int_tol": 1e-6}

    block: Optional[str] = None
    saw_header = False

    for raw in txt:
        line = raw.strip()
        if not line or is_comment(line):
            continue

        if line.startswith("p "):
            parts = line.split()
            if len(parts) < 5 or parts[1] != "wmibo":
                raise ValueError("invalid header line")
            # Accept both:
            #   p wmibo 1 B I R ...
            #   p wmibo B I R ...
            if len(parts) >= 6 and parts[2].isdigit() and int(parts[2]) == 1:
                B, I, R = int(parts[3]), int(parts[4]), int(parts[5])
            else:
                B, I, R = int(parts[2]), int(parts[3]), int(parts[4])
            saw_header = True
            continue

        if line.startswith("begin "):
            block = line.split()[1]
            continue
        if line == "end":
            block = None
            continue

        if line.startswith("opt "):
            _, k, v = line.split(maxsplit=2)
            try:
                opts[k] = float(v)
            except ValueError:
                # ignore non-numeric opts in validator
                pass
            continue

        if line.startswith("var "):
            parts = line.split()
            if len(parts) < 4:
                raise ValueError(f"bad var line: {line}")
            kind = parts[1]
            idx = int(parts[2])
            spec = parts[3]
            if spec == "bin":
                vars_[(kind, idx)] = VarDecl(kind, idx, 0.0, 1.0, binary=True)
            elif spec == "free":
                vars_[(kind, idx)] = VarDecl(kind, idx, -INF, INF, free=True)
            else:
                lo, hi = parse_bounds(spec)
                vars_[(kind, idx)] = VarDecl(kind, idx, lo, hi)
            continue

        # ---- block content ----
        if block == "cnf":
            parts = line.split()
            if parts[0] != "cl" or parts[1] not in ("hard", "soft"):
                raise ValueError(f"bad cnf clause line: {line}")
            hard = (parts[1] == "hard")
            lits: List[Tuple[int, bool]] = []
            for tok in parts[2:]:
                if tok == "0":
                    break
                lits.append(parse_lit(tok))
            cl = Clause(hard=hard, weight=1, lits=lits)  # cl soft has weight 1 by convention
            (cnf_hard if hard else cnf_soft).append(cl)
            continue

        if block == "wcnf":
            parts = line.split()
            if parts[0] != "wcl" or len(parts) < 4 or parts[2] not in ("hard", "soft"):
                raise ValueError(f"bad wcnf clause line: {line}")
            w = int(parts[1])
            hard = (parts[2] == "hard")
            lits: List[Tuple[int, bool]] = []
            for tok in parts[3:]:
                if tok == "0":
                    break
                lits.append(parse_lit(tok))
            cl = Clause(hard=hard, weight=w, lits=lits)
            (wcnf_hard if hard else wcnf_soft).append(cl)
            continue

        if block == "lin":
            m = re.match(r"^lc\s+(\w+)\s+(<=|>=|=)\s+([^\s]+)\s*:\s*(.*)$", line)
            if not m:
                raise ValueError(f"bad linear constraint line: {line}")
            cid = m.group(1)
            sense = m.group(2)
            rhs = float(m.group(3))
            rest = m.group(4).strip()
            terms: List[Tuple[float, str, int]] = []
            if rest:
                toks = rest.split()
                if len(toks) % 2 != 0:
                    raise ValueError(f"odd number of tokens in lin expr: {line}")
                for j in range(0, len(toks), 2):
                    coef = float(toks[j])
                    kind, idx = parse_var(toks[j + 1])
                    terms.append((coef, kind, idx))
            if cid in lin:
                raise ValueError(f"duplicate linear constraint id: {cid}")
            lin[cid] = LinConstr(cid=cid, sense=sense, rhs=rhs, terms=terms)
            continue

        if block == "ind":
            m = re.match(r"^ind\s+(~?b\d+)\s*=>\s*(\w+)$", line)
            if not m:
                raise ValueError(f"bad indicator line: {line}")
            lit = parse_lit(m.group(1))
            cid = m.group(2)
            if cid in ind and ind[cid] != lit:
                ind[cid] = ("CONFLICT",)
            else:
                ind[cid] = lit
            continue

        if block == "obj":
            m = re.match(r"^obj\s+(min|max)\s*:\s*lin\s*(.*)$", line)
            if not m:
                raise ValueError(f"bad obj line: {line}")
            obj_sense = m.group(1)
            rest = m.group(2).strip()
            terms: List[Tuple[float, str, int]] = []
            if rest:
                toks = rest.split()
                if len(toks) % 2 != 0:
                    raise ValueError(f"odd number of tokens in obj expr: {line}")
                for j in range(0, len(toks), 2):
                    coef = float(toks[j])
                    kind, idx = parse_var(toks[j + 1])
                    terms.append((coef, kind, idx))
            obj_terms = terms
            continue

        # Unknown content outside supported blocks: ignore (forward compatibility)
        # If you prefer strict mode, raise here.

    if not saw_header:
        raise ValueError("missing header 'p wmibo ...'")

    return WMIBO(
        B=B, I=I, R=R, vars=vars_,
        cnf_hard=cnf_hard, cnf_soft=cnf_soft,
        wcnf_hard=wcnf_hard, wcnf_soft=wcnf_soft,
        lin=lin, ind=ind,
        obj_sense=obj_sense, obj_terms=obj_terms,
        opts=opts
    )

# ---------- Solution parsing ----------

@dataclass
class Solution:
    status: Optional[str]
    reported_obj: Optional[float]
    model: Dict[str, float]  # 'b1'->0/1, 'i2'->int, 'r3'->float

def parse_solution_text(text: str) -> Solution:
    status = None
    reported_obj = None
    model: Dict[str, float] = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("s "):
            status = line[2:].strip()
        elif line.startswith("o "):
            try:
                reported_obj = float(line.split()[1])
            except Exception:
                pass
        elif line.startswith("v "):
            for tok in line.split()[1:]:
                if "=" not in tok:
                    continue
                var, val = tok.split("=", 1)
                try:
                    model[var] = float(val)
                except ValueError:
                    pass

    return Solution(status=status, reported_obj=reported_obj, model=model)

# ---------- Evaluation ----------

def get_model_value(sol: Solution, kind: str, idx: int) -> Optional[float]:
    return sol.model.get(f"{kind}{idx}")

def lit_value(sol: Solution, bi: int, neg: bool) -> Optional[int]:
    v = get_model_value(sol, "b", bi)
    if v is None:
        return None
    b = 1 if v >= 0.5 else 0
    return (1 - b) if neg else b

def clause_satisfied(sol: Solution, cl: Clause) -> Optional[bool]:
    for (bi, neg) in cl.lits:
        t = lit_value(sol, bi, neg)
        if t is None:
            return None
        if t == 1:
            return True
    return False

def eval_lin(sol: Solution, terms: List[Tuple[float, str, int]]) -> Optional[float]:
    s = 0.0
    for coef, kind, idx in terms:
        v = get_model_value(sol, kind, idx)
        if v is None:
            return None
        s += coef * v
    return s

def is_active_constraint(w: WMIBO, sol: Solution, cid: str) -> Tuple[bool, Optional[str]]:
    """Returns (active?, error_str_if_any)."""
    ind = w.ind.get(cid)
    if ind is None:
        return True, None
    if ind == ("CONFLICT",):
        return False, f"conflicting indicators for constraint '{cid}'"
    bi, neg = ind  # type: ignore
    t = lit_value(sol, bi, neg)
    if t is None:
        return False, f"missing indicator variable b{bi} for constraint '{cid}'"
    return (t == 1), None

def validate(w: WMIBO, sol: Solution) -> Tuple[bool, List[str], Dict[str, float]]:
    errs: List[str] = []
    feas_tol = float(w.opts.get("feas_tol", 1e-8))
    int_tol = float(w.opts.get("int_tol", 1e-6))

    # --- variable presence and domains ---
    for k in range(1, w.B + 1):
        v = get_model_value(sol, "b", k)
        if v is None:
            errs.append(f"missing assignment: b{k}")
        else:
            if not (abs(v - 0.0) <= 1e-9 or abs(v - 1.0) <= 1e-9):
                errs.append(f"b{k} not boolean (0/1): {v}")

    for k in range(1, w.I + 1):
        v = get_model_value(sol, "i", k)
        if v is None:
            errs.append(f"missing assignment: i{k}")
        else:
            if abs(v - round(v)) > int_tol:
                errs.append(f"i{k} not integral within int_tol={int_tol}: {v}")
            decl = w.vars.get(("i", k))
            if decl is not None:
                if v < decl.lo - int_tol or v > decl.hi + int_tol:
                    errs.append(f"i{k} out of bounds [{decl.lo},{decl.hi}]: {v}")
            # if no decl, we allow but warn:
            else:
                errs.append(f"warning: i{k} has no 'var i {k} ...' declaration; skipping bounds check")

    for k in range(1, w.R + 1):
        v = get_model_value(sol, "r", k)
        if v is None:
            errs.append(f"missing assignment: r{k}")
        else:
            decl = w.vars.get(("r", k))
            if decl is not None and not decl.free:
                if v < decl.lo - feas_tol or v > decl.hi + feas_tol:
                    errs.append(f"r{k} out of bounds [{decl.lo},{decl.hi}] (feas_tol={feas_tol}): {v}")
            elif decl is None:
                errs.append(f"warning: r{k} has no 'var r {k} ...' declaration; skipping bounds check")

    # --- hard CNF/WCNF ---
    for j, cl in enumerate(w.cnf_hard, 1):
        sat = clause_satisfied(sol, cl)
        if sat is None:
            errs.append(f"hard CNF clause #{j}: missing bool var")
        elif not sat:
            errs.append(f"hard CNF clause #{j} violated")

    for j, cl in enumerate(w.wcnf_hard, 1):
        sat = clause_satisfied(sol, cl)
        if sat is None:
            errs.append(f"hard WCNF clause #{j}: missing bool var")
        elif not sat:
            errs.append(f"hard WCNF clause #{j} violated")

    # --- soft penalties ---
    penalty = 0.0
    soft_violations = 0

    for j, cl in enumerate(w.cnf_soft, 1):
        sat = clause_satisfied(sol, cl)
        if sat is None:
            errs.append(f"soft CNF clause #{j}: missing bool var")
            continue
        if not sat:
            penalty += 1.0
            soft_violations += 1

    for j, cl in enumerate(w.wcnf_soft, 1):
        sat = clause_satisfied(sol, cl)
        if sat is None:
            errs.append(f"soft WCNF clause #{j}: missing bool var")
            continue
        if not sat:
            penalty += float(cl.weight)
            soft_violations += 1

    # --- linear constraints ---
    for cid, lc in w.lin.items():
        active, e = is_active_constraint(w, sol, cid)
        if e:
            # It's a format/solution consistency problem; record it.
            errs.append(e)
            continue
        if not active:
            continue

        lhs = eval_lin(sol, lc.terms)
        if lhs is None:
            errs.append(f"linear constraint {cid}: missing variable value")
            continue

        if lc.sense == "<=":
            if lhs > lc.rhs + feas_tol:
                errs.append(f"linear {cid} violated: lhs={lhs:.12g} <= rhs={lc.rhs:.12g} (tol={feas_tol})")
        elif lc.sense == ">=":
            if lhs < lc.rhs - feas_tol:
                errs.append(f"linear {cid} violated: lhs={lhs:.12g} >= rhs={lc.rhs:.12g} (tol={feas_tol})")
        else:  # "="
            if abs(lhs - lc.rhs) > feas_tol:
                errs.append(f"linear {cid} violated: lhs={lhs:.12g} = rhs={lc.rhs:.12g} (tol={feas_tol})")

    # --- objective ---
    lin_obj = eval_lin(sol, w.obj_terms) if w.obj_terms else 0.0
    if lin_obj is None:
        errs.append("objective: missing variable value in linear objective")
        lin_obj = float("nan")

    # Candidate totals depending on conventions
    # Convention A (most common): minimize (lin + penalties). For max, solver often minimizes (-lin + penalties).
    total_min = float(lin_obj) + penalty
    total_internal = total_min if (w.obj_sense != "max") else (-float(lin_obj) + penalty)

    # Convention B (also plausible for max): maximize (lin - penalties); if solver prints original max objective:
    total_max_original = float(lin_obj) - penalty

    stats = {
        "penalty": penalty,
        "soft_violations": float(soft_violations),
        "lin_obj": float(lin_obj),
        "total_min": total_min,
        "total_internal": total_internal,
        "total_max_original": total_max_original,
    }

    # Compare with reported objective if present
    if sol.reported_obj is not None and not math.isnan(sol.reported_obj):
        tol_obj = 1e-6
        candidates = {
            "total_min": total_min,
            "total_internal": total_internal,
            "total_max_original": total_max_original,
        }
        best_name = min(candidates, key=lambda k: abs(candidates[k] - sol.reported_obj))
        best_val = candidates[best_name]
        stats["reported_obj"] = float(sol.reported_obj)
        stats["best_match"] = best_name
        stats["best_match_value"] = float(best_val)
        stats["best_abs_error"] = float(abs(best_val - sol.reported_obj))
        if abs(best_val - sol.reported_obj) > tol_obj:
            errs.append(f"objective mismatch: reported o={sol.reported_obj:.12g} best_match({best_name})={best_val:.12g} |err|={abs(best_val-sol.reported_obj):.3g} > {tol_obj}")

    ok = all(not e.startswith("hard ") and "violated" not in e and "missing assignment" not in e and "objective mismatch" not in e
             for e in errs) and not any("violated" in e and e.startswith("hard") for e in errs)

    # Treat any non-warning error as failure
    fatal = [e for e in errs if not e.startswith("warning:")]
    ok = (len(fatal) == 0)

    return ok, errs, stats

# ---------- Main ----------

def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a WMIBO solver output against a .wmibo instance")
    ap.add_argument("instance", help="path to .wmibo instance")
    ap.add_argument("--sol", help="path to solver output; if omitted, read from stdin", default=None)
    ap.add_argument("--show-soft", action="store_true", help="print which soft clauses are violated (indices)")
    args = ap.parse_args()

    try:
        w = parse_wmibo(args.instance)
    except Exception as e:
        print(f"PARSE ERROR (instance): {e}", file=sys.stderr)
        return 2

    if args.sol:
        sol_text = Path(args.sol).read_text(encoding="utf-8", errors="replace")
    else:
        sol_text = sys.stdin.read()

    try:
        sol = parse_solution_text(sol_text)
    except Exception as e:
        print(f"PARSE ERROR (solution): {e}", file=sys.stderr)
        return 2

    ok, errs, stats = validate(w, sol)

    # Summary
    print("WMIBO VALIDATION REPORT")
    print(f"  instance: {args.instance}")
    print(f"  status:   {sol.status}")
    if sol.reported_obj is not None:
        print(f"  o(reported): {sol.reported_obj:.12g}")
    print(f"  lin_obj:  {stats['lin_obj']:.12g}")
    print(f"  penalty:  {stats['penalty']:.12g}   (soft_violations={int(stats['soft_violations'])})")
    print(f"  total_min:        {stats['total_min']:.12g}")
    print(f"  total_internal:   {stats['total_internal']:.12g}")
    print(f"  total_max_orig:   {stats['total_max_original']:.12g}")
    if "best_match" in stats:
        print(f"  best_match: {stats['best_match']}  value={stats['best_match_value']:.12g}  abs_err={stats['best_abs_error']:.3g}")

    # Errors/warnings
    warnings = [e for e in errs if e.startswith("warning:")]
    failures = [e for e in errs if not e.startswith("warning:")]

    if warnings:
        print("\nWARNINGS:")
        for wmsg in warnings:
            print("  -", wmsg)

    if failures:
        print("\nFAILURES:")
        for emsg in failures:
            print("  -", emsg)

    print("\nRESULT:", "OK" if ok else "FAIL")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
