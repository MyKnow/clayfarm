"""Durable DB inbox plus optional SMTP dispatcher. Never embeds approval credentials."""
from __future__ import annotations
import os, smtplib, ssl
from email.message import EmailMessage
from sqlalchemy import select
from .db import users,events
from .common import CFError,now

def deliver(db,dry_run=False):
    required=("CLAYFARM_SMTP_HOST","CLAYFARM_SMTP_FROM")
    if not dry_run and any(not os.environ.get(k) for k in required):raise CFError("smtp_not_configured","Configure SMTP host/from and credentials")
    sent=[]
    # Row locks serialize dispatchers. SMTP is at-least-once; crash after send may duplicate.
    with db.transaction() as c:
        pending=c.execute(select(events).where(events.c.delivered_at.is_(None)).order_by(events.c.id).with_for_update(skip_locked=True).limit(20)).mappings().all()
        for item in pending:
            q=select(users.c.email).where(users.c.status=="active")
            q=q.where(users.c.role=="admin") if item["audience"]=="admins" else q.where(users.c.id==item["audience"])
            emails=list(c.execute(q).scalars())
            if not emails:continue
            if not dry_run:
                with smtplib.SMTP(os.environ["CLAYFARM_SMTP_HOST"],int(os.environ.get("CLAYFARM_SMTP_PORT","587")),timeout=20) as smtp:
                    smtp.starttls(context=ssl.create_default_context())
                    if os.environ.get("CLAYFARM_SMTP_USER"):smtp.login(os.environ["CLAYFARM_SMTP_USER"],os.environ.get("CLAYFARM_SMTP_PASSWORD",""))
                    for address in emails:
                        m=EmailMessage();m["From"]=os.environ["CLAYFARM_SMTP_FROM"];m["To"]=address;m["Subject"]="ClayFarm: "+item["kind"];m["Message-ID"]=f'<clayfarm-event-{item["id"]}@clayfarm.local>'
                        m.set_content("Event: "+item["kind"]+"\nTarget: "+str(item["payload"].get("target",""))+"\nInspect with: clayfarm notify inbox\nApprove from an authenticated admin CLI. No credential is included in this message.")
                        smtp.send_message(m)
                c.execute(events.update().where(events.c.id==item["id"]).values(delivered_at=now()))
            sent.append({"event_id":item["id"],"recipients":len(emails),"sent":not dry_run})
    return {"events":sent,"delivery_semantics":"at_least_once","dry_run":dry_run}
