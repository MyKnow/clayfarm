from __future__ import annotations
import getpass, os, platform, plistlib, subprocess, sys
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from .common import CFError, sha

def build_plan(home,system=None,python=None,user=None):
    system=system or platform.system();python=python or sys.executable;name="clayfarm-control-"+sha(str(home).encode())[:12]
    argv=[python,"-m","clayfarm_control","--home",str(home),"node","worker"]
    if system=="Darwin":
        label="xyz.myknow."+name
        uid = getattr(os, "getuid", lambda: 0)() # foreign-OS template tests; actual Darwin has getuid
        path=Path.home()/"Library/LaunchAgents"/(label+".plist")
        content=plistlib.dumps({"Label":label,"ProgramArguments":argv,"RunAtLoad":True,"KeepAlive":{"SuccessfulExit":False},"ThrottleInterval":30,"StandardOutPath":str(home/"agent.stdout.log"),"StandardErrorPath":str(home/"agent.stderr.log")})
        return {"name":label,"path":path,"content":content,"install":["launchctl","bootstrap",f"gui/{uid}",str(path)],"uninstall":["launchctl","bootout",f"gui/{uid}/{label}"]}
    if system=="Windows":
        root=Element("Task",version="1.4",xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task")
        triggers=SubElement(root,"Triggers");trigger=SubElement(triggers,"LogonTrigger");SubElement(trigger,"Enabled").text="true"
        principals=SubElement(root,"Principals");principal=SubElement(principals,"Principal",id="Author")
        SubElement(principal,"UserId").text=user or getpass.getuser();SubElement(principal,"LogonType").text="InteractiveToken";SubElement(principal,"RunLevel").text="LeastPrivilege"
        settings=SubElement(root,"Settings");SubElement(settings,"MultipleInstancesPolicy").text="IgnoreNew";SubElement(settings,"ExecutionTimeLimit").text="PT0S"
        restart=SubElement(settings,"RestartOnFailure");SubElement(restart,"Interval").text="PT1M";SubElement(restart,"Count").text="10"
        actions=SubElement(root,"Actions",Context="Author");action=SubElement(actions,"Exec");SubElement(action,"Command").text=python;SubElement(action,"Arguments").text=subprocess.list2cmdline(argv[1:])
        path=home/(name+".xml");content=tostring(root,encoding="utf-16",xml_declaration=True)
        return {"name":name,"path":path,"content":content,"install":["schtasks","/Create","/TN",name,"/XML",str(path)],"uninstall":["schtasks","/Delete","/TN",name,"/F"]}
    raise CFError("service_os_unsupported","Current-user autostart is implemented for Windows and macOS; Linux uses the supplied service/container instructions")

def service(home,action):
    plan=build_plan(home)
    if action=="plan":return {"path":str(plan["path"]),"command":plan["install"],"mode":"current_user_logon_not_system_service"}
    if action=="install":
        path=plan["path"]
        if path.exists():raise CFError("service_exists","Existing autostart file is not overwritten; uninstall first")
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(plan["content"])
        result=subprocess.run(plan["install"],capture_output=True,text=True,timeout=30)
        if result.returncode:raise CFError("service_registration_failed","OS rejected autostart registration; no privilege escalation attempted")
    else:
        result=subprocess.run(plan["uninstall"],capture_output=True,text=True,timeout=30)
        if result.returncode:raise CFError("service_removal_failed","OS did not confirm removal; inspect current-user tasks")
        plan["path"].unlink(missing_ok=True)
    return {"action":action,"service":plan["name"]}
