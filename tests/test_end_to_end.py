from pathlib import Path
import json
from clayfarm_control.demo import demo
from clayfarm_control.autostart import build_plan

def test_actual_end_to_end(tmp_path):
    result=demo(tmp_path/"demo")
    assert len(result["outputs"])==2
    assert all(x["state"]=="done" and Path(x["file"]).is_file() for x in result["outputs"])
    assert result["gpu_models_executed"] is False

def test_windows_service_xml_spaces(tmp_path):
    from xml.etree.ElementTree import fromstring
    p=build_plan(tmp_path/"한글 space",system="Windows",python=r"C:\Program Files\Python\python.exe",user=r"TEST\user")
    root=fromstring(p["content"])
    assert "LeastPrivilege" in p["content"].decode("utf-16")
    assert "InteractiveToken" in p["content"].decode("utf-16")

def test_mac_service_plist_spaces(tmp_path):
    import plistlib
    p=build_plan(tmp_path/"한글 space",system="Darwin",python="/path with space/python")
    d=plistlib.loads(p["content"])
    assert d["ProgramArguments"][0]=="/path with space/python"
    assert str(tmp_path/"한글 space") in d["ProgramArguments"]
