"""Definitive spec audit — run from scratch, no reliance on prior turns."""
import sys, os, importlib, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ok = 0
fail = 0

def check(label, condition, detail=""):
    global ok, fail
    if condition:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label} -- {detail}")

print("=" * 64)
print("TASK 1: formula/ extracted to app/formula/")
print("=" * 64)
EXPECTED_FORMULA = [
    "__init__.py", "covariance.py", "performance.py", "portfolio_returns.py",
    "returns.py", "risk_contribution.py", "risk_metrics.py", "rolling_volatility.py",
    "sharpe_ratio.py", "sortino_ratio.py", "volatility.py",
]
for f in EXPECTED_FORMULA:
    p = os.path.join("app", "formula", f)
    check(f"formula/{f}", os.path.isfile(p))

print("\n" + "=" * 64)
print("TASK 2: solvers/ extracted to app/solvers/")
print("=" * 64)
for f in ["__init__.py", "slsqp_solver.py"]:
    p = os.path.join("app", "solvers", f)
    check(f"solvers/{f}", os.path.isfile(p))

print("\n" + "=" * 64)
print("TASK 3: strategies/ renamed to allocation/")
print("=" * 64)
check("app/strategies/ does NOT exist", not os.path.exists("app/strategies"))
check("app/allocation/ exists", os.path.isdir("app/allocation"))
EXPECTED_ALLOC = [
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
for f in EXPECTED_ALLOC:
    p = os.path.join("app", "allocation", f)
    check(f"allocation/{f}", os.path.isfile(p))

print("\n" + "=" * 64)
print("TASK 4+5: Zero app.strategies in entire app/ tree")
print("=" * 64)
bad_files = []
for root, dirs, files in os.walk("app"):
    dirs[:] = [d for d in dirs if d not in ("__pycache__", "venv", ".venv")]
    for fname in files:
        if fname.endswith(".py"):
            path = os.path.join(root, fname)
            with open(path, "r", encoding="utf-8") as fh:
                if "app.strategies" in fh.read():
                    bad_files.append(path)
check("no app.strategies in app/", len(bad_files) == 0,
      f"found in: {bad_files}" if bad_files else "")

print("\n" + "=" * 64)
print("TASK 6: MongoDB migration script + fallback imports")
print("=" * 64)
check("scripts/migrate_strategy_imports.py exists",
      os.path.isfile("scripts/migrate_strategy_imports.py"))

with open("app/allocation/builtin_templates.py", "r", encoding="utf-8") as f:
    bt = f.read()
check("builtin_templates.py: no app.strategies",
      "app.strategies" not in bt)

# Check fallback imports use new paths
fallbacks = re.findall(r'"(from app\..+?)"', bt)
old_fallbacks = [fb for fb in fallbacks if "strategies" in fb]
check("builtin_templates.py: fallback imports use new paths",
      len(old_fallbacks) == 0, f"old: {old_fallbacks}")

# Check MongoDB directly
try:
    from app.config.settings import settings
    from pymongo import MongoClient
    client = MongoClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000)
    db = client[settings.DATABASE_NAME]
    col = db["model_templates"]
    mongo_bad = 0
    for doc in col.find():
        src = doc.get("source_code", "") or ""
        if "app.strategies" in src:
            mongo_bad += 1
    check(f"MongoDB: 0 templates with old paths (total={col.count_documents({})})",
          mongo_bad == 0, f"{mongo_bad} templates still have app.strategies")
    client.close()
except Exception as e:
    check("MongoDB check", False, str(e))

print("\n" + "=" * 64)
print("TASK 7: Verification")
print("=" * 64)

# 7.1 Import completeness
IMPORTS = [
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
import_ok = 0
import_fail = 0
for mod_path, attr in IMPORTS:
    try:
        m = importlib.import_module(mod_path)
        getattr(m, attr)
        import_ok += 1
    except Exception as e:
        import_fail += 1
check(f"7.1 Import completeness ({import_ok}/{import_ok+import_fail})",
      import_fail == 0)

# 7.2 Cross-module
cross_modules = [
    ("app.control", "create_monitor"),
    ("app.control.volatility.rolling_vol", "RollingVolMonitor"),
    ("app.control.volatility.ewma_vol", "EWMAMonitor"),
    ("app.allocation.factor_model", "PcaFactorModel"),
]
cross_ok = 0
cross_fail = 0
for mod_path, attr in cross_modules:
    try:
        m = importlib.import_module(mod_path)
        getattr(m, attr)
        cross_ok += 1
    except Exception as e:
        cross_fail += 1
check(f"7.2 Cross-module imports ({cross_ok}/{cross_ok+cross_fail})",
      cross_fail == 0)

# 7.3 DynamicLoader
import inspect
from app.allocation.dynamic_loader import DynamicStrategyLoader
dl_src = inspect.getsource(DynamicStrategyLoader)
check("7.3 DynamicLoader: no old app.strategies refs",
      "app.strategies" not in dl_src)

# 7.4 App startup
try:
    from main import app
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
    weights = pd.Series({"A": 0.4, "B": 0.3, "C": 0.3})
    from app.allocation.models.base import _default_portfolio_vol
    from app.control import create_monitor
    vol = _default_portfolio_vol(weights, prices)
    monitor = create_monitor("rolling_vol")
    metrics = monitor.compute_metrics(weights, prices, vol_reset_threshold=0.06)
    from app.allocation.models.risk_parity import RiskParityStrategy
    s = RiskParityStrategy()
    m = s.compute_monitoring_metrics(weights, prices)
    check("7.5 Backtest engine", vol is not None and metrics and m,
          f"vol={vol}, metrics={metrics}")
except Exception as e:
    check("7.5 Backtest engine", False, str(e))

# builtin_templates runtime
try:
    from app.allocation.builtin_templates import get_builtin_templates
    templates = get_builtin_templates()
    bad_t = [t["code"] for t in templates if "app.strategies" in t.get("source_code", "")]
    check(f"builtin_templates runtime ({len(templates)} templates, 0 bad)",
          len(bad_t) == 0, f"bad: {bad_t}")
except Exception as e:
    check("builtin_templates runtime", False, str(e))

print("\n" + "=" * 64)
total = ok + fail
print(f"FINAL: {ok}/{total} checks passed, {fail} failed")
if fail == 0:
    print("ALL SPEC REQUIREMENTS SATISFIED")
else:
    print("SOME REQUIREMENTS NOT MET")
print("=" * 64)
