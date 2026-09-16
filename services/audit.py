from flask import request
from flask_login import current_user
from extensions import db
from models import AuditLog

def audit(action, entity_type, entity_id, old_values=None, new_values=None):
    if not getattr(current_user, "is_authenticated", False):
        return
    row = AuditLog(business_id=current_user.business_id, user_id=current_user.id, action=action,
                   entity_type=entity_type, entity_id=entity_id, old_values=old_values, new_values=new_values,
                   ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
                   user_agent=request.headers.get("User-Agent", ""))
    db.session.add(row)
    db.session.commit()
