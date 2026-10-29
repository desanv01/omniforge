"""Injected authority/settlement boundaries only; no SQL, roles or filesystem I/O."""
from collections import Counter
from contextlib import contextmanager
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from tests.integration.core import worker_authority as proof


class Value:
    def __init__(self,value):self.value=value
    def scalar_one(self):return self.value
    def one(self):return self.value
    def all(self):return self.value
    def scalars(self):return self
    def mappings(self):return self
    def __iter__(self):return iter(self.value)


class ControlStop(BaseException):pass


class WorkerAuthorityContract(unittest.TestCase):
    def test_exact_twenty_tables_and_no_journal_grants(self):
        self.assertEqual(len(proof.TABLES),20);self.assertEqual(len(set(proof.TABLES)),20)
        self.assertEqual(proof.MIGRATION,"0009_provider_diagnostics")
        for table in ("provider_diagnostics","provider_diagnostic_rounds"):
            self.assertIn(table,proof.TABLES)
            for matrix in proof.MATRIX.values():self.assertNotIn(table,matrix)
            self.assertFalse(any(table in sql for sql in proof.grant_sql()))
        self.assertEqual(proof.UPDATE["case_grants"],"can_write")
        self.assertEqual(proof.UPDATE["artifact_associations"],"revision")
        self.assertEqual(proof.UPDATE["artifacts"],"bytes")
        self.assertFalse(any("ALL TABLES" in sql or "ALL PRIVILEGES" in sql for sql in proof.grant_sql()))

    def test_guard_rejects_missing_extra_or_wrong_owned_table_and_wrong_schema(self):
        for variant in ("valid","missing_journal","extra","wrong_owner","old_schema"):
            resources=[(table,"owner") for table in (*proof.TABLES,"alembic_version")]
            if variant=="missing_journal":resources=[row for row in resources if row[0]!="provider_diagnostics"]
            if variant=="extra":resources.append(("unexpected","owner"))
            if variant=="wrong_owner":resources[-1]=("alembic_version",proof.ROLE)
            conn=MagicMock()
            conn.execute.side_effect=[Value((proof.DATABASE,"owner","owner","public","owner")),
                Value("123"),Value(["0008_run_cancellation" if variant=="old_schema" else proof.MIGRATION]),
                Value(0),Value(resources),Value(0)]
            if variant=="valid":proof.guard_owner(conn,"owner","123")
            else:
                with self.subTest(variant=variant),self.assertRaises(proof.ProofFailure):proof.guard_owner(conn,"owner","123")

    def test_effective_catalog_check_rejects_each_journal_column_privilege(self):
        for table in proof.JOURNAL_TABLES:
            for privilege in ("SELECT","INSERT","UPDATE"):
                def execute(sql,params=None):
                    statement=str(sql)
                    if statement.startswith("SELECT c.relname,a.attname"):return Value([(t,"operation_id") for t in proof.JOURNAL_TABLES])
                    if statement.startswith("SELECT has_column_privilege"):
                        return Value(params["t"]=="public."+table and params["p"]==privilege)
                    return Value(False)
                conn=SimpleNamespace(execute=execute)
                with self.subTest(table=table,privilege=privilege),self.assertRaisesRegex(proof.ProofFailure,"effective_column_privilege_mismatch"):
                    proof.effective_privileges(conn)

    def test_journal_probes_are_rollback_only_exact_permission_denial(self):
        probes=proof.journal_denial_probes();self.assertEqual(len(probes),8)
        self.assertTrue(all("WHERE false" in sql for sql in probes))
        self.assertFalse(any("TRUNCATE" in sql or "CREATE " in sql for sql in probes))
        for state in ("42501","42P01","23502",None):
            conn=MagicMock();engine=MagicMock();engine.connect.return_value.__enter__.return_value=conn
            if state is not None:
                conn.execute.side_effect=proof.DBAPIError("inert",{},SimpleNamespace(sqlstate=state))
            if state=="42501":proof.denied_sql(engine,probes[0])
            else:
                with self.subTest(state=state),self.assertRaises(proof.ProofFailure):proof.denied_sql(engine,probes[0])
            conn.begin.return_value.rollback.assert_called_once_with()

    def invoke(self,fault=None):
        owner=MagicMock();owner.echo=False;owner.hide_parameters=True;owner.pool.checkedout.return_value=0
        worker=MagicMock();worker.pool.checkedout.return_value=0
        conn=MagicMock();conn.execute.return_value.scalar_one.return_value=False
        events=[];transactions=[0]
        baseline={table:Counter({"synthetic":1}) for table in proof.TABLES}
        if fault=="empty_baseline":baseline["provider_diagnostics"]=Counter()
        after={table:Counter(value) for table,value in baseline.items()}
        if fault=="preservation":after["provider_diagnostic_rounds"]=Counter()
        @contextmanager
        def transaction(engine):
            transactions[0]+=1;index=transactions[0];events.append("transaction_"+str(index))
            yield conn
            if (fault=="commit" and index==1) or (fault=="disable" and index==2):raise RuntimeError("PRIVATE_FAULT")
        def provision(*args):
            events.append("provision")
            if fault=="provision":raise RuntimeError("PRIVATE_FAULT")
        probes=[]
        def deny(engine,sql):
            probes.append(sql)
            if fault=="probe" and len(probes)==2:raise RuntimeError("PRIVATE_FAULT")
        def receiver(*args,checks):
            for purpose in proof.PURPOSES:
                checks.append({"purpose":purpose,"status":"passed"})
                if fault=="interrupt":raise ControlStop("PRIVATE_FAULT")
            return checks
        fixtures=[SimpleNamespace(run_id=uuid4()) for _ in range(7)]
        startup=SimpleNamespace(role=proof.ROLE,database=proof.DATABASE,migration=proof.MIGRATION,
            temporary_allowed=True,authority="synthetic")
        if fault=="worker_dispose":worker.dispose.side_effect=RuntimeError("PRIVATE_FAULT")
        if fault=="owner_dispose":owner.dispose.side_effect=RuntimeError("PRIVATE_FAULT")
        if fault=="pool":worker.pool.checkedout.return_value=1
        evidence={}
        with patch.object(proof,"owner_transaction",side_effect=transaction),\
            patch.object(proof,"guard_owner",side_effect=RuntimeError("PRIVATE_FAULT") if fault=="guard" else None),\
            patch.object(proof,"snapshot",side_effect=[baseline,after]),patch.object(proof,"schema_projection",return_value=["shape"]),\
            patch.object(proof,"provision",side_effect=provision),patch.object(proof,"seed",return_value=fixtures),\
            patch.object(proof,"build_worker_engine",return_value=worker),patch.object(proof,"validate_worker_startup",return_value=startup),\
            patch.object(proof,"effective_privileges",return_value={"synthetic":True}),patch.object(proof,"denied_sql",side_effect=deny),\
            patch.object(proof,"receiver_checks",side_effect=receiver):
            try:
                result=proof.execute(owner_engine=owner,expected_owner="owner",expected_cluster="123",
                    new_secret="public-inert-only",release=proof.RELEASE,evidence=evidence)
                self.assertIs(result,evidence)
            except proof.ProofInterrupted as error:self.assertIs(error.report,evidence)
        self.assertNotIn("PRIVATE_FAULT",json.dumps(evidence));self.assertNotIn("public-inert-only",json.dumps(evidence))
        owner.dispose.assert_called_once_with()
        return evidence,events,probes,worker,conn

    def test_success_preserves_twenty_baselines_and_settles_role_and_pools(self):
        report,events,probes,worker,_=self.invoke()
        self.assertEqual(report["status"],"passed");self.assertEqual(set(report["baseline20"]),set(proof.TABLES))
        self.assertNotIn("baseline18",report);self.assertEqual(report["empty_baseline_tables"],[])
        self.assertTrue(report["baseline_preserved"]);self.assertTrue(report["schema_preserved"])
        self.assertEqual(report["role_disable_commit"],"confirmed");self.assertEqual(report["provisioning_commit"],"confirmed")
        self.assertEqual(len(probes),21);self.assertEqual(len(report["sql_denial_checks"]),21)
        self.assertEqual(probes[-8:],list(proof.journal_denial_probes()));worker.dispose.assert_called_once_with()

    def test_failed_or_uncertain_provision_never_blindly_disables_or_retries(self):
        for fault in ("guard","empty_baseline","provision","commit"):
            with self.subTest(fault=fault):
                report,events,probes,worker,conn=self.invoke(fault)
                self.assertEqual(report["status"],"failed");self.assertFalse(probes)
                self.assertLessEqual(events.count("provision"),1);worker.dispose.assert_not_called()
                self.assertEqual(report["role_disable_commit"],"not_attempted")
                self.assertFalse(any("ALTER ROLE" in str(call) for call in conn.execute.call_args_list))
                if fault in ("provision","commit"):
                    self.assertEqual(report["provisioning_commit"],"unconfirmed_requires_Main_inspection")
                    self.assertTrue(report["baseline_preserved"])

    def test_first_probe_failure_keeps_partial_checks_and_stops_later_work(self):
        report,events,probes,worker,_=self.invoke("probe")
        self.assertEqual(report["status"],"failed");self.assertEqual(len(probes),2)
        self.assertEqual(len(report["sql_denial_checks"]),1);self.assertNotIn("receiver_checks",report)
        self.assertEqual(report["role_disable_commit"],"confirmed");worker.dispose.assert_called_once_with()

    def test_control_and_independent_settlement_failures_remain_nonpassing(self):
        for fault in ("interrupt","pool","worker_dispose","disable","preservation","owner_dispose"):
            with self.subTest(fault=fault):
                report,events,probes,worker,_=self.invoke(fault)
                self.assertIn(report["status"],("failed","interrupted"));worker.dispose.assert_called_once_with()
                self.assertIn("baseline20",report);self.assertIn("owner_checked_out",report)
                self.assertTrue(report["failure_stages"])
                if fault=="interrupt":
                    self.assertTrue(report["control_interrupted"]);self.assertEqual(len(report["receiver_checks"]),1)
                if fault=="disable":self.assertEqual(report["role_disable_commit"],"unconfirmed_requires_Main_inspection")


if __name__=="__main__":unittest.main()
