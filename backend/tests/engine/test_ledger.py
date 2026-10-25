import pytest
from engine.ledger import Ledger


def test_four_kw_for_fifteen_minutes_owes_one_kwh_and_catchup_repays():
    ledger=Ledger()
    ledger.reduce("hvac",10)
    ledger.observe({"hvac":6},15,{"hvac"})
    assert ledger.owed("hvac")==pytest.approx(1)
    ledger.observe({"hvac":12},15,set())
    assert ledger.owed("hvac")==pytest.approx(.5)
    ledger.observe({"hvac":14},15,set())
    assert ledger.owed("hvac")==0
