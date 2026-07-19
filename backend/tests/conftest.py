import os,time
from pathlib import Path
TEST_DB=Path(__file__).parent/'test_spot_welding.db'
if TEST_DB.exists(): TEST_DB.unlink()
os.environ['DATABASE_URL']=f'sqlite:///{TEST_DB}'
os.environ['ADMIN_EMAIL']='admin@spotwelding.example'
os.environ['ADMIN_PASSWORD']='ChangeMe123!'
os.environ['JWT_SECRET_KEY']='test-secret-key-with-sufficient-length'
import pytest
from fastapi.testclient import TestClient
from app.core.security import hash_password
from app.db.session import Base,SessionLocal,engine
from app.main import app
from app.models.entities import User
@pytest.fixture(scope='session',autouse=True)
def database():
 Base.metadata.create_all(bind=engine)
 with SessionLocal() as db:
  if not db.query(User).filter(User.email=='admin@spotwelding.example').first():
   db.add(User(email='admin@spotwelding.example',full_name='System Administrator',password_hash=hash_password('ChangeMe123!'),role='System Admin',is_active=True)); db.commit()
 yield
 Base.metadata.drop_all(bind=engine); engine.dispose()
 for _ in range(10):
  try:
   if TEST_DB.exists(): TEST_DB.unlink()
   break
  except PermissionError: time.sleep(.1)
@pytest.fixture()
def client():
 with TestClient(app) as c: yield c
@pytest.fixture()
def auth_headers(client):
 r=client.post('/api/v1/auth/login',json={'email':'admin@spotwelding.example','password':'ChangeMe123!'})
 assert r.status_code==200
 return {'Authorization':f"Bearer {r.json()['access_token']}"}
