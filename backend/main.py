from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from pysnmp.hlapi import getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity
import asyncio
import os
from typing import Optional

app = FastAPI()

origins = [
    "http://localhost:3000",  # React frontend default port
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Database Configuration ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./sql_app.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class DeviceDB(Base):
    __tablename__ = "devices"

    ip = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    community = Column(String)

def create_db_tables():
    Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Pydantic Models ---
class DeviceBase(BaseModel):
    ip: str
    name: str
    community: str = "public"

class DeviceCreate(DeviceBase):
    pass

class Device(DeviceBase):
    status: str
    sys_descr: Optional[str] = None

    class Config:
        from_attributes = True

# --- SNMP Fetching Logic ---
async def snmp_get(host, community, oid):
    """
    Performs an SNMP GET request.
    """
    raw_snmp_result = await asyncio.to_thread(
        lambda: next(getCmd(
            SnmpEngine(),
            CommunityData(community),
            UdpTransportTarget((host, 161)),
            ContextData(),
            ObjectType(ObjectIdentity(oid))
        ))
    )

    if not isinstance(raw_snmp_result, tuple) or len(raw_snmp_result) != 4:
        print(f"ERROR: getCmd for {host} ({oid}) returned unexpected value after next(): {raw_snmp_result}")
        return None

    errorIndication, errorStatus, errorIndex, varBinds = raw_snmp_result

    if errorIndication:
        print(f"SNMP Error for {host} ({oid}): {errorIndication}")
        return None
    elif errorStatus:
        print(f"SNMP Error for {host} ({oid}): %s at %s" % (errorStatus.prettyPrint(),
                            errorIndex and varBinds[int(errorIndex) - 1][0] or '?'))
        return None
    else:
        print(f"DEBUG: varBinds for {host} ({oid}): {varBinds}")
        for varBind in varBinds:
            return varBind[1].prettyPrint()
    return None

# --- FastAPI Endpoints ---
@app.on_event("startup")
async def startup_event():
    create_db_tables()
    # Add some initial devices if the database is empty
    db = SessionLocal()
    if db.query(DeviceDB).count() == 0:
        initial_devices = [
            DeviceDB(ip="172.22.20.201", name="Switch FL2", community="public"),
            DeviceDB(ip="192.168.1.100", name="Router Main", community="public"),
        ]
        db.add_all(initial_devices)
        db.commit()
    db.close()

@app.get("/")
async def root():
    return {"message": "Hello from FastAPI Backend!"}

@app.get("/devices", response_model=list[Device])
async def get_devices(db: Session = Depends(get_db)):
    devices_from_db = db.query(DeviceDB).all()
    devices_data = []
    for device_db in devices_from_db:
        sys_descr = await snmp_get(device_db.ip, device_db.community, "1.3.6.1.2.1.1.1.0")
        status = "online" if sys_descr else "offline"
        devices_data.append({
            "id": device_db.ip,
            "name": device_db.name,
            "ip": device_db.ip,
            "status": status,
            "sys_descr": sys_descr
        })
    return devices_data

@app.post("/devices", response_model=Device)
async def add_device(device: DeviceCreate, db: Session = Depends(get_db)):
    db_device = db.query(DeviceDB).filter(DeviceDB.ip == device.ip).first()
    if db_device:
        raise HTTPException(status_code=400, detail="Device with this IP already exists")
    db_device = DeviceDB(**device.dict())
    db.add(db_device)
    db.commit()
    db.refresh(db_device)
    return db_device

@app.put("/devices/{device_ip}", response_model=Device)
async def update_device(device_ip: str, device: DeviceCreate, db: Session = Depends(get_db)):
    db_device = db.query(DeviceDB).filter(DeviceDB.ip == device_ip).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="Device not found")
    db_device.name = device.name
    db_device.community = device.community
    db.commit()
    db.refresh(db_device)
    return db_device

@app.delete("/devices/{device_ip}")
async def delete_device(device_ip: str, db: Session = Depends(get_db)):
    db_device = db.query(DeviceDB).filter(DeviceDB.ip == device_ip).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="Device not found")
    db.delete(db_device)
    db.commit()
    return {"message": "Device deleted successfully"}

@app.get("/devices/{device_ip}/metrics")
async def get_device_metrics(device_ip: str, db: Session = Depends(get_db)):
    db_device = db.query(DeviceDB).filter(DeviceDB.ip == device_ip).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="Device not found")

    community = db_device.community

    uptime = await snmp_get(device_ip, community, "1.3.6.1.2.1.1.3.0")
    in_octets = await snmp_get(device_ip, community, "1.3.6.1.2.1.2.2.1.10.1")
    out_octets = await snmp_get(device_ip, community, "1.3.6.1.2.1.2.2.1.16.1")

    # For CPU/Memory, these OIDs are highly vendor-specific. 
    # You would need to find the correct OIDs for your specific devices.
    # For now, we'll return None or simulated values if real OIDs are not known.
    cpu_usage = None # await snmp_get(device_ip, community, "YOUR_CPU_OID")
    memory_usage = None # await snmp_get(device_ip, community, "YOUR_MEMORY_OID")

    return {
        "device_ip": device_ip,
        "metrics": {
            "uptime": uptime,
            "ifInOctets_eth0": in_octets,
            "ifOutOctets_eth0": out_octets,
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
        }
    }
