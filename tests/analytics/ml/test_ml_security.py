"""Static guarantees about the ML package, checked by reading its source (no database needed).

These protect the design decisions: no pickle, no files, no network, no dynamic code, no web training,
and nothing that stops the application from starting when scikit-learn or numpy is absent.
"""
import ast
from pathlib import Path

ML = Path(__file__).resolve().parents[3] / "app" / "analytics" / "ml"
FILES = sorted(ML.glob("*.py"))

FORBIDDEN_MODULES = {"pickle", "cPickle", "joblib", "marshal", "shelve", "dill", "subprocess", "socket", "requests",
                     "urllib", "http", "ftplib", "os", "pathlib", "shutil", "tempfile", "ctypes", "importlib"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "open", "__import__", "input"}


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_roots(node_tree, top_level_only=False):
    nodes = node_tree.body if top_level_only else ast.walk(node_tree)
    roots = set()
    for n in nodes:
        if isinstance(n, ast.Import):
            roots |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            roots.add(n.module.split(".")[0])
    return roots


def test_the_package_is_found():
    assert len(FILES) >= 12 and (ML / "training.py").exists()


def test_no_pickle_no_filesystem_no_network_no_subprocess():
    for path in FILES:
        bad = imported_roots(tree(path)) & FORBIDDEN_MODULES
        assert not bad, f"{path.name} imports {sorted(bad)}"


def test_no_dynamic_code_execution_or_file_opening():
    for path in FILES:
        for n in ast.walk(tree(path)):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                assert n.func.id not in FORBIDDEN_CALLS, f"{path.name} calls {n.func.id}()"
            if isinstance(n, ast.Attribute):
                assert n.attr not in {"system", "popen", "loads_unsafe"}, f"{path.name} uses .{n.attr}"


def test_scikit_learn_is_only_ever_imported_lazily_inside_fit_ridge():
    for path in FILES:
        assert "sklearn" not in imported_roots(tree(path), top_level_only=True), path.name     # never at import time
    lazy = [p.name for p in FILES if "sklearn" in imported_roots(tree(p))]
    assert lazy == ["forecasting.py"]


def test_the_cli_module_is_safe_to_import_when_ml_packages_are_missing():
    # app/cli.py imports this module at startup; it must not need numpy, scikit-learn or the database.
    assert imported_roots(tree(ML / "cli.py"), top_level_only=True) <= {"json", "click"}


def test_modules_needed_for_readiness_do_not_import_numpy_or_sklearn():
    for name in ("policy.py", "schemas.py", "data_validation.py", "data_preparation.py", "readiness.py", "data_source.py"):
        assert not imported_roots(tree(ML / name)) & {"numpy", "sklearn", "scipy", "pandas"}, name


def test_no_deep_learning_or_ai_service_dependencies():
    banned = {"torch", "tensorflow", "keras", "openai", "anthropic", "transformers", "statsmodels", "prophet", "xgboost", "lightgbm"}
    for path in FILES:
        assert not imported_roots(tree(path)) & banned, path.name


def test_training_is_not_reachable_from_any_web_route():
    routes = (ML.parent / "routes.py").read_text(encoding="utf-8")
    assert "analytics.ml.training" not in routes and "import training" not in routes and ".train(" not in routes
    services = (ML.parent / "services.py").read_text(encoding="utf-8")
    assert "analytics.ml.training" not in services


def test_the_ml_layer_never_selects_personal_columns():
    banned = ("customer_name", "customer_contact", "contact_number", "contact_normalized", "full_name", "email",
              "password", "didit", "token", "address", "birth", "id_number")
    for path in FILES:
        code = path.read_text(encoding="utf-8").lower()
        string_literals = " ".join(n.value.lower() for n in ast.walk(tree(path)) if isinstance(n, ast.Constant) and isinstance(n.value, str))
        attributes = " ".join(n.attr.lower() for n in ast.walk(tree(path)) if isinstance(n, ast.Attribute))
        for word in banned:
            assert word not in attributes and f'"{word}"' not in code, f"{path.name} touches {word}"
