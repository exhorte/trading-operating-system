"""The terminals registry (ADR 0039 § 4, I3): what the launcher knows about each MetaTrader terminal, in ``var/launcher/terminals.json``.

*Observed* facts (the server, the login, the account type) are read live from the core and the EA, never saved here: the file keeps what
identifies a terminal and what **Exhorte declares** about it. A declaration is checked, and no two terminals may share a magic number, a Trading OS
account or an expected login — so that no order can be addressed to the wrong account. No password, no token, no secret has a field.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from tests.unit.launcher.mt5.support import DATA, DATA_ID, INSTALL, clock, declared
from tests.unit.launcher.support import T0, FakeProcessTable, make_config, proc
from trading_os.launcher.lock import LauncherBusy
from trading_os.launcher.mt5.model import (
    ChartSpec,
    DeclaredTerminal,
    OperationKind,
    TerminalSource,
)
from trading_os.launcher.mt5.terminals import (
    RegistryRefused,
    TerminalRegistry,
    is_overdue,
    terminal_lock,
    validate_declared,
)


@pytest.fixture
def registry(tmp_path: Path) -> TerminalRegistry:
    return TerminalRegistry(
        tmp_path / "var" / "launcher" / "terminals.json", clock(), FakeProcessTable([proc(100)]), pid=100
    )


def add(registry: TerminalRegistry, terminal_id: str = DATA_ID, **declared_changes: object):  # type: ignore[no-untyped-def]
    return registry.register(
        terminal_id=terminal_id,
        label="exness-demo-01",
        install_path=INSTALL,
        data_path=DATA,
        portable=False,
        source=TerminalSource.DISCOVERED,
        declared=declared(**declared_changes) if declared_changes is not None else None,
    )


class TestTheFile:
    def test_a_missing_file_is_an_empty_registry_and_loading_creates_nothing(self, registry: TerminalRegistry) -> None:
        snapshot = registry.load()
        assert snapshot.terminals == ()
        assert snapshot.problem is None
        assert not registry.path.exists()

    def test_registering_writes_the_file_atomically_and_it_loads_back_identical(
        self, registry: TerminalRegistry
    ) -> None:
        entry = add(registry)
        assert registry.path.is_file()
        assert not list(registry.path.parent.glob("*.tmp"))
        (loaded,) = registry.load().terminals
        assert loaded == entry
        document = json.loads(registry.path.read_text(encoding="utf-8"))
        assert document["version"] == 1
        stored = document["terminals"][0]
        assert stored["terminalId"] == DATA_ID
        assert stored["declared"]["expectedLogin"] == "486046157"
        assert stored["declared"]["chart"] == {"symbol": "XAUUSDm", "period": "M5"}
        assert stored["operation"]["kind"] == "IDLE"

    def test_nothing_that_could_hold_a_secret_has_a_place_in_the_file(self, registry: TerminalRegistry) -> None:
        add(registry)
        secret = re.compile(r"token|password|passwd|secret|credential|api_?key", re.IGNORECASE)

        def keys(node: object) -> list[str]:
            if isinstance(node, dict):
                return [str(k) for k in node] + [name for v in node.values() for name in keys(v)]
            if isinstance(node, list):
                return [name for v in node for name in keys(v)]
            return []

        assert not [k for k in keys(json.loads(registry.path.read_text(encoding="utf-8"))) if secret.search(k)]

    def test_a_second_write_keeps_the_previous_file_aside_and_a_first_write_has_nothing_to_keep(
        self, registry: TerminalRegistry
    ) -> None:
        add(registry)
        assert not list(registry.path.parent.glob("terminals.json.bak-*"))
        before = registry.path.read_bytes()
        registry.declare(DATA_ID, declared(magic=486047))
        (backup,) = registry.path.parent.glob("terminals.json.bak-*")
        assert backup.read_bytes() == before

    def test_an_unreadable_file_owns_nothing_and_is_kept_aside_when_a_new_one_is_written(
        self, registry: TerminalRegistry
    ) -> None:
        registry.path.parent.mkdir(parents=True)
        registry.path.write_text("{ not json", encoding="utf-8")
        snapshot = registry.load()
        assert snapshot.terminals == ()
        assert snapshot.problem is not None
        add(registry)
        assert registry.load().problem is None
        (aside,) = registry.path.parent.glob("terminals.json.corrupt-*")
        assert aside.read_text(encoding="utf-8") == "{ not json"

    def test_a_file_of_an_unknown_version_is_a_problem_not_a_guess(self, registry: TerminalRegistry) -> None:
        registry.path.parent.mkdir(parents=True)
        registry.path.write_text(json.dumps({"version": 99, "terminals": []}), encoding="utf-8")
        assert registry.load().problem is not None


class TestRegistering:
    def test_a_terminal_is_found_by_its_identifier(self, registry: TerminalRegistry) -> None:
        add(registry)
        snapshot = registry.load()
        assert snapshot.find(DATA_ID) is not None
        assert snapshot.find("nope") is None

    def test_a_terminal_registered_twice_is_refused_and_the_file_is_untouched(self, registry: TerminalRegistry) -> None:
        add(registry)
        before = registry.path.read_bytes()
        with pytest.raises(RegistryRefused) as refused:
            add(registry)
        assert "déjà enregistré" in " ".join(refused.value.problems)
        assert registry.path.read_bytes() == before

    def test_a_terminal_can_be_registered_with_nothing_declared_yet(self, registry: TerminalRegistry) -> None:
        entry = registry.register(
            terminal_id=DATA_ID,
            label="exness-demo-01",
            install_path=INSTALL,
            data_path=DATA,
            portable=False,
            source=TerminalSource.DISCOVERED,
        )
        assert entry.declared == DeclaredTerminal()
        assert set(entry.declared.missing_fields()) == {
            "account_id",
            "expected_login",
            "chart",
            "magic",
            "allowed_symbols",
            "provider",
            "product",
        }

    def test_a_complete_declaration_misses_nothing(self) -> None:
        assert declared().missing_fields() == ()

    @pytest.mark.parametrize("bad", ["", "a/b", "..\\x", "x" * 60, "with space"])
    def test_an_identifier_that_could_name_a_path_is_refused(self, registry: TerminalRegistry, bad: str) -> None:
        with pytest.raises(RegistryRefused):
            registry.register(
                terminal_id=bad,
                label="x",
                install_path=INSTALL,
                data_path=DATA,
                portable=False,
                source=TerminalSource.MANUAL,
            )


class TestDeclarationsAreChecked:
    @pytest.mark.parametrize(
        ("changes", "expected"),
        [
            ({"magic": 0}, "numéro magique"),
            ({"magic": -5}, "numéro magique"),
            ({"magic": 2**31}, "numéro magique"),
            ({"expected_login": "48a6"}, "login"),
            ({"expected_login": ""}, "login"),
            ({"expected_login": "1" * 20}, "login"),
            ({"chart": ChartSpec(symbol="XAUUSDm", period="M7")}, "période"),
            ({"chart": ChartSpec(symbol="XAU USD", period="M5")}, "symbole"),
            ({"allowed_symbols": ("XAUUSDm", "bad symbol")}, "symbole"),
            ({"chart": ChartSpec(symbol="GBPUSDm", period="M5")}, "liste des symboles autorisés"),
            ({"provider": "exness"}, "fournisseur"),
            ({"product": "Exness Standard"}, "produit"),
            ({"account_id": "x y"}, "compte"),
        ],
    )
    def test_each_invalid_value_is_named(self, changes: dict[str, object], expected: str) -> None:
        problems = validate_declared(declared(**changes), others=())
        assert any(expected in problem for problem in problems), problems

    def test_a_good_declaration_has_no_problem(self) -> None:
        assert validate_declared(declared(), others=()) == []

    def test_every_period_metatrader_knows_is_accepted(self) -> None:
        for period in [
            "M1",
            "M2",
            "M3",
            "M4",
            "M5",
            "M6",
            "M10",
            "M12",
            "M15",
            "M20",
            "M30",
            "H1",
            "H2",
            "H3",
            "H4",
            "H6",
            "H8",
            "H12",
            "D1",
            "W1",
            "MN1",
        ]:
            assert validate_declared(declared(chart=ChartSpec(symbol="XAUUSDm", period=period)), others=()) == []

    def test_broker_symbols_with_dots_hashes_and_dashes_are_accepted(self) -> None:
        for symbol in ("XAUUSD.r", "EURUSD#", "US30-cash", "BTCUSD+"):
            changes = {"chart": ChartSpec(symbol=symbol, period="M5"), "allowed_symbols": (symbol,)}
            assert validate_declared(declared(**changes), others=()) == [], symbol

    def test_a_declaration_refused_by_the_registry_leaves_the_file_untouched(self, registry: TerminalRegistry) -> None:
        add(registry)
        before = registry.path.read_bytes()
        with pytest.raises(RegistryRefused):
            registry.declare(DATA_ID, declared(magic=0))
        assert registry.path.read_bytes() == before
        assert not list(registry.path.parent.glob("terminals.json.bak-*"))


class TestNoTwoTerminalsShareAnIdentity:
    def other(self, registry: TerminalRegistry, **changes: object) -> None:
        registry.register(
            terminal_id="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            label="ftmo-01",
            install_path=r"D:\Brokers\FTMO MT5",
            data_path=r"D:\Brokers\FTMO MT5\data",
            portable=True,
            source=TerminalSource.MANUAL,
            declared=declared(**changes),
        )

    @pytest.mark.parametrize(
        ("changes", "named"),
        [
            ({"magic": 486046}, "numéro magique"),
            ({"account_id": "exness-486046157"}, "compte"),
            ({"expected_login": "486046157"}, "login"),
        ],
    )
    def test_a_magic_number_an_account_or_a_login_already_taken_is_refused(
        self, registry: TerminalRegistry, changes: dict[str, object], named: str
    ) -> None:
        add(registry)
        with pytest.raises(RegistryRefused) as refused:
            self.other(registry, **changes)
        assert any(named in problem and DATA_ID in problem for problem in refused.value.problems), (
            refused.value.problems
        )

    def test_distinct_identities_coexist(self, registry: TerminalRegistry) -> None:
        add(registry)
        self.other(
            registry,
            account_id="ftmo-100",
            expected_login="100",
            magic=100100,
            provider="FTMO",
            product="FTMO_CHALLENGE",
        )
        assert len(registry.load().terminals) == 2

    def test_a_terminal_may_be_redeclared_with_its_own_values(self, registry: TerminalRegistry) -> None:
        add(registry)
        registry.declare(DATA_ID, declared(allowed_symbols=("XAUUSDm",)))
        assert registry.load().find(DATA_ID).declared.allowed_symbols == ("XAUUSDm",)  # type: ignore[union-attr]

    def test_an_unknown_terminal_cannot_be_declared(self, registry: TerminalRegistry) -> None:
        with pytest.raises(RegistryRefused) as refused:
            registry.declare("nothing", declared())
        assert "inconnu" in " ".join(refused.value.problems)


class TestOperations:
    def test_an_operation_starts_with_a_deadline_and_ends_back_to_idle(self, registry: TerminalRegistry) -> None:
        add(registry)
        started = registry.begin_operation(
            DATA_ID, OperationKind.DEPLOYING, deployment_id="d-1", step="copie", timeout_s=120
        )
        assert started.operation.kind is OperationKind.DEPLOYING
        assert started.operation.deployment_id == "d-1"
        assert started.operation.started_at == T0
        assert started.operation.deadline == T0 + timedelta(seconds=120)
        ended = registry.end_operation(DATA_ID)
        assert ended.operation.kind is OperationKind.IDLE
        assert ended.operation.deployment_id is None

    def test_a_second_operation_on_the_same_terminal_is_refused(self, registry: TerminalRegistry) -> None:
        add(registry)
        registry.begin_operation(DATA_ID, OperationKind.DEPLOYING, deployment_id="d-1", step="copie", timeout_s=120)
        with pytest.raises(RegistryRefused) as refused:
            registry.begin_operation(
                DATA_ID, OperationKind.TERMINAL_STARTING, deployment_id="d-2", step="lancement", timeout_s=60
            )
        assert "d-1" in " ".join(refused.value.problems)

    def test_idle_is_not_an_operation_to_begin(self, registry: TerminalRegistry) -> None:
        add(registry)
        with pytest.raises(RegistryRefused):
            registry.begin_operation(DATA_ID, OperationKind.IDLE, deployment_id="d", step="x", timeout_s=1)

    def test_an_operation_past_its_deadline_is_overdue_and_never_resumed_silently(
        self, registry: TerminalRegistry
    ) -> None:
        add(registry)
        entry = registry.begin_operation(
            DATA_ID, OperationKind.EA_LOADING, deployment_id="d-1", step="hello", timeout_s=90
        )
        assert is_overdue(entry.operation, T0 + timedelta(seconds=89)) is False
        assert is_overdue(entry.operation, T0 + timedelta(seconds=91)) is True

    def test_an_idle_operation_is_never_overdue(self, registry: TerminalRegistry) -> None:
        entry = add(registry)
        assert is_overdue(entry.operation, T0 + timedelta(days=30)) is False

    def test_a_deadline_must_be_positive(self, registry: TerminalRegistry) -> None:
        add(registry)
        with pytest.raises(RegistryRefused):
            registry.begin_operation(DATA_ID, OperationKind.DEPLOYING, deployment_id="d", step="x", timeout_s=0)


class TestTheLocks:
    def test_the_registry_refuses_a_second_writer(self, tmp_path: Path) -> None:
        path = tmp_path / "var" / "launcher" / "terminals.json"
        table = FakeProcessTable([proc(100), proc(200)])
        first = TerminalRegistry(path, clock(), table, pid=100)
        second = TerminalRegistry(path, clock(), table, pid=200)
        lock = path.with_name("terminals.json.lock")
        lock.parent.mkdir(parents=True)
        lock.write_text(
            json.dumps({"pid": 100, "createdAt": "2026-11-06T15:30:00Z"}), encoding="utf-8"
        )  # first holds it
        with pytest.raises(LauncherBusy):
            second.register(
                terminal_id=DATA_ID,
                label="x",
                install_path=INSTALL,
                data_path=DATA,
                portable=False,
                source=TerminalSource.MANUAL,
            )
        assert first.load().terminals == ()

    def test_a_stale_registry_lock_does_not_block_and_is_released_after_the_write(self, tmp_path: Path) -> None:
        path = tmp_path / "var" / "launcher" / "terminals.json"
        lock = path.with_name("terminals.json.lock")
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"pid": 999, "createdAt": "2026-11-06T09:00:00Z"}), encoding="utf-8")
        registry = TerminalRegistry(path, clock(), FakeProcessTable([proc(100)]), pid=100)
        add(registry)
        assert not lock.exists()

    def test_the_lock_of_a_terminal_lives_in_its_own_file_named_after_it(self, tmp_path: Path) -> None:
        config = make_config(tmp_path / "04_code")
        table = FakeProcessTable([proc(100), proc(200)])
        with terminal_lock(config, DATA_ID, table, clock(), pid=100):
            assert (config.var_dir / "locks" / f"{DATA_ID}.lock").is_file()
        assert not (config.var_dir / "locks" / f"{DATA_ID}.lock").exists()

    def test_two_operations_on_one_terminal_are_refused_and_the_message_names_the_terminal(
        self, tmp_path: Path
    ) -> None:
        config = make_config(tmp_path / "04_code")
        table = FakeProcessTable([proc(100), proc(200)])
        with (
            terminal_lock(config, DATA_ID, table, clock(), pid=100),
            pytest.raises(LauncherBusy) as busy,
            terminal_lock(config, DATA_ID, table, clock(), pid=200),
        ):
            pass
        assert DATA_ID in str(busy.value)
        assert "100" in str(busy.value)

    def test_two_different_terminals_do_not_interfere(self, tmp_path: Path) -> None:
        config = make_config(tmp_path / "04_code")
        table = FakeProcessTable([proc(100), proc(200)])
        with (
            terminal_lock(config, DATA_ID, table, clock(), pid=100),
            terminal_lock(config, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", table, clock(), pid=200),
        ):
            assert len(list((config.var_dir / "locks").glob("*.lock"))) == 2

    @pytest.mark.parametrize("bad", ["", "../x", "a\\b", "x" * 60])
    def test_an_identifier_that_could_leave_the_locks_folder_is_refused(self, tmp_path: Path, bad: str) -> None:
        config = make_config(tmp_path / "04_code")
        with pytest.raises(ValueError):
            terminal_lock(config, bad, FakeProcessTable(), clock(), pid=100)
