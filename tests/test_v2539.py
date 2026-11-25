import ast
from pathlib import Path
from app import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_version():
    assert __version__ == (ROOT / 'VERSION').read_text().strip()
    assert '${APP_VERSION:-' + __version__ + '}' in (ROOT / 'compose.yaml').read_text()


def test_balance_list_color_and_label():
    tree = ast.parse((ROOT / 'app/handlers.py').read_text())
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'servers')
    branch = next(n for n in ast.walk(handler) if isinstance(n, ast.If) and 'billing_mode' in ast.unparse(n.test))
    code = compile(ast.Module(body=branch.body, type_ignores=[]), '<balance-list>', 'exec')
    from types import SimpleNamespace
    for days in (0, 1, 5, 7, 8, 30):
        for alert in (1, 3, 7):
            account = {'days_left': days, 'balance_alert_days': alert}
            env = {'server': {'name': 'VPS', 'provider': 'Host', 'currency': 'USD', 'balance_alert_days': alert}, 'self': SimpleNamespace(today=None, db=SimpleNamespace(provider_balance=lambda *args: account))}
            exec(code, env)
            assert env['label'] == f'VPS · ~{days} дн.'
            assert env['style'] == ('primary' if days <= 7 else 'success')
