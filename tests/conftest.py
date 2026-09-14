import pytest
from pathlib import Path
from clayfarm_control.db import Database
from clayfarm_control.api import create_app
from clayfarm_control.registry import load_registry
from clayfarm_control.demo import ADMIN,FixtureVerifier,fixture_client

@pytest.fixture
def system(tmp_path):
    db=Database("sqlite:///"+str(tmp_path/"test.db"));db.init();db.bootstrap_admin(ADMIN,"admin@example.test")
    app=create_app(db,load_registry(),FixtureVerifier(),artifact_root=tmp_path/"artifacts")
    admin=fixture_client(tmp_path/"admin",app,"fixture-admin")
    user=fixture_client(tmp_path/"user",app,"fixture-user")
    other=fixture_client(tmp_path/"other",app,"fixture-other")
    yield db,app,admin,user,other
    for c in (admin,user,other):c.http.close()
    db.engine.dispose()
