# from app.db import engine
# from app.models import Lead
# from sqlalchemy import text

# with engine.connect() as conn:
#     conn.execute(text("DROP TABLE IF EXISTS leads"))
#     conn.commit()

# print("Leads table dropped")
from app.auth import hash_password
print(hash_password("123456"))