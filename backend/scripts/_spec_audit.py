"""Independent spec audit — derives requirements from spec, verifies against current state."""
import sys, os, importlib, inspect, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = 0
failed = 0
failures = []

def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        failures.append(label)
        print(f"  FAIL  {label}  {detail}")

# =====================================================================
# TASK 1: formula/ extracted to app/formula/ (11 files)
# =====================================================================
print("\n--- Task 1: formula/ ---")
FORMULA_FILES = [
    "__init__.py", "covariance.py", "performance.py", "portfolio_returns.py",
    "returns.py", "risk_contribution.py", "risk_metrics.py", "rolling_volatility.py",
    "sharpe_ratio.py", "sortino_ratio.py", "volatility.py",
]
for f in FORMULA_FILES:
    check(f"app/formula/{f} exists", os.path.isfile(os.path.join("app", "formula", f)))

# =====================================================================
# TASK 2: solvers/ extracted to app/solvers/ (2 files)
# =====================================================================
print("\n--- Task 2: solvers/ ---")
SOLVER_FILES = ["__init__.py", "slsqp_solver.py"]
for f in SOLVER_FILES:
    check(f"app/solvers/{f} exists", os.path.isfile(os.path.join("app", "solvers", f)))

# =====================================================================
# TASK 3: strategies/ renamed to allocation/
# =====================================================================
print("\n--- Task 3: strategies -> allocation ---")
check("app/strategies/ does NOT exist", not os.path.exists("app/strategies"),
      "old directory still present")
check("app/allocation/ is a directory", os.path.isdir("app/allocation"))

ALLOC_FILES = [
    "__init__.py", "builtin_templates.py", "dynamic_loader.py",
    "models/__init__.py", "models/base.py", "models/param_schema.py",
    "models/risk_parity.py", "models/mean_variance.py", "models/black_litterman.py",
    "models/enhanced_risk_parity.py", "models/risk_budget.py",
    "models/factor_risk_parity.py", "models/risk_budget_target_vol.py",
    "models/target_volatility.py", "models/sharpe_risk_budget.py",
    "models/momentum_risk_parity.py", "models/trend_cross_sectional.py",
    "models/etf_cycle_rotation.py", "models/etf_discount_strategy.py",
    "models/manual_allocation.py", "models/wdc_tf_pcrp.py", "models/half_life_pcrp.py",
    "services/__init__.py", "services/config.py", "services/registry.py",
    "services/strategy_service.py",
]
for f in ALLOC_FILES:
    check(f"app/allocation/{f} exists", os.path.isfile(os.path.join("app", "allocation", f)))

# =====================================================================
# TASK 4+5: Zero app.strategies references in entire app/
# =====================================================================
print("\n--- Task 4+5: zero app.strategies in app/ ---")
bad_refs = []
for root, dirs, files in os.walk("app"):
    dirs[:] = [d for d in dirs if d not in ("__pycache__", "venv", ".venv", "node_modules")]
    for fname in files:
        if fname.endswith(".py"):
            path = os.path.join(root, fname)
            with open(path, "r", encoding="utf-8") as fh:
                if "app.strategies" in fh.read():
                    bad_refs.append(path)
check("no app.strategies references in app/", len(bad_refs) == 0,
      f"found in: {bad_refs}")

# Also check main.py
with open("main.py", "r", encoding="utf-8") as f:
    main_content = f.read()
check("main.py has no app.strategies", "app.strategies" not in main_content)

# =====================================================================
# TASK 6: MongoDB migration script
# =====================================================================
print("\n--- Task 6: migration script ---")
check("scripts/migrate_strategy_imports.py exists",
      os.path.isfile("scripts/migrate_strategy_imports.py"))

# Verify script has dry-run support
with open("scripts/migrate_strategy_imports.py", "r", encoding="utf-8") as f:
    ms_content = f.read()
check("migration script has dry-run mode", "dry-run" in ms_content or "dry_run" in ms_content)

# Verify builtin_templates.py fallback imports updated
with open("app/allocation/builtin_templates.py", "r", encoding="utf-8") as f:
    bt_content = f.read()
check("builtin_templates.py: no app.strategies",
      "app.strategies" not in bt_content)

# Check fallback imports use new paths
fallbacks = re.findall(r'"(from app\..+?)"', bt_content)
old_fb = [fb for fb in fallbacks if "strategies" in fb]
check("builtin_templates.py fallback imports use new paths",
      len(old_fb) == 0, f"old: {old_fb}")

# Check MongoDB directly
try:
    from app.config.settings import settings
    from pymongo import MongoClient
    client = MongoClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000)
    db = client[settings.DATABASE_NAME]
    col = db["model_templates"]
    total_templates = col.count_documents({})
    mongo_bad = 0
    for doc in col.find():
        src = doc.get("source_code", "") or ""
        if "app.strategies" in src:
            mongo_bad += 1
    check(f"MongoDB: {total_templates} templates, 0 with old paths",
          mongo_bad == 0 and total_templates > 0,
          f"{mongo_bad} bad templates")
    client.close()
except Exception as e:
    check("MongoDB template check", False, str(e))

# =====================================================================
# TASK 7: Verification
# =====================================================================
print("\n--- Task 7: verification ---")

# 7.1 Import completeness
IMPORT_TESTS = [
    ("app.formula.returns", "compute_simple_returns"),
    ("app.formula.covariance", "compute_covariance"),
    ("app.formula.rolling_volatility", "compute_portfolio_volatility"),
    ("app.formula.performance", "compute_sharpe_ratio"),
    ("app.formula.risk_contribution", "compute_risk_contribution"),
    ("app.solvers.slsqp_solver", "solve_slsqp"),
    ("app.allocation.models.base", "BaseStrategyModel"),
    ("app.allocation.models.param_schema", "StrategyParamSchema"),
    ("app.allocation.models.risk_parity", "RiskParityStrategy"),
    ("app.allocation.models.mean_variance", "MeanVarianceOptimization"),
    ("app.allocation.models.black_litterman", "BlackLittermanOptimization"),
    ("app.allocation.models.enhanced_risk_parity", "CovarianceSharpeOptimization"),
    ("app.allocation.models.risk_budget", "RiskBudgetStrategy"),
    ("app.allocation.models.risk_budget_target_vol", "RiskBudgetTargetVolStrategy"),
    ("app.allocation.models.target_volatility", "TargetVolatilityStrategy"),
    ("app.allocation.models.sharpe_risk_budget", "SharpeRiskBudgetStrategy"),
    ("app.allocation.dynamic_loader", "DynamicStrategyLoader"),
    ("app.allocation.builtin_templates", "get_builtin_templates"),
    ("app.allocation.services", "StrategyService"),
    ("app.allocation.services.registry", "create_strategy_service_from_database"),
]
imp_ok = imp_fail = 0
imp_errors = []
for mod, attr in IMPORT_TESTS:
    try:
        m = importlib.import_module(mod)
        getattr(m, attr)
        imp_ok += 1
    except Exception as e:
        imp_fail += 1
        imp_errors.append(f"{mod}.{attr}: {e}")
check(f"7.1 Import completeness ({imp_ok}/{imp_ok+imp_fail})",
      imp_fail == 0, str(imp_errors))

# 7.2 Cross-module imports
CROSS_TESTS = [
    ("app.control", "create_monitor"),
    ("app.control.base", "BaseMonitor"),
    ("app.control.volatility.rolling_vol", "RollingVolMonitor"),
    ("app.control.volatility.ewma_vol", "EWMAMonitor"),
    ("app.allocation.factor_model", "PcaFactorModel"),
]
cross_ok = cross_fail = 0
for mod, attr in CROSS_TESTS:
    try:
        m = importlib.import_module(mod)
        getattr(m, attr)
        cross_ok += 1
    except Exception as e:
        cross_fail += 1
check(f"7.2 Cross-module imports ({cross_ok}/{cross_ok+cross_fail})",
      cross_fail == 0)

# 7.3 DynamicLoader safe_globals
from app.allocation.dynamic_loader import DynamicStrategyLoader
dl_src = inspect.getsource(DynamicStrategyLoader)
check("7.3 DynamicLoader has no app.strategies refs",
      "app.strategies" not in dl_src)

# 7.4 FastAPI app startup
try:
    from main import app as fastapi_app
    check("7.4 FastAPI app startup", True)
except Exception as e:
    check("7.4 FastAPI app startup", False, str(e))

# 7.5 Backtest engine
try:
    import pandas as pd, numpy as np
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=200, freq="B")
    prices = pd.DataFrame(
        np.random.randn(200, 3).cumsum(axis=0) * 0.01 + 100,
        index=dates, columns=["A", "B", "C"]
    )
    w = pd.Series({"A": 0.4, "B": 0.3, "C": 0.3})

    from app.allocation.models.base import _default_portfolio_vol
    vol = _default_portfolio_vol(w, prices)

    from app.control import create_monitor
    mon = create_monitor("rolling_vol")
    metrics = mon.compute_metrics(w, prices, vol_reset_threshold=0.06)

    from app.allocation.models.risk_parity import RiskParityStrategy
    strat = RiskParityStrategy()
    m = strat.compute_monitoring_metrics(w, prices)

    from app.allocation.builtin_templates import get_builtin_templates
    templates = get_builtin_templates()
    bad_t = [t["code"] for t in templates if "app.strategies" in t.get("source_code", "")]

    check(f"7.5 Backtest engine (vol={vol:.6f}, {len(templates)} templates)",
          vol is not None and metrics and m and len(bad_t) == 0,
          f"bad_templates={bad_t}")
except Exception as e:
    check("7.5 Backtest engine", False, str(e))

# =====================================================================
# SUMMARY
# =====================================================================
total = passed + failed
print(f"\n{'='*64}")
print(f"AUDIT RESULT: {passed}/{total} passed, {failed} failed")
if failures:
    print("\nFailed checks:")
    for f in failures:
        print(f"  - {f}")
print("="*64)
sys.exit(0 if failed == 0 else 1)
