from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from pysnmp.hlapi import getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity
import asyncio
import json
import platform
import re
import subprocess
from typing import Optional, List

app = FastAPI()

# --- CORS Configuration ---
origins = [
    "http://localhost:3000",
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
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DeviceDB(Base):
    __tablename__ = "devices"
    ip = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    community = Column(String)

def create_db_tables():
    Base.metadata.create_all(bind=engine)

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
    id: str # Add id field
    status: str
    sys_descr: Optional[str] = None
    class Config:
        from_attributes = True

# --- Real-time Status Handling ---
device_status_cache = {}
device_status_stream = asyncio.Queue()

# --- SNMP Fetching Logic ---
async def snmp_get(host, community, oid):
    try:
        errorIndication, errorStatus, errorIndex, varBinds = await asyncio.to_thread(
            lambda: next(getCmd(
                SnmpEngine(),
                CommunityData(community),
                UdpTransportTarget((host, 161), timeout=2, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity(oid))
            ))
        )
        if errorIndication:
            # print(f"SNMP Error for {host}: {errorIndication}")
            return None
        elif errorStatus:
            # print(f"SNMP Error for {host}: {errorStatus.prettyPrint()}")
            return None
        else:
            return varBinds[0][1].prettyPrint()
    except Exception as e:
        # print(f"Exception during SNMP GET for {host}: {e}")
        return None

async def ping_check(host: str) -> bool:
    """
    Performs a simple ping check to see if the host is reachable.
    Returns True if reachable, False otherwise.
    """
    param = "-n" if platform.system().lower() == "windows" else "-c"
    command = [param, "3", host] # Ping 3 times to check reachability

    try:
        # Run ping command, capture output, and don't raise exception for non-zero exit codes
        result = await asyncio.to_thread(
            subprocess.run,
            ["ping"] + command,
            capture_output=True,
            text=True,
            check=False,
            timeout=5 # Add a timeout for the ping command itself
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"Ping check for {host} timed out.")
        return False
    except Exception as e:
        print(f"Exception during ping check for {host}: {e}")
        return False

# --- Background Monitoring Task ---
async def monitor_devices():
    while True:
        db = SessionLocal()
        devices_from_db = db.query(DeviceDB).all()
        db.close()

        for device_db in devices_from_db:
            print(f"Monitoring device: {device_db.ip} ({device_db.name})")
            sys_descr = await snmp_get(device_db.ip, device_db.community, "1.3.6.1.2.1.1.1.0")
            print(f"  SNMP sys_descr result: {sys_descr}")
            
            status = "offline"
            if sys_descr:
                status = "online"
            else:
                print(f"  SNMP failed for {device_db.ip}, attempting ping check...")
                # SNMP failed, try ping as fallback
                if await ping_check(device_db.ip):
                    print(f"  Ping check for {device_db.ip}: Online")
                    status = "online"
                else:
                    print(f"  Ping check for {device_db.ip}: Offline")
                    status = "offline"
            
            device_data = {
                "id": device_db.ip,
                "name": device_db.name,
                "ip": device_db.ip,
                "community": device_db.community,
                "status": status,
                "sys_descr": sys_descr # sys_descr will be None if SNMP failed
            }
            print(f"  Final status for {device_db.ip}: {status}")

            if device_db.ip not in device_status_cache or device_status_cache[device_db.ip]['status'] != status:
                print(f"  Status change detected for {device_db.ip}: {device_status_cache.get(device_db.ip, {}).get('status', 'N/A')} -> {status}. Notifying clients.")
                device_status_cache[device_db.ip] = device_data
                await device_status_stream.put({"event": "update", "data": device_data})
            else:
                print(f"  No status change for {device_db.ip}. Current status: {status}")
        
        await asyncio.sleep(5) # Check every 5 seconds

# --- FastAPI Endpoints ---
@app.on_event("startup")
async def startup_event():
    create_db_tables()
    db = SessionLocal()
    if db.query(DeviceDB).count() == 0:
        initial_devices = [
            DeviceDB(ip="172.22.20.201", name="Switch FL2", community="public"),
            DeviceDB(ip="192.168.1.100", name="Router Main", community="public"),
        ]
        db.add_all(initial_devices)
        db.commit()
    db.close()
    asyncio.create_task(monitor_devices())

@app.get("/")
async def root():
    return {"message": "Hello from FastAPI Backend!"}

@app.get("/devices", response_model=List[Device])
async def get_devices_initial():
    return list(device_status_cache.values())

@app.get("/devices/stream")
async def stream_device_status(request: Request):
    async def event_generator():
        # Send initial full list
        initial_data = list(device_status_cache.values())
        yield f"data: {json.dumps({'event': 'initial', 'data': initial_data})}\n\n"
        
        # Listen for updates
        q = asyncio.Queue()
        # This is a simplified consumer registration, for a real app you'd need a more robust fan-out mechanism
        # For this example, we create a new queue for each client.
        # A better approach would be a central distributor.
        async def reader():
            while True:
                data = await device_status_stream.get()
                await q.put(data)
        
        reader_task = asyncio.create_task(reader())

        try:
            while True:
                if await request.is_disconnected():
                    break
                update = await q.get()
                yield f"data: {json.dumps(update)}\n\n"
                await asyncio.sleep(0.1)
        finally:
            reader_task.cancel()

    return StreamingResponse(event_generator(), media_type="text/event-stream")

async def notify_clients_of_change():
    """Puts a reload event in the stream for all clients."""
    await device_status_stream.put({"event": "reload", "data": {}})


@app.post("/devices", response_model=Device)
async def add_device(device: DeviceCreate, db: Session = Depends(get_db)):
    db_device = db.query(DeviceDB).filter(DeviceDB.ip == device.ip).first()
    if db_device:
        raise HTTPException(status_code=400, detail="Device with this IP already exists")
    
    db_device = DeviceDB(**device.dict())
    db.add(db_device)
    db.commit()
    db.refresh(db_device)
    
    # Manually update cache and notify
    new_device_data = Device.from_orm(db_device).dict()
    new_device_data['status'] = 'offline' # Assume offline initially
    device_status_cache[db_device.ip] = new_device_data
    await notify_clients_of_change()
    
    return new_device_data

@app.put("/devices/{device_ip}", response_model=Device)
async def update_device(device_ip: str, device: DeviceCreate, db: Session = Depends(get_db)):
    db_device = db.query(DeviceDB).filter(DeviceDB.ip == device_ip).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    db_device.name = device.name
    db_device.community = device.community
    db.commit()
    db.refresh(db_device)
    
    await notify_clients_of_change()
    
    return Device.from_orm(db_device)


@app.delete("/devices/{device_ip}")
async def delete_device(device_ip: str, db: Session = Depends(get_db)):
    print(f"Attempting to delete device with IP: {device_ip}")
    db_device = db.query(DeviceDB).filter(DeviceDB.ip == device_ip).first()
    if not db_device:
        print(f"Device with IP {device_ip} not found in DB.")
        raise HTTPException(status_code=404, detail="Device not found")
    
    db.delete(db_device)
    print(f"db.delete() called for device {device_ip}.")
    db.commit()
    print(f"db.commit() called for device {device_ip}.")
    
    # Remove from cache
    if device_ip in device_status_cache:
        del device_status_cache[device_ip]
        print(f"Device {device_ip} removed from cache.")
        
    await notify_clients_of_change()
    print(f"Clients notified of change for device {device_ip}.")
    
    return {"message": "Device deleted successfully"}


@app.get("/devices/{device_ip}/ping")
async def ping_device(device_ip: str):
    """
    Pings a device to check for reachability.
    """
    if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", device_ip):
        raise HTTPException(status_code=400, detail="Invalid IP address format")

    param = "-n" if platform.system().lower() == "windows" else "-c"
    command = ["ping", param, "5", device_ip] # Use list for subprocess.run for safety
    print(f"Executing command: {' '.join(command)}")

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True, # Capture output as text
            check=False # Do not raise an exception for non-zero exit codes
        )

        stdout_str = result.stdout
        stderr_str = result.stderr

        print(f"Ping stdout: {stdout_str}")
        print(f"Ping stderr: {stderr_str}")

        if result.returncode == 0:
            return {"status": "success", "output": stdout_str}
        else:
            return {"status": "error", "output": stderr_str}
    except Exception as e:
        import traceback
        print(f"Exception in ping_device of type {type(e)}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to execute ping command: {str(e)}")


@app.get("/devices/{device_ip}/metrics")
async def get_device_metrics(device_ip: str, db: Session = Depends(get_db)):
    db_device = db.query(DeviceDB).filter(DeviceDB.ip == device_ip).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="Device not found")

    community = db_device.community

    uptime = await snmp_get(device_ip, community, "1.3.6.1.2.1.1.3.0")
    in_octets = await snmp_get(device_ip, community, "1.3.6.1.2.1.2.2.1.10.1")
    out_octets = await snmp_get(device_ip, community, "1.3.6.1.2.1.2.2.1.16.1")

    cpu_usage = None
    memory_usage = None

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